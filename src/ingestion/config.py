from __future__ import annotations

import os
import re
from pathlib import Path

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Transmis à NCBI avec l'email pour identifier l'appelant.
TOOL_NAME = "rag-genomique-ingestion"

# Ancrés sur la racine du dépôt : la collecte doit écrire au même endroit quel que soit
# le répertoire courant depuis lequel on lance le script.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_EXTERNAL_DIR = PROJECT_ROOT / "data" / "external"
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

# Couches du médaillon : raw (format de la source), bronze (Parquet), silver et
# gold (Delta). Sur MinIO, chaque couche est un bucket ; en local, un sous-dossier
# de DEFAULT_LAKE_DIR.
RAW = "raw"
BRONZE = "bronze"
SILVER = "silver"
GOLD = "gold"

DEFAULT_LAKE_DIR = PROJECT_ROOT / "data" / "lake"

# Format de la date logique d'un run (`AAAA-MM-JJ`). Vit ici plutôt que dans
# `clinvar.py` : les DAGs la valident à chaque parsing, et `clinvar.py` importe polars.
LOGICAL_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def current_lake_uri() -> str:
    """Racine du lac, lue à l'appel (et non à l'import) pour rester testable.

    `file://<chemin>` en local et dans les tests, `s3://` quand les couches sont
    des buckets MinIO. Le défaut local garantit que la suite de tests tourne sans
    conteneur ni réseau.
    """
    return os.environ.get("LAKE_URI") or f"file://{DEFAULT_LAKE_DIR}"

# Panel germinal complet cancer du sein (haute + modérée pénétrance) — genes_cancer_sein.md
BREAST_CANCER_GENES = [
    "BRCA1", "BRCA2", "TP53", "PALB2", "PTEN", "CDH1", "STK11",
    "ATM", "CHEK2", "BARD1", "RAD51C", "RAD51D",
]

# Gène causal + modificateurs HbF majeurs + co-morbidité — genes_drepanocytose.md
# Le locus modulateur HbF est couvert par HBS1L et MYB : la région intergénique "HBS1L-MYB"
# n'est pas un symbole interrogeable (0 variant ClinVar, esearch NCBI Gene vide).
SICKLE_CELL_GENES = ["HBB", "BCL11A", "HBS1L", "MYB", "KLF1", "G6PD"]

ALL_GENES = BREAST_CANCER_GENES + SICKLE_CELL_GENES

PANEL_GENES: dict[str, list[str]] = {"brca": BREAST_CANCER_GENES, "sickle": SICKLE_CELL_GENES}

# Les neuf tables Silver produites par bronze_to_silver et contrôlées par
# quality_check_silver — une seule source pour que les deux ne divergent jamais si
# une table est ajoutée ou renommée par un sous-projet ultérieur.
SILVER_TABLES = [
    "clinvar_variant", "clinvar_variant_gene", "ncbi_gene", "refseq_transcript",
    "medgen_concept", "medgen_mim", "medgen_inheritance", "hpo_gene_phenotype", "hpo_term",
]
