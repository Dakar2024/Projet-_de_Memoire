from __future__ import annotations

from pathlib import Path

import polars as pl

from ingestion.config import LOGICAL_DATE_PATTERN
from ingestion.download import download_to_file

CLINVAR_BULK_URL = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
)

# Archives mensuelles immuables. Le fichier « latest » est rafraîchi plus souvent
# que la publication mensuelle : l'épingler par mois est ce qui rend un rejeu de
# `dt=2026-08-01` réellement identique à l'exécution d'origine.
CLINVAR_ARCHIVE_URL_TEMPLATE = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/"
    "variant_summary_{version}.txt.gz"
)


def archive_version_for(logical_date: str) -> str:
    """Version d'archive ClinVar (`YYYY-MM`) correspondant à une date logique `YYYY-MM-DD`."""
    # La date logique vient d'Airflow, mais cette fonction est aussi appelable depuis la
    # ligne de commande : une entrée malformée produirait sinon une version
    # syntaxiquement valide mais fausse, donc une URL silencieusement erronée.
    if not LOGICAL_DATE_PATTERN.match(logical_date or ""):
        raise ValueError(
            f"date logique invalide : {logical_date!r} — format attendu YYYY-MM-DD"
        )
    return logical_date[:7]


def archive_url_for(logical_date: str) -> str:
    """URL de l'archive ClinVar épinglée sur le mois de la date logique."""
    return CLINVAR_ARCHIVE_URL_TEMPLATE.format(version=archive_version_for(logical_date))


def filter_clinvar(source_path: Path, genes: list[str]) -> pl.DataFrame:
    """Filtre le fichier bulk ClinVar sur les gènes cibles, gère les doublons d'assemblage.

    Limite connue : `is_in` fait une correspondance exacte, donc les lignes dont le champ
    `GeneSymbol` joint plusieurs gènes par `;` sont ignorées — environ 270 associations
    variant-gène sur 97 000 (0,3 %), surtout ATM, PTEN, HBB, BRCA1 et MYB. Éclater ces
    lignes ferait apparaître un même variant sous plusieurs gènes : c'est une décision de
    modélisation qui appartient à la couche Silver, pas à la couche raw.
    """
    return (
        pl.scan_csv(source_path, separator="\t", infer_schema_length=0)
        .filter(pl.col("GeneSymbol").is_in(genes))
        .filter(pl.col("Assembly").is_in(["GRCh38", "na"]))
        # maintain_order pour que deux collectes du même bulk produisent des fichiers
        # identiques, et donc comparables par diff.
        .unique(subset=["#AlleleID"], keep="first", maintain_order=True)
        .collect()
    )


def download_variant_summary(
    destination: Path, url: str = CLINVAR_BULK_URL, force: bool = False
) -> Path:
    """Télécharge le fichier bulk ClinVar (~440 Mo) vers `destination`."""
    return download_to_file(url, destination, force=force)
