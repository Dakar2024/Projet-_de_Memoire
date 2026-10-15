import pytest

from RAG.src.retrieval.significance import SIGNIFICANCE_VALUES, clinvar_labels

KNOWN = [
    "Pathogenic", "Likely pathogenic", "Pathogenic/Likely pathogenic", "Pathogenic; other",
    "Benign", "Likely benign", "Benign/Likely benign", "Uncertain significance",
    "Conflicting classifications of pathogenicity", "not provided", "other",
]


def test_pathogenic_includes_composites_starting_with_pathogenic():
    assert clinvar_labels("pathogenic", KNOWN) == (
        "Pathogenic", "Likely pathogenic", "Pathogenic/Likely pathogenic", "Pathogenic; other",
    )


def test_each_value_maps_to_exact_clinvar_labels():
    assert clinvar_labels("benign", KNOWN) == ("Benign", "Likely benign", "Benign/Likely benign")
    assert clinvar_labels("uncertain", KNOWN) == ("Uncertain significance",)
    assert clinvar_labels("conflicting", KNOWN) == ("Conflicting classifications of pathogenicity",)


def test_none_means_no_filter():
    assert clinvar_labels("none", KNOWN) == ()


def test_labels_absent_from_the_index_are_dropped():
    assert clinvar_labels("benign", ["Benign"]) == ("Benign",)


def test_an_unknown_value_is_never_guessed():
    with pytest.raises(ValueError):
        clinvar_labels("dangereux", KNOWN)


def test_the_five_values_are_fixed():
    assert SIGNIFICANCE_VALUES == ("pathogenic", "benign", "uncertain", "conflicting", "none")
