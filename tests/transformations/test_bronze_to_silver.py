import io
import json as _json

import polars as pl
import pytest
from deltalake import DeltaTable

from ingestion.config import SILVER_TABLES as ALL_SILVER_TABLES
from ingestion.errors import OutOfOrderMonthError
from ingestion.storage import put_bytes
from transformations.bronze_to_silver import (
    _build_clinvar_variant_disease,
    _build_clinvar_variant_gene,
    _build_clinvar_variant_rows,
    _build_hpo_gene_phenotype,
    _build_hpo_term,
    _build_medgen_tables,
    _build_ncbi_gene,
    _build_refseq_transcript,
    _check_month_order,
    _load_clinvar_variants,
    _read_bronze_table,
    _write_clinvar_variant,
    _write_silver_snapshot,
    bronze_to_silver,
)
from transformations.quality_check_silver import SilverQualityError


def _seed_bronze_parquet(tmp_path, source, panel, df: pl.DataFrame) -> str:
    partition = f"file://{tmp_path}/lake/bronze/{source}/dt=2026-09-01"
    if panel:
        partition += f"/panel={panel}"
    buf = io.BytesIO()
    df.write_parquet(buf)
    put_bytes(f"{partition}/data.parquet", buf.getvalue())
    return partition


def test_read_bronze_table_reads_back_the_parquet_file(tmp_path):
    df = pl.DataFrame({"gene_symbol": ["BRCA1"], "esummary_json": ["{}"]})
    partition = _seed_bronze_parquet(tmp_path, "ncbi_gene", "brca", df)

    result = _read_bronze_table(partition)

    assert result["gene_symbol"].to_list() == ["BRCA1"]


def test_read_bronze_table_drops_bronze_technical_columns(tmp_path):
    """Ces colonnes ne doivent jamais atteindre une table Silver (contrainte globale
    de ce plan) — retirées ici, au point de lecture unique de toutes les sources."""
    df = pl.DataFrame({
        "gene_symbol": ["BRCA1"], "esummary_json": ["{}"],
        "_source_version": ["2026-09-01"], "_logical_date": ["2026-09-01"],
        "_ingested_at": ["2026-09-01T00:00:00+00:00"],
    })
    partition = _seed_bronze_parquet(tmp_path, "ncbi_gene", "brca", df)

    result = _read_bronze_table(partition)

    assert result.columns == ["gene_symbol", "esummary_json"]


def test_write_silver_snapshot_only_replaces_the_given_panel(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/ncbi_gene"

    _write_silver_snapshot(
        pl.DataFrame({"gene_symbol": ["BRCA1"], "panel": ["brca"]}), uri, "brca"
    )
    _write_silver_snapshot(
        pl.DataFrame({"gene_symbol": ["HBB"], "panel": ["sickle"]}), uri, "sickle"
    )
    # Un second run sur brca ne doit pas toucher les lignes sickle.
    _write_silver_snapshot(
        pl.DataFrame({"gene_symbol": ["BRCA1", "BRCA2"], "panel": ["brca", "brca"]}),
        uri,
        "brca",
    )

    result = pl.read_delta(uri).sort(["panel", "gene_symbol"])
    assert result["gene_symbol"].to_list() == ["BRCA1", "BRCA2", "HBB"]
    assert result["panel"].to_list() == ["brca", "brca", "sickle"]


CLINVAR_ROWS = pl.DataFrame({
    "alleleid": ["1", "2", "3"],
    "genesymbol": ["BRCA1", "ATM;PTEN", "HBB"],
    "assembly": ["GRCh38", "GRCh38", "GRCh38"],
})


def _seed_clinvar_bronze(tmp_path, df: pl.DataFrame = CLINVAR_ROWS) -> str:
    return _seed_bronze_parquet(tmp_path, "clinvar", None, df)


def test_build_clinvar_variant_gene_explodes_multi_gene_rows(tmp_path):
    partition = _seed_clinvar_bronze(tmp_path)
    clinvar_variants = _load_clinvar_variants(partition, ["BRCA1", "ATM", "PTEN"])

    result = _build_clinvar_variant_gene(clinvar_variants, ["BRCA1", "ATM", "PTEN"])

    pairs = sorted(zip(result["alleleid"].to_list(), result["gene_symbol"].to_list()))
    assert pairs == [("1", "BRCA1"), ("2", "ATM"), ("2", "PTEN")]


def test_build_clinvar_variant_gene_excludes_genes_outside_the_panel(tmp_path):
    partition = _seed_clinvar_bronze(tmp_path)
    clinvar_variants = _load_clinvar_variants(partition, ["BRCA1"])

    result = _build_clinvar_variant_gene(clinvar_variants, ["BRCA1"])

    assert result["gene_symbol"].to_list() == ["BRCA1"]


REFSEQ_ROWS = pl.DataFrame({
    "gene_symbol": ["AP5Z1"],
    "accession": ["NM_014855"],
    "version": [3],
})


def test_load_clinvar_variants_keeps_only_panel_variants(tmp_path):
    """Le bulk ClinVar GRCh38 complet (~3M lignes) ne tient pas dans la mémoire du
    worker Airflow : le filtre au panel doit précéder le `.collect()`. Un variant
    multi-gènes dont un seul gène est au panel reste inclus."""
    partition = _seed_clinvar_bronze(tmp_path)

    result = _load_clinvar_variants(partition, ["BRCA1", "PTEN"])

    assert sorted(result["alleleid"].to_list()) == ["1", "2"]


def test_load_clinvar_variants_keeps_only_grch38(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1", "1"],
        "genesymbol": ["AP5Z1", "AP5Z1"],
        "assembly": ["GRCh37", "GRCh38"],
        "clinicalsignificance": ["Benign", "Benign"],
        "reviewstatus": ["criteria provided", "criteria provided"],
        "lastevaluated": ["2026-08-01", "2026-08-01"],
        "rs_dbsnp": ["397704705", "397704705"],
        "name": [
            "NM_014855.3(AP5Z1):c.80_83delinsTGCTG",
            "NM_014855.3(AP5Z1):c.80_83delinsTGCTG",
        ],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)

    result = _load_clinvar_variants(partition, ["AP5Z1"])

    assert result["alleleid"].to_list() == ["1"]
    assert result["assembly"].to_list() == ["GRCh38"]


def test_load_clinvar_variants_deduplicates_on_alleleid(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1", "1"],
        "genesymbol": ["AP5Z1", "AP5Z1"],
        "assembly": ["GRCh38", "GRCh38"],
        "clinicalsignificance": ["Benign", "Benign"],
        "reviewstatus": ["criteria provided", "criteria provided"],
        "lastevaluated": ["2026-08-01", "2026-08-01"],
        "rs_dbsnp": ["-1", "-1"],
        "name": ["NM_014855.3(AP5Z1):c.1A>G", "NM_014855.3(AP5Z1):c.1A>G"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)

    result = _load_clinvar_variants(partition, ["AP5Z1"])

    assert len(result) == 1


def test_clinvar_variant_gene_and_variant_share_the_same_alleleid_set_despite_grch37_duplicates(
    tmp_path,
):
    """Régression C3+C4 : un alleleid présent en double, une fois GRCh37 une fois
    GRCh38, ne doit produire qu'une seule ligne (alleleid, gene_symbol) dans
    clinvar_variant_gene (pas de doublon issu du GRCh37) ; et un alleleid qui
    n'existe qu'en GRCh37 ne doit apparaître dans AUCUNE des deux tables."""
    df = pl.DataFrame({
        "alleleid": ["1", "1", "2"],
        "genesymbol": ["AP5Z1", "AP5Z1", "AP5Z1"],
        "assembly": ["GRCh37", "GRCh38", "GRCh37"],
        "clinicalsignificance": ["Benign", "Benign", "Benign"],
        "reviewstatus": ["criteria provided", "criteria provided", "criteria provided"],
        "lastevaluated": ["2026-08-01", "2026-08-01", "2026-08-01"],
        "rs_dbsnp": ["-1", "-1", "-1"],
        "name": [
            "NM_014855.3(AP5Z1):c.1A>G",
            "NM_014855.3(AP5Z1):c.1A>G",
            "NM_014855.3(AP5Z1):c.2A>G",
        ],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    clinvar_variants = _load_clinvar_variants(partition, ["AP5Z1"])

    variant_gene = _build_clinvar_variant_gene(clinvar_variants, ["AP5Z1"])
    variant_rows = _build_clinvar_variant_rows(clinvar_variants, REFSEQ_ROWS, variant_gene)

    pairs = list(zip(variant_gene["alleleid"].to_list(), variant_gene["gene_symbol"].to_list()))
    assert pairs == [("1", "AP5Z1")]
    assert "2" not in variant_gene["alleleid"].to_list()
    assert "2" not in variant_rows["alleleid"].to_list()


def test_build_clinvar_variant_rows_casts_rs_dbsnp_to_integer_with_sentinel(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1"], "genesymbol": ["AP5Z1"], "assembly": ["GRCh38"],
        "clinicalsignificance": ["Benign"], "reviewstatus": ["criteria provided"],
        "lastevaluated": ["2026-08-01"], "rs_dbsnp": ["-1"],
        "name": ["NM_014855.3(AP5Z1):c.1A>G"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    clinvar_variants = _load_clinvar_variants(partition, ["AP5Z1"])
    variant_gene = _build_clinvar_variant_gene(clinvar_variants, ["AP5Z1"])

    result = _build_clinvar_variant_rows(clinvar_variants, REFSEQ_ROWS, variant_gene)

    assert result["rs_dbsnp"].to_list() == [-1]
    assert result.schema["rs_dbsnp"] == pl.Int64


def test_build_clinvar_variant_rows_parses_hgvs_and_validates_against_refseq(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1"], "genesymbol": ["AP5Z1"], "assembly": ["GRCh38"],
        "clinicalsignificance": ["Benign"], "reviewstatus": ["criteria provided"],
        "lastevaluated": ["2026-08-01"], "rs_dbsnp": ["-1"],
        "name": ["NM_014855.3(AP5Z1):c.80_83delinsTGCTG"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    clinvar_variants = _load_clinvar_variants(partition, ["AP5Z1"])
    variant_gene = _build_clinvar_variant_gene(clinvar_variants, ["AP5Z1"])

    result = _build_clinvar_variant_rows(clinvar_variants, REFSEQ_ROWS, variant_gene)
    row = result.row(0, named=True)

    assert row["refseq_accession"] == "NM_014855"
    assert row["refseq_version"] == 3
    assert row["hgvs_c"] == "c.80_83delinsTGCTG"
    assert row["hgvs_p"] is None
    assert row["refseq_accession_known"] is True


def test_build_clinvar_variant_rows_keeps_a_row_with_irregular_hgvs(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1"], "genesymbol": ["AP5Z1"], "assembly": ["GRCh38"],
        "clinicalsignificance": ["Benign"], "reviewstatus": ["criteria provided"],
        "lastevaluated": ["2026-08-01"], "rs_dbsnp": ["-1"],
        "name": ["forme HGVS non reconnue"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    clinvar_variants = _load_clinvar_variants(partition, ["AP5Z1"])
    variant_gene = _build_clinvar_variant_gene(clinvar_variants, ["AP5Z1"])

    result = _build_clinvar_variant_rows(clinvar_variants, REFSEQ_ROWS, variant_gene)
    row = result.row(0, named=True)

    assert row["name"] == "forme HGVS non reconnue"
    assert row["refseq_accession"] is None
    assert row["refseq_accession_known"] is False


def _rows(alleleid, panel, significance, review="criteria provided", evaluated="2026-08-01"):
    # Schéma explicite : `evaluated=None` (utilisé par les tests de transition
    # null -> valeur) inférerait autrement `lastevaluated` en type `Null`.
    return pl.DataFrame(
        {
            "alleleid": [alleleid], "panel": [panel],
            "clinicalsignificance": [significance], "reviewstatus": [review],
            "lastevaluated": [evaluated],
        },
        schema={
            "alleleid": pl.Utf8, "panel": pl.Utf8, "clinicalsignificance": pl.Utf8,
            "reviewstatus": pl.Utf8, "lastevaluated": pl.Utf8,
        },
    )


def test_write_clinvar_variant_creates_the_table_on_first_run(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"

    _write_clinvar_variant(_rows("1", "brca", "Benign"), uri, "brca", "2026-08-01")

    result = pl.read_delta(uri)
    assert result["is_current"].to_list() == [True]
    assert result["valid_from"].to_list() == ["2026-08-01"]
    assert result["valid_to"].to_list() == [None]


def test_write_clinvar_variant_closes_and_reopens_on_a_real_change(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-08-01")

    _write_clinvar_variant(
        _rows("1", "brca", "Pathogenic/Likely pathogenic"), uri, "brca", "2026-09-01"
    )

    result = pl.read_delta(uri).sort("valid_from")
    assert result["is_current"].to_list() == [False, True]
    assert result["valid_to"].to_list() == ["2026-09-01", None]
    assert result["clinicalsignificance"].to_list() == [
        "Pathogenic", "Pathogenic/Likely pathogenic",
    ]


def test_write_clinvar_variant_replay_is_idempotent(tmp_path):
    """Rejouer le même mois avec les mêmes valeurs ne doit créer aucune ligne."""
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "brca", "Benign"), uri, "brca", "2026-08-01")
    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-09-01")

    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-09-01")

    assert len(pl.read_delta(uri)) == 2


def test_write_clinvar_variant_ignores_unwatched_field_changes(tmp_path):
    """Un champ hors liste surveillée (ex. `name`) ne doit pas déclencher de nouvelle
    version — seuls clinical_significance/review_status/last_evaluated comptent."""
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    first = _rows("1", "brca", "Benign").with_columns(pl.lit("Name v1").alias("name"))
    _write_clinvar_variant(first, uri, "brca", "2026-08-01")

    second = _rows("1", "brca", "Benign").with_columns(pl.lit("Name v2").alias("name"))
    _write_clinvar_variant(second, uri, "brca", "2026-09-01")

    assert len(pl.read_delta(uri)) == 1


def test_write_clinvar_variant_detects_a_null_to_value_transition(tmp_path):
    """Un champ surveillé qui passe de None à une vraie valeur doit produire une
    nouvelle version SCD2 — `!=` renvoie `null` (donc ignoré) quand un des deux
    côtés est `null`, ce qui masquait cette transition avant le correctif I1."""
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    first = _rows("1", "brca", "Benign", evaluated=None)
    _write_clinvar_variant(first, uri, "brca", "2026-08-01")

    second = _rows("1", "brca", "Benign", evaluated="2026-09-01")
    _write_clinvar_variant(second, uri, "brca", "2026-09-01")

    result = pl.read_delta(uri).sort("valid_from")
    assert result["is_current"].to_list() == [False, True]
    assert result["lastevaluated"].to_list() == [None, "2026-09-01"]


def test_write_clinvar_variant_replay_with_a_null_watched_field_is_idempotent(tmp_path):
    """Rejouer le même mois quand `clinicalsignificance` (le premier champ surveillé)
    est `None` (donc `None` aussi côté `current` après le premier run) ne doit créer
    aucune ligne d'historique supplémentaire — le proxy `cur_clinicalsignificance.is_null()`
    confondait à tort ce cas avec une absence de correspondance avant le correctif I1.
    Champ choisi précisément parce que c'est lui que l'ancien proxy testait : un champ
    surveillé différent ne discriminerait pas l'ancien code du nouveau."""
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    rows = _rows("1", "brca", None)
    _write_clinvar_variant(rows, uri, "brca", "2026-08-01")

    _write_clinvar_variant(rows, uri, "brca", "2026-08-01")

    assert len(pl.read_delta(uri)) == 1


def test_write_clinvar_variant_does_not_touch_the_other_panel(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "sickle", "Benign"), uri, "sickle", "2026-08-01")

    _write_clinvar_variant(_rows("2", "brca", "Pathogenic"), uri, "brca", "2026-08-01")

    result = pl.read_delta(uri).sort("panel")
    assert result["panel"].to_list() == ["brca", "sickle"]
    assert result.filter(pl.col("panel") == "sickle")["clinicalsignificance"].to_list() == ["Benign"]


def test_check_month_order_accepts_a_panel_without_history(tmp_path):
    _check_month_order(f"file://{tmp_path}/lake/silver/clinvar_variant", "brca", "2026-08-01")


@pytest.mark.parametrize("month", ["2026-09-01", "2026-10-01"])
def test_check_month_order_accepts_the_latest_month_again_or_a_later_one(tmp_path, month):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "brca", "Benign"), uri, "brca", "2026-08-01")
    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-09-01")

    _check_month_order(uri, "brca", month)


def test_check_month_order_refuses_a_month_older_than_the_history(tmp_path):
    """Rejouer novembre après décembre fermerait les versions de décembre au 1er novembre
    et rendrait l'état de novembre « courant » : l'historique serait faux, sans erreur."""
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "brca", "Benign"), uri, "brca", "2026-10-01")
    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-12-01")

    with pytest.raises(OutOfOrderMonthError, match="2026-12-01.*2026-11-01"):
        _check_month_order(uri, "brca", "2026-11-01")


def test_check_month_order_ignores_the_history_of_the_other_panel(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "sickle", "Benign"), uri, "sickle", "2026-12-01")

    _check_month_order(uri, "brca", "2026-11-01")


def test_build_ncbi_gene_extracts_known_esummary_fields(tmp_path):
    df = pl.DataFrame({
        "gene_symbol": ["HBB"],
        "esummary_json": [_json.dumps({
            "name": "HBB", "description": "hemoglobin subunit beta",
            "maplocation": "11p15.4", "summary": "This gene encodes beta-globin.",
        })],
    })
    partition = _seed_bronze_parquet(tmp_path, "ncbi_gene", "sickle", df)

    result = _build_ncbi_gene(partition)
    row = result.row(0, named=True)

    assert row["gene_symbol"] == "HBB"
    assert row["name"] == "HBB"
    assert row["description"] == "hemoglobin subunit beta"
    assert row["maplocation"] == "11p15.4"


def test_build_ncbi_gene_keeps_a_row_for_an_unresolved_gene(tmp_path):
    df = pl.DataFrame({"gene_symbol": ["HBS1L"], "esummary_json": ["{}"]})
    partition = _seed_bronze_parquet(tmp_path, "ncbi_gene", "sickle", df)

    result = _build_ncbi_gene(partition)

    assert result["gene_symbol"].to_list() == ["HBS1L"]
    assert result["name"].to_list() == [None]


def test_build_refseq_transcript_explodes_one_row_per_transcript(tmp_path):
    df = pl.DataFrame({
        "gene_symbol": ["BRCA2"],
        "transcripts_json": [_json.dumps([
            {"accessionversion": "NM_001432077.1", "slen": 11863},
            {"accessionversion": "NM_000059.4", "slen": 11986},
        ])],
    })
    partition = _seed_bronze_parquet(tmp_path, "refseq", "brca", df)

    result = _build_refseq_transcript(partition).sort("accession")

    assert result["accession"].to_list() == ["NM_000059", "NM_001432077"]
    assert result["version"].to_list() == [4, 1]
    assert result["gene_symbol"].to_list() == ["BRCA2", "BRCA2"]


def test_build_refseq_transcript_keeps_a_gene_with_no_transcript(tmp_path):
    df = pl.DataFrame({"gene_symbol": ["HBS1L"], "transcripts_json": ["[]"]})
    partition = _seed_bronze_parquet(tmp_path, "refseq", "sickle", df)

    result = _build_refseq_transcript(partition)

    assert len(result) == 0


CONCEPTMETA_TWO_MIM = (
    "<OMIM><MIM>603903</MIM></OMIM><OMIM><MIM>141900</MIM></OMIM>"
    "<ModeOfInheritance><Name>Autosomal recessive inheritance</Name></ModeOfInheritance>"
)


def test_build_medgen_tables_reuses_parse_medgen_conceptmeta(tmp_path):
    df = pl.DataFrame({
        "cui": ["C0002895"],
        "esummary_json": [_json.dumps({"conceptid": "C0002895", "conceptmeta": CONCEPTMETA_TWO_MIM})],
    })
    partition = _seed_bronze_parquet(tmp_path, "medgen", "sickle", df)

    concept, mim, inheritance = _build_medgen_tables(partition)

    assert concept["cui"].to_list() == ["C0002895"]
    assert concept["conceptmeta_xml"].to_list() == [CONCEPTMETA_TWO_MIM]
    assert sorted(mim["mim_number"].to_list()) == ["141900", "603903"]
    assert inheritance["mode_inheritance"].to_list() == ["Autosomal recessive inheritance"]


def test_build_medgen_tables_keeps_an_unresolved_cui_without_exploding_rows(tmp_path):
    df = pl.DataFrame({"cui": ["C9999999"], "esummary_json": ["{}"]})
    partition = _seed_bronze_parquet(tmp_path, "medgen", "sickle", df)

    concept, mim, inheritance = _build_medgen_tables(partition)

    assert concept["cui"].to_list() == ["C9999999"]
    assert concept["conceptmeta_xml"].to_list() == [None]
    assert len(mim) == 0
    assert len(inheritance) == 0


def test_build_hpo_gene_phenotype_filters_to_the_panel(tmp_path):
    df = pl.DataFrame({
        "ncbi_gene_id": ["3043", "9999"],
        "gene_symbol": ["HBB", "AUTRE"],
        "hpo_id": ["HP:0001903", "HP:0000118"],
        "hpo_name": ["Anemia", "Phenotypic abnormality"],
    })
    partition = _seed_bronze_parquet(tmp_path, "hpo", None, df)

    result = _build_hpo_gene_phenotype(partition, ["HBB"])

    assert result["gene_symbol"].to_list() == ["HBB"]
    assert result["hpo_id"].to_list() == ["HP:0001903"]


def test_build_hpo_term_extracts_details(tmp_path):
    df = pl.DataFrame({
        "gene_symbol": ["HBB"], "hpo_id": ["HP:0001903"], "hpo_name": ["Anemia"],
        "details_json": [_json.dumps({
            "definition": "A reduction in erythrocytes.",
            "synonyms": ["Low blood count"], "xrefs": ["UMLS:C0002871"],
        })],
    })
    partition = _seed_bronze_parquet(tmp_path, "hpo_terms", "sickle", df)

    result = _build_hpo_term(partition)
    row = result.row(0, named=True)

    assert row["hpo_id"] == "HP:0001903"
    assert row["definition"] == "A reduction in erythrocytes."
    assert row["synonyms"] == ["Low blood count"]


def test_build_hpo_term_keeps_a_row_with_empty_details(tmp_path):
    df = pl.DataFrame({
        "gene_symbol": ["HBB"], "hpo_id": ["HP:0009999"], "hpo_name": ["Terme retire"],
        "details_json": ["{}"],
    })
    partition = _seed_bronze_parquet(tmp_path, "hpo_terms", "sickle", df)

    result = _build_hpo_term(partition)

    assert result["hpo_id"].to_list() == ["HP:0009999"]
    assert result["definition"].to_list() == [None]


# Notice MedGen minimale mais réelle : sans MIM ni mode, `medgen_mim` et `medgen_inheritance`
# sortiraient vides et le contrôle d'avant publication refuserait le Silver.
_CONCEPTMETA = (
    "<ModesOfInheritance><ModeOfInheritance><Name>Autosomal recessive inheritance</Name>"
    "</ModeOfInheritance></ModesOfInheritance><OMIM><MIM>603903</MIM></OMIM>"
)


def _clinvar_bronze(hbb_variants: int) -> pl.DataFrame:
    """`hbb_variants` variants HBB (panel sickle), plus un BRCA1 pour que le panel brca ne soit pas vide."""
    ids = [str(i) for i in range(1, hbb_variants + 1)] + ["brca-1"]
    n = len(ids)
    return pl.DataFrame({
        "alleleid": ids, "genesymbol": ["HBB"] * hbb_variants + ["BRCA1"], "assembly": ["GRCh38"] * n,
        "clinicalsignificance": ["Benign"] * n, "reviewstatus": ["criteria provided"] * n,
        "lastevaluated": ["2026-08-01"] * n, "rs_dbsnp": ["-1"] * n,
        "name": [f"NM_000518.5(HBB):c.{i}A>G" for i in range(1, hbb_variants + 1)]
        + ["NM_007294.4(BRCA1):c.116G>A"],
        "phenotypelist": ["Sickle cell anemia"] * n, "phenotypeids": ["MedGen:C0002895"] * n,
    })


def _seed_all_bronze(tmp_path, lake, panel, hbb_variants=1):
    _seed_bronze_parquet(tmp_path, "clinvar", None, _clinvar_bronze(hbb_variants))
    _seed_bronze_parquet(tmp_path, "hpo", None, pl.DataFrame({
        "ncbi_gene_id": ["3043"], "gene_symbol": ["HBB"],
        "hpo_id": ["HP:0001903"], "hpo_name": ["Anemia"],
    }))
    _seed_bronze_parquet(tmp_path, "ncbi_gene", panel, pl.DataFrame({
        "gene_symbol": ["HBB"], "esummary_json": [_json.dumps({"name": "HBB"})],
    }))
    _seed_bronze_parquet(tmp_path, "refseq", panel, pl.DataFrame({
        "gene_symbol": ["HBB"],
        "transcripts_json": [_json.dumps([{"accessionversion": "NM_000518.5", "slen": 1000}])],
    }))
    _seed_bronze_parquet(tmp_path, "medgen", panel, pl.DataFrame({
        "cui": ["C0002895"],
        "esummary_json": [_json.dumps({"conceptid": "C0002895", "conceptmeta": _CONCEPTMETA})],
    }))
    _seed_bronze_parquet(tmp_path, "hpo_terms", panel, pl.DataFrame({
        "gene_symbol": ["HBB"], "hpo_id": ["HP:0001903"], "hpo_name": ["Anemia"],
        "details_json": [_json.dumps({"definition": "A reduction in erythrocytes."})],
    }))


SILVER_TABLES = [
    "clinvar_variant", "clinvar_variant_gene", "ncbi_gene", "refseq_transcript",
    "medgen_concept", "medgen_mim", "medgen_inheritance", "hpo_gene_phenotype", "hpo_term",
]


def test_bronze_to_silver_writes_all_nine_tables(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_all_bronze(tmp_path, lake, "sickle")

    bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)

    for table in SILVER_TABLES:
        result = pl.read_delta(f"{lake}/silver/{table}")
        assert "panel" in result.columns
        assert set(result["panel"].to_list()) <= {"sickle"}


def test_bronze_to_silver_does_not_disturb_the_other_panel(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_all_bronze(tmp_path, lake, "sickle")
    bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)

    _seed_all_bronze(tmp_path, lake, "brca")
    bronze_to_silver("2026-09-01", "brca", lake_uri=lake)

    result = pl.read_delta(f"{lake}/silver/ncbi_gene")
    assert set(result["panel"].to_list()) == {"brca", "sickle"}


def test_bronze_to_silver_writes_clinvar_variant_disease(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_all_bronze(tmp_path, lake, "sickle")

    bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)

    table = pl.read_delta(f"{lake}/silver/clinvar_variant_disease")
    assert table["panel"].unique().to_list() == ["sickle"]
    assert set(table.columns) >= {
        "alleleid", "disease_name", "medgen_cui", "omim_id", "orpha_id", "mondo_id", "panel",
    }


DISEASE_ROWS = pl.DataFrame({
    "alleleid": ["1", "2", "3", "4"],
    "phenotypelist": [
        "Breast-ovarian cancer, familial, susceptibility to, 1|not provided",
        "FETAL HEMOGLOBIN QTL 6;Congenital dyserythropoietic anemia type 4",
        "not provided",
        "Hereditary cancer-predisposing syndrome",
    ],
    "phenotypeids": [
        "MONDO:MONDO:0011450,MedGen:C2676676,OMIM:604370,Orphanet:145|MedGen:C3661900",
        "MedGen:C3150805,OMIM:613566,Orphanet:251380;MONDO:MONDO:0013355,MedGen:C3150926,OMIM:613673",
        "MedGen:CN169374",
        "MedGen:C0027672",
    ],
})


def test_build_clinvar_variant_disease_splits_on_pipe_then_semicolon():
    result = _build_clinvar_variant_disease(DISEASE_ROWS).sort("alleleid", "disease_name")

    rows = result.filter(pl.col("alleleid") == "2").sort("disease_name")
    assert rows["disease_name"].to_list() == [
        "Congenital dyserythropoietic anemia type 4",
        "FETAL HEMOGLOBIN QTL 6",
    ]
    assert rows["medgen_cui"].to_list() == ["C3150926", "C3150805"]
    assert rows["omim_id"].to_list() == ["613673", "613566"]


def test_build_clinvar_variant_disease_extracts_every_identifier():
    result = _build_clinvar_variant_disease(DISEASE_ROWS)

    row = result.filter(pl.col("alleleid") == "1").row(0, named=True)
    assert row["medgen_cui"] == "C2676676"
    assert row["omim_id"] == "604370"
    assert row["orpha_id"] == "145"
    assert row["mondo_id"] == "MONDO:0011450"


def test_build_clinvar_variant_disease_drops_placeholder_names():
    """« not provided » porte son propre CUI vide chez MedGen (C3661900, CN169374) :
    le garder ferait apparaître « not provided » comme une maladie dans le RAG."""
    result = _build_clinvar_variant_disease(DISEASE_ROWS)

    assert "not provided" not in result["disease_name"].to_list()
    assert "3" not in result["alleleid"].to_list()


def test_build_clinvar_variant_disease_keeps_identifiers_when_a_group_is_misaligned():
    """Un groupe où les noms et les identifiants n'ont pas le même nombre de
    sous-entrées : associer un nom au hasard serait pire que ne pas en donner."""
    df = pl.DataFrame({
        "alleleid": ["9"],
        "phenotypelist": ["Only one name"],
        "phenotypeids": ["MedGen:C1;OMIM:222"],
    })

    result = _build_clinvar_variant_disease(df).sort("medgen_cui", nulls_last=True)

    assert result["disease_name"].to_list() == [None, None]
    assert result["medgen_cui"].to_list() == ["C1", None]
    assert result["omim_id"].to_list() == [None, "222"]


def test_bronze_to_silver_refuses_an_older_month_before_writing_anything(tmp_path):
    """Les neuf autres tables sont des instantanés : les écrire avant de refuser les
    ramènerait elles aussi à l'état du mois ancien."""
    lake = f"file://{tmp_path}/lake"
    _seed_all_bronze(tmp_path, lake, "sickle")
    _write_clinvar_variant(
        _rows("1", "sickle", "Benign"), f"{lake}/silver/clinvar_variant", "sickle", "2026-10-01"
    )

    with pytest.raises(OutOfOrderMonthError):
        bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)

    assert not (tmp_path / "lake" / "silver" / "ncbi_gene").exists()


def _versions(lake: str) -> dict[str, int]:
    return {table: DeltaTable(f"{lake}/silver/{table}").version() for table in ALL_SILVER_TABLES}


def test_bronze_to_silver_refuses_a_truncated_archive_before_writing_anything(tmp_path):
    """O-E3b-2 : le contrôle Silver bloquait le Gold, pas le Silver ; une archive tronquée de
    moitié réécrivait les instantanés du panel avant d'être refusée (E3b P4, v7 → v8)."""
    lake = f"file://{tmp_path}/lake"
    _seed_all_bronze(tmp_path, lake, "sickle", hbb_variants=40)
    bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)
    before = _versions(lake)

    _seed_all_bronze(tmp_path, lake, "sickle", hbb_variants=20)
    with pytest.raises(SilverQualityError, match="Silver non publié") as raised:
        bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)

    assert "50%" in str(raised.value)
    assert _versions(lake) == before


def test_bronze_to_silver_refuses_a_first_run_without_variants_before_creating_tables(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_all_bronze(tmp_path, lake, "sickle", hbb_variants=0)

    with pytest.raises(SilverQualityError, match="aucune ligne"):
        bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)

    assert not (tmp_path / "lake" / "silver").exists()


def test_bronze_to_silver_publishes_a_month_with_a_few_retired_variants(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_all_bronze(tmp_path, lake, "sickle", hbb_variants=40)
    bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)

    _seed_all_bronze(tmp_path, lake, "sickle", hbb_variants=39)
    bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)

    gene = pl.read_delta(f"{lake}/silver/clinvar_variant_gene").filter(pl.col("panel") == "sickle")
    assert gene.height == 39

