import pytest

from ingestion.errors import ConfigurationError
from ingestion.maintenance import (
    KEEP_DOWNLOADS_PER_SOURCE,
    MIN_FREE_BYTES,
    ensure_free_space,
    purge_old_downloads,
)


def _touch(directory, name, mtime):
    path = directory / name
    path.write_bytes(b"x")
    import os

    os.utime(path, (mtime, mtime))
    return path


def test_purge_keeps_the_most_recent_files_of_each_source(tmp_path):
    """Chaque source garde ses deux derniers mois : le mois courant pour le run en
    cours, le précédent pour pouvoir rejouer sans retélécharger 440 Mo."""
    for index, month in enumerate(["2026-06", "2026-07", "2026-08", "2026-09"]):
        _touch(tmp_path, f"variant_summary_{month}.txt.gz", 1_000 + index)
    for index, month in enumerate(["2026-07-01", "2026-08-01", "2026-09-01"]):
        _touch(tmp_path, f"genes_to_phenotype_v{month}.txt", 2_000 + index)

    removed = purge_old_downloads(tmp_path)

    restants = sorted(p.name for p in tmp_path.iterdir())
    assert restants == [
        "genes_to_phenotype_v2026-08-01.txt",
        "genes_to_phenotype_v2026-09-01.txt",
        "variant_summary_2026-08.txt.gz",
        "variant_summary_2026-09.txt.gz",
    ]
    assert removed == 3


def test_purge_leaves_a_directory_that_is_already_small_enough(tmp_path):
    _touch(tmp_path, "variant_summary_2026-09.txt.gz", 1_000)

    assert purge_old_downloads(tmp_path) == 0
    assert len(list(tmp_path.iterdir())) == 1


def test_purge_ignores_a_missing_directory(tmp_path):
    """Un premier run sur une machine neuve ne doit pas échouer sur l'absence du
    dossier de cache."""
    assert purge_old_downloads(tmp_path / "jamais-cree") == 0


def test_purge_never_touches_an_unrelated_file(tmp_path):
    """Le dossier est partagé : un fichier qui ne suit aucun motif connu — un
    `.gitkeep`, un téléchargement manuel — n'appartient pas à la purge."""
    _touch(tmp_path, ".gitkeep", 1)
    for index, month in enumerate(["2026-06", "2026-07", "2026-08"]):
        _touch(tmp_path, f"variant_summary_{month}.txt.gz", 1_000 + index)

    purge_old_downloads(tmp_path)

    assert (tmp_path / ".gitkeep").exists()


def test_purge_keeps_a_partial_download_out_of_the_count(tmp_path):
    """Un `.part` est un téléchargement en cours, pas une archive conservée : le
    compter ferait purger une archive complète encore utile."""
    for index, month in enumerate(["2026-07", "2026-08", "2026-09"]):
        _touch(tmp_path, f"variant_summary_{month}.txt.gz", 1_000 + index)
    _touch(tmp_path, "variant_summary_2026-10.txt.gz.part", 9_999)

    purge_old_downloads(tmp_path)

    assert (tmp_path / "variant_summary_2026-10.txt.gz.part").exists()
    assert (tmp_path / "variant_summary_2026-07.txt.gz").exists() is False
    assert (tmp_path / "variant_summary_2026-09.txt.gz").exists()


def test_ensure_free_space_passes_when_the_disk_has_room(tmp_path):
    ensure_free_space(tmp_path, free_bytes_fn=lambda _: MIN_FREE_BYTES + 1)  # ne lève pas


def test_ensure_free_space_fails_before_downloading_when_the_disk_is_nearly_full(tmp_path):
    """Échec immédiat et explicite plutôt qu'un téléchargement de 440 Mo qui meurt à
    99 % avec une erreur d'écriture opaque. `ConfigurationError` n'est pas retentée
    par les DAGs : relancer ne libérerait pas d'espace."""
    with pytest.raises(ConfigurationError, match="espace disque"):
        ensure_free_space(tmp_path, free_bytes_fn=lambda _: 100)


def test_ensure_free_space_says_how_much_is_missing(tmp_path):
    with pytest.raises(ConfigurationError) as raised:
        ensure_free_space(tmp_path, free_bytes_fn=lambda _: 512 * 1024 * 1024)

    message = str(raised.value)
    assert "0,5 Gio" in message and "2,0 Gio" in message


def test_keep_downloads_per_source_is_two():
    assert KEEP_DOWNLOADS_PER_SOURCE == 2
