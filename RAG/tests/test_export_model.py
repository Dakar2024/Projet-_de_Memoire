"""Remplacement d'un export de modèle : jamais de dossier servi absent hors de deux renommages."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "docker" / "embeddings" / "export_model.py"


@pytest.fixture(scope="module")
def export_model():
    """Charge le script par son chemin : `docker/` n'est pas un paquet importable."""
    spec = importlib.util.spec_from_file_location("export_model", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _export(root: Path, name: str, content: str) -> Path:
    folder = root / name
    folder.mkdir()
    (folder / "export.json").write_text(content, encoding="utf-8")
    return folder


def test_swap_replaces_the_served_export_and_drops_the_old_one(tmp_path, export_model):
    final = _export(tmp_path, "modele", "ancien")
    partial = _export(tmp_path, ".modele.partial", "nouveau")

    export_model.swap_in(partial, final)

    assert (final / "export.json").read_text(encoding="utf-8") == "nouveau"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["modele"]


def test_swap_works_without_a_previous_export(tmp_path, export_model):
    partial = _export(tmp_path, ".modele.partial", "nouveau")
    export_model.swap_in(partial, tmp_path / "modele")
    assert (tmp_path / "modele" / "export.json").read_text(encoding="utf-8") == "nouveau"


def test_an_interrupted_swap_is_restored_before_anything_else(tmp_path, export_model):
    """Arrêt entre les deux renommages : l'ancien export, mis de côté, redevient le dossier servi."""
    final = tmp_path / "modele"
    _export(tmp_path, ".modele.previous", "ancien")

    export_model.restore_interrupted_swap(final)

    assert (final / "export.json").read_text(encoding="utf-8") == "ancien"
    assert not (tmp_path / ".modele.previous").exists()


def test_a_completed_swap_leaves_nothing_to_restore(tmp_path, export_model):
    final = _export(tmp_path, "modele", "nouveau")
    export_model.restore_interrupted_swap(final)
    assert (final / "export.json").read_text(encoding="utf-8") == "nouveau"
