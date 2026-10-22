"""Configuration du RAG : réglages dans `config.yaml`, secrets et adresses dans l'environnement."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
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

# Plafond de lot du service d'embedding : au-delà, 422.
MAX_CLIENT_BATCH_SIZE = 32

_SERVICE_VARIABLES = (
    "RAG_EMBEDDINGS_URL",
    "RAG_EMBEDDINGS_API_KEY",
    "RAG_PG_HOST",
    "RAG_PG_DB",
    "RAG_PG_USER",
    "RAG_PG_PASSWORD",
    # Dossier servi par rag-embeddings : relie l'empreinte au modèle réellement servi.
    "RAG_EMBEDDING_MODEL",
)


@dataclass(frozen=True)
class EmbeddingSettings:
    """Réglages d'embedding de `config.yaml`."""

    fingerprint: str
    canary_path: Path
    canary_min_cosine: float
    batch_size: int
    request_timeout_s: float


@dataclass(frozen=True)
class IndexSettings:
    """Réglages d'indexation de `config.yaml`."""

    max_delete_ratio: float


@dataclass(frozen=True)
class RagConfig:
    """Configuration de l'indexation."""

    embedding: EmbeddingSettings
    index: IndexSettings


@dataclass(frozen=True)
class ServiceSettings:
    """Adresses et secrets des services, lus dans l'environnement."""

    embeddings_url: str
    embeddings_api_key: str
    pg_conninfo: str
    served_model_dir: Path


# Clients LLM : `groq` (candidats, offre gratuite), `gemini` (juge de E3a), `openrouter` (en réserve, payant).
LLM_BACKENDS = ("openrouter", "groq", "gemini")


@dataclass(frozen=True)
class LlmProfile:
    """Modèle figé sur un point d'accès : tag demandé, nom renvoyé par le fournisseur, client (`backend`)."""

    name: str
    model: str
    provider_tag: str
    provider_name: str
    quantization: str | None
    backend: str = "openrouter"


@dataclass(frozen=True)
class SearchConfig:
    """Réglages de la recherche et du LLM d'analyse."""

    k: int
    min_filtered: int
    max_question_chars: int
    analysis_profile: LlmProfile
    profiles: dict[str, LlmProfile]
    llm_timeout_s: float
    llm_max_tokens: int
    # Profils d'essai : jamais candidats de la règle de choix du modèle.
    trial_profiles: dict[str, LlmProfile] = field(default_factory=dict)
    # Profils OpenRouter en réserve (crédits non achetés) : validés, jamais candidats ni sélectionnables.
    reserve_profiles: dict[str, LlmProfile] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationConfig:
    """Réglages du LLM de génération."""

    profile: LlmProfile
    max_tokens: int
    timeout_s: float


@dataclass(frozen=True)
class ApiConfig:
    """Réglages de l'API."""

    max_concurrency: int
    request_timeout_s: float
    max_body_bytes: int
    openapi: bool


MIN_API_KEY_CHARS = 32


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> RagConfig:
    """Lit et valide la configuration d'indexation ; toute anomalie lève `RagConfigurationError`."""
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
    """Lit les adresses et secrets des services, en nommant d'un coup toutes les variables manquantes."""
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
    # make_conninfo échappe chaque valeur : pas d'injection de paramètre par le mot de passe.
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
    """Renvoie l'empreinte écrite dans `export.json` du dossier servi."""
    path = model_dir / EXPORT_MANIFEST
    try:
        fingerprint = str(json.loads(path.read_text(encoding="utf-8"))["fingerprint"] or "").strip()
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise RagConfigurationError(f"{path} illisible ou incomplet : {exc!r}") from exc
    if not fingerprint:
        raise RagConfigurationError(f"{path} : empreinte vide, réexporter le modèle (RAG/README.md)")
    return fingerprint


def check_served_model(config_fingerprint: str, served: str) -> None:
    """Refuse un modèle servi différent de celui qu'attend `config.yaml`."""
    if served != config_fingerprint:
        raise RagConfigurationError(
            f"le dossier servi (RAG_EMBEDDING_MODEL) porte l'empreinte « {served} », "
            f"config.yaml attend « {config_fingerprint} » : aligner .env et config.yaml "
            "(RAG/README.md, « Changer de modèle »)"
        )


def _profile(name: str, raw: Mapping) -> LlmProfile:
    """Valide et construit un profil LLM."""
    fields = {key: raw.get(key) for key in ("model", "provider_tag", "provider_name")}
    if not all(isinstance(value, str) and value.strip() for value in fields.values()):
        raise RagConfigurationError(f"profil LLM « {name} » incomplet : model, provider_tag, provider_name")
    quantization = raw.get("quantization")
    if quantization is not None and not (isinstance(quantization, str) and quantization.strip()):
        raise RagConfigurationError(f"profil LLM « {name} » : quantization invalide")
    backend = raw.get("backend", "openrouter")
    if backend not in LLM_BACKENDS:
        raise RagConfigurationError(f"profil LLM « {name} » : backend {backend!r} inconnu, "
                                    f"attendu {' ou '.join(LLM_BACKENDS)}")
    return LlmProfile(name=name, quantization=quantization, backend=backend,
                      **{k: v.strip() for k, v in fields.items()})


def _refuse_gemini(path: Path, *sections: Mapping[str, LlmProfile]) -> None:
    """Refuse Gemini dans config.yaml : son offre gratuite réutilise les données, elle ne sert qu'au juge de E3a."""
    names = sorted(name for section in sections for name, p in section.items() if p.backend == "gemini")
    if names:
        raise RagConfigurationError(f"{path} : profils sur l'offre gratuite de Gemini {names} : elle sert au "
                                    "juge de E3a seulement (Google réutilise les requêtes)")


def load_search_config(path: Path = DEFAULT_CONFIG_PATH, profile: str | None = None) -> SearchConfig:
    """Lit les réglages de recherche ; `profile` remplace le profil d'analyse (officiel ou d'essai)."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        search, llm = raw["search"], raw["llm"]
        profiles = {name: _profile(name, value) for name, value in llm["profiles"].items()}
        trials = {name: _profile(name, value) for name, value in (llm.get("trial_profiles") or {}).items()}
        reserve = {name: _profile(name, value) for name, value in (llm.get("reserve_profiles") or {}).items()}
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
    # Les profils officiels concourent à la règle de choix : Groq depuis le 22/10/2026 (pas de crédits OpenRouter).
    _refuse_gemini(path, profiles, trials, reserve)
    both = sorted((set(profiles) & set(trials)) | (set(reserve) & (set(profiles) | set(trials))))
    if both:
        raise RagConfigurationError(f"{path} : profils présents dans plusieurs sections {both}")
    if chosen not in profiles and chosen not in trials:
        raise RagConfigurationError(
            f"{path} : profil d'analyse « {chosen} » absent de llm.profiles et de llm.trial_profiles")
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
        analysis_profile=profiles.get(chosen) or trials[chosen], profiles=profiles,
        llm_timeout_s=timeout, llm_max_tokens=max_tokens, trial_profiles=trials, reserve_profiles=reserve,
    )


def load_openrouter_key(env: Mapping[str, str] | None = None) -> str:
    """Lit la clé OpenRouter ; l'erreur nomme la variable, jamais sa valeur."""
    env = os.environ if env is None else env
    key = (env.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise RagConfigurationError("OPENROUTER_API_KEY absente ou vide (.env)")
    return key


def load_groq_key(env: Mapping[str, str] | None = None) -> str:
    """Lit la clé Groq ; l'erreur nomme la variable, jamais sa valeur."""
    env = os.environ if env is None else env
    key = (env.get("GROQ_API_KEY") or "").strip()
    if not key:
        raise RagConfigurationError("GROQ_API_KEY absente ou vide (.env)")
    return key


def load_gemini_key(env: Mapping[str, str] | None = None) -> str:
    """Lit la clé Gemini (juge de E3a) ; l'erreur nomme la variable, jamais sa valeur."""
    env = os.environ if env is None else env
    key = (env.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise RagConfigurationError("GEMINI_API_KEY absente ou vide (.env)")
    return key


def load_generation_config(path: Path = DEFAULT_CONFIG_PATH) -> GenerationConfig:
    """Lit le profil de génération, cherché parmi les profils officiels puis d'essai."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        llm = raw["llm"]
        profiles = {name: _profile(name, value) for name, value in llm["profiles"].items()}
        trials = {name: _profile(name, value) for name, value in (llm.get("trial_profiles") or {}).items()}
        chosen = str(llm["generation_profile"])
        max_tokens = int(llm["generation_max_tokens"])
        timeout = float(llm["request_timeout_s"])
    except (OSError, KeyError, TypeError, ValueError, AttributeError, yaml.YAMLError) as exc:
        raise RagConfigurationError(f"{path} : llm.generation_profile / generation_max_tokens illisibles : {exc!r}") from exc
    _refuse_gemini(path, profiles, trials)
    profile = profiles.get(chosen) or trials.get(chosen)
    if profile is None:
        raise RagConfigurationError(f"{path} : llm.generation_profile « {chosen} » absent des profils")
    if max_tokens < 1024 or timeout <= 0:
        raise RagConfigurationError(f"{path} : llm.generation_max_tokens ≥ 1024 et request_timeout_s > 0 requis")
    return GenerationConfig(profile=profile, max_tokens=max_tokens, timeout_s=timeout)


def load_api_config(path: Path = DEFAULT_CONFIG_PATH) -> ApiConfig:
    """Lit et valide la section `api` de `config.yaml`."""
    try:
        api = yaml.safe_load(path.read_text(encoding="utf-8"))["api"]
        # Vrai booléen YAML exigé : bool("false") vaudrait True et exposerait /schema sans clé.
        if not isinstance(api["openapi"], bool):
            raise RagConfigurationError(f"{path} : api.openapi doit valoir true ou false (booléen YAML)")
        config = ApiConfig(max_concurrency=int(api["max_concurrency"]),
                           request_timeout_s=float(api["request_timeout_s"]),
                           max_body_bytes=int(api["max_body_bytes"]), openapi=api["openapi"])
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise RagConfigurationError(f"{path} : section api illisible ou incomplète : {exc!r}") from exc
    if not 1 <= config.max_concurrency <= 16:
        raise RagConfigurationError(f"{path} : api.max_concurrency doit être entre 1 et 16")
    if not 10 <= config.request_timeout_s <= 600:
        raise RagConfigurationError(f"{path} : api.request_timeout_s doit être entre 10 et 600")
    if not 1024 <= config.max_body_bytes <= 65536:
        raise RagConfigurationError(f"{path} : api.max_body_bytes doit être entre 1024 et 65536")
    return config


def load_api_key(env: Mapping[str, str] | None = None) -> str:
    """Lit la clé de l'API (≥ 32 caractères) ; l'erreur nomme la variable, jamais sa valeur."""
    env = os.environ if env is None else env
    key = (env.get("RAG_API_KEY") or "").strip()
    if len(key) < MIN_API_KEY_CHARS:
        raise RagConfigurationError(f"RAG_API_KEY absente ou trop courte (≥ {MIN_API_KEY_CHARS} caractères, .env)")
    return key
