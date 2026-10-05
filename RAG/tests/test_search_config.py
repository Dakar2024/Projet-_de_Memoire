from pathlib import Path

import pytest

from RAG.src.utils.config import DEFAULT_CONFIG_PATH, load_openrouter_key, load_search_config
from RAG.src.utils.errors import RagConfigurationError

VALID = """
embedding: {}
index: {}
search:
  k: 10
  min_filtered: 3
  max_question_chars: 1000
llm:
  analysis_profile: claude-opus-5.5
  request_timeout_s: 60
  max_tokens: 2000
  profiles:
    claude-opus-5.5: {model: anthropic/claude-opus-5.5, provider_tag: google-vertex/europe, provider_name: Google, quantization: null}
    gpt-oss-120b: {model: openai/gpt-oss-120b, provider_tag: deepinfra/bf16, provider_name: DeepInfra, quantization: bf16}
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_repository_config_is_valid():
    config = load_search_config(DEFAULT_CONFIG_PATH)

    assert config.k == 10
    assert set(config.profiles) == {"claude-opus-5.5", "mistral-medium", "gpt-oss-120b"}
    assert config.profiles["gpt-oss-120b"].quantization == "bf16"


def test_reads_every_setting(tmp_path):
    config = load_search_config(_write(tmp_path, VALID))

    assert (config.k, config.min_filtered, config.max_question_chars) == (10, 3, 1000)
    assert config.analysis_profile.name == "claude-opus-5.5"
    assert config.analysis_profile.provider_tag == "google-vertex/europe"
    assert config.analysis_profile.quantization is None
    assert config.llm_max_tokens == 2000


def test_profile_argument_overrides_the_default(tmp_path):
    config = load_search_config(_write(tmp_path, VALID), profile="gpt-oss-120b")

    assert config.analysis_profile.name == "gpt-oss-120b"


@pytest.mark.parametrize("profile", ["inconnu", "mistral-medium"])
def test_unknown_profile_is_refused(tmp_path, profile):
    with pytest.raises(RagConfigurationError, match="profil"):
        load_search_config(_write(tmp_path, VALID), profile=profile)


@pytest.mark.parametrize("old,new", [("k: 10", "k: 0"), ("min_filtered: 3", "min_filtered: 11"),
                                     ("max_question_chars: 1000", "max_question_chars: 5")])
def test_out_of_range_settings_are_refused(tmp_path, old, new):
    with pytest.raises(RagConfigurationError):
        load_search_config(_write(tmp_path, VALID.replace(old, new)))


def test_a_profile_without_provider_is_refused(tmp_path):
    with pytest.raises(RagConfigurationError):
        load_search_config(_write(tmp_path, VALID.replace("provider_tag: deepinfra/bf16, ", "")))


def test_openrouter_key_is_required_and_never_echoed():
    with pytest.raises(RagConfigurationError, match="OPENROUTER_API_KEY"):
        load_openrouter_key({"OPENROUTER_API_KEY": "   "})
    assert load_openrouter_key({"OPENROUTER_API_KEY": "sk-or-abc"}) == "sk-or-abc"
