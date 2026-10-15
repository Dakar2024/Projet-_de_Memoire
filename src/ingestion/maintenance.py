"""Entretien du cache de téléchargement : purge des anciennes archives et contrôle de l'espace disque."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Callable

from ingestion.errors import ConfigurationError

# Mois courant + mois précédent (rejeu sans retélécharger 440 Mo).
KEEP_DOWNLOADS_PER_SOURCE = 2

# Deux fois le bulk ClinVar compressé, plus la marge du `.part`.
MIN_FREE_BYTES = 2 * 1024**3

# Seuls les fichiers suivant ces motifs sont purgés ; tout autre fichier est laissé en place.
_SOURCE_PATTERNS = {
    "clinvar": re.compile(r"^variant_summary_\d{4}-\d{2}\.txt\.gz$"),
    "hpo": re.compile(r"^genes_to_phenotype_v\d{4}-\d{2}-\d{2}\.txt$"),
}


def _gio(octets: float) -> str:
    """Formate un nombre d'octets en Gio, à la française."""
    return f"{octets / 1024**3:.1f} Gio".replace(".", ",")


def purge_old_downloads(directory: Path, keep: int = KEEP_DOWNLOADS_PER_SOURCE) -> int:
    """Garde les `keep` fichiers les plus récents de chaque source et renvoie le nombre supprimé."""
    if not directory.exists():
        return 0

    removed = 0
    for pattern in _SOURCE_PATTERNS.values():
        matching = [p for p in directory.iterdir() if p.is_file() and pattern.match(p.name)]
        matching.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for path in matching[keep:]:
            path.unlink()
            removed += 1
    return removed


def ensure_free_space(
    directory: Path,
    minimum: int = MIN_FREE_BYTES,
    free_bytes_fn: Callable[[Path], int] | None = None,
) -> None:
    """Lève `ConfigurationError` (non relancée) si l'espace libre est insuffisant."""
    free = (free_bytes_fn or _free_bytes)(directory)
    if free < minimum:
        raise ConfigurationError(
            f"espace disque insuffisant dans {directory} : {_gio(free)} libres pour "
            f"{_gio(minimum)} requis. Libérer de la place avant de relancer."
        )


def _free_bytes(directory: Path) -> int:
    """Renvoie l'espace libre du disque de `directory` ou de son plus proche parent existant."""
    probe = directory
    while not probe.exists():
        probe = probe.parent
    return shutil.disk_usage(probe).free
