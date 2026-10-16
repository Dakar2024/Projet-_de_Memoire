"""Point d'entrée local de l'API RAG : `uvicorn app:app --port 8000 --reload` depuis la racine.

Lance l'API hors Docker, sur l'hôte. Les variables que docker-compose.yml fournit au
conteneur rag-api sont reconstituées ici : `.env` est lu, et la base et l'embedding
sont joints par l'IP de leur conteneur (ils ne publient aucun port). Pas de passerelle
nginx ni de proxy Squid devant : réservé au développement.
"""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
# Comme PYTHONPATH=/opt/projet:/opt/projet/src dans le conteneur.
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
# Une variable déjà exportée dans le shell l'emporte sur `.env`.
load_dotenv(ROOT / ".env", override=False)


def _container_ip(name: str) -> str:
    """Renvoie l'IP du conteneur sur le réseau genomique_rag-network."""
    fmt = '{{(index .NetworkSettings.Networks "genomique_rag-network").IPAddress}}'
    return subprocess.run(["docker", "inspect", "-f", fmt, name],
                          check=True, capture_output=True, text=True).stdout.strip()


# setdefault : chaque valeur reste surchargeable depuis le shell.
if "RAG_PG_HOST" not in os.environ:
    os.environ["RAG_PG_HOST"] = _container_ip("genomique-rag-postgres")
if "RAG_EMBEDDINGS_URL" not in os.environ:
    os.environ["RAG_EMBEDDINGS_URL"] = f"http://{_container_ip('genomique-rag-embeddings')}:8080"
os.environ.setdefault("RAG_PG_PORT", "5432")
os.environ.setdefault("RAG_PG_DB", "rag")
# Lecture seule, comme le conteneur rag-api.
os.environ.setdefault("RAG_PG_USER", "rag_reader")
os.environ.setdefault("RAG_PG_PASSWORD", os.environ.get("RAG_READER_PASSWORD", ""))

from RAG.src.api.app import create_app  # noqa: E402  (après la préparation de l'environnement)
from RAG.src.utils.config import load_api_config  # noqa: E402

# Documentation OpenAPI (/schema) ouverte en local seulement ; config.yaml la garde fermée en production.
app = create_app(api_config=replace(load_api_config(), openapi=True))
