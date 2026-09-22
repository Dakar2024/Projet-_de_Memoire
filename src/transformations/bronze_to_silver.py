"""Passage bronze -> silver : dix tables Delta typées, historique SCD2 sur
`clinvar_variant`. Voir docs/superpowers/specs/2026-09-16-sous-projet-c-bronze-silver-design.md.
"""

from __future__ import annotations

import io
import json
import re

import polars as pl
from deltalake import DeltaTable

from ingestion.config import BRONZE, PANEL_GENES
from ingestion.medgen import parse_medgen_conceptmeta
from ingestion.storage import get_bytes, layer_uri, partition_uri, scan_parquet, storage_options


# Jamais propagées dans une table Silver (contrainte globale de ce plan) : aucun
# bâtisseur n'en a besoin, retirées une bonne fois ici plutôt que dans chacun.
# `strict=False` : les fixtures de test, minimales, ne les incluent pas toujours —
# ce n'est pas une erreur de les retirer quand elles sont déjà absentes.
_BRONZE_TECHNICAL_COLUMNS = ["_source_version", "_logical_date", "_ingested_at"]


def _read_bronze_table(bronze_partition: str) -> pl.DataFrame:
    """Relit le Parquet d'une partition bronze (fichier unique `data.parquet`),
    sans ses colonnes techniques (`_source_version`/`_logical_date`/`_ingested_at`)."""
    df = pl.read_parquet(io.BytesIO(get_bytes(f"{bronze_partition}/data.parquet")))
    return df.drop(_BRONZE_TECHNICAL_COLUMNS, strict=False)


def _write_silver_snapshot(df: pl.DataFrame, table_uri: str, panel: str) -> None:
    """Remplace entièrement les lignes du panel dans une table Silver sans historique.

    `predicate` scinde l'overwrite à la seule partition `panel` courante : sans lui,
    chaque run écraserait la table entière et effacerait l'autre panel.
    """
    df.write_delta(
        table_uri,
        mode="overwrite",
        storage_options=storage_options(table_uri),
        delta_write_options={"partition_by": ["panel"], "predicate": f"panel = '{panel}'"},
    )


def _load_clinvar_variants(bronze_partition: str, genes: list[str]) -> pl.DataFrame:
    """Lit la partition ClinVar bronze en lazy, filtrée GRCh38, restreinte aux
    `alleleid` du panel et dédoublonnée sur `alleleid` — `clinvar_variant_gene` et
    `clinvar_variant` en dérivent toutes les deux, pour ne jamais diverger sur
    l'ensemble des `alleleid` qu'elles couvrent.

    Le filtre au panel précède le `.collect()` : matérialiser tout le ClinVar GRCh38
    fait tuer le worker Airflow par OOM (vérifié en run réel). Il retient un
    `alleleid` dès qu'une de ses lignes GRCh38 cite un gène du panel ; le
    dédoublonnage (première ligne gardée, ordre préservé) donne donc les mêmes lignes
    que s'il était appliqué au bulk entier, et `_build_clinvar_variant_gene` refiltre
    au panel sur la ligne retenue."""
    grch38 = (
        scan_parquet(f"{bronze_partition}/data.parquet")
        .drop(_BRONZE_TECHNICAL_COLUMNS, strict=False)
        .filter(pl.col("assembly") == "GRCh38")
    )
    panel_ids = (
        grch38.select("alleleid", pl.col("genesymbol").str.split(";").alias("gene_symbol"))
        .explode("gene_symbol", empty_as_null=True)
        .filter(pl.col("gene_symbol").is_in(genes))
        .select("alleleid")
        .unique()
        .collect()["alleleid"]
        .to_list()
    )
    return (
        grch38.filter(pl.col("alleleid").is_in(panel_ids))
        .unique(subset=["alleleid"], keep="first", maintain_order=True)
        .collect()
    )


def _build_clinvar_variant_gene(clinvar_variants: pl.DataFrame, genes: list[str]) -> pl.DataFrame:
    """Éclate `genesymbol` (jointure `;` pour les variants multi-gènes) et filtre au panel.

    C'est cette table, et non `clinvar_variant`, qui décide quels `alleleid`
    appartiennent au panel : `clinvar_variant` la consulte plutôt que de refiltrer
    `genesymbol` elle-même. Reçoit `clinvar_variants` déjà filtré GRCh38 et
    dédoublonné par `_load_clinvar_variants` : pas de filtre ni de dédoublonnage ici.
    """
    exploded = (
        clinvar_variants.select(["alleleid", "genesymbol"])
        .with_columns(pl.col("genesymbol").str.split(";").alias("gene_symbol"))
        .explode("gene_symbol")
        .drop("genesymbol")
    )
    return exploded.filter(pl.col("gene_symbol").is_in(genes))


# Identifiants portés par `phenotypeids`. `MedGen:` accepte la forme `CN123`
# (concepts sans code UMLS), comme `ingestion.medgen.MEDGEN_CUI_PATTERN`.
_DISEASE_ID_PATTERNS = {
    "medgen_cui": r"MedGen:(CN?\d+)",
    "omim_id": r"OMIM:(\d+)",
    "orpha_id": r"Orphanet:(\d+)",
    "mondo_id": r"MONDO:(MONDO:\d+)",
}

# ClinVar emploie ces libellés quand le soumetteur n'a pas nommé de maladie. Ils
# portent leur propre CUI vide côté MedGen (C3661900, CN169374, CN517202 — 31 875
# occurrences sur le run de 2026-09), donc filtrer sur l'absence d'identifiant ne
# suffirait pas.
_PLACEHOLDER_DISEASE_NAMES = ["not provided", "not specified"]


def _build_clinvar_variant_disease(clinvar_variants: pl.DataFrame) -> pl.DataFrame:
    """Éclate `phenotypelist`/`phenotypeids` en une ligne par (variant, maladie).

    Les deux colonnes sont alignées sur `|`, puis sur `;` à l'intérieur d'un groupe
    (vérifié sur le run réel : 96 892/96 892 sur `|`, 201 097/201 098 sur `;`). Un
    groupe désaligné garde ses identifiants et laisse le nom nul : associer un nom à
    la mauvaise maladie serait pire que de n'en donner aucun.
    """
    groups = (
        clinvar_variants.select(
            "alleleid",
            pl.col("phenotypelist").str.split("|").alias("group_names"),
            pl.col("phenotypeids").str.split("|").alias("group_ids"),
        )
        .filter(pl.col("group_names").list.len() == pl.col("group_ids").list.len())
        .explode("group_names", "group_ids")
        .with_columns(
            pl.col("group_names").str.split(";").alias("names"),
            pl.col("group_ids").str.split(";").alias("ids"),
        )
    )
    same_length = pl.col("names").list.len() == pl.col("ids").list.len()
    aligned = groups.filter(same_length).explode("names", "ids")
    misaligned = (
        groups.filter(~same_length)
        .explode("ids")
        .with_columns(pl.lit(None, dtype=pl.Utf8).alias("names"))
    )

    rows = pl.concat([
        aligned.select("alleleid", "names", "ids"),
        misaligned.select("alleleid", "names", "ids"),
    ]).with_columns(
        pl.col("names").str.strip_chars().alias("disease_name"),
        *[
            pl.col("ids").str.extract(pattern, 1).alias(column)
            for column, pattern in _DISEASE_ID_PATTERNS.items()
        ],
    )

    without_id = pl.all_horizontal(
        [pl.col(column).is_null() for column in _DISEASE_ID_PATTERNS]
    )
    placeholder = pl.col("disease_name").str.to_lowercase().is_in(_PLACEHOLDER_DISEASE_NAMES)
    return (
        rows.filter(~placeholder.fill_null(False) & ~(without_id & pl.col("disease_name").is_null()))
        .select("alleleid", "disease_name", *_DISEASE_ID_PATTERNS)
        .unique(subset=["alleleid", "disease_name", "medgen_cui"], keep="first")
    )


# `NM_014855.3(AP5Z1):c.80_83delinsTGCTG` -> accession, version, gène, HGVS coding.
# Le HGVS protéique, s'il existe, apparaît entre parenthèses après le HGVS coding
# (ex. "...c.1A>G (p.Met1?)") : capturé séparément, absent la plupart du temps.
_HGVS_PATTERN = re.compile(
    r"^(?P<accession>[A-Z]+_\d+)\.(?P<version>\d+)\([^)]+\):(?P<hgvs_c>[^\s(]+)"
    r"(?:\s*\((?P<hgvs_p>p\.[^)]+)\))?"
)


def _parse_hgvs(name: str) -> dict:
    match = _HGVS_PATTERN.match(name)
    if not match:
        return {"refseq_accession": None, "refseq_version": None, "hgvs_c": None, "hgvs_p": None}
    return {
        "refseq_accession": match.group("accession"),
        "refseq_version": int(match.group("version")),
        "hgvs_c": match.group("hgvs_c"),
        "hgvs_p": match.group("hgvs_p"),
    }


def _build_clinvar_variant_rows(
    clinvar_variants: pl.DataFrame, refseq_df: pl.DataFrame, variant_gene: pl.DataFrame
) -> pl.DataFrame:
    """Une ligne par variant du panel, sans l'historique SCD2 (ajouté à l'écriture).

    `rs_dbsnp` en entier, HGVS parsé et validé contre le catalogue RefSeq du panel.
    Ne filtre jamais sur la signification clinique. Reçoit `clinvar_variants` déjà
    filtré GRCh38 et dédoublonné sur `alleleid` par `_load_clinvar_variants` — le même
    ensemble de lignes que `_build_clinvar_variant_gene`, pour que les deux tables ne
    divergent jamais sur les `alleleid` qu'elles couvrent.
    """
    # `.to_list()` : `is_in` avec une Series du même dtype est ambigu et dépréciée
    # côté Polars (avertissement, comportement inchangé) — une liste lève l'ambiguïté.
    panel_ids = variant_gene["alleleid"].unique().to_list()

    filtered = (
        clinvar_variants.filter(pl.col("alleleid").is_in(panel_ids))
        .with_columns(pl.col("rs_dbsnp").cast(pl.Int64))
    )

    parsed = [
        {"alleleid": row["alleleid"], **_parse_hgvs(row["name"])}
        for row in filtered.select(["alleleid", "name"]).to_dicts()
    ]
    hgvs_df = pl.DataFrame(
        parsed,
        schema={
            "alleleid": pl.Utf8, "refseq_accession": pl.Utf8,
            "refseq_version": pl.Int64, "hgvs_c": pl.Utf8, "hgvs_p": pl.Utf8,
        },
    )

    known_accessions = set(refseq_df["accession"].to_list())
    # `is_in` propage le null d'une accession non parsée au lieu de le traiter comme
    # "absente" : `fill_null(False)` pour qu'un HGVS non reconnu reste `False`, pas `null`.
    hgvs_df = hgvs_df.with_columns(
        pl.col("refseq_accession")
        .is_in(known_accessions)
        .fill_null(False)
        .alias("refseq_accession_known")
    )

    return filtered.join(hgvs_df, on="alleleid")


def _build_ncbi_gene(bronze_partition: str) -> pl.DataFrame:
    """Extrait les champs connus d'`esummary_json`. Un gène non résolu (esummary
    vide) garde sa ligne, champs nuls — le verdict qualité appartient à
    `quality_check_silver`, pas à cette étape."""
    df = _read_bronze_table(bronze_partition)
    rows = [
        {
            "gene_symbol": row["gene_symbol"],
            **{
                field: json.loads(row["esummary_json"]).get(field)
                for field in ("name", "description", "maplocation", "summary")
            },
        }
        for row in df.to_dicts()
    ]
    # Schéma explicite : sans lui, une colonne entièrement nulle dans ce lot (ex.
    # `summary` absent pour tous les gènes du panel) s'infère en type `Null`, que
    # Delta refuse à l'écriture — pas seulement un artefact des fixtures de test.
    return pl.DataFrame(
        rows,
        schema={
            "gene_symbol": pl.Utf8, "name": pl.Utf8, "description": pl.Utf8,
            "maplocation": pl.Utf8, "summary": pl.Utf8,
        },
    )


def _build_refseq_transcript(bronze_partition: str) -> pl.DataFrame:
    """Éclate `transcripts_json` (une ligne par transcrit), sépare `accessionversion`
    (`"NM_007294.4"`) en `accession` + `version`. Un gène sans transcrit ne produit
    aucune ligne (liste vide), sans que ce soit une erreur."""
    df = _read_bronze_table(bronze_partition)
    rows = []
    for row in df.to_dicts():
        for transcript in json.loads(row["transcripts_json"]):
            accession, _, version = transcript["accessionversion"].partition(".")
            rows.append({
                "gene_symbol": row["gene_symbol"],
                "accession": accession,
                "version": int(version) if version else None,
            })
    return pl.DataFrame(rows, schema={"gene_symbol": pl.Utf8, "accession": pl.Utf8, "version": pl.Int64})


def _build_medgen_tables(bronze_partition: str) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Parse `esummary_json.conceptmeta` (réutilise `parse_medgen_conceptmeta`, déjà
    testée) pour produire `medgen_concept`, `medgen_mim` et `medgen_inheritance`.

    Un CUI non résolu (`esummary_json` vide) garde sa ligne dans `medgen_concept`,
    XML nul, et n'explose aucune ligne dans les deux autres tables."""
    df = _read_bronze_table(bronze_partition)

    concept_rows, mim_rows, inheritance_rows = [], [], []
    for row in df.to_dicts():
        esummary = json.loads(row["esummary_json"])
        conceptmeta = esummary.get("conceptmeta")
        parsed = parse_medgen_conceptmeta(conceptmeta) if conceptmeta else {
            "mim_number": None, "mim_numbers": [], "mode_inheritance": None,
            "modes_inheritance": [], "clinical_summary": None, "definitions": [],
        }
        concept_rows.append({
            "cui": row["cui"],
            "conceptmeta_xml": conceptmeta,
            "mim_number": parsed["mim_number"] or None,
            "mode_inheritance": parsed["mode_inheritance"] or None,
            "clinical_summary": parsed["clinical_summary"] or None,
        })
        mim_rows.extend({"cui": row["cui"], "mim_number": mim} for mim in parsed["mim_numbers"])
        inheritance_rows.extend(
            {"cui": row["cui"], "mode_inheritance": mode} for mode in parsed["modes_inheritance"]
        )

    # Schéma explicite sur `concept_rows` pour la même raison que `_build_ncbi_gene` :
    # un CUI non résolu (cas fréquent, voir docstring) laisse `mim_number`/
    # `mode_inheritance`/`clinical_summary`/`conceptmeta_xml` nuls sur toute la ligne,
    # et un lot d'un seul CUI non résolu inférerait ces colonnes en type `Null`.
    return (
        pl.DataFrame(
            concept_rows,
            schema={
                "cui": pl.Utf8, "conceptmeta_xml": pl.Utf8, "mim_number": pl.Utf8,
                "mode_inheritance": pl.Utf8, "clinical_summary": pl.Utf8,
            },
        ),
        pl.DataFrame(mim_rows, schema={"cui": pl.Utf8, "mim_number": pl.Utf8}),
        pl.DataFrame(inheritance_rows, schema={"cui": pl.Utf8, "mode_inheritance": pl.Utf8}),
    )


def _build_hpo_gene_phenotype(bronze_partition: str, genes: list[str]) -> pl.DataFrame:
    """Filtre le fichier plat HPO partagé aux gènes du panel. Un panel sans aucune
    ligne (HBS1L, MYB) produit une table vide, légitime — voir `quality_check_silver`."""
    df = _read_bronze_table(bronze_partition)
    return df.filter(pl.col("gene_symbol").is_in(genes))


def _build_hpo_term(bronze_partition: str) -> pl.DataFrame:
    """Extrait `definition`/`synonyms`/`xrefs` de `details_json`. Un terme retiré de
    HPO (details vide) garde sa ligne, champs nuls."""
    df = _read_bronze_table(bronze_partition)
    rows = []
    for row in df.to_dicts():
        details = json.loads(row["details_json"])
        rows.append({
            "gene_symbol": row["gene_symbol"],
            "hpo_id": row["hpo_id"],
            "hpo_name": row["hpo_name"],
            "definition": details.get("definition") or None,
            "synonyms": details.get("synonyms") or [],
            "xrefs": details.get("xrefs") or [],
        })
    # Schéma explicite : `synonyms`/`xrefs` sont des listes vides quand `details_json`
    # n'en fournit pas — sur un lot où c'est le cas pour toutes les lignes, Polars
    # infère `List(Null)`, que Delta refuse à l'écriture, comme pour `_build_ncbi_gene`.
    return pl.DataFrame(
        rows,
        schema={
            "gene_symbol": pl.Utf8, "hpo_id": pl.Utf8, "hpo_name": pl.Utf8,
            "definition": pl.Utf8, "synonyms": pl.List(pl.Utf8), "xrefs": pl.List(pl.Utf8),
        },
    )


# Seuls ces champs, mesurés comme ayant varié d'un mois à l'autre (spec du 15/09,
# §2.2), déclenchent une nouvelle version SCD2. Un autre champ qui change (ex. `name`
# retraité par NCBI) n'est pas une reclassification et ne doit pas en créer une.
_CLINVAR_WATCHED_FIELDS = ["clinicalsignificance", "reviewstatus", "lastevaluated"]


def _write_clinvar_variant(
    rows: pl.DataFrame, table_uri: str, panel: str, logical_date: str
) -> None:
    """Écrit `clinvar_variant` avec historique SCD2 : MERGE si la table existe déjà
    (pour n'importe quel panel), création directe sinon.

    `rows` doit déjà porter une colonne `panel` — comme pour `_write_silver_snapshot`,
    c'est à l'appelant de l'ajouter (cohérent avec l'orchestration de `bronze_to_silver`,
    qui l'ajoute de la même façon aux huit autres tables avant d'écrire).

    Le rejeu du même mois est idempotent : un variant dont les champs surveillés
    n'ont pas changé ne génère aucune ligne — voir `_CLINVAR_WATCHED_FIELDS`.
    """
    if not DeltaTable.is_deltatable(table_uri, storage_options=storage_options(table_uri)):
        initial = rows.with_columns([
            pl.lit(logical_date).alias("valid_from"),
            pl.lit(None, dtype=pl.Utf8).alias("valid_to"),
            pl.lit(True).alias("is_current"),
        ])
        # Toutes les colonnes ClinVar d'origine sont conservées (Silver type, il ne
        # retire jamais une colonne) — seules les trois colonnes SCD2 sont ajoutées.
        initial.write_delta(
            table_uri,
            mode="overwrite",
            storage_options=storage_options(table_uri),
            delta_write_options={"partition_by": ["panel"]},
        )
        return

    current = pl.read_delta(table_uri, storage_options=storage_options(table_uri)).filter(
        pl.col("is_current") & (pl.col("panel") == panel)
    )
    current_ids = current["alleleid"].to_list()

    # `_matched_current` : littéral posé avant le left join, il survit à celui-ci
    # (`null` côté non-matché). Sert d'indicateur de correspondance fiable — contrairement
    # à `cur_<champ>.is_null()`, qui confondrait à tort un champ surveillé réellement
    # `null` côté `current` avec une absence de correspondance, cassant l'idempotence
    # du rejeu.
    current_watched = (
        current.select(["alleleid"] + _CLINVAR_WATCHED_FIELDS)
        .rename({f: f"cur_{f}" for f in _CLINVAR_WATCHED_FIELDS})
        .with_columns(pl.lit(True).alias("_matched_current"))
    )
    joined = rows.join(current_watched, on="alleleid", how="left")
    # `ne_missing` (et non `!=`) : `!=` renvoie `null` dès qu'un des deux côtés est
    # `null`, ce qui masque une vraie transition `null -> valeur` (ignorée par
    # `any_horizontal`). `ne_missing` traite `null != null` comme `False` et
    # `null != valeur` comme `True`, la sémantique voulue ici.
    changed = pl.any_horizontal(
        [pl.col(f).ne_missing(pl.col(f"cur_{f}")) for f in _CLINVAR_WATCHED_FIELDS]
    ) | pl.col("_matched_current").is_null()
    to_process = joined.filter(changed).drop(
        [f"cur_{f}" for f in _CLINVAR_WATCHED_FIELDS] + ["_matched_current"]
    )

    if len(to_process) == 0:
        return

    close_rows = to_process.filter(pl.col("alleleid").is_in(current_ids)).with_columns([
        pl.col("alleleid").alias("merge_key"),
        pl.lit("close").alias("action"),
        pl.lit(None, dtype=pl.Utf8).alias("valid_from"),
        pl.lit(None, dtype=pl.Utf8).alias("valid_to"),
        pl.lit(False).alias("is_current"),
    ])
    insert_rows = to_process.with_columns([
        pl.lit(None, dtype=pl.Utf8).alias("merge_key"),
        pl.lit("insert_new").alias("action"),
        pl.lit(logical_date).alias("valid_from"),
        pl.lit(None, dtype=pl.Utf8).alias("valid_to"),
        pl.lit(True).alias("is_current"),
    ])
    staged = pl.concat([close_rows, insert_rows], how="vertical")

    merger = staged.write_delta(
        table_uri,
        mode="merge",
        storage_options=storage_options(table_uri),
        delta_merge_options={
            "predicate": (
                "target.alleleid = source.merge_key AND target.panel = source.panel "
                "AND target.is_current = true"
            ),
            "source_alias": "source",
            "target_alias": "target",
        },
    )
    # Toutes les colonnes réelles, hors les deux colonnes techniques du merge lui-même
    # (`merge_key`, `action`) qui n'ont pas leur place dans la table finale.
    write_cols = [c for c in staged.columns if c not in ("merge_key", "action")]
    (
        merger.when_matched_update(
            updates={"is_current": "false", "valid_to": f"'{logical_date}'"},
            predicate="source.action = 'close'",
        )
        .when_not_matched_insert(
            updates={c: f"source.{c}" for c in write_cols},
            predicate="source.action = 'insert_new'",
        )
        .execute()
    )


def _silver_table_uri(table: str, lake_uri: str | None) -> str:
    """URI d'une table Silver : `layer_uri` donne la racine de la couche
    (`file:///.../silver` ou `s3://silver`) ; une table Silver est un chemin direct
    en dessous, sans date ni panel (contrairement à `partition_uri`, conçue pour
    raw/bronze). Vérifié à la main : `layer_uri("silver", lake_uri=...)` fonctionne
    aussi bien en local qu'avec `lake_uri="s3://"`."""
    return f"{layer_uri('silver', lake_uri=lake_uri)}/{table}"


def bronze_to_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None:
    """Construit les dix tables Silver du panel à partir du Bronze.

    Un seul appel par run de panel : lit les bronze partagés (`clinvar`, `hpo`,
    filtrés au panel) et les bronze du panel (`ncbi_gene`, `refseq`, `medgen`,
    `hpo_terms`). `clinvar_variant` seule porte un historique SCD2 ; les neuf autres
    tables sont remplacées entièrement pour ce panel à chaque run.
    """
    genes = PANEL_GENES[panel]

    clinvar_partition = partition_uri(BRONZE, "clinvar", logical_date, lake_uri=lake_uri)
    hpo_partition = partition_uri(BRONZE, "hpo", logical_date, lake_uri=lake_uri)
    ncbi_gene_partition = partition_uri(BRONZE, "ncbi_gene", logical_date, panel=panel, lake_uri=lake_uri)
    refseq_partition = partition_uri(BRONZE, "refseq", logical_date, panel=panel, lake_uri=lake_uri)
    medgen_partition = partition_uri(BRONZE, "medgen", logical_date, panel=panel, lake_uri=lake_uri)
    hpo_terms_partition = partition_uri(BRONZE, "hpo_terms", logical_date, panel=panel, lake_uri=lake_uri)

    silver_uri = lambda table: _silver_table_uri(table, lake_uri)

    clinvar_variants = _load_clinvar_variants(clinvar_partition, genes)
    variant_gene = _build_clinvar_variant_gene(clinvar_variants, genes)
    variant_disease = _build_clinvar_variant_disease(
        clinvar_variants.filter(pl.col("alleleid").is_in(variant_gene["alleleid"].unique().to_list()))
    )
    refseq_transcript = _build_refseq_transcript(refseq_partition)
    variant_rows = _build_clinvar_variant_rows(clinvar_variants, refseq_transcript, variant_gene)

    concept, mim, inheritance = _build_medgen_tables(medgen_partition)
    hpo_gene_phenotype = _build_hpo_gene_phenotype(hpo_partition, genes)
    hpo_term = _build_hpo_term(hpo_terms_partition)
    ncbi_gene = _build_ncbi_gene(ncbi_gene_partition)

    _write_clinvar_variant(
        variant_rows.with_columns(pl.lit(panel).alias("panel")),
        silver_uri("clinvar_variant"), panel, logical_date,
    )
    for table, df in [
        ("clinvar_variant_disease", variant_disease),
        ("clinvar_variant_gene", variant_gene),
        ("ncbi_gene", ncbi_gene),
        ("refseq_transcript", refseq_transcript),
        ("medgen_concept", concept),
        ("medgen_mim", mim),
        ("medgen_inheritance", inheritance),
        ("hpo_gene_phenotype", hpo_gene_phenotype),
        ("hpo_term", hpo_term),
    ]:
        _write_silver_snapshot(df.with_columns(pl.lit(panel).alias("panel")), silver_uri(table), panel)
