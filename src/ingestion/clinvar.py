from __future__ import annotations

from pathlib import Path

import polars as pl

from ingestion.download import download_to_file

CLINVAR_BULK_URL = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
)


def filter_clinvar(source_path: Path, genes: list[str]) -> pl.DataFrame:
    """Filtre le fichier bulk ClinVar sur les gènes cibles, gère les doublons d'assemblage.

    Limite connue : `is_in` fait une correspondance exacte, donc les lignes dont le champ
    `GeneSymbol` joint plusieurs gènes par `;` sont ignorées — environ 270 associations
    variant-gène sur 97 000 (0,3 %), surtout ATM, PTEN, HBB, BRCA1 et MYB. Éclater ces
    lignes ferait apparaître un même variant sous plusieurs gènes : c'est une décision de
    modélisation qui appartient à la couche Bronze, pas à la couche RAW.
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
