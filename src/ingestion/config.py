from __future__ import annotations

from pathlib import Path

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

DATA_EXTERNAL_DIR = Path("data/external")
DATA_RAW_DIR = Path("data/raw")

# Panel germinal complet cancer du sein (haute + modérée pénétrance) — genes_cancer_sein.md
BREAST_CANCER_GENES = [
    "BRCA1", "BRCA2", "TP53", "PALB2", "PTEN", "CDH1", "STK11",
    "ATM", "CHEK2", "BARD1", "RAD51C", "RAD51D",
]

# Gène causal + modificateurs HbF majeurs + co-morbidité — genes_drepanocytose.md
SICKLE_CELL_GENES = ["HBB", "BCL11A", "HBS1L-MYB", "KLF1", "G6PD"]

ALL_GENES = BREAST_CANCER_GENES + SICKLE_CELL_GENES
