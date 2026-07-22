from __future__ import annotations

from pathlib import Path

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Transmis à NCBI avec l'email pour identifier l'appelant.
TOOL_NAME = "rag-genomique-ingestion"

# Ancrés sur la racine du dépôt : la collecte doit écrire au même endroit quel que soit
# le répertoire courant depuis lequel on lance le script.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_EXTERNAL_DIR = PROJECT_ROOT / "data" / "external"
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

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
