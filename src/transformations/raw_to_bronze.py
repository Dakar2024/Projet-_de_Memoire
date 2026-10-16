"""Passage raw → bronze : intégrité et en-tête des sources vérifiés, conversion en Parquet, colonnes techniques."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from ingestion.config import BRONZE, RAW
from ingestion.errors import SourceSchemaError
from ingestion.storage import (
    begin_partition,
    build_manifest,
    finalize_partition,
    get_bytes,
    open_stream,
    partition_uri,
    put_file,
    read_manifest,
)


def _normalize_column_name(name: str) -> str:
    """Normalise un nom de colonne : minuscules, non-alphanumériques en `_` (`#AlleleID` → `alleleid`)."""
    return re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()


def _download_to_local(
    raw_partition: str, object_name: str, work_dir: Path, expected_sha256: str | None = None
) -> Path:
    """Copie un objet raw en local, en flux, et vérifie son SHA-256 s'il est au manifest ; garde l'extension."""
    local_path = work_dir / object_name
    digest = hashlib.sha256()
    with open_stream(f"{raw_partition}/{object_name}") as src, open(local_path, "wb") as dst:
        while chunk := src.read(1024 * 1024):
            digest.update(chunk)
            dst.write(chunk)
    # Partitions déposées avant le 16/10/2026 : pas de somme au manifest, rien à comparer.
    if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
        raise ValueError(
            f"SHA-256 de {raw_partition}/{object_name} différent de celui du manifest : "
            "objet raw altéré depuis son dépôt, relancer l'acquisition"
        )
    return local_path


def _check_columns(location: str, actual: list[str], expected: tuple[str, ...]) -> None:
    """Refuse un en-tête dont l'ensemble des colonnes diffère du schéma attendu, en nommant les écarts."""
    missing = sorted(set(expected) - set(actual))
    added = sorted(set(actual) - set(expected))
    if missing or added:
        raise SourceSchemaError(
            f"{location} : schéma changé par la source, colonnes manquantes {missing}, nouvelles {added} ; "
            "mettre à jour le schéma attendu (raw_to_bronze) et le Silver avant de relancer"
        )


def _convert_flat_source(
    raw_partition: str,
    object_name: str,
    technical_columns: dict[str, str],
    work_dir: Path,
    expected_sha256: str | None = None,
    expected_columns: tuple[str, ...] | None = None,
) -> Path:
    """Convertit une source TSV en Parquet, en flux : intégrité et en-tête vérifiés, noms normalisés."""
    local_input = _download_to_local(raw_partition, object_name, work_dir, expected_sha256)
    lf = pl.scan_csv(local_input, separator="\t", infer_schema_length=0)
    original_names = lf.collect_schema().names()
    if expected_columns is not None:
        _check_columns(f"{raw_partition}/{object_name}", original_names, expected_columns)
    lf = lf.rename({name: _normalize_column_name(name) for name in original_names})
    lf = lf.filter(~pl.all_horizontal(pl.all().is_null()))
    # Colonnes techniques ajoutées après le filtre : jamais vides, elles masqueraient les lignes vides.
    lf = lf.with_columns(
        [pl.lit(value).alias(key) for key, value in technical_columns.items()]
    )
    output_path = work_dir / "output.parquet"
    lf.sink_parquet(output_path)
    return output_path


def _convert_jsonl_source(
    raw_partition: str,
    object_name: str,
    scalar_fields: tuple[str, ...],
    nested_fields: tuple[str, ...],
    technical_columns: dict[str, str],
    work_dir: Path,
) -> Path:
    """Convertit une source JSONL en Parquet : scalaires en colonnes, imbriqués en chaîne `<champ>_json`."""
    raw = gzip.decompress(get_bytes(f"{raw_partition}/{object_name}")).decode("utf-8")
    rows: list[dict] = []
    for line in raw.splitlines():
        if not line:
            continue
        record = json.loads(line)
        row = {field: record.get(field) for field in scalar_fields}
        row.update(
            {f"{field}_json": json.dumps(record.get(field)) for field in nested_fields}
        )
        rows.append(row)

    schema = {field: pl.Utf8 for field in scalar_fields}
    schema |= {f"{field}_json": pl.Utf8 for field in nested_fields}
    df = pl.DataFrame(rows, schema=schema)
    df = df.with_columns(
        [pl.lit(value).alias(key) for key, value in technical_columns.items()]
    )
    output_path = work_dir / "output.parquet"
    df.write_parquet(output_path)
    return output_path


@dataclass(frozen=True)
class _FlatSource:
    object_name: str
    columns: tuple[str, ...]


# En-têtes attendus, figés sur les fichiers réels (ClinVar 2026-09 et 2026-10, HPO v2026-09-01) : le Silver
# `clinvar_variant` garde toutes les colonnes, donc un ajout comme un retrait change son schéma Delta.
CLINVAR_COLUMNS: tuple[str, ...] = (
    "#AlleleID", "Type", "Name", "GeneID", "GeneSymbol", "HGNC_ID", "ClinicalSignificance", "ClinSigSimple",
    "LastEvaluated", "RS# (dbSNP)", "nsv/esv (dbVar)", "RCVaccession", "PhenotypeIDS", "PhenotypeList",
    "Origin", "OriginSimple", "Assembly", "ChromosomeAccession", "Chromosome", "Start", "Stop",
    "ReferenceAllele", "AlternateAllele", "Cytogenetic", "ReviewStatus", "NumberSubmitters", "Guidelines",
    "TestedInGTR", "OtherIDs", "SubmitterCategories", "VariationID", "PositionVCF", "ReferenceAlleleVCF",
    "AlternateAlleleVCF", "SomaticClinicalImpact", "SomaticClinicalImpactLastEvaluated",
    "ReviewStatusClinicalImpact", "Oncogenicity", "OncogenicityLastEvaluated", "ReviewStatusOncogenicity",
    "SCVsForAggregateGermlineClassification", "SCVsForAggregateSomaticClinicalImpact",
    "SCVsForAggregateOncogenicityClassification",
)
HPO_GENES_TO_PHENOTYPE_COLUMNS: tuple[str, ...] = (
    "ncbi_gene_id", "gene_symbol", "hpo_id", "hpo_name", "frequency", "disease_id",
)


@dataclass(frozen=True)
class _JsonlSource:
    object_name: str
    scalar_fields: tuple[str, ...]
    nested_fields: tuple[str, ...]


# Table déclarative des sources : fichier raw et, pour le JSONL, champs scalaires et imbriqués.
_FLAT_SOURCES: dict[str, _FlatSource] = {
    "clinvar": _FlatSource("variant_summary.txt.gz", CLINVAR_COLUMNS),
    "hpo": _FlatSource("genes_to_phenotype.txt", HPO_GENES_TO_PHENOTYPE_COLUMNS),
}

_JSONL_SOURCES: dict[str, _JsonlSource] = {
    "ncbi_gene": _JsonlSource("gene_summaries.jsonl.gz", ("gene_symbol",), ("esummary",)),
    "refseq": _JsonlSource("transcripts.jsonl.gz", ("gene_symbol",), ("transcripts",)),
    "medgen": _JsonlSource("concepts.jsonl.gz", ("cui",), ("esummary",)),
    "hpo_terms": _JsonlSource(
        "hpo_terms.jsonl.gz",
        ("gene_symbol", "hpo_id", "hpo_name"),
        ("details",),
    ),
}

OUTPUT_OBJECT_NAME = "data.parquet"


def raw_to_bronze(
    logical_date: str,
    sources: list[str],
    panel: str | None = None,
    lake_uri: str | None = None,
) -> list[str]:
    """Convertit les partitions raw complètes des sources en partitions bronze Parquet et renvoie leurs URI."""
    partitions: list[str] = []
    for source in sources:
        if source in _FLAT_SOURCES:
            spec: _FlatSource | _JsonlSource = _FLAT_SOURCES[source]
        elif source in _JSONL_SOURCES:
            spec = _JSONL_SOURCES[source]
        else:
            raise ValueError(f"source inconnue de raw_to_bronze : {source!r}")

        raw_partition = partition_uri(RAW, source, logical_date, panel=panel, lake_uri=lake_uri)
        bronze_partition = partition_uri(BRONZE, source, logical_date, panel=panel, lake_uri=lake_uri)
        raw_manifest = read_manifest(raw_partition)
        if raw_manifest is None:
            raise ValueError(f"partition raw sans manifest : {raw_partition}")
        technical_columns = {
            "_source_version": raw_manifest["source_version"],
            "_logical_date": logical_date,
            "_ingested_at": raw_manifest["written_at"],
        }

        begin_partition(bronze_partition)
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            if isinstance(spec, _FlatSource):
                output_path = _convert_flat_source(
                    raw_partition, spec.object_name, technical_columns, work_dir,
                    raw_manifest.get("sha256", {}).get(spec.object_name), spec.columns,
                )
            else:
                output_path = _convert_jsonl_source(
                    raw_partition, spec.object_name, spec.scalar_fields,
                    spec.nested_fields, technical_columns, work_dir,
                )

            record_count = pl.scan_parquet(output_path).select(pl.len()).collect().item()
            file_size = output_path.stat().st_size
            put_file(f"{bronze_partition}/{OUTPUT_OBJECT_NAME}", output_path)

        finalize_partition(
            bronze_partition,
            build_manifest(
                source=source,
                logical_date=logical_date,
                source_url=raw_partition,
                source_version=raw_manifest["source_version"],
                files={OUTPUT_OBJECT_NAME: file_size},
                record_count=record_count,
                panel=panel,
            ),
        )
        partitions.append(bronze_partition)
    return partitions
