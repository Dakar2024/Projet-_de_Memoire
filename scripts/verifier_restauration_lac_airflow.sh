#!/usr/bin/env bash
# Restaure une sauvegarde (base Airflow, buckets MinIO) dans des conteneurs jetables isolés et vérifie sa fidélité.
# Usage (racine du dépôt, stack démarrée) : ./scripts/verifier_restauration_lac_airflow.sh [/chemin/vers/<date>]
set -euo pipefail

DESTINATION="${DESTINATION_SAUVEGARDE:-$HOME/sauvegardes-genomique}"
PG_EN_SERVICE=genomique-postgres
MINIO_EN_SERVICE=genomique-minio
AIRFLOW_EN_SERVICE=genomique-airflow-scheduler
PREFIXE=genomique-restauration-lac
RESEAU="${PREFIXE}-reseau"
PG_JETABLE="${PREFIXE}-postgres"
MINIO_JETABLE="${PREFIXE}-minio"
# Même image `mc` que scripts/sauvegarde.sh, construite par docker compose (docker/minio/Dockerfile).
MC_IMAGE=genomique/minio-mc:RELEASE.2025-08-13T08-35-41Z
BUCKETS="raw bronze silver gold"

if [ "$#" -ge 1 ]; then
  SAUVEGARDE="${1%/}"
else
  SAUVEGARDE="$(ls -1d "${DESTINATION}"/*/ 2>/dev/null | sort | tail -n 1 || true)"
  SAUVEGARDE="${SAUVEGARDE%/}"
fi
if [ -z "${SAUVEGARDE}" ] || [ ! -f "${SAUVEGARDE}/airflow.dump" ]; then
  echo "erreur : aucune sauvegarde trouvée (${DESTINATION}/<date>/airflow.dump ou argument)" >&2
  exit 1
fi
for b in ${BUCKETS}; do
  [ -d "${SAUVEGARDE}/${b}" ] || { echo "erreur : bucket ${b} absent de ${SAUVEGARDE}" >&2; exit 1; }
done
if [ ! -f scripts/verifier_restauration_lac.py ]; then
  echo "erreur : lancer depuis la racine du dépôt (scripts/verifier_restauration_lac.py introuvable)" >&2
  exit 1
fi
# shellcheck source=scripts/lib/empreintes.sh
. scripts/lib/empreintes.sh

aleatoire() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
RETOUR=""
nettoyer() {
  docker rm -f "${PG_JETABLE}" "${MINIO_JETABLE}" > /dev/null 2>&1 || true
  docker network rm "${RESEAU}" > /dev/null 2>&1 || true
  if [ -n "${RETOUR}" ]; then rm -rf "${RETOUR}"; fi
}
trap nettoyer EXIT
nettoyer
RETOUR="$(mktemp -d)"
ecarts=0

echo "== sauvegarde : ${SAUVEGARDE}"

# ---------------------------------------------------------------- base Airflow
echo "== base Airflow : restauration dans un PostgreSQL jetable sans réseau"
docker run -d --name "${PG_JETABLE}" --network none --memory 1g \
  --security-opt no-new-privileges:true \
  -e POSTGRES_USER=airflow -e POSTGRES_DB=airflow -e POSTGRES_PASSWORD="$(aleatoire)" \
  "$(docker inspect "${PG_EN_SERVICE}" --format '{{.Config.Image}}')" > /dev/null
# TCP et non socket : le serveur temporaire d'initialisation n'écoute que sur le socket.
for _ in $(seq 1 60); do
  docker exec "${PG_JETABLE}" pg_isready -h 127.0.0.1 -U airflow -d airflow > /dev/null 2>&1 && break
  sleep 1
done
docker exec "${PG_JETABLE}" pg_isready -h 127.0.0.1 -U airflow -d airflow > /dev/null
debut=$(date +%s)
docker exec -i "${PG_JETABLE}" pg_restore -U airflow -d airflow --clean --if-exists --exit-on-error \
  < "${SAUVEGARDE}/airflow.dump"
echo "   restaurée en $(( $(date +%s) - debut )) s"

# Seul l'historique figé au moment du dump se compare à la base en service : runs et tâches terminés avant.
CREE_LE="$(docker exec -i "${PG_JETABLE}" pg_restore --list < "${SAUVEGARDE}/airflow.dump" \
  | sed -n 's/^; Archive created at //p')"
echo "   dump créé le ${CREE_LE}"
empreintes_airflow "${CREE_LE}"
comparer_requetes airflow airflow "${PG_EN_SERVICE}" "${PG_JETABLE}" "en service" "restaurée "

# ---------------------------------------------------------------- buckets MinIO
echo "== buckets : chargement dans un MinIO jetable, sur un réseau interne sans sortie"
docker network create --internal "${RESEAU}" > /dev/null
MINIO_UTILISATEUR="restauration"
MINIO_MOT_DE_PASSE="$(aleatoire)"
docker run -d --name "${MINIO_JETABLE}" --network "${RESEAU}" --network-alias minio --memory 2g \
  --security-opt no-new-privileges:true \
  -e MINIO_ROOT_USER="${MINIO_UTILISATEUR}" -e MINIO_ROOT_PASSWORD="${MINIO_MOT_DE_PASSE}" \
  "$(docker inspect "${MINIO_EN_SERVICE}" --format '{{.Config.Image}}')" server /data > /dev/null
# Aller (sauvegarde → MinIO) puis retour (MinIO → disque) : la comparaison porte sur ce que MinIO a gardé.
# `--user` : copies de retour à l'UID de l'hôte, supprimables par `nettoyer`.
debut=$(date +%s)
docker run --rm --network "${RESEAU}" --user "$(id -u):$(id -g)" --security-opt no-new-privileges:true \
  --entrypoint sh \
  -e MC_HOST_t="http://${MINIO_UTILISATEUR}:${MINIO_MOT_DE_PASSE}@minio:9000" \
  -v "${SAUVEGARDE}:/sauvegarde:ro" -v "${RETOUR}:/retour" \
  "${MC_IMAGE}" -c "
    for _ in \$(seq 1 30); do mc --config-dir /tmp/mc ls t > /dev/null 2>&1 && break; sleep 1; done
    for b in ${BUCKETS}; do
      mc --config-dir /tmp/mc mb --ignore-existing t/\$b > /dev/null &&
      mc --config-dir /tmp/mc mirror --quiet /sauvegarde/\$b t/\$b > /dev/null &&
      mc --config-dir /tmp/mc mirror --quiet t/\$b /retour/\$b > /dev/null || exit 1
    done"
echo "   aller-retour en $(( $(date +%s) - debut )) s"

attendu="$(empreintes_fichiers "${SAUVEGARDE}")"
obtenu="$(empreintes_fichiers "${RETOUR}")"
objets="$(printf '%s\n' "${attendu}" | wc -l)"
if [ "${attendu}" = "${obtenu}" ]; then
  echo "   OK     ${objets} objets identiques octet pour octet ($(du -sh "${SAUVEGARDE}" --exclude='*.dump' | cut -f1))"
else
  echo "   ÉCART  objets différents entre la sauvegarde et le MinIO restauré :"
  # `|| true` : diff renvoie 1 quand il trouve un écart, ce qui arrêterait le script (pipefail).
  { diff <(printf '%s\n' "${attendu}") <(printf '%s\n' "${obtenu}") || true; } | head -n 10 | sed 's/^/          /'
  ecarts=$((ecarts + 1))
fi

echo "== tables Delta relues depuis le MinIO restauré (silver, gold)"
# UID de l'hôte pour lire la sauvegarde (umask 077) ; groupe 0 pour les bibliothèques de l'image (convention OpenShift).
if ! docker run --rm --network "${RESEAU}" --user "$(id -u):0" --security-opt no-new-privileges:true \
  -e HOME=/tmp -e AWS_ENDPOINT_URL=http://minio:9000 \
  -e AWS_ACCESS_KEY_ID="${MINIO_UTILISATEUR}" -e AWS_SECRET_ACCESS_KEY="${MINIO_MOT_DE_PASSE}" \
  -v "${PWD}:/opt/projet:ro" -v "${SAUVEGARDE}:/sauvegarde:ro" \
  --entrypoint /home/airflow/.local/bin/python \
  "$(docker inspect "${AIRFLOW_EN_SERVICE}" --format '{{.Config.Image}}')" \
  /opt/projet/scripts/verifier_restauration_lac.py --restaure s3:// --sauvegarde file:///sauvegarde; then
  ecarts=$((ecarts + 1))
fi

if [ "${ecarts}" -ne 0 ]; then
  echo "restauration NON conforme : ${ecarts} écart(s)" >&2
  exit 1
fi
echo "restauration conforme : la sauvegarde ${SAUVEGARDE} redonne la base Airflow et le lac"
