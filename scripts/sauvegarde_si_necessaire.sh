#!/usr/bin/env bash
# Lance scripts/sauvegarde.sh seulement si la dernière copie a plus de 7 jours ou précède un run de panel réussi.
# Cron horaire : une machine éteinte à l'échéance est rattrapée à l'heure suivante, sans copie inutile.
#   0 * * * * cd /chemin/du/depot && ./scripts/sauvegarde_si_necessaire.sh >> ~/sauvegarde.log 2>&1
set -euo pipefail
DESTINATION="${DESTINATION_SAUVEGARDE:-$HOME/sauvegardes-genomique}"
AGE_MAXIMAL_JOURS="${AGE_MAXIMAL_JOURS:-7}"
PG_AIRFLOW=genomique-postgres

# Un seul exemplaire à la fois : une sauvegarde de 1,7 Go peut dépasser l'heure sur un disque lent.
exec 9> "${TMPDIR:-/tmp}/genomique-sauvegarde.lock"
flock -n 9 || exit 0

requete() {
  docker exec "${PG_AIRFLOW}" psql -U airflow -d airflow -At -c "$1"
}

if [ "$(docker inspect -f '{{.State.Health.Status}}' "${PG_AIRFLOW}" 2>/dev/null)" != healthy ]; then
  exit 0  # pile arrêtée : rien à copier, l'heure suivante réessaiera
fi
# Une copie prise pendant un run mélangerait deux états du lac.
if [ "$(requete "SELECT count(*) FROM dag_run WHERE state IN ('running', 'queued')")" != 0 ]; then
  echo "$(date '+%F %T') sauvegarde reportée : un run Airflow est en cours"
  exit 0
fi

# Les dossiers de copie sont nommés AAAA-MM-JJ-HHMM (heure locale) par scripts/sauvegarde.sh.
derniere="$(ls -1d "${DESTINATION}"/*/ 2>/dev/null | sort | tail -n 1 || true)"
derniere="$(basename "${derniere%/}" 2>/dev/null || true)"
if [[ "${derniere}" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2})-([0-9]{2})([0-9]{2})$ ]]; then
  copie_le="$(date -d "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}:${BASH_REMATCH[3]}" +%s)"
else
  copie_le=0
fi

raison=""
if [ "$(( $(date +%s) - copie_le ))" -gt "$(( AGE_MAXIMAL_JOURS * 86400 ))" ]; then
  raison="dernière copie de plus de ${AGE_MAXIMAL_JOURS} jours (${derniere:-aucune})"
else
  dernier_run="$(requete "SELECT coalesce(floor(extract(epoch FROM max(end_date))), 0) FROM dag_run
    WHERE dag_id LIKE 'dag_genomic_pipeline_%' AND state = 'success'")"
  if [ "${dernier_run}" -gt "${copie_le}" ]; then
    raison="run de panel réussi depuis la copie ${derniere}"
  fi
fi

if [ -n "${raison}" ]; then
  echo "$(date '+%F %T') sauvegarde : ${raison}"
  ./scripts/sauvegarde.sh
fi
