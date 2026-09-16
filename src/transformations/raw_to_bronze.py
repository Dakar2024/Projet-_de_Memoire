"""Passage raw -> bronze : conversion en Parquet, colonnes techniques, rien d'autre.

Deux convertisseurs génériques (`_convert_flat_source` pour les sources TSV,
`_convert_jsonl_source` pour les sources JSONL) dispatchés par une table déclarative
par source. Voir docs/superpowers/specs/2026-09-16-sous-projet-b-raw-bronze-design.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from ingestion.storage import open_stream


def _normalize_column_name(name: str) -> str:
    """Minuscule, tout non-alphanumérique devient `_`, runs fusionnés, bords retirés.

    Mécanique et sans exception : `#AlleleID` -> `alleleid` (pas de coupure aux
    frontières minuscule->MAJUSCULE, qui serait incohérente avec un sigle comme
    `dbSNP` dans `RS# (dbSNP)` -> `rs_dbsnp`, laissé tel quel). Le découpage en mots
    est une décision Silver, pas Bronze.
    """
    return re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()


def _download_to_local(raw_partition: str, object_name: str, work_dir: Path) -> Path:
    """Copie un objet raw vers un fichier local, en flux, sans le charger en mémoire.

    Le nom de fichier local reprend `object_name` (donc son extension `.gz` le cas
    échéant) : Polars détecte la compression gzip d'un CSV local sur l'extension,
    déjà le comportement dont dépend `ingestion.clinvar.filter_clinvar`.
    """
    local_path = work_dir / object_name
    with open_stream(f"{raw_partition}/{object_name}") as src, open(local_path, "wb") as dst:
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)
    return local_path


def _convert_flat_source(
    raw_partition: str,
    object_name: str,
    technical_columns: dict[str, str],
    work_dir: Path,
) -> Path:
    """Convertit une source flat (TSV) en Parquet, en lazy, sans jamais tout charger.

    Colonnes renommées (mécaniquement), lignes entièrement vides retirées, colonnes
    techniques ajoutées après ce filtre (elles ne sont jamais vides, ce qui
    fausserait la détection d'une ligne vide si elles étaient ajoutées avant).
    """
    local_input = _download_to_local(raw_partition, object_name, work_dir)
    lf = pl.scan_csv(local_input, separator="\t", infer_schema_length=0)
    original_names = lf.collect_schema().names()
    lf = lf.rename({name: _normalize_column_name(name) for name in original_names})
    lf = lf.filter(~pl.all_horizontal(pl.all().is_null()))
    lf = lf.with_columns(
        [pl.lit(value).alias(key) for key, value in technical_columns.items()]
    )
    output_path = work_dir / "output.parquet"
    lf.sink_parquet(output_path)
    return output_path


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
