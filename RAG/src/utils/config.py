"""Configuration du RAG : `config.yaml` pour les réglages, l'environnement pour les
secrets et les adresses de service. Aucun secret n'est écrit dans le dépôt."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from psycopg.conninfo import make_conninfo

from RAG.src.utils.errors import RagConfigurationError

RAG_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = RAG_ROOT / "config.yaml"
# Racine du dépôt : `/opt/projet` dans les conteneurs Airflow, où `./data` est monté.
PROJECT_ROOT = RAG_ROOT.parent
# Dossiers exportés par docker/embeddings/export_model.py, servis par rag-embeddings.
MODELS_DIR = PROJECT_ROOT / "data" / "models"
EXPORT_MANIFEST = "export.json"

# Plafond du service d'embedding (`--max-client-batch-size`, 32 par défaut) : au-delà,
# il répond 422 (vérifié le 02/10/2026 sur l'image cpu-1.9).
MAX_CLIENT_BATCH_SIZE = 32

_SERVICE_VARIABLES = (
    "RAG_EMBEDDINGS_URL",
    "RAG_EMBEDDINGS_API_KEY",
    "RAG_PG_HOST",
    "RAG_PG_DB",
    "RAG_PG_USER",
    "RAG_PG_PASSWORD",
    # Même variable que celle qui choisit le dossier servi par rag-embeddings
    # (docker-compose.yml) : c'est elle qui relie l'empreinte au modèle réellement servi.
    "RAG_EMBEDDING_MODEL",
)


@dataclass(frozen=True)
class EmbeddingSettings:
    fingerprint: str
    canary_path: Path
    canary_min_cosine: float
    batch_size: int
    request_timeout_s: float


@dataclass(frozen=True)
class IndexSettings:
    max_delete_ratio: float


@dataclass(frozen=True)
class RagConfig:
    embedding: EmbeddingSettings
    index: IndexSettings


@dataclass(frozen=True)
class ServiceSettings:
    embeddings_url: str
    embeddings_api_key: str
    pg_conninfo: str
    served_model_dir: Path


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> RagConfig:
    """Lit et valide `config.yaml`. Toute anomalie est une `RagConfigurationError` :
    une configuration fausse ne se corrige pas en relançant."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        embedding, index = raw["embedding"], raw["index"]
        settings = EmbeddingSettings(
            fingerprint=str(embedding["fingerprint"] or "").strip(),
            canary_path=RAG_ROOT / embedding["canary_file"],
            canary_min_cosine=float(embedding["canary_min_cosine"]),
            batch_size=int(embedding["batch_size"]),
            request_timeout_s=float(embedding["request_timeout_s"]),
        )
        index_settings = IndexSettings(max_delete_ratio=float(index["max_delete_ratio"]))
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise RagConfigurationError(f"{path} illisible ou incomplet : {exc!r}") from exc

    if not settings.fingerprint:
        raise RagConfigurationError(
            f"{path} : embedding.fingerprint est vide, aucun modèle n'a encore été "
            "validé (RAG/README.md, « Installer le modèle »)."
        )
    if not 1 <= settings.batch_size <= MAX_CLIENT_BATCH_SIZE:
        raise RagConfigurationError(
            f"{path} : embedding.batch_size doit être entre 1 et {MAX_CLIENT_BATCH_SIZE}."
        )
    if not 0 < settings.canary_min_cosine <= 1:
        raise RagConfigurationError(f"{path} : embedding.canary_min_cosine hors de ]0, 1].")
    if not 0 <= index_settings.max_delete_ratio < 1:
        raise RagConfigurationError(f"{path} : index.max_delete_ratio hors de [0, 1[.")
    return RagConfig(embedding=settings, index=index_settings)


def load_service_settings(env: Mapping[str, str] | None = None) -> ServiceSettings:
    """Adresses et secrets des services, lus dans l'environnement du conteneur.
    Toutes les variables manquantes sont nommées d'un coup, pour un seul aller-retour."""
    env = os.environ if env is None else env
    missing = [name for name in _SERVICE_VARIABLES if not env.get(name)]
    if missing:
        raise RagConfigurationError(f"variables d'environnement manquantes : {', '.join(missing)}")
    model_name = env["RAG_EMBEDDING_MODEL"]
    if not model_name.strip() or model_name == "." or any(c in model_name for c in ("/", "\\", "..")):
        raise RagConfigurationError(
            f"RAG_EMBEDDING_MODEL invalide ({model_name!r}) : attendu un nom de dossier de "
            f"{MODELS_DIR}, sans « / », « \\ » ni « .. »"
        )
    # make_conninfo échappe chaque valeur : un mot de passe contenant une apostrophe
    # ou un espace ne peut pas injecter un paramètre de connexion.
    conninfo = make_conninfo(
        host=env["RAG_PG_HOST"],
        port=env.get("RAG_PG_PORT") or "5432",
        dbname=env["RAG_PG_DB"],
        user=env["RAG_PG_USER"],
        password=env["RAG_PG_PASSWORD"],
    )
    return ServiceSettings(
        embeddings_url=env["RAG_EMBEDDINGS_URL"].rstrip("/"),
        embeddings_api_key=env["RAG_EMBEDDINGS_API_KEY"],
        pg_conninfo=conninfo,
        served_model_dir=MODELS_DIR / model_name,
    )


def served_fingerprint(model_dir: Path) -> str:
    """Empreinte écrite par l'export dans `export.json` du dossier servi."""
    path = model_dir / EXPORT_MANIFEST
    try:
        fingerprint = str(json.loads(path.read_text(encoding="utf-8"))["fingerprint"] or "").strip()
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise RagConfigurationError(f"{path} illisible ou incomplet : {exc!r}") from exc
    if not fingerprint:
        raise RagConfigurationError(f"{path} : empreinte vide, réexporter le modèle (RAG/README.md)")
    return fingerprint


def check_served_model(config_fingerprint: str, served: str) -> None:
    """Refuse un modèle servi différent de celui que `config.yaml` attend : sans ce
    contrôle, des vecteurs d'un modèle porteraient l'empreinte de l'autre."""
    if served != config_fingerprint:
        raise RagConfigurationError(
            f"le dossier servi (RAG_EMBEDDING_MODEL) porte l'empreinte « {served} », "
            f"config.yaml attend « {config_fingerprint} » : aligner .env et config.yaml "
            "(RAG/README.md, « Changer de modèle »)"
        )
