#!/usr/bin/env bash
# Restaure un dump de la base vectorielle dans un conteneur jetable sans réseau et le compare à la base en service.
# Usage (racine du dépôt, stack démarrée) : ./scripts/verifier_restauration_rag.sh [/chemin/vers/rag.dump]
set -euo pipefail

DESTINATION="${DESTINATION_SAUVEGARDE:-$HOME/sauvegardes-genomique}"
EN_SERVICE=genomique-rag-postgres
JETABLE=genomique-rag-restauration-test

if [ "$#" -ge 1 ]; then
  DUMP="$1"
else
  DUMP="$(ls -1d "${DESTINATION}"/*/rag.dump 2>/dev/null | sort | tail -n 1 || true)"
fi
if [ -z "${DUMP}" ] || [ ! -f "${DUMP}" ]; then
  echo "erreur : aucun dump rag.dump trouvé (${DESTINATION}/<date>/rag.dump ou argument)" >&2
  exit 1
fi
if [ ! -f RAG/sql/001_schema.sql ]; then
  echo "erreur : lancer depuis la racine du dépôt (RAG/sql/001_schema.sql introuvable)" >&2
  exit 1
fi

IMAGE="$(docker inspect "${EN_SERVICE}" --format '{{.Config.Image}}')"
aleatoire() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

nettoyer() { docker rm -f "${JETABLE}" > /dev/null 2>&1 || true; }
trap nettoyer EXIT
nettoyer

echo "== dump : ${DUMP} ($(du -h "${DUMP}" | cut -f1))"
echo "== conteneur jetable (${IMAGE%%@*}, sans réseau)"
docker run -d --name "${JETABLE}" --network none --memory 1g \
  --security-opt no-new-privileges:true \
  -e POSTGRES_USER=rag_owner -e POSTGRES_DB=rag -e POSTGRES_PASSWORD="$(aleatoire)" \
  -v "${PWD}/RAG/sql:/sql:ro" "${IMAGE}" > /dev/null
# TCP et non socket : le serveur temporaire d'initialisation n'écoute que sur le socket.
for _ in $(seq 1 60); do
  docker exec "${JETABLE}" pg_isready -h 127.0.0.1 -U rag_owner -d rag > /dev/null 2>&1 && break
  sleep 1
done
docker exec "${JETABLE}" pg_isready -h 127.0.0.1 -U rag_owner -d rag > /dev/null

echo "== schéma et comptes (RAG/sql/001_schema.sql, comme rag-postgres-init)"
docker exec -e RAG_INDEXER_PASSWORD="$(aleatoire)" -e RAG_READER_PASSWORD="$(aleatoire)" "${JETABLE}" \
  psql -q -U rag_owner -d rag -f /sql/001_schema.sql

echo "== restauration (pg_restore --clean --if-exists)"
debut=$(date +%s)
docker exec -i "${JETABLE}" pg_restore -U rag_owner -d rag --clean --if-exists --exit-on-error < "${DUMP}"
echo "   $(( $(date +%s) - debut )) s"

# Requêtes de comparaison, exécutées à l'identique sur les deux bases.
requete() {  # conteneur sql
  docker exec "$1" psql -U rag_owner -d rag -At -c "$2"
}
declare -a NOMS=(
  "documents et modèles d'embedding"
  "empreinte des identifiants (doc_id, chunk_id)"
  "empreinte des vecteurs"
  "index"
  "droits de rag_reader et rag_indexer"
  "10 plus proches voisins (recherche exacte)"
)
declare -a SQL=(
  "SELECT count(*) || ' documents, ' || count(DISTINCT embedding_model) || ' modèle(s) : ' || string_agg(DISTINCT embedding_model, ', ') FROM rag_documents"
  "SELECT md5(string_agg(doc_id || ':' || chunk_id, ',' ORDER BY doc_id)) FROM rag_documents"
  "SELECT md5(string_agg(md5(embedding::text), '' ORDER BY doc_id)) FROM rag_documents"
  "SELECT string_agg(indexname, ', ' ORDER BY indexname) FROM pg_indexes WHERE tablename = 'rag_documents'"
  "SELECT 'lecteur lit=' || has_table_privilege('rag_reader', 'rag_documents', 'SELECT') || ' écrit=' || has_table_privilege('rag_reader', 'rag_documents', 'INSERT') || ' ; indexeur écrit=' || has_table_privilege('rag_indexer', 'rag_documents', 'INSERT')"
  "SET enable_indexscan = off; SELECT string_agg(doc_id, ',') FROM (SELECT doc_id FROM rag_documents ORDER BY embedding <=> (SELECT embedding FROM rag_documents ORDER BY doc_id LIMIT 1), doc_id LIMIT 10) t"
)

echo "== comparaison avec la base en service"
ecarts=0
for i in "${!SQL[@]}"; do
  service="$(requete "${EN_SERVICE}" "${SQL[$i]}" | tail -n 1)"
  restauree="$(requete "${JETABLE}" "${SQL[$i]}" | tail -n 1)"
  if [ "${service}" = "${restauree}" ]; then
    echo "   OK     ${NOMS[$i]} : ${restauree:0:90}"
  else
    echo "   ÉCART  ${NOMS[$i]}"
    echo "          en service : ${service:0:90}"
    echo "          restaurée  : ${restauree:0:90}"
    ecarts=$((ecarts + 1))
  fi
done

if [ "${ecarts}" -ne 0 ]; then
  echo "restauration NON conforme : ${ecarts} écart(s)" >&2
  exit 1
fi
echo "restauration conforme : la sauvegarde ${DUMP} redonne la base en service"
