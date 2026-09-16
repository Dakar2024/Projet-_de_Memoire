from transformations.raw_to_bronze import _normalize_column_name


def test_normalize_column_name_lowercases_a_plain_word():
    assert _normalize_column_name("Assembly") == "assembly"


def test_normalize_column_name_has_no_word_boundary_without_a_separator():
    """Pas de coupure aux frontières minuscule->MAJUSCULE : aucun indice mécanique
    pour deviner où découper un nom sans séparateur d'origine."""
    assert _normalize_column_name("#AlleleID") == "alleleid"
    assert _normalize_column_name("GeneSymbol") == "genesymbol"


def test_normalize_column_name_collapses_separators_to_one_underscore():
    assert _normalize_column_name("RS# (dbSNP)") == "rs_dbsnp"
    assert _normalize_column_name("nsv/esv (dbVar)") == "nsv_esv_dbvar"


def test_normalize_column_name_keeps_an_existing_single_underscore():
    assert _normalize_column_name("HGVS_p") == "hgvs_p"
