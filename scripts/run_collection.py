"""Collecte historique : un JSON par gène dans `data/raw/` (hors pipeline médaillon)."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from ingestion.clinvar import CLINVAR_BULK_URL, download_variant_summary, filter_clinvar
from ingestion.config import ALL_GENES, DATA_EXTERNAL_DIR, DATA_RAW_DIR
from ingestion.hpo import (
    GENES_TO_PHENOTYPE_URL,
    HP_TERMS_URL,
    download_hpo_files,
    enrich_hpo_rows,
    fetch_hpo_term_details,
    parse_genes_to_phenotype,
)
from ingestion.http_client import NcbiClient
from ingestion.medgen import fetch_medgen_concept
from ingestion.ncbi_gene import fetch_gene_info
from ingestion.orchestrate import (
    add_medgen_cuis,
    build_gene_documents,
    find_empty_genes,
    write_raw_gene_files,
)


def run_collection(
    genes: list[str] = ALL_GENES, refresh: bool = False
) -> tuple[list[Path], list[str]]:
    """Collecte les 4 sources, écrit un JSON par gène et renvoie les fichiers écrits et les gènes incomplets."""
    load_dotenv()
    if not os.environ.get("NCBI_EMAIL"):
        raise SystemExit(
            "NCBI_EMAIL manquant : copier .env.example en .env et y renseigner votre email."
        )
    client = NcbiClient(email=os.environ["NCBI_EMAIL"], api_key=os.environ.get("NCBI_API_KEY", ""))

    bulk_path = DATA_EXTERNAL_DIR / "variant_summary.txt.gz"
    if bulk_path.exists() and not refresh:
        age = datetime.fromtimestamp(bulk_path.stat().st_mtime)
        print(
            f"Réutilisation du bulk ClinVar téléchargé le {age:%Y-%m-%d %H:%M} "
            "(--refresh pour le retélécharger)."
        )
    clinvar_path = download_variant_summary(bulk_path, force=refresh)
    variants = add_medgen_cuis(filter_clinvar(clinvar_path, genes))

    gene_info_by_symbol = {gene: fetch_gene_info(client, gene) for gene in genes}

    all_cuis: list[str] = []
    for cui_list in variants["medgen_cuis"].to_list():
        for cui in cui_list:
            if cui not in all_cuis:
                all_cuis.append(cui)
    medgen_by_cui = {cui: fetch_medgen_concept(client, cui) for cui in all_cuis}

    hpo_paths = download_hpo_files(DATA_EXTERNAL_DIR, force=refresh)
    hpo_rows = parse_genes_to_phenotype(hpo_paths["genes_to_phenotype"], genes)
    hpo_term_details = fetch_hpo_term_details([row["hpo_id"] for row in hpo_rows])
    hpo_rows = enrich_hpo_rows(hpo_rows, hpo_term_details)
    hpo_rows_by_gene: dict[str, list[dict]] = {}
    for row in hpo_rows:
        hpo_rows_by_gene.setdefault(row["gene_symbol"], []).append(row)

    provenance = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "n_genes": len(genes),
        "clinvar_bulk_url": CLINVAR_BULK_URL,
        "clinvar_bulk_mtime": datetime.fromtimestamp(
            clinvar_path.stat().st_mtime, timezone.utc
        ).isoformat(),
        "hpo_genes_to_phenotype_url": GENES_TO_PHENOTYPE_URL,
        "hpo_genes_to_phenotype_mtime": datetime.fromtimestamp(
            hpo_paths["genes_to_phenotype"].stat().st_mtime, timezone.utc
        ).isoformat(),
        "hpo_terms_api_url": HP_TERMS_URL,
    }

    documents = build_gene_documents(
        variants, gene_info_by_symbol, medgen_by_cui, hpo_rows_by_gene, provenance=provenance
    )

    return write_raw_gene_files(documents, DATA_RAW_DIR), find_empty_genes(documents)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Collecte les données brutes ClinVar / NCBI Gene / MedGen / HPO."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="retélécharge le bulk ClinVar (~440 Mo) au lieu de réutiliser l'existant",
    )
    args = parser.parse_args()

    written_files, incomplete_genes = run_collection(refresh=args.refresh)
    print(f"{len(written_files)} fichiers écrits dans {DATA_RAW_DIR}/")

    if incomplete_genes:
        # Code 1 : distingue une collecte partielle d'une collecte complète.
        print(
            f"ATTENTION : variants ou métadonnées NCBI Gene manquants pour "
            f"{', '.join(incomplete_genes)} (symbole invalide ou collecte en échec).",
            file=sys.stderr,
        )
        sys.exit(1)
