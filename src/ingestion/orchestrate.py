from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from ingestion.medgen import extract_medgen_cuis


def add_medgen_cuis(df: pl.DataFrame) -> pl.DataFrame:
    """Ajoute une colonne `medgen_cuis` (liste de CUI) dérivée de PhenotypeIDS."""
    return df.with_columns(
        pl.col("PhenotypeIDS")
        .map_elements(extract_medgen_cuis, return_dtype=pl.List(pl.Utf8))
        .alias("medgen_cuis")
    )


def build_gene_documents(
    clinvar_variants: pl.DataFrame,
    gene_info_by_symbol: dict[str, dict],
    medgen_by_cui: dict[str, dict],
    hpo_rows_by_gene: dict[str, list[dict]],
) -> dict[str, dict]:
    """Assemble un document par gène combinant ClinVar, NCBI Gene, MedGen et HPO."""
    documents: dict[str, dict] = {}
    for gene_symbol in gene_info_by_symbol:
        variant_records = clinvar_variants.filter(
            pl.col("GeneSymbol") == gene_symbol
        ).to_dicts()

        cuis_for_gene: list[str] = []
        for record in variant_records:
            for cui in record.get("medgen_cuis") or []:
                if cui not in cuis_for_gene:
                    cuis_for_gene.append(cui)

        documents[gene_symbol] = {
            "gene_symbol": gene_symbol,
            "gene_info": gene_info_by_symbol.get(gene_symbol, {}),
            "variants": variant_records,
            "medgen_concepts": [
                medgen_by_cui[cui] for cui in cuis_for_gene if cui in medgen_by_cui
            ],
            "hpo_terms": hpo_rows_by_gene.get(gene_symbol, []),
        }
    return documents


def write_raw_gene_files(documents: dict[str, dict], output_dir: Path) -> list[Path]:
    """Écrit un fichier JSON par gène dans `output_dir`."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for gene_symbol, document in documents.items():
        path = output_dir / f"{gene_symbol}.json"
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    return written
