import pytest
import yaml

from RAG.src.evaluation.settings import DEFAULT_SETTINGS_PATH, load_settings, settings_sha256
from RAG.src.utils.errors import RagConfigurationError


def _write(tmp_path, **changes):
    raw = yaml.safe_load(DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8"))
    for dotted, value in changes.items():
        node = raw
        *parents, last = dotted.split("__")
        for key in parents:
            node = node[key]
        if value is _DELETE:
            del node[last]
        else:
            node[last] = value
    path = tmp_path / "e3a.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


_DELETE = object()


def test_the_versioned_settings_load():
    s = load_settings()
    assert s.judge.name == "juge-gemini-3.8-flash"
    assert s.judge.model == "google/gemini-3.8-flash"
    assert s.judge.provider_name == "Google"
    assert s.candidates == ("claude-opus-5.5", "mistral-medium", "gpt-oss-120b")
    assert s.strata == {"I": 25, "S": 25, "G": 10, "M": 10}
    assert s.total_questions == 70
    assert (s.repeat_questions, s.passes, s.sample_size) == (20, 3, 40)
    assert s.thresholds.faithfulness_min == 0.90
    assert s.thresholds.kappa_min == 0.6
    assert (s.budget_usd, s.reserve_per_call_usd) == (25.0, 0.25)


def test_a_judge_of_a_candidate_family_is_refused(tmp_path):
    with pytest.raises(RagConfigurationError, match="famille"):
        load_settings(_write(tmp_path, judge__model="mistralai/mistral-large"))


def test_incomplete_judge_is_refused(tmp_path):
    with pytest.raises(RagConfigurationError, match="juge"):
        load_settings(_write(tmp_path, judge__provider_name=_DELETE))


def test_unknown_candidate_is_refused(tmp_path):
    with pytest.raises(RagConfigurationError, match="inconnu"):
        load_settings(_write(tmp_path, candidates=["claude-opus-5.5", "nope"]))


def test_trial_profile_cannot_be_a_candidate(tmp_path):
    with pytest.raises(RagConfigurationError, match="inconnu"):
        load_settings(_write(tmp_path, candidates=["essai-groq-gpt-oss-120b"]))


def test_threshold_outside_unit_interval_is_refused(tmp_path):
    with pytest.raises(RagConfigurationError, match="seuil"):
        load_settings(_write(tmp_path, thresholds__rejection_max=1.5))


def test_budget_must_exceed_the_reserve(tmp_path):
    with pytest.raises(RagConfigurationError, match="budget"):
        load_settings(_write(tmp_path, budget_usd=0.2))


@pytest.mark.parametrize("key", ["repeat_questions", "sample_size"])
def test_non_positive_counts_are_refused(tmp_path, key):
    with pytest.raises(RagConfigurationError):
        load_settings(_write(tmp_path, **{key: 0}))


def test_more_repeats_than_questions_is_refused(tmp_path):
    with pytest.raises(RagConfigurationError):
        load_settings(_write(tmp_path, repeat_questions=71))


def test_settings_sha_changes_with_the_file(tmp_path):
    first = _write(tmp_path, budget_usd=25.0)
    sha = settings_sha256(first)
    assert len(sha) == 64
    second = _write(tmp_path, budget_usd=24.0)
    assert settings_sha256(second) != sha
