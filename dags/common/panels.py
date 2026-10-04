from __future__ import annotations

from airflow.sdk import Asset

from ingestion.config import BREAST_CANCER_GENES, SICKLE_CELL_GENES

# Source unique de vérité : les listes de gènes vivent dans ingestion.config, où
# elles sont déjà sous test.
PANELS: dict[str, list[str]] = {
    "brca": BREAST_CANCER_GENES,
    "sickle": SICKLE_CELL_GENES,
}

PANEL_LABELS: dict[str, str] = {
    "brca": "Cancer du sein héréditaire",
    "sickle": "Drépanocytose et modificateurs HbF",
}

# Le bronze ne filtre pas sur le panel : la conversion d'une source partagée est
# identique pour tous les panels et s'exécute une seule fois, dans le DAG
# d'acquisition. Les sources par panel sont converties dans chaque DAG de panel.
SHARED_SOURCES: list[str] = ["clinvar", "hpo"]
PANEL_SOURCES: list[str] = ["ncbi_gene", "refseq", "medgen", "hpo_terms"]

# Publié quand le bronze des sources partagées est complet : les DAGs de panel se
# déclenchent sur la donnée réellement disponible, pas sur un horaire.
SOURCES_READY = Asset("s3://bronze/_sources_pretes")

# Pool Airflow à un seul slot pour les tâches qui interrogent les E-utilities NCBI.
# Le `RateLimiter` de `http_client` est par processus : deux DAGs de panel lancés
# ensemble, chacun avec trois tâches NCBI, dépasseraient la limite globale de NCBI
# (3 req/s, 10 avec clé). Le pool est créé par le service `airflow-init`.
NCBI_POOL = "ncbi"

# Pool Airflow à un seul slot pour bronze_to_silver : les neuf tables Silver sont
# partagées entre les deux panels (partitionnées par `panel`, pas par run), et les
# deux DAGs de panel se déclenchent sur le même Asset SOURCES_READY — sans ce pool,
# une création de table Delta concurrente (`DeltaTable.is_deltatable()` avant le
# premier commit) peut effacer silencieusement le panel de l'autre run. Le pool est
# créé par le service `airflow-init`, comme `NCBI_POOL`.
SILVER_WRITE_POOL = "silver_write"

# Les tables Gold sont, comme les Silver, partagées entre les deux panels : le même
# risque d'écriture concurrente s'applique. Pool créé par le service `airflow-init`.
GOLD_WRITE_POOL = "gold_write"

# Une indexation RAG à la fois : le service d'embedding sature déjà le processeur, et
# deux indexations du même panel se bloqueraient sur le verrou de la base. Pool créé
# par le service `airflow-init`.
RAG_INDEX_POOL = "rag_index"
