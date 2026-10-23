#!/usr/bin/env bash
# Sauvegarde le lac MinIO, la base Airflow et la base vectorielle du RAG ; chaque dump est relu.
# Usage (racine du dépôt, stack démarrée) : ./scripts/sauvegarde.sh
# Cron hebdomadaire : 0 3 * * 0 cd /chemin/du/depot && ./scripts/sauvegarde.sh >> ~/sauvegarde.log 2>&1
set -euo pipefail
umask 077  # copies lisibles par le seul propriétaire

DESTINATION="${DESTINATION_SAUVEGARDE:-$HOME/sauvegardes-genomique}"
COPIES_CONSERVEES="${COPIES_CONSERVEES:-4}"
HORODATAGE="$(date +%Y-%m-%d-%H%M)"
CIBLE="${DESTINATION}/${HORODATAGE}"

if [ ! -f .env ]; then
  echo "erreur : lancer depuis la racine du dépôt (.env introuvable)" >&2
  exit 1
fi
set -a  # exporte les variables du .env
# Sans les CR : un .env édité sous Windows ferait échouer `.` (Docker Compose, lui, les tolère).
# shellcheck disable=SC1090
. <(tr -d '\r' < .env)
set +a

mkdir -p "${CIBLE}"

# Dumpe une base par le socket local du conteneur (aucun secret exposé), puis relit le dump.
dump_base() {  # conteneur compte base fichier
  docker exec "$1" pg_dump --username="$2" --dbname="$3" --format=custom > "${CIBLE}/$4"
  docker exec -i "$1" pg_restore --list > /dev/null < "${CIBLE}/$4"
  echo "   $(du -h "${CIBLE}/$4" | cut -f1), relu"
}

echo "== base de métadonnées Airflow"
dump_base genomique-postgres airflow airflow airflow.dump

echo "== base vectorielle du RAG (pgvector)"
dump_base genomique-rag-postgres rag_owner rag rag.dump

echo "== buckets MinIO"
# `mc` jetable sur le réseau de la stack, sous l'UID de l'hôte pour que la rotation puisse supprimer.
docker run --rm \
  --network genomique_genomique-network \
  --user "$(id -u):$(id -g)" \
  --security-opt no-new-privileges:true \
  --entrypoint sh \
  -e MC_HOST_lac="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000" \
  -v "${CIBLE}:/sauvegarde" \
  genomique/minio-mc:RELEASE.2025-08-13T08-35-41Z \
  -c 'for b in raw bronze silver gold; do mc --config-dir /tmp/mc mirror --quiet --overwrite "lac/$b" "/sauvegarde/$b" > /dev/null || exit 1; done'
echo "   $(du -sh "${CIBLE}" | cut -f1) au total"

echo "== rotation : on garde les ${COPIES_CONSERVEES} dernières"
ls -1d "${DESTINATION}"/*/ 2>/dev/null | sort -r | tail -n "+$((COPIES_CONSERVEES + 1))" | while read -r ancienne; do
  echo "   suppression de ${ancienne}"
  rm -rf "${ancienne}"
done

echo "sauvegarde terminée : ${CIBLE}"
