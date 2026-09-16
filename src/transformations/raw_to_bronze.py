"""Passage raw -> bronze : conversion en Parquet, colonnes techniques, rien d'autre.

Deux convertisseurs génériques (`_convert_flat_source` pour les sources TSV,
`_convert_jsonl_source` pour les sources JSONL) dispatchés par une table déclarative
par source. Voir docs/superpowers/specs/2026-09-16-sous-projet-b-raw-bronze-design.md.
"""

from __future__ import annotations

import re


def _normalize_column_name(name: str) -> str:
    """Minuscule, tout non-alphanumérique devient `_`, runs fusionnés, bords retirés.

    Mécanique et sans exception : `#AlleleID` -> `alleleid` (pas de coupure aux
    frontières minuscule->MAJUSCULE, qui serait incohérente avec un sigle comme
    `dbSNP` dans `RS# (dbSNP)` -> `rs_dbsnp`, laissé tel quel). Le découpage en mots
    est une décision Silver, pas Bronze.
    """
    return re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()


def raw_to_bronze(
    logical_date: str,
    sources: list[str],
    panel: str | None = None,
    lake_uri: str | None = None,
) -> list[str]:
    """Convertit les partitions raw des sources données en Parquet dans la couche bronze.

    Contrat d'entrée : partitions `raw/<source>/dt=<date>[/panel=<panel>]` complètes
    (marqueur `_SUCCESS` présent, vérifié par `check_raw` en amont — pas revérifié ici).

    Contrat de sortie : partitions `bronze/<source>/dt=<date>[/panel=<panel>]` en
    Parquet (`data.parquet`), écrites selon le protocole `begin_partition` → données →
    manifest → `_SUCCESS`. Renvoie leurs URI.

    Règle : ce passage change le format et rien d'autre. Colonnes lues en chaînes,
    noms de colonnes normalisés (sources flat), colonnes techniques
    `_source_version`/`_logical_date`/`_ingested_at` propagées depuis le manifest
    raw. Aucun filtre, aucun typage métier, aucun dédoublonnage ; seule une ligne
    entièrement vide peut être retirée. Les payloads imbriqués des sources JSONL
    restent des chaînes JSON, jamais aplatis. Le bulk ClinVar se lit en mode lazy et
    s'écrit en flux, jamais chargé entièrement en mémoire.
    """
    raise NotImplementedError("raw_to_bronze : implémenté tâche par tâche — voir Task 4")
