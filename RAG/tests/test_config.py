from pathlib import Path

import pytest

from RAG.src.utils.config import (
    MAX_CLIENT_BATCH_SIZE,
    PROJECT_ROOT,
    RAG_ROOT,
    check_served_model,
    load_config,
    load_service_settings,
    served_fingerprint,
)
from RAG.src.utils.errors import RagConfigurationError

VALID = """
embedding:
  fingerprint: "NeuML/pubmedbert-base-embeddings@b79526d6ef36+onnx:2ab209f97e0a83ca"
  canary_file: canari.json
  canary_min_cosine: 0.995
  batch_size: 32
  request_timeout_s: 60
index:
  max_delete_ratio: 0.05
"""

ENV = {
    "RAG_EMBEDDINGS_URL": "http://rag-embeddings:8080",
    "RAG_EMBEDDINGS_API_KEY": "cle",
    "RAG_PG_HOST": "rag-postgres",
    "RAG_PG_DB": "rag",
    "RAG_PG_USER": "rag_indexer",
    "RAG_PG_PASSWORD": "mot de passe'avec apostrophe",
    "RAG_EMBEDDING_MODEL": "pubmedbert-base-embeddings",
}


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_reads_every_setting(tmp_path):
    config = load_config(_write(tmp_path, VALID))

    assert config.embedding.fingerprint.startswith("NeuML/pubmedbert-base-embeddings@")
    assert config.embedding.canary_path == RAG_ROOT / "canari.json"
    assert config.embedding.canary_min_cosine == 0.995
    assert config.embedding.batch_size == 32
    assert config.index.max_delete_ratio == 0.05


def test_an_empty_fingerprint_refuses_to_index(tmp_path):
    """Tant qu'aucun modèle n'est validé, indexer serait indexer avec un modèle
    inconnu : on refuse explicitement."""
    with pytest.raises(RagConfigurationError, match="fingerprint"):
        load_config(_write(tmp_path, VALID.replace(
            '"NeuML/pubmedbert-base-embeddings@b79526d6ef36+onnx:2ab209f97e0a83ca"', '""')))


@pytest.mark.parametrize("text", ["", "embedding: {}\n", "::: pas du yaml"])
def test_an_unreadable_config_is_a_configuration_error(tmp_path, text):
    with pytest.raises(RagConfigurationError):
        load_config(_write(tmp_path, text))


def test_a_batch_larger_than_the_service_limit_is_refused(tmp_path):
    with pytest.raises(RagConfigurationError, match="batch_size"):
        load_config(_write(tmp_path, VALID.replace("batch_size: 32",
                                                   f"batch_size: {MAX_CLIENT_BATCH_SIZE + 1}")))


def test_service_settings_build_a_safely_quoted_conninfo():
    settings = load_service_settings(ENV)

    assert settings.embeddings_url == "http://rag-embeddings:8080"
    assert "password='mot de passe\\'avec apostrophe'" in settings.pg_conninfo
    assert "port=5432" in settings.pg_conninfo


def test_missing_service_variables_are_all_named():
    env = {k: v for k, v in ENV.items() if k not in {"RAG_PG_PASSWORD", "RAG_EMBEDDINGS_API_KEY"}}

    with pytest.raises(RagConfigurationError) as excinfo:
        load_service_settings(env)

    assert "RAG_PG_PASSWORD" in str(excinfo.value)
    assert "RAG_EMBEDDINGS_API_KEY" in str(excinfo.value)


def test_the_served_model_directory_comes_from_rag_embedding_model():
    """Même variable que celle qui choisit le dossier servi par rag-embeddings."""
    settings = load_service_settings(ENV)

    assert settings.served_model_dir == PROJECT_ROOT / "data" / "models" / "pubmedbert-base-embeddings"
    assert PROJECT_ROOT == RAG_ROOT.parent


def test_a_missing_embedding_model_variable_is_named():
    env = {k: v for k, v in ENV.items() if k != "RAG_EMBEDDING_MODEL"}

    with pytest.raises(RagConfigurationError, match="RAG_EMBEDDING_MODEL"):
        load_service_settings(env)


@pytest.mark.parametrize("name", ["../secrets", "a/b", "a\\b", "..", "  "])
def test_a_dangerous_model_directory_name_is_refused(name):
    """Le nom sert à construire un chemin : il ne doit pas en sortir."""
    with pytest.raises(RagConfigurationError, match="RAG_EMBEDDING_MODEL"):
        load_service_settings(ENV | {"RAG_EMBEDDING_MODEL": name})


def test_served_fingerprint_reads_export_json(tmp_path):
    (tmp_path / "export.json").write_text(
        '{"model_id": "m", "fingerprint": "m@abc+onnx:123", "files": {}}', encoding="utf-8")

    assert served_fingerprint(tmp_path) == "m@abc+onnx:123"


@pytest.mark.parametrize("content", [None, "pas du json", '{"model_id": "m"}', '{"fingerprint": ""}'])
def test_an_absent_or_unreadable_export_json_is_a_configuration_error(tmp_path, content):
    if content is not None:
        (tmp_path / "export.json").write_text(content, encoding="utf-8")

    with pytest.raises(RagConfigurationError, match="export.json"):
        served_fingerprint(tmp_path)


def test_matching_fingerprints_pass():
    check_served_model("m@abc+onnx:123", "m@abc+onnx:123")


def test_diverging_fingerprints_are_refused_and_both_are_named():
    """`.env` désigne un dossier, `config.yaml` une empreinte : s'ils divergent, des
    vecteurs d'un modèle seraient étiquetés du nom de l'autre."""
    with pytest.raises(RagConfigurationError) as excinfo:
        check_served_model("neuml@abc+onnx:123", "biobert@def+onnx:456")

    assert "neuml@abc+onnx:123" in str(excinfo.value)
    assert "biobert@def+onnx:456" in str(excinfo.value)
