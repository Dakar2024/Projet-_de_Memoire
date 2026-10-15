"""Téléchargement et filtrage du fichier bulk ClinVar sur le panel de gènes."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from ingestion.config import LOGICAL_DATE_PATTERN
from ingestion.download import download_to_file

CLINVAR_BULK_URL = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
)

# Archive mensuelle immuable : un rejeu relit exactement le fichier d'origine.
CLINVAR_ARCHIVE_URL_TEMPLATE = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/"
    "variant_summary_{version}.txt.gz"
)


def archive_version_for(logical_date: str) -> str:
    """Renvoie la version d'archive ClinVar (`YYYY-MM`) d'une date logique `YYYY-MM-DD`."""
    if not LOGICAL_DATE_PATTERN.match(logical_date or ""):
        raise ValueError(
            f"date logique invalide : {logical_date!r} — format attendu YYYY-MM-DD"
        )
    return logical_date[:7]


def archive_url_for(logical_date: str) -> str:
    """Renvoie l'URL de l'archive ClinVar du mois de la date logique."""
    return CLINVAR_ARCHIVE_URL_TEMPLATE.format(version=archive_version_for(logical_date))


def filter_clinvar(source_path: Path, genes: list[str]) -> pl.DataFrame:
    """Filtre le bulk ClinVar sur les gènes cibles (correspondance exacte) et dédoublonne par AlleleID."""
    return (
        pl.scan_csv(source_path, separator="\t", infer_schema_length=0)
        .filter(pl.col("GeneSymbol").is_in(genes))
        .filter(pl.col("Assembly").is_in(["GRCh38", "na"]))
        # Ordre conservé : deux collectes du même bulk donnent des fichiers identiques.
        .unique(subset=["#AlleleID"], keep="first", maintain_order=True)
        .collect()
    )


def download_variant_summary(
    destination: Path, url: str = CLINVAR_BULK_URL, force: bool = False
) -> Path:
    """Télécharge le fichier bulk ClinVar (~440 Mo) vers `destination`."""
    return download_to_file(url, destination, force=force)
