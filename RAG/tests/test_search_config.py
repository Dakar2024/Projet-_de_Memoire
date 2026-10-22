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
    assert set(config.profiles) == {"groq-gpt-oss-120b", "groq-gpt-oss-20b", "groq-qwen3.8-27b"}
    assert set(config.reserve_profiles) == {"claude-opus-5.5", "mistral-medium", "gpt-oss-120b"}
    assert config.reserve_profiles["gpt-oss-120b"].quantization == "bf16"


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


TRIAL = VALID + """
  trial_profiles:
    essai-groq: {model: openai/gpt-oss-120b, backend: groq, provider_tag: groq, provider_name: Groq, quantization: null}
"""


def test_repository_config_has_a_separate_groq_trial_profile():
    config = load_search_config(DEFAULT_CONFIG_PATH, profile="essai-groq-gpt-oss-120b")

    trial = config.analysis_profile
    assert (trial.model, trial.backend, trial.provider_name, trial.quantization) == (
        "openai/gpt-oss-120b", "groq", "Groq", None)
    assert set(config.trial_profiles) == {"essai-groq-gpt-oss-120b"}
    assert "essai-groq-gpt-oss-120b" not in config.profiles


def test_official_profiles_are_served_by_groq_and_the_reserve_by_openrouter():
    config = load_search_config(DEFAULT_CONFIG_PATH)

    assert {p.backend for p in config.profiles.values()} == {"groq"}
    assert {p.backend for p in config.reserve_profiles.values()} == {"openrouter"}


def test_a_trial_profile_can_be_chosen_by_argument_or_by_default(tmp_path):
    config = load_search_config(_write(tmp_path, TRIAL), profile="essai-groq")
    assert config.analysis_profile.name == "essai-groq" and config.analysis_profile.backend == "groq"
    assert set(config.profiles) == {"claude-opus-5.5", "gpt-oss-120b"}

    default = load_search_config(_write(tmp_path, TRIAL.replace("analysis_profile: claude-opus-5.5",
                                                                "analysis_profile: essai-groq")))
    assert default.analysis_profile.name == "essai-groq"


def test_trial_profiles_are_optional(tmp_path):
    assert load_search_config(_write(tmp_path, VALID)).trial_profiles == {}


def test_an_unknown_backend_is_refused(tmp_path):
    with pytest.raises(RagConfigurationError, match="backend"):
        load_search_config(_write(tmp_path, TRIAL.replace("backend: groq", "backend: ollama")))


def test_an_official_profile_may_be_served_by_groq(tmp_path):
    text = VALID.replace("provider_name: DeepInfra,", "provider_name: DeepInfra, backend: groq,")
    assert load_search_config(_write(tmp_path, text)).profiles["gpt-oss-120b"].backend == "groq"


@pytest.mark.parametrize("section", ["profiles", "trial_profiles"])
def test_a_gemini_profile_is_refused_in_config_yaml(tmp_path, section):
    """L'offre gratuite de Gemini réutilise les requêtes : réservée au juge de E3a, jamais à l'application."""
    gemini = ("    gem: {model: gemini-3.8-flash, backend: gemini, provider_tag: gemini-api, "
              "provider_name: Google, quantization: null}\n")
    text = TRIAL if section == "trial_profiles" else VALID
    anchor = "  trial_profiles:\n" if section == "trial_profiles" else "  profiles:\n"
    with pytest.raises(RagConfigurationError, match="Gemini"):
        load_search_config(_write(tmp_path, text.replace(anchor, anchor + gemini)))


def test_a_reserve_profile_is_neither_a_candidate_nor_selectable(tmp_path):
    reserve = ("  reserve_profiles:\n    opus: {model: anthropic/claude-opus-5.5, provider_tag: google-vertex/europe, "
               "provider_name: Google, quantization: null}\n")
    config = load_search_config(_write(tmp_path, VALID + reserve))
    assert "opus" in config.reserve_profiles and "opus" not in config.profiles
    with pytest.raises(RagConfigurationError, match="opus"):
        load_search_config(_write(tmp_path, VALID + reserve), profile="opus")


def test_a_name_in_both_sections_is_refused(tmp_path):
    with pytest.raises(RagConfigurationError, match="gpt-oss-120b"):
        load_search_config(_write(tmp_path, TRIAL.replace("essai-groq:", "gpt-oss-120b:")))


def test_groq_key_is_required_and_never_echoed():
    from RAG.src.utils.config import load_groq_key

    with pytest.raises(RagConfigurationError, match="GROQ_API_KEY"):
        load_groq_key({"GROQ_API_KEY": "  ", "OPENROUTER_API_KEY": "sk-or-abc"})
    assert load_groq_key({"GROQ_API_KEY": "gsk_abc"}) == "gsk_abc"
