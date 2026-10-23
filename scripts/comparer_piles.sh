#!/usr/bin/env bash
# Vérifie qu'une pile restaurée par scripts/restaurer.sh redonne la copie : bases Airflow et RAG, lac.
# Usage (racine du dépôt, les deux piles démarrées) : ./scripts/comparer_piles.sh <copie> genomique-e3b
# Référence des bases : la pile principale, supposée inchangée depuis la copie (aucun run ni indexation).
set -euo pipefail

# Même image `mc` que scripts/sauvegarde.sh, construite par docker compose (docker/minio/Dockerfile).
MC_IMAGE=genomique/minio-mc:RELEASE.2025-08-13T08-35-41Z
PRINCIPALE=genomique

if [ "$#" -ne 2 ]; then
  echo "usage : $0 <dossier de copie> <pile restaurée>" >&2
  exit 2
fi
COPIE="${1%/}"
PILE="$2"
if [ "${PILE}" = "${PRINCIPALE}" ]; then
  echo "erreur : la pile principale sert de référence, elle ne peut pas être comparée à elle-même" >&2
  exit 2
fi
for f in airflow.dump rag.dump raw bronze silver gold; do
  [ -e "${COPIE}/${f}" ] || { echo "erreur : ${f} absent de la copie ${COPIE}" >&2; exit 1; }
done
if [ ! -f .env ] || [ ! -f scripts/verifier_restauration_lac.py ]; then
  echo "erreur : lancer depuis la racine du dépôt" >&2
  exit 1
fi
COPIE="$(cd "${COPIE}" && pwd)"

set -a  # exporte les variables du .env
# Sans les CR : un .env édité sous Windows ferait échouer `.` (Docker Compose, lui, les tolère).
# shellcheck disable=SC1090
. <(tr -d '\r' < .env)
set +a
# shellcheck source=scripts/lib/empreintes.sh
. scripts/lib/empreintes.sh

RETOUR=""
nettoyer() { if [ -n "${RETOUR}" ]; then rm -rf "${RETOUR}"; fi; }
trap nettoyer EXIT
RETOUR="$(mktemp -d)"
ecarts=0

echo "== copie : ${COPIE} ; pile restaurée : ${PILE}"

echo "== base Airflow : pile restaurée contre pile principale, historique antérieur au dump"
CREE_LE="$(docker exec -i "${PRINCIPALE}-postgres" pg_restore --list < "${COPIE}/airflow.dump" \
  | sed -n 's/^; Archive created at //p')"
echo "   dump créé le ${CREE_LE}"
empreintes_airflow "${CREE_LE}"
comparer_requetes airflow airflow "${PRINCIPALE}-postgres" "${PILE}-postgres" "principale" "restaurée "

echo "== base RAG : pile restaurée contre pile principale"
empreintes_rag
comparer_requetes rag_owner rag "${PRINCIPALE}-rag-postgres" "${PILE}-rag-postgres" "principale" "restaurée "

echo "== lac : buckets de la pile restaurée recopiés, puis comparés octet pour octet à la copie"
# `--user` : copies de retour à l'UID de l'hôte, supprimables par `nettoyer`.
docker run --rm --network "${PILE}_genomique-network" --user "$(id -u):$(id -g)" \
  --security-opt no-new-privileges:true --entrypoint sh \
  -e MC_HOST_lac="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000" \
  -v "${RETOUR}:/retour" "${MC_IMAGE}" \
  -c 'for b in raw bronze silver gold; do mc --config-dir /tmp/mc mirror --quiet "lac/$b" "/retour/$b" > /dev/null || exit 1; done'
attendu="$(empreintes_fichiers "${COPIE}")"
obtenu="$(empreintes_fichiers "${RETOUR}")"
objets="$(printf '%s\n' "${attendu}" | wc -l)"
if [ "${attendu}" = "${obtenu}" ]; then
  echo "   OK     ${objets} objets identiques octet pour octet"
else
  echo "   ÉCART  objets différents entre la copie et la pile restaurée :"
  # `|| true` : diff renvoie 1 quand il trouve un écart, ce qui arrêterait le script (pipefail).
  { diff <(printf '%s\n' "${attendu}") <(printf '%s\n' "${obtenu}") || true; } | head -n 10 | sed 's/^/          /'
  ecarts=$((ecarts + 1))
fi

echo "== tables Delta relues dans la pile restaurée (silver, gold)"
# Compte de service du pipeline, limité aux quatre buckets ; groupe 0 pour les bibliothèques de l'image.
if ! docker run --rm --network "${PILE}_genomique-network" --user "$(id -u):0" \
  --security-opt no-new-privileges:true \
  -e HOME=/tmp -e AWS_ENDPOINT_URL=http://minio:9000 -e AWS_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID="${MINIO_AIRFLOW_USER}" -e AWS_SECRET_ACCESS_KEY="${MINIO_AIRFLOW_PASSWORD}" \
  -v "${PWD}:/opt/projet:ro" -v "${COPIE}:/sauvegarde:ro" \
  --entrypoint /home/airflow/.local/bin/python \
  "$(docker inspect "${PILE}-airflow-scheduler" --format '{{.Config.Image}}')" \
  /opt/projet/scripts/verifier_restauration_lac.py --restaure s3:// --sauvegarde file:///sauvegarde; then
  ecarts=$((ecarts + 1))
fi

if [ "${ecarts}" -ne 0 ]; then
  echo "pile ${PILE} NON conforme à la copie : ${ecarts} écart(s)" >&2
  exit 1
fi
echo "pile ${PILE} conforme : elle redonne la copie ${COPIE}"
