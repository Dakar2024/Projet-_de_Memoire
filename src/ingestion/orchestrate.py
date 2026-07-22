from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from ingestion.medgen import extract_medgen_cuis, parse_medgen_conceptmeta


def _enrich_medgen_concept(concept: dict, cui: str) -> dict:
    """Ajoute les champs extraits du XML `conceptmeta` sans retirer les données brutes.

    Un concept vide signale un CUI que MedGen ne résout pas : on conserve au moins
    son identifiant, sans quoi le CUI en échec serait irrécupérable depuis le document.
    """
    if not concept:
        return {"conceptid": cui}
    conceptmeta = concept.get("conceptmeta")
    if not conceptmeta:
        return dict(concept)
    return {**concept, **parse_medgen_conceptmeta(conceptmeta)}


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
    provenance: dict | None = None,
) -> dict[str, dict]:
    """Assemble un document par gène combinant ClinVar, NCBI Gene, MedGen et HPO.

    `provenance`, si fourni, est copié dans chaque document sous la clé `_provenance`
    (date de collecte, versions des sources) pour rendre la couche RAW traçable.
    """
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

        document = {
            "gene_symbol": gene_symbol,
            "gene_info": gene_info_by_symbol.get(gene_symbol, {}),
            "variants": variant_records,
            "medgen_concepts": [
                _enrich_medgen_concept(medgen_by_cui[cui], cui)
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
    """Retourne les gènes auxquels il manque les variants ou les métadonnées NCBI Gene.

    `build_gene_documents` émet un document par gène demandé : n'alerter que sur les
    documents entièrement vides ne détecterait que l'échec total. Un gène résolu par
    NCBI Gene mais sans aucun variant ClinVar est le défaut le plus probable (symbole
    absent du bulk, filtre d'assemblage cassé) — il doit alerter aussi.

    Volontairement muet sur les termes HPO : HBS1L et MYB en ont légitimement zéro.
    """
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
