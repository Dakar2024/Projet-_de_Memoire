"""Entretien du cache de téléchargement : purge des archives anciennes et contrôle
de l'espace disque avant un téléchargement volumineux.

Le pipeline tourne une fois par mois sans surveillance. Sans purge, `data/external`
grossit de 442 Mo par mois indéfiniment ; sans contrôle préalable, un disque saturé
se manifeste par une écriture qui échoue à la fin d'un transfert de 440 Mo, avec un
message qui ne dit pas la vraie cause.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Callable

from ingestion.errors import ConfigurationError

# Le mois courant sert au run en cours, le précédent permet de rejouer le mois
# passé sans retélécharger 440 Mo. Au-delà, une archive ne sert plus à rien : elle
# reste téléchargeable chez la source tant qu'elle date de moins de trois ans.
KEEP_DOWNLOADS_PER_SOURCE = 2

# Deux fois la taille du bulk ClinVar compressé, plus de la marge pour le `.part`
# et la décompression en flux.
MIN_FREE_BYTES = 2 * 1024**3

# Une source = un motif de nom. Un fichier qui n'en suit aucun (un `.gitkeep`, un
# téléchargement manuel) n'est jamais supprimé : ce dossier n'appartient pas qu'à
# la purge.
_SOURCE_PATTERNS = {
    "clinvar": re.compile(r"^variant_summary_\d{4}-\d{2}\.txt\.gz$"),
    "hpo": re.compile(r"^genes_to_phenotype_v\d{4}-\d{2}-\d{2}\.txt$"),
}


def _gio(octets: float) -> str:
    return f"{octets / 1024**3:.1f} Gio".replace(".", ",")


def purge_old_downloads(directory: Path, keep: int = KEEP_DOWNLOADS_PER_SOURCE) -> int:
    """Ne garde que les `keep` fichiers les plus récents de chaque source connue.

    Renvoie le nombre de fichiers supprimés. Un dossier absent n'est pas une erreur :
    un premier run sur une machine neuve n'a encore rien téléchargé.

    Les `.part` sont ignorés : ce sont des téléchargements en cours, et les compter
    ferait purger une archive complète encore utile.
    """
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
    """Échoue avant le téléchargement si l'espace libre est insuffisant.

    `ConfigurationError` plutôt qu'une erreur ordinaire : les DAGs la convertissent
    en échec non retenté, et relancer trois fois ne libérerait pas d'espace.
    """
    free = (free_bytes_fn or _free_bytes)(directory)
    if free < minimum:
        raise ConfigurationError(
            f"espace disque insuffisant dans {directory} : {_gio(free)} libres pour "
            f"{_gio(minimum)} requis. Libérer de la place avant de relancer."
        )


def _free_bytes(directory: Path) -> int:
    """Espace libre du système de fichiers portant `directory`, ou son parent le plus
    proche qui existe — le dossier de cache peut ne pas encore avoir été créé."""
    probe = directory
    while not probe.exists():
        probe = probe.parent
    return shutil.disk_usage(probe).free
