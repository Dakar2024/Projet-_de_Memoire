import polars as pl

from scripts.ecarts_rejeu import TECHNICAL_COLUMNS, Ecart, ecart_lignes


def test_identical_tables_have_no_difference_whatever_the_row_and_column_order():
    avant = pl.DataFrame({"gene": ["BRCA1", "HBB"], "n": [1, 2]})
    apres = pl.DataFrame({"n": [2, 1], "gene": ["HBB", "BRCA1"]})

    assert ecart_lignes(avant, apres) == Ecart(ajoutees=0, retirees=0)


def test_a_modified_row_counts_as_one_removed_and_one_added():
    """Sans clé commune à toutes les tables, une modification se voit comme un retrait plus un ajout."""
    avant = pl.DataFrame({"gene": ["BRCA1", "HBB"], "description": ["v1", "x"]})
    apres = pl.DataFrame({"gene": ["BRCA1", "HBB"], "description": ["v2", "x"]})

    assert ecart_lignes(avant, apres) == Ecart(ajoutees=1, retirees=1)


def test_duplicated_rows_are_counted_as_a_multiset():
    avant = pl.DataFrame({"x": [1, 1, 2]})
    apres = pl.DataFrame({"x": [1, 2, 2, 2]})

    assert ecart_lignes(avant, apres) == Ecart(ajoutees=2, retirees=1)


def test_nested_columns_are_compared():
    avant = pl.DataFrame({"ids": [["a", "b"]], "meta": [{"v": 1}]})
    apres = pl.DataFrame({"ids": [["a", "c"]], "meta": [{"v": 1}]})

    assert ecart_lignes(avant, apres) == Ecart(ajoutees=1, retirees=1)


def test_a_schema_change_is_reported_instead_of_a_row_count():
    avant = pl.DataFrame({"x": [1]})
    apres = pl.DataFrame({"x": [1], "y": [2]})

    assert ecart_lignes(avant, apres) == Ecart(ajoutees=0, retirees=0, schema="colonnes ajoutées : y")


def test_bronze_technical_columns_are_ignored():
    """`_ingested_at` change à chaque rejeu par construction : ce n'est pas un écart de données."""
    avant = pl.DataFrame({"x": [1], "_ingested_at": ["2026-10-21"], "_source_version": ["a"], "_logical_date": ["d"]})
    apres = pl.DataFrame({"x": [1], "_ingested_at": ["2026-10-23"], "_source_version": ["a"], "_logical_date": ["d"]})

    assert set(TECHNICAL_COLUMNS) == {"_ingested_at", "_source_version", "_logical_date"}
    assert ecart_lignes(avant, apres) == Ecart(ajoutees=0, retirees=0)
