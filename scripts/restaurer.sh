#!/usr/bin/env bash
# Restaure une copie de scripts/sauvegarde.sh (base Airflow, lac, base RAG) dans une pile désignée.
# Usage (racine du dépôt) : ./scripts/restaurer.sh --pile genomique-e3b <copie>
#                           ./scripts/restaurer.sh --pile genomique --pile-principale <copie>
# ÉCRASE la base Airflow, les quatre buckets et la base RAG de la pile visée (procedure_reprise.md § 5.3).
set -euo pipefail

# Même image `mc` que scripts/sauvegarde.sh, construite par docker compose (docker/minio/Dockerfile).
MC_IMAGE=genomique/minio-mc:RELEASE.2025-08-13T08-35-41Z

usage() {
  echo "usage : $0 --pile genomique-e3b|genomique [--pile-principale] <dossier de copie>" >&2
  exit 2
}

# ------------------------------------------------ arguments : tout refus précède le premier appel docker
PILE=""
PRINCIPALE=0
COPIE=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --pile) [ "$#" -ge 2 ] || usage; PILE="$2"; shift 2 ;;
    --pile-principale) PRINCIPALE=1; shift ;;
    -*) usage ;;
    *) [ -z "${COPIE}" ] || usage; COPIE="${1%/}"; shift ;;
  esac
done
{ [ -n "${PILE}" ] && [ -n "${COPIE}" ]; } || usage

case "${PILE}" in
  genomique)
    if [ "${PRINCIPALE}" -ne 1 ]; then
      echo "erreur : la pile principale porte le seul lac ; ajouter --pile-principale pour l'écraser" >&2
      exit 2
    fi
    FICHIERS=(-f docker-compose.yml)
    SERVICES=()  # toute la pile
    ;;
  genomique-e3b)
    FICHIERS=(-f docker-compose.yml -f docker/e3b/docker-compose.e3b.yml)
    # Ni API RAG, ni passerelle, ni proxy : le pipeline n'en a pas besoin (spec E3b § 3).
    SERVICES=(postgres minio-server minio airflow-apiserver airflow-scheduler airflow-dag-processor
      airflow-triggerer rag-postgres rag-embeddings)
    ;;
  *)
    echo "erreur : pile inconnue « ${PILE} » (genomique-e3b ou genomique)" >&2
    exit 2
    ;;
esac

if [ ! -f .env ] || [ ! -f docker-compose.yml ]; then
  echo "erreur : lancer depuis la racine du dépôt (.env ou docker-compose.yml introuvable)" >&2
  exit 1
fi
for f in airflow.dump rag.dump raw bronze silver gold; do
  [ -e "${COPIE}/${f}" ] || { echo "erreur : ${f} absent de la copie ${COPIE}" >&2; exit 1; }
done
COPIE="$(cd "${COPIE}" && pwd)"  # chemin absolu, monté dans le conteneur `mc`

set -a  # exporte les variables du .env
# Sans les CR : un .env édité sous Windows ferait échouer `.` (Docker Compose, lui, les tolère).
# shellcheck disable=SC1090
. <(tr -d '\r' < .env)
set +a

compose() {
  docker compose -p "${PILE}" "${FICHIERS[@]}" --env-file .env "$@"
}

echo "== copie : ${COPIE} → pile ${PILE}"

echo "== arrêt de ce qui écrit dans le lac et les bases"
compose stop airflow-scheduler airflow-dag-processor airflow-triggerer airflow-apiserver rag-api

echo "== base Airflow (historique des runs et des événements d'Asset)"
compose up -d --wait postgres
docker exec -i "${PILE}-postgres" pg_restore -U airflow -d airflow \
  --clean --if-exists --exit-on-error < "${COPIE}/airflow.dump"

echo "== lac : buckets (versionnage et cycle de vie posés par minio-init), puis miroir de la copie"
compose up -d --wait minio
compose run --rm minio-init > /dev/null
# `--remove` : sans lui, les journaux Delta postérieurs à la copie resteraient et pointeraient vers
# des fichiers absents. Les objets retirés restent récupérables grâce au versionnage des buckets.
docker run --rm --network "${PILE}_genomique-network" --user "$(id -u):$(id -g)" \
  --security-opt no-new-privileges:true --entrypoint sh \
  -e MC_HOST_lac="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000" \
  -v "${COPIE}:/sauvegarde:ro" "${MC_IMAGE}" \
  -c 'for b in raw bronze silver gold; do mc --config-dir /tmp/mc mirror --quiet --overwrite --remove "/sauvegarde/$b" "lac/$b" > /dev/null || exit 1; done'

echo "== base RAG : schéma et comptes (mots de passe depuis .env), puis contenu"
compose up -d --wait rag-postgres
compose run --rm rag-postgres-init
docker exec -i "${PILE}-rag-postgres" pg_restore -U rag_owner -d rag \
  --clean --if-exists --exit-on-error < "${COPIE}/rag.dump"

echo "== redémarrage"
compose up -d --wait "${SERVICES[@]}"
echo "restauration terminée : ${PILE} redonne l'état de la copie ${COPIE}"
