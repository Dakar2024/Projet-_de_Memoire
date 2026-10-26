from pathlib import Path

import pytest

from RAG.src.utils.config import (
    DEFAULT_CONFIG_PATH,
    load_api_config,
    load_api_key,
    load_generation_config,
    load_search_config,
)
from RAG.src.utils.errors import RagConfigurationError

BASE = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_repository_generation_profile_is_the_provisional_groq_trial():
    config = load_generation_config(DEFAULT_CONFIG_PATH)

    assert config.profile.name == "essai-groq-gpt-oss-120b"
    assert config.profile.backend == "groq"
    assert config.max_tokens >= 1024 and config.timeout_s > 0


def test_repository_analysis_profile_is_provisional_too():
    assert load_search_config(DEFAULT_CONFIG_PATH).analysis_profile.name == "essai-groq-gpt-oss-120b"


def test_api_settings():
    api = load_api_config(DEFAULT_CONFIG_PATH)

    assert (api.max_concurrency, api.request_timeout_s, api.max_body_bytes, api.openapi) == (4, 120.0, 8192, False)


def test_unknown_generation_profile_is_refused(tmp_path):
    text = BASE.replace("generation_profile: essai-groq-gpt-oss-120b", "generation_profile: inconnu")
    with pytest.raises(RagConfigurationError, match="generation_profile"):
        load_generation_config(_write(tmp_path, text))


@pytest.mark.parametrize("old,new", [("max_concurrency: 4", "max_concurrency: 0"),
                                     ("max_body_bytes: 8192", "max_body_bytes: 100"),
                                     ("request_timeout_s: 120", "request_timeout_s: 0")])
def test_out_of_range_api_settings_are_refused(tmp_path, old, new):
    with pytest.raises(RagConfigurationError):
        load_api_config(_write(tmp_path, BASE.replace(old, new)))


@pytest.mark.parametrize("value", ["", "   ", "trop-courte"])
def test_api_key_must_be_long_enough_and_is_never_echoed(value):
    with pytest.raises(RagConfigurationError, match="RAG_API_KEY") as excinfo:
        load_api_key({"RAG_API_KEY": value})
    assert value.strip() == "" or value not in str(excinfo.value)


def test_api_key_is_returned_stripped():
    assert load_api_key({"RAG_API_KEY": "  " + "k" * 40 + " "}) == "k" * 40


@pytest.mark.parametrize("value", ['"false"', '"no"', "0", "1", "null"])
def test_openapi_must_be_a_real_boolean(tmp_path, value):
    # bool("false") vaudrait True : une chaîne activerait /schema sans clé.
    with pytest.raises(RagConfigurationError, match="openapi"):
        load_api_config(_write(tmp_path, BASE.replace("openapi: false", f"openapi: {value}")))
