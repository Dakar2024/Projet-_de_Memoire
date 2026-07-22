import json

import polars as pl

from ingestion.orchestrate import (
    add_medgen_cuis,
    build_gene_documents,
    find_empty_genes,
    write_raw_gene_files,
)

EMPTY_SCHEMA = {
    "#AlleleID": pl.Utf8,
    "GeneSymbol": pl.Utf8,
    "PhenotypeIDS": pl.Utf8,
}


def test_add_medgen_cuis_extracts_list_column():
    df = pl.DataFrame(
        {
            "#AlleleID": ["1"],
            "GeneSymbol": ["HBB"],
            "PhenotypeIDS": ["MedGen:C3661900,OMIM:603903"],
        }
    )
    result = add_medgen_cuis(df)
    assert result["medgen_cuis"].to_list() == [["C3661900"]]


def test_build_gene_documents_assembles_variant_gene_medgen_hpo():
    variants = add_medgen_cuis(
        pl.DataFrame(
            {
                "#AlleleID": ["1"],
                "GeneSymbol": ["HBB"],
                "PhenotypeIDS": ["MedGen:C3661900"],
                "ClinicalSignificance": ["Pathogenic"],
            }
        )
    )
    gene_info = {"HBB": {"name": "HBB", "description": "hemoglobin subunit beta"}}
    medgen = {"C3661900": {"title": "Hb SS disease", "mim_number": "603903"}}
    hpo = {"HBB": [{"hpo_id": "HP:0001878", "hpo_name": "Hemolytic anemia"}]}

    documents = build_gene_documents(variants, gene_info, medgen, hpo)

    assert set(documents.keys()) == {"HBB"}
    doc = documents["HBB"]
    assert doc["gene_info"]["name"] == "HBB"
    assert doc["variants"][0]["ClinicalSignificance"] == "Pathogenic"
    assert doc["medgen_concepts"] == [{"title": "Hb SS disease", "mim_number": "603903"}]
    assert doc["hpo_terms"] == [{"hpo_id": "HP:0001878", "hpo_name": "Hemolytic anemia"}]


def test_build_gene_documents_handles_gene_with_no_variants():
    variants = add_medgen_cuis(
        pl.DataFrame(
            {"#AlleleID": [], "GeneSymbol": [], "PhenotypeIDS": []},
            schema={"#AlleleID": pl.Utf8, "GeneSymbol": pl.Utf8, "PhenotypeIDS": pl.Utf8},
        )
    )
    gene_info = {"ATM": {"name": "ATM"}}

    documents = build_gene_documents(variants, gene_info, {}, {})

    assert documents["ATM"]["variants"] == []
    assert documents["ATM"]["medgen_concepts"] == []
    assert documents["ATM"]["hpo_terms"] == []


def test_build_gene_documents_parses_medgen_conceptmeta():
    variants = add_medgen_cuis(
        pl.DataFrame(
            {
                "#AlleleID": ["1"],
                "GeneSymbol": ["HBB"],
                "PhenotypeIDS": ["MedGen:C0005283"],
            }
        )
    )
    conceptmeta = (
        "<Definitions><Definition source='GeneReviews'>Beta-thalassemia summary."
        "</Definition></Definitions>"
        "<ModesOfInheritance><ModeOfInheritance uid='141025'>"
        "<Name>Autosomal recessive inheritance</Name></ModeOfInheritance></ModesOfInheritance>"
        "<OMIM><MIM>141900</MIM><MIM>613985</MIM></OMIM>"
        "<ClinicalFeatures><ClinicalFeature uid='124413' SDUI='HP:0004840'>"
        "<Name>Hypochromic microcytic anemia</Name></ClinicalFeature></ClinicalFeatures>"
    )
    medgen = {"C0005283": {"title": "beta Thalassemia", "conceptmeta": conceptmeta}}

    documents = build_gene_documents(variants, {"HBB": {}}, medgen, {})

    concept = documents["HBB"]["medgen_concepts"][0]
    assert concept["title"] == "beta Thalassemia"
    assert concept["mim_number"] == "141900"
    assert concept["mode_inheritance"] == "Autosomal recessive inheritance"
    assert concept["clinical_summary"] == "Beta-thalassemia summary."
    assert concept["hpo_terms"] == [
        {"hpo_id": "HP:0004840", "hpo_name": "Hypochromic microcytic anemia"}
    ]
    assert concept["conceptmeta"] == conceptmeta


def test_build_gene_documents_leaves_concept_without_conceptmeta_untouched():
    variants = add_medgen_cuis(
        pl.DataFrame(
            {"#AlleleID": ["1"], "GeneSymbol": ["HBB"], "PhenotypeIDS": ["MedGen:C3661900"]}
        )
    )
    medgen = {"C3661900": {"title": "not provided"}}

    documents = build_gene_documents(variants, {"HBB": {}}, medgen, {})

    assert documents["HBB"]["medgen_concepts"] == [{"title": "not provided"}]


def test_build_gene_documents_records_provenance_in_each_document():
    variants = add_medgen_cuis(
        pl.DataFrame({"#AlleleID": [], "GeneSymbol": [], "PhenotypeIDS": []}, schema=EMPTY_SCHEMA)
    )
    provenance = {"collected_at": "2026-07-22T14:00:00+00:00", "clinvar_bulk_url": "https://x"}

    documents = build_gene_documents(variants, {"HBB": {}}, {}, {}, provenance=provenance)

    assert documents["HBB"]["_provenance"] == provenance


def test_build_gene_documents_omits_provenance_when_not_supplied():
    variants = add_medgen_cuis(
        pl.DataFrame({"#AlleleID": [], "GeneSymbol": [], "PhenotypeIDS": []}, schema=EMPTY_SCHEMA)
    )

    documents = build_gene_documents(variants, {"HBB": {}}, {}, {})

    assert "_provenance" not in documents["HBB"]


def test_write_raw_gene_files_keeps_non_ascii_characters_readable(tmp_path):
    """Les définitions MedGen contiennent des caractères non-ASCII (ß, accents) :
    ils doivent rester lisibles dans le JSON, pas être échappés en \\uXXXX."""
    documents = {"HBB": {"gene_symbol": "HBB", "summary": "ß-thalassémie sévère"}}

    written = write_raw_gene_files(documents, tmp_path)

    content = written[0].read_text(encoding="utf-8")
    assert "ß-thalassémie sévère" in content
    assert json.loads(content)["summary"] == "ß-thalassémie sévère"


def test_find_empty_genes_flags_any_missing_variants_or_gene_info():
    documents = {
        "HBB": {"gene_info": {"name": "HBB"}, "variants": [{"#AlleleID": "1"}]},
        "HBS1L-MYB": {"gene_info": {}, "variants": []},
        "KLF1": {"gene_info": {}, "variants": [{"#AlleleID": "2"}]},
        "MYB": {"gene_info": {"name": "MYB"}, "variants": []},
    }

    # build_gene_documents émet un document par gène demandé : n'alerter que sur les
    # documents totalement vides laisserait passer un symbole ClinVar devenu invalide.
    assert find_empty_genes(documents) == ["HBS1L-MYB", "KLF1", "MYB"]


def test_build_gene_documents_keeps_provenance_of_unresolvable_cui():
    variants = add_medgen_cuis(
        pl.DataFrame(
            {"#AlleleID": ["1"], "GeneSymbol": ["HBB"], "PhenotypeIDS": ["MedGen:CN517202"]}
        )
    )
    # fetch_medgen_concept renvoie {} quand esearch ne trouve rien : sans marqueur,
    # le CUI en échec devient irrécupérable depuis le document.
    medgen = {"CN517202": {}}

    documents = build_gene_documents(variants, {"HBB": {}}, medgen, {})

    assert documents["HBB"]["medgen_concepts"] == [{"conceptid": "CN517202"}]


def test_build_gene_documents_does_not_alias_the_caller_concept_dicts():
    variants = add_medgen_cuis(
        pl.DataFrame(
            {
                "#AlleleID": ["1", "2"],
                "GeneSymbol": ["HBB", "KLF1"],
                "PhenotypeIDS": ["MedGen:C3661900", "MedGen:C3661900"],
            }
        )
    )
    concept = {"title": "not provided"}

    documents = build_gene_documents(
        variants, {"HBB": {}, "KLF1": {}}, {"C3661900": concept}, {}
    )

    hbb_concept = documents["HBB"]["medgen_concepts"][0]
    assert hbb_concept is not concept
    assert hbb_concept is not documents["KLF1"]["medgen_concepts"][0]


def test_find_empty_genes_returns_empty_list_when_all_populated():
    documents = {"HBB": {"gene_info": {"name": "HBB"}, "variants": [{"#AlleleID": "1"}]}}

    assert find_empty_genes(documents) == []


def test_write_raw_gene_files_creates_one_json_per_gene(tmp_path):
    documents = {"HBB": {"gene_symbol": "HBB", "variants": []}}
    written = write_raw_gene_files(documents, tmp_path / "raw")

    assert written == [tmp_path / "raw" / "HBB.json"]
    content = (tmp_path / "raw" / "HBB.json").read_text(encoding="utf-8")
    assert '"gene_symbol": "HBB"' in content
