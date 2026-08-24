from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl

from ingestion.medgen import MEDGEN_CUI_PATTERN, parse_medgen_conceptmeta


def _parsed_conceptmeta_fields(concept: dict, cui: str, cache: dict[str, dict | None]) -> dict | None:
    """Parse le XML `conceptmeta` d'un CUI une seule fois, quel que soit le nombre de gènes
    qui le référencent (ex. le concept « syndrome sein-ovaire héréditaire » est partagé par
    BRCA1, BRCA2, PALB2, ATM, CHEK2...) : sans cache, il serait reparsé une fois par gène.

    Renvoie `None` si le concept n'a pas de `conceptmeta`, ou si son XML est mal formé — une
    collecte complète fait ~1200 appels NCBI et rien n'est écrit avant la toute fin du run
    (voir http_client.py) ; un concept malformé isolé ne doit pas faire perdre tout ce travail.
    """
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
    """Ajoute les champs extraits du XML `conceptmeta` sans retirer les données brutes.

    Un concept vide signale un CUI que MedGen ne résout pas : on conserve au moins
    son identifiant, sans quoi le CUI en échec serait irrécupérable depuis le document.
    """
    if not concept:
        return {"conceptid": cui}
    if parsed_fields is None:
        return dict(concept)
    return {**concept, **parsed_fields}


def add_medgen_cuis(df: pl.DataFrame) -> pl.DataFrame:
    """Ajoute une colonne `medgen_cuis` (liste de CUI dédupliqués, dans l'ordre d'apparition)
    dérivée de PhenotypeIDS, par extraction polars vectorisée (pas de callback Python par
    ligne)."""
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
    """Assemble un document par gène combinant ClinVar, NCBI Gene, MedGen et HPO.

    `provenance`, si fourni, est copié dans chaque document sous la clé `_provenance`
    (date de collecte, versions des sources) pour rendre la couche RAW traçable.
    """
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
