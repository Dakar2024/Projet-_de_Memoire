"""Assemblage des documents par gène de la collecte historique (`scripts/run_collection.py`)."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl

from ingestion.medgen import MEDGEN_CUI_PATTERN, parse_medgen_conceptmeta


def _parsed_conceptmeta_fields(concept: dict, cui: str, cache: dict[str, dict | None]) -> dict | None:
    """Lit le `conceptmeta` d'un CUI une seule fois (cache) ; `None` s'il est absent ou mal formé."""
    if cui in cache:
        return cache[cui]
    conceptmeta = concept.get("conceptmeta") if concept else None
    if not conceptmeta:
        cache[cui] = None
        return None
    try:
        cache[cui] = parse_medgen_conceptmeta(conceptmeta)
    except ET.ParseError as exc:
        print(
            f"medgen: conceptmeta invalide pour {cui} ({exc}), concept conservé sans "
            "enrichissement",
            file=sys.stderr,
        )
        cache[cui] = None
    return cache[cui]


def _enrich_medgen_concept(concept: dict, parsed_fields: dict | None, cui: str) -> dict:
    """Ajoute les champs du `conceptmeta` au concept brut ; un CUI non résolu garde son identifiant."""
    if not concept:
        return {"conceptid": cui}
    if parsed_fields is None:
        return dict(concept)
    return {**concept, **parsed_fields}


def add_medgen_cuis(df: pl.DataFrame) -> pl.DataFrame:
    """Ajoute la colonne `medgen_cuis` : CUI dédoublonnés de PhenotypeIDS, dans l'ordre d'apparition."""
    return df.with_columns(
        pl.col("PhenotypeIDS")
        .fill_null("")
        .str.extract_all(MEDGEN_CUI_PATTERN.pattern)
        .list.eval(pl.element().str.replace("MedGen:", ""))
        .list.unique(maintain_order=True)
        .alias("medgen_cuis")
    )


def build_gene_documents(
    clinvar_variants: pl.DataFrame,
    gene_info_by_symbol: dict[str, dict],
    medgen_by_cui: dict[str, dict],
    hpo_rows_by_gene: dict[str, list[dict]],
    provenance: dict | None = None,
) -> dict[str, dict]:
    """Assemble un document par gène (ClinVar, NCBI Gene, MedGen, HPO), avec `_provenance` si fournie."""
    documents: dict[str, dict] = {}
    parsed_conceptmeta_cache: dict[str, dict | None] = {}
    for gene_symbol in gene_info_by_symbol:
        variant_records = clinvar_variants.filter(
            pl.col("GeneSymbol") == gene_symbol
        ).to_dicts()

        cuis_for_gene: list[str] = []
        for record in variant_records:
            for cui in record.get("medgen_cuis") or []:
                if cui not in cuis_for_gene:
                    cuis_for_gene.append(cui)

        document = {
            "gene_symbol": gene_symbol,
            "gene_info": gene_info_by_symbol.get(gene_symbol, {}),
            "variants": variant_records,
            "medgen_concepts": [
                _enrich_medgen_concept(
                    medgen_by_cui[cui],
                    _parsed_conceptmeta_fields(medgen_by_cui[cui], cui, parsed_conceptmeta_cache),
                    cui,
                )
                for cui in cuis_for_gene
                if cui in medgen_by_cui
            ],
            "hpo_terms": hpo_rows_by_gene.get(gene_symbol, []),
        }
        if provenance is not None:
            document["_provenance"] = provenance
        documents[gene_symbol] = document
    return documents


def find_empty_genes(documents: dict[str, dict]) -> list[str]:
    """Renvoie les gènes sans variants ou sans métadonnées NCBI Gene (HPO ignoré : HBS1L et MYB n'en ont pas)."""
    return [
        gene_symbol
        for gene_symbol, document in documents.items()
        if not document.get("variants") or not document.get("gene_info")
    ]


def write_raw_gene_files(documents: dict[str, dict], output_dir: Path) -> list[Path]:
    """Écrit un fichier JSON par gène dans `output_dir`."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for gene_symbol, document in documents.items():
        path = output_dir / f"{gene_symbol}.json"
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    return written
