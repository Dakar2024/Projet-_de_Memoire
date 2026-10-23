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
# shellcheck source=scripts/lib/empreintes.sh
. scripts/lib/empreintes.sh

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

echo "== comparaison avec la base en service"
ecarts=0
empreintes_rag
comparer_requetes rag_owner rag "${EN_SERVICE}" "${JETABLE}" "en service" "restaurée "

if [ "${ecarts}" -ne 0 ]; then
  echo "restauration NON conforme : ${ecarts} écart(s)" >&2
  exit 1
fi
echo "restauration conforme : la sauvegarde ${DUMP} redonne la base en service"
