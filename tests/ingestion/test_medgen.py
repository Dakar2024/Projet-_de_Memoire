import responses

from ingestion.http_client import NcbiClient, RateLimiter
from ingestion.medgen import extract_medgen_cuis


def test_extract_medgen_cuis_parses_multiple_xrefs():
    field = "MedGen:C3661900,OMIM:603903|MedGen:CN169374"
    assert extract_medgen_cuis(field) == ["C3661900", "CN169374"]


def test_extract_medgen_cuis_deduplicates():
    field = "MedGen:C3661900|MedGen:C3661900,OMIM:603903"
    assert extract_medgen_cuis(field) == ["C3661900"]


def test_extract_medgen_cuis_returns_empty_list_when_absent():
    assert extract_medgen_cuis("") == []
    assert extract_medgen_cuis("na") == []


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


@responses.activate
def test_fetch_medgen_concept_returns_esummary_for_found_cui():
    from ingestion.medgen import fetch_medgen_concept

    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": ["287"]}},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        json={"result": {"287": {"title": "Hb SS disease", "conceptid": "C0002895"}}},
        status=200,
    )
    result = fetch_medgen_concept(_client(), "C0002895")
    assert result["title"] == "Hb SS disease"


@responses.activate
def test_fetch_medgen_concept_returns_empty_dict_when_not_found():
    from ingestion.medgen import fetch_medgen_concept

    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": []}},
        status=200,
    )
    assert fetch_medgen_concept(_client(), "C9999999") == {}


CONCEPTMETA_SAMPLE = """
<Definitions>
<Definition source="GeneReviews">Sickle cell disease (SCD) is characterized by intermittent vaso-occlusive events and chronic hemolytic anemia.</Definition>
</Definitions>
<ModesOfInheritance>
<ModeOfInheritance><Name>Autosomal recessive inheritance</Name></ModeOfInheritance>
</ModesOfInheritance>
<OMIM><MIM>603903</MIM></OMIM>
<AssociatedGenes><Gene gene_id="3043" chromosome="11" cytogen_loc="11p15.4">HBB</Gene></AssociatedGenes>
<ClinicalFeatures>
<ClinicalFeature SDUI="HP:0002027"><Name>Abdominal pain</Name></ClinicalFeature>
</ClinicalFeatures>
"""


def test_parse_medgen_conceptmeta_extracts_expected_fields():
    from ingestion.medgen import parse_medgen_conceptmeta

    result = parse_medgen_conceptmeta(CONCEPTMETA_SAMPLE)
    assert result["mim_number"] == "603903"
    assert result["mode_inheritance"] == "Autosomal recessive inheritance"
    assert "Sickle cell disease" in result["clinical_summary"]
    assert result["hpo_terms"] == [{"hpo_id": "HP:0002027", "hpo_name": "Abdominal pain"}]


def test_parse_medgen_conceptmeta_handles_missing_fields():
    from ingestion.medgen import parse_medgen_conceptmeta

    result = parse_medgen_conceptmeta("<Definitions></Definitions>")
    assert result == {
        "mim_number": "",
        "mim_numbers": [],
        "mode_inheritance": "",
        "modes_inheritance": [],
        "clinical_summary": "",
        "definitions": [],
        "hpo_terms": [],
    }


# beta Thalassemia (C0005283) : deux MIM, deux modes d'hérédité, plusieurs définitions.
# Les champs singuliers ne gardent que la première occurrence, d'où les champs pluriels.
MULTI_VALUED_CONCEPTMETA = """
<Definitions>
<Definition source="GeneReviews">Beta-thalassemia has two clinically significant forms.</Definition>
<Definition source="MONDO">A thalassemia caused by reduced beta globin synthesis.</Definition>
</Definitions>
<ModesOfInheritance>
<ModeOfInheritance uid="141025"><Name>Autosomal recessive inheritance</Name></ModeOfInheritance>
<ModeOfInheritance uid="141047"><Name>Autosomal dominant inheritance</Name></ModeOfInheritance>
</ModesOfInheritance>
<OMIM><MIM>141900</MIM><MIM>613985</MIM></OMIM>
"""


def test_parse_medgen_conceptmeta_collects_every_mim_and_inheritance_mode():
    from ingestion.medgen import parse_medgen_conceptmeta

    result = parse_medgen_conceptmeta(MULTI_VALUED_CONCEPTMETA)

    assert result["mim_numbers"] == ["141900", "613985"]
    assert result["modes_inheritance"] == [
        "Autosomal recessive inheritance",
        "Autosomal dominant inheritance",
    ]
    # Les singuliers restent la première occurrence, pour compatibilité.
    assert result["mim_number"] == "141900"
    assert result["mode_inheritance"] == "Autosomal recessive inheritance"


def test_parse_medgen_conceptmeta_keeps_every_definition_with_its_source():
    from ingestion.medgen import parse_medgen_conceptmeta

    result = parse_medgen_conceptmeta(MULTI_VALUED_CONCEPTMETA)

    assert result["definitions"] == [
        {
            "source": "GeneReviews",
            "text": "Beta-thalassemia has two clinically significant forms.",
        },
        {
            "source": "MONDO",
            "text": "A thalassemia caused by reduced beta globin synthesis.",
        },
    ]
    assert result["clinical_summary"] == "Beta-thalassemia has two clinically significant forms."


def test_parse_medgen_conceptmeta_keeps_text_split_by_nested_tags():
    from ingestion.medgen import parse_medgen_conceptmeta

    conceptmeta = "<Definitions><Definition source='NCBI'>Anémie <i>sévère</i> chronique.</Definition></Definitions>"

    result = parse_medgen_conceptmeta(conceptmeta)

    assert result["clinical_summary"] == "Anémie sévère chronique."
