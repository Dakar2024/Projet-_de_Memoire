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


@dataclass(frozen=True)
class LlmProfile:
    """Un modèle figé sur un point d'accès précis d'OpenRouter : le tag désigne le
    point d'accès dans la requête, le nom est celui que renvoie OpenRouter pour
    dire qui a réellement servi la requête."""

    name: str
    model: str
    provider_tag: str
    provider_name: str
    quantization: str | None


@dataclass(frozen=True)
class SearchConfig:
    k: int
    min_filtered: int
    max_question_chars: int
    analysis_profile: LlmProfile
    profiles: dict[str, LlmProfile]
    llm_timeout_s: float
    llm_max_tokens: int


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


def _profile(name: str, raw: Mapping) -> LlmProfile:
    fields = {key: raw.get(key) for key in ("model", "provider_tag", "provider_name")}
    if not all(isinstance(value, str) and value.strip() for value in fields.values()):
        raise RagConfigurationError(f"profil LLM « {name} » incomplet : model, provider_tag, provider_name")
    quantization = raw.get("quantization")
    if quantization is not None and not (isinstance(quantization, str) and quantization.strip()):
        raise RagConfigurationError(f"profil LLM « {name} » : quantization invalide")
    return LlmProfile(name=name, quantization=quantization, **{k: v.strip() for k, v in fields.items()})


def load_search_config(path: Path = DEFAULT_CONFIG_PATH, profile: str | None = None) -> SearchConfig:
    """Réglages de la recherche (E2a). `profile` remplace le profil d'analyse par
    défaut : la mesure compare ainsi plusieurs modèles sans toucher au fichier."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        search, llm = raw["search"], raw["llm"]
        profiles = {name: _profile(name, value) for name, value in llm["profiles"].items()}
        k = int(search["k"])
        min_filtered = int(search["min_filtered"])
        max_chars = int(search["max_question_chars"])
        chosen = profile if profile is not None else str(llm["analysis_profile"])
        timeout = float(llm["request_timeout_s"])
        max_tokens = int(llm["max_tokens"])
    except (OSError, KeyError, TypeError, ValueError, AttributeError, yaml.YAMLError) as exc:
        raise RagConfigurationError(f"{path} : sections search/llm illisibles ou incomplètes : {exc!r}") from exc
    if not profiles:
        raise RagConfigurationError(f"{path} : aucun profil LLM")
    if chosen not in profiles:
        raise RagConfigurationError(f"{path} : profil d'analyse « {chosen} » absent de llm.profiles")
    if not 1 <= k <= 50:
        raise RagConfigurationError(f"{path} : search.k doit être entre 1 et 50")
    if not 1 <= min_filtered <= k:
        raise RagConfigurationError(f"{path} : search.min_filtered doit être entre 1 et k")
    if not 10 <= max_chars <= 10_000:
        raise RagConfigurationError(f"{path} : search.max_question_chars hors de [10, 10000]")
    if timeout <= 0 or max_tokens < 256:
        raise RagConfigurationError(f"{path} : llm.request_timeout_s > 0 et llm.max_tokens ≥ 256 requis")
    return SearchConfig(
        k=k, min_filtered=min_filtered, max_question_chars=max_chars,
        analysis_profile=profiles[chosen], profiles=profiles,
        llm_timeout_s=timeout, llm_max_tokens=max_tokens,
    )


def load_openrouter_key(env: Mapping[str, str] | None = None) -> str:
    """Clé OpenRouter, lue dans l'environnement. Le message d'erreur nomme la variable,
    jamais sa valeur."""
    env = os.environ if env is None else env
    key = (env.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise RagConfigurationError("OPENROUTER_API_KEY absente ou vide (.env)")
    return key
