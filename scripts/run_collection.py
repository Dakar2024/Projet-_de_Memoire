from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from ingestion.clinvar import download_variant_summary, filter_clinvar
from ingestion.config import ALL_GENES, DATA_EXTERNAL_DIR, DATA_RAW_DIR
from ingestion.hpo import download_hpo_files, parse_genes_to_phenotype
from ingestion.http_client import NcbiClient
from ingestion.medgen import fetch_medgen_concept
from ingestion.ncbi_gene import fetch_gene_info
from ingestion.orchestrate import (
    add_medgen_cuis,
    build_gene_documents,
    find_empty_genes,
    write_raw_gene_files,
)


def run_collection(genes: list[str] = ALL_GENES) -> list[Path]:
    load_dotenv()
    client = NcbiClient(email=os.environ["NCBI_EMAIL"], api_key=os.environ.get("NCBI_API_KEY", ""))

    clinvar_path = download_variant_summary(DATA_EXTERNAL_DIR / "variant_summary.txt.gz")
    variants = add_medgen_cuis(filter_clinvar(clinvar_path, genes))

    gene_info_by_symbol = {gene: fetch_gene_info(client, gene) for gene in genes}

    all_cuis: list[str] = []
    for cui_list in variants["medgen_cuis"].to_list():
        for cui in cui_list:
            if cui not in all_cuis:
                all_cuis.append(cui)
    medgen_by_cui = {cui: fetch_medgen_concept(client, cui) for cui in all_cuis}

    hpo_paths = download_hpo_files(DATA_EXTERNAL_DIR)
    hpo_rows = parse_genes_to_phenotype(hpo_paths["genes_to_phenotype"], genes)
    hpo_rows_by_gene: dict[str, list[dict]] = {}
    for row in hpo_rows:
        hpo_rows_by_gene.setdefault(row["gene_symbol"], []).append(row)

    documents = build_gene_documents(variants, gene_info_by_symbol, medgen_by_cui, hpo_rows_by_gene)

    empty_genes = find_empty_genes(documents)
    if empty_genes:
        print(
            f"ATTENTION: aucun variant ni metadonnee NCBI Gene pour {', '.join(empty_genes)} "
            "(symbole invalide ou collecte en echec).",
            file=sys.stderr,
        )

    return write_raw_gene_files(documents, DATA_RAW_DIR)


if __name__ == "__main__":
    written_files = run_collection()
    print(f"{len(written_files)} fichiers écrits dans {DATA_RAW_DIR}/")
