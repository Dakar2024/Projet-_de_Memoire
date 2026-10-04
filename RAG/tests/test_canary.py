import json
from types import SimpleNamespace

import numpy as np
import pytest

from RAG.src.embeddings import canary as canary_module
from RAG.src.embeddings.canary import (
    CANARY_PHRASES,
    Canary,
    build_canary,
    canary_to_json,
    load_canary,
    verify_canary,
)
from RAG.src.utils.errors import CanaryMismatchError, RagConfigurationError

FP = "NeuML/pubmedbert-base-embeddings@b79526d6ef36+onnx:2ab209f97e0a83ca"


class StubClient:
    def __init__(self, vectors: np.ndarray):
        self.vectors = vectors

    def embed(self, texts):
        assert len(texts) == len(self.vectors)
        return self.vectors


def _unit(rows: int, seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=(rows, 768)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_round_trip_through_json(tmp_path):
    canary = build_canary(StubClient(_unit(len(CANARY_PHRASES), 1)), FP)
    path = tmp_path / "canari.json"
    path.write_text(canary_to_json(canary), encoding="utf-8")

    loaded = load_canary(path)

    assert loaded.fingerprint == FP
    assert loaded.phrases == CANARY_PHRASES
    np.testing.assert_allclose(loaded.vectors, canary.vectors, rtol=1e-6)


def test_the_same_model_passes_and_reports_its_worst_similarity():
    reference = _unit(3, 1)
    canary = Canary(FP, CANARY_PHRASES, reference)
    slightly_off = reference + 1e-4 * _unit(3, 2)

    worst = verify_canary(StubClient(slightly_off), canary, FP, min_cosine=0.995)

    assert 0.999 < worst <= 1.0


def test_another_model_is_rejected():
    canary = Canary(FP, CANARY_PHRASES, _unit(3, 1))

    with pytest.raises(CanaryMismatchError, match="cosinus"):
        verify_canary(StubClient(_unit(3, 99)), canary, FP, min_cosine=0.995)


def test_a_canary_from_another_export_is_rejected_before_any_call():
    canary = Canary("autre@modele", CANARY_PHRASES, _unit(3, 1))

    with pytest.raises(CanaryMismatchError, match="empreinte"):
        verify_canary(StubClient(_unit(3, 1)), canary, FP, min_cosine=0.995)


def test_verify_canary_rejects_non_finite_similarity():
    """Un vecteur nul donne un cosinus NaN, et `NaN < seuil` vaut False : sans
    contrôle explicite, un service dégénéré passerait le canari."""
    canary = Canary(FP, CANARY_PHRASES, _unit(3, 1))

    with pytest.raises(CanaryMismatchError, match="non fini"):
        verify_canary(StubClient(np.zeros((3, 768), dtype=np.float32)), canary, FP, min_cosine=0.995)


def test_a_malformed_canary_file_is_a_configuration_error(tmp_path):
    path = tmp_path / "canari.json"
    path.write_text('{"fingerprint": "x", "phrases": ["a"], "vectors": [[1, 2]]}', encoding="utf-8")

    with pytest.raises(RagConfigurationError):
        load_canary(path)


def test_a_missing_canary_file_is_a_configuration_error(tmp_path):
    with pytest.raises(RagConfigurationError):
        load_canary(tmp_path / "absent.json")


def _served(tmp_path, fingerprint: str):
    (tmp_path / "export.json").write_text(json.dumps({"fingerprint": fingerprint}), encoding="utf-8")
    return SimpleNamespace(embeddings_url="http://x", embeddings_api_key="k", served_model_dir=tmp_path)


def _config(fingerprint: str):
    return SimpleNamespace(embedding=SimpleNamespace(fingerprint=fingerprint))


def test_main_labels_the_canary_with_the_served_export_fingerprint(tmp_path, monkeypatch, capsys):
    """L'empreinte ne se saisit plus à la main : elle vient de export.json du dossier
    réellement servi, et doit égaler celle de config.yaml."""
    monkeypatch.setattr(canary_module, "load_service_settings", lambda: _served(tmp_path, FP))
    monkeypatch.setattr(canary_module, "load_config", lambda: _config(FP))
    monkeypatch.setattr(canary_module, "EmbeddingClient", lambda *a, **k: StubClient(_unit(3, 1)))

    assert canary_module.main([]) == 0

    assert json.loads(capsys.readouterr().out)["fingerprint"] == FP


def test_main_refuses_when_the_served_export_is_not_the_configured_model(tmp_path, monkeypatch, capsys):
    def no_service(*args, **kwargs):
        raise AssertionError("le service ne doit pas être appelé")

    monkeypatch.setattr(canary_module, "load_service_settings", lambda: _served(tmp_path, "biobert@x+onnx:y"))
    monkeypatch.setattr(canary_module, "load_config", lambda: _config(FP))
    monkeypatch.setattr(canary_module, "EmbeddingClient", no_service)

    assert canary_module.main([]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "biobert@x+onnx:y" in captured.err and FP in captured.err


def test_main_no_longer_accepts_a_free_text_fingerprint():
    with pytest.raises(SystemExit):
        canary_module.main(["--fingerprint", FP])
