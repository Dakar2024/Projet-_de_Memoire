from __future__ import annotations

from pathlib import Path

import polars as pl
import requests

CLINVAR_BULK_URL = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
)


def filter_clinvar(source_path: Path, genes: list[str]) -> pl.DataFrame:
    """Filtre le fichier bulk ClinVar sur les gènes cibles, gère les doublons d'assemblage."""
    return (
        pl.scan_csv(source_path, separator="\t", infer_schema_length=0)
        .filter(pl.col("GeneSymbol").is_in(genes))
        .filter(pl.col("Assembly").is_in(["GRCh38", "na"]))
        .unique(subset=["#AlleleID"], keep="first")
        .collect()
    )


def download_variant_summary(
    destination: Path, url: str = CLINVAR_BULK_URL, force: bool = False
) -> Path:
    """Télécharge le fichier bulk ClinVar en streaming vers `destination`.

    Le fichier fait ~440 Mo : s'il est déjà présent il est réutilisé tel quel,
    sauf si `force=True` (pour rafraîchir les données).
    """
    if destination.exists() and not force:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(destination, "wb") as fh:
            for chunk in response.iter_content(chunk_size=8192):
                fh.write(chunk)
    return destination
