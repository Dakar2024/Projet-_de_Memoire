import polars as pl


def test_add_medgen_cuis_extracts_list_column():
    from ingestion.orchestrate import add_medgen_cuis

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
    from ingestion.orchestrate import add_medgen_cuis, build_gene_documents

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
    from ingestion.orchestrate import add_medgen_cuis, build_gene_documents

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


def test_write_raw_gene_files_creates_one_json_per_gene(tmp_path):
    from ingestion.orchestrate import write_raw_gene_files

    documents = {"HBB": {"gene_symbol": "HBB", "variants": []}}
    written = write_raw_gene_files(documents, tmp_path / "raw")

    assert written == [tmp_path / "raw" / "HBB.json"]
    content = (tmp_path / "raw" / "HBB.json").read_text(encoding="utf-8")
    assert '"gene_symbol": "HBB"' in content
