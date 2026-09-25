"""Alerte par e-mail à l'échec d'une tâche.

Le pipeline tourne une fois par mois sans surveillance : sans alerte, un échec ne
se voit qu'en ouvrant l'interface. Le cas le plus coûteux n'est même pas visible
là : si l'acquisition échoue, l'Asset de fin n'est jamais émis et les DAGs de panel
ne se déclenchent pas du tout — le mois est simplement absent.

L'envoi passe par le serveur SMTP configuré dans `docker-compose.yml` (variables
`AIRFLOW__SMTP__*`, toutes alimentées par le `.env`) : le fournisseur reste libre.
Aucune adresse n'est écrite dans le dépôt — le destinataire vient de l'environnement,
et une valeur absente désactive simplement l'envoi sans rien casser.
"""

from __future__ import annotations

import os


def alert_args() -> dict:
    """Arguments par défaut d'un DAG pour l'alerte : destinataire et déclencheurs.

    Pas d'alerte sur une tentative intermédiaire (`email_on_retry`) : les erreurs
    réseau transitoires sont normales sur des sources publiques, et une alerte par
    tentative apprendrait vite à être ignorée.
    """
    destinataires = [a.strip() for a in os.environ.get("ALERT_EMAIL", "").split(",") if a.strip()]
    return {
        "email": destinataires,
        "email_on_failure": bool(destinataires),
        "email_on_retry": False,
    }
