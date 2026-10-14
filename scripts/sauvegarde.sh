#!/usr/bin/env bash
# Sauvegarde du lac MinIO, de la base de métadonnées Airflow et de la base vectorielle du RAG.
#
# Pourquoi : les archives mensuelles ClinVar antérieures à 2023 ne sont plus
# accessibles par l'URL épinglée. Une perte du lac ne se rattrape donc pas par un
# simple rejeu : l'historique des reclassifications serait définitivement perdu.
# La base vectorielle se reconstruit depuis le Gold, mais en ~4 h sur CPU (tous les
# embeddings recalculés) : sa copie ramène ce délai à quelques minutes.
#
# Chaque dump est relu (`pg_restore --list`) aussitôt écrit : un fichier illisible
# arrête le script en erreur au lieu d'annoncer une sauvegarde réussie. La
# restauration complète se vérifie avec `scripts/verifier_restauration_rag.sh`.
#
# À lancer depuis la racine du dépôt, stack démarrée. Exemple de planification
# hebdomadaire (le dimanche à 3 h) via `crontab -e` :
#   0 3 * * 0 cd /chemin/vers/Projet-_de_Memoire && ./scripts/sauvegarde.sh >> ~/sauvegarde.log 2>&1
set -euo pipefail
# Copies lisibles par le seul propriétaire : le dump Airflow peut contenir des connexions.
umask 077

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

# Dump d'une base PostgreSQL depuis son conteneur, par le socket local : l'image officielle
# y accepte le compte sans mot de passe (`local all all trust` dans pg_hba.conf), si bien
# qu'aucun secret ne transite ni n'apparaît dans la liste des processus. Aucun client
# PostgreSQL n'est requis sur l'hôte. Le dump est relu dans la foulée.
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
# Conteneur `mc` jetable, raccroché au réseau de la stack : il joint MinIO par son
# nom de service, sans dépendre des ports publiés sur l'hôte.
# `--entrypoint sh` : l'image a `mc` comme point d'entrée, donc sans cela la boucle
# lui serait passée comme sous-commande.
# `--user` : sans lui, `mc` tourne en root et les copies appartiennent à root ; la rotation
# ci-dessous (lancée par l'utilisateur) ne pourrait plus les supprimer et ferait échouer la
# sauvegarde suivante (défaut constaté le 14/10/2026). `--config-dir` : HOME n'est pas
# inscriptible sous un utilisateur arbitraire.
docker run --rm \
  --network genomique_genomique-network \
  --user "$(id -u):$(id -g)" \
  --security-opt no-new-privileges:true \
  --entrypoint sh \
  -e MC_HOST_lac="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000" \
  -v "${CIBLE}:/sauvegarde" \
  quay.io/minio/mc@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727 \
  -c 'for b in raw bronze silver gold; do mc --config-dir /tmp/mc mirror --quiet --overwrite "lac/$b" "/sauvegarde/$b" > /dev/null || exit 1; done'
echo "   $(du -sh "${CIBLE}" | cut -f1) au total"

echo "== rotation : on garde les ${COPIES_CONSERVEES} dernières"
# `tail -n +N` saute les copies à conserver et ne liste que le surplus.
ls -1d "${DESTINATION}"/*/ 2>/dev/null | sort -r | tail -n "+$((COPIES_CONSERVEES + 1))" | while read -r ancienne; do
  echo "   suppression de ${ancienne}"
  rm -rf "${ancienne}"
done

echo "sauvegarde terminée : ${CIBLE}"
