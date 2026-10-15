"""Constantes du projet : panel de gènes, chemins, couches du lac et tables Silver."""
from __future__ import annotations

import os
import re
from pathlib import Path

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Identifie l'appelant auprès de NCBI, avec l'email.
TOOL_NAME = "rag-genomique-ingestion"

# Chemins ancrés sur la racine du dépôt, indépendants du répertoire courant.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_EXTERNAL_DIR = PROJECT_ROOT / "data" / "external"
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

# Couches du médaillon : un bucket MinIO chacune, ou un sous-dossier de DEFAULT_LAKE_DIR en local.
RAW = "raw"
BRONZE = "bronze"
SILVER = "silver"
GOLD = "gold"

DEFAULT_LAKE_DIR = PROJECT_ROOT / "data" / "lake"

# Date logique d'un run (AAAA-MM-JJ) ; ici pour que les DAGs la valident sans importer polars.
LOGICAL_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def current_lake_uri() -> str:
    """Renvoie la racine du lac (`LAKE_URI`, sinon le dossier local), lue à chaque appel."""
    return os.environ.get("LAKE_URI") or f"file://{DEFAULT_LAKE_DIR}"


# Panel germinal cancer du sein, haute et modérée pénétrance.
BREAST_CANCER_GENES = [
    "BRCA1", "BRCA2", "TP53", "PALB2", "PTEN", "CDH1", "STK11",
    "ATM", "CHEK2", "BARD1", "RAD51C", "RAD51D",
]

# Drépanocytose : gène causal, modificateurs HbF (locus HBS1L-MYB couvert par ses deux gènes), co-morbidité.
SICKLE_CELL_GENES = ["HBB", "BCL11A", "HBS1L", "MYB", "KLF1", "G6PD"]

ALL_GENES = BREAST_CANCER_GENES + SICKLE_CELL_GENES

PANEL_GENES: dict[str, list[str]] = {"brca": BREAST_CANCER_GENES, "sickle": SICKLE_CELL_GENES}

# Tables Silver, partagées par bronze_to_silver et quality_check_silver.
SILVER_TABLES = [
    "clinvar_variant", "clinvar_variant_gene", "clinvar_variant_disease", "ncbi_gene",
    "refseq_transcript", "medgen_concept", "medgen_mim", "medgen_inheritance",
    "hpo_gene_phenotype", "hpo_term",
]
