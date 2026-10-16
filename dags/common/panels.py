"""Panels, sources, Asset et pools Airflow partagés par les DAGs."""
from __future__ import annotations

from airflow.sdk import Asset

from ingestion.config import PANEL_GENES

PANELS: dict[str, list[str]] = PANEL_GENES

PANEL_LABELS: dict[str, str] = {
    "brca": "Cancer du sein héréditaire",
    "sickle": "Drépanocytose et modificateurs HbF",
}

# Sources partagées converties une fois par l'acquisition ; sources par panel, dans chaque DAG de panel.
SHARED_SOURCES: list[str] = ["clinvar", "hpo"]
PANEL_SOURCES: list[str] = ["ncbi_gene", "refseq", "medgen", "hpo_terms"]

# Émis quand le bronze partagé est complet ; déclenche les DAGs de panel.
SOURCES_READY = Asset("s3://bronze/_sources_pretes")

# Pools à un slot, créés par `airflow-init`. NCBI : la limite de débit est globale, le limiteur par processus.
NCBI_POOL = "ncbi"

# Conversions lourdes (ClinVar ≈ 2 Go, Silver 1,37 Go, plafond 3 Go) et écritures Delta partagées entre
# panels (une création concurrente effacerait l'autre panel) : une seule à la fois, par construction.
HEAVY_CONVERSION_POOL = "conversion_lourde"
# Une indexation RAG à la fois : le service d'embedding sature déjà le processeur.
RAG_INDEX_POOL = "rag_index"
