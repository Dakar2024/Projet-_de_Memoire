from __future__ import annotations

from transformations import SPEC


def raw_to_bronze(
    logical_date: str,
    sources: list[str],
    panel: str | None = None,
    lake_uri: str | None = None,
) -> list[str]:
    """Convertit les partitions raw des sources données en Parquet dans la couche bronze.

    Contrat d'entrée : partitions `raw/<source>/dt=<date>[/panel=<panel>]` complètes
    (marqueur `_SUCCESS` présent).

    Contrat de sortie : partitions `bronze/<source>/dt=<date>[/panel=<panel>]` en
    Parquet, closes par `manifest.json` puis `_SUCCESS`. Renvoie leurs URI.

    Règle : ce passage change le format et rien d'autre. Colonnes lues en chaînes,
    noms de colonnes normalisés, colonnes techniques `_source_version`,
    `_logical_date`, `_ingested_at`. Aucun filtre, aucun typage métier, aucun
    dédoublonnage ; seule une ligne entièrement vide peut être retirée. Le XML
    `conceptmeta` reste une chaîne. Le bulk ClinVar se lit en mode lazy et s'écrit en
    flux, jamais chargé entièrement en mémoire.
    """
    raise NotImplementedError(f"raw_to_bronze : implémenté par le sous-projet B ({SPEC}, §7)")
