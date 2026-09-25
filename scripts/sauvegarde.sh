#!/usr/bin/env bash
# Sauvegarde du lac MinIO et de la base de métadonnées Airflow.
#
# Pourquoi : les archives mensuelles ClinVar antérieures à 2023 ne sont plus
# accessibles par l'URL épinglée. Une perte du lac ne se rattrape donc pas par un
# simple rejeu : l'historique des reclassifications serait définitivement perdu.
#
# À lancer depuis la racine du dépôt, stack démarrée. Exemple de planification
# hebdomadaire (le dimanche à 3 h) via `crontab -e` :
#   0 3 * * 0 cd /chemin/vers/Projet-_de_Memoire && ./scripts/sauvegarde.sh >> ~/sauvegarde.log 2>&1
set -euo pipefail

DESTINATION="${DESTINATION_SAUVEGARDE:-$HOME/sauvegardes-genomique}"
COPIES_CONSERVEES="${COPIES_CONSERVEES:-4}"
HORODATAGE="$(date +%Y-%m-%d-%H%M)"
CIBLE="${DESTINATION}/${HORODATAGE}"

if [ ! -f .env ]; then
  echo "erreur : lancer depuis la racine du dépôt (.env introuvable)" >&2
  exit 1
fi
# `set -a` exporte automatiquement ce que le fichier définit, pour que `mc` le voie.
set -a
# shellcheck disable=SC1091
. ./.env
set +a

mkdir -p "${CIBLE}"

echo "== base de métadonnées Airflow"
# `pg_dump` depuis le conteneur : aucun client PostgreSQL n'est requis sur l'hôte.
docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" genomique-postgres \
  pg_dump --username=airflow --format=custom airflow > "${CIBLE}/airflow.dump"
echo "   $(du -h "${CIBLE}/airflow.dump" | cut -f1)"

echo "== buckets MinIO"
# Conteneur `mc` jetable, raccroché au réseau de la stack : il joint MinIO par son
# nom de service, sans dépendre des ports publiés sur l'hôte.
# `--entrypoint sh` : l'image a `mc` comme point d'entrée, donc sans cela la boucle
# lui serait passée comme sous-commande.
docker run --rm \
  --network genomique_genomique-network \
  --entrypoint sh \
  -e MC_HOST_lac="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000" \
  -v "${CIBLE}:/sauvegarde" \
  quay.io/minio/mc@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727 \
  -c 'for b in raw bronze silver gold; do mc mirror --quiet --overwrite "lac/$b" "/sauvegarde/$b"; done'
echo "   $(du -sh "${CIBLE}" | cut -f1) au total"

echo "== rotation : on garde les ${COPIES_CONSERVEES} dernières"
# `tail -n +N` saute les copies à conserver et ne liste que le surplus.
ls -1d "${DESTINATION}"/*/ 2>/dev/null | sort -r | tail -n "+$((COPIES_CONSERVEES + 1))" | while read -r ancienne; do
  echo "   suppression de ${ancienne}"
  rm -rf "${ancienne}"
done

echo "sauvegarde terminée : ${CIBLE}"
