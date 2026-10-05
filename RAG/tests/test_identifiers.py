import pytest

from RAG.src.retrieval.identifiers import extract_identifiers


def test_rs_in_both_spellings():
    assert extract_identifiers("Le variant rs80357906 est-il pathogène ?").rs == (80357906,)
    assert extract_identifiers("Que sait-on de RS 334 ?").rs == (334,)


@pytest.mark.parametrize("text,expected", [
    ("NM_007294.4(BRCA1):c.68_69delAG", "c.68_69del"),
    ("la mutation c.5266dupC", "c.5266dup"),
    ("c.20A>T", "c.20A>T"),
    ("c.20a>t", "c.20A>T"),
    ("c.100_101delinsTT", "c.100_101delinsTT"),
    ("c.68+1G>A", "c.68+1G>A"),
    ("c.123_124insA", "c.123_124insA"),
])
def test_coding_hgvs_is_normalized_like_clinvar(text, expected):
    assert extract_identifiers(text).hgvs_c == (expected,)


@pytest.mark.parametrize("text,expected", [
    ("p.Glu7Val", "p.Glu7Val"),
    ("p.(Glu7Val)", "p.Glu7Val"),
    ("p.E7V", "p.Glu7Val"),
    ("p.R1443*", "p.Arg1443Ter"),
    ("p.Glu23ValfsTer17", "p.Glu23fs"),
    ("le variant p.Gln1756fs ?", "p.Gln1756fs"),
])
def test_protein_hgvs_is_normalized_to_three_letters(text, expected):
    assert extract_identifiers(text).hgvs_p == (expected,)


def test_panel_genes_are_recognized_case_insensitively_and_in_order():
    ids = extract_identifiers("brca2 et HBB, puis BRCA2 encore")

    assert ids.genes == ("BRCA2", "HBB")
    assert ids.out_of_panel == ()


def test_out_of_panel_genes_are_reported():
    assert extract_identifiers("Le variant rs123 sur MLH1").out_of_panel == ("MLH1",)
    assert extract_identifiers("Rôle du gène APC ?").out_of_panel == ("APC",)


def test_legacy_names_are_not_translated():
    """5382insC et Glu6Val sont des noms historiques, absents de ClinVar : ils ne
    produisent aucun identifiant plutôt qu'un identifiant deviné."""
    ids = extract_identifiers("La mutation 5382insC ou Glu6Val est-elle grave ?")

    assert (ids.rs, ids.hgvs_c, ids.hgvs_p) == ((), (), ())
    assert ids.has_variant_identifier is False


def test_rs_like_text_is_not_a_gene():
    assert extract_identifiers("RS80357906").out_of_panel == ()


def test_identifier_fragments_are_not_genes():
    """« R1443 » dans p.R1443* ressemble à un symbole de gène : il ne doit pas
    déclencher gene_out_of_panel."""
    assert extract_identifiers("p.R1443* sur BRCA1").out_of_panel == ()


def test_lowercase_word_after_gene_is_not_a_gene():
    assert extract_identifiers("Le gène est-il impliqué dans la drépanocytose ?").out_of_panel == ()


def test_as_dict_is_json_ready():
    assert extract_identifiers("rs334 sur HBB").as_dict() == {
        "rs": [334], "hgvs_c": [], "hgvs_p": [], "genes": ["HBB"], "out_of_panel": [],
    }
