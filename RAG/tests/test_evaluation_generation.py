"""Outil de l'évaluation E3a : tirage, contrôles du jeu, vérité terrain (sans réseau ni base)."""

import json

import polars as pl
import pytest
import yaml

from RAG.experiments import evaluation_generation as ev

GENES = ["BRCA1", "BRCA2", "TP53", "HBB"]
STRATA = {"I": 6, "S": 5, "G": 3, "M": 3}


def _gold():
    rows = [{"doc_id": f"gene:{g}", "doc_type": "gene", "gene_symbol": g, "clinical_significance": None,
             "rs_dbsnp": None, "hgvs_c": None, "hgvs_p": None} for g in GENES]
    labels = ["Pathogenic", "Benign", "Uncertain significance", "Likely benign",
              "Conflicting classifications of pathogenicity"]
    n = 0
    for g in GENES:
        for k in range(12):
            n += 1
            rows.append({"doc_id": f"clinvar:{n}", "doc_type": "variant", "gene_symbol": g,
                         "clinical_significance": labels[k % len(labels)],
                         "rs_dbsnp": (1000 + n) if k % 3 else -1,
                         "hgvs_c": f"c.{100 + k}A>G" if k % 4 else None, "hgvs_p": None})
    return pl.DataFrame(rows, schema_overrides={"rs_dbsnp": pl.Int64})


def _diseases():
    rows = []
    for i in range(1, 49):
        rows.append({"doc_id": f"clinvar:{i}", "disease_name": ["Breast cancer", "Fanconi anemia",
                                                               "Li-Fraumeni syndrome", "not provided"][i % 4]})
        rows.append({"doc_id": f"clinvar:{i}", "disease_name": "8 conditions"})
    return pl.DataFrame(rows)


def _draw(seed=7, excluded=frozenset()):
    return ev.draw_questions(_gold(), _diseases(), strata=STRATA, seed=seed, excluded_doc_ids=set(excluded))


def test_draw_is_deterministic():
    assert _draw(7) == _draw(7)
    assert _draw(7) != _draw(8)


def test_draw_counts_and_ids():
    qs = _draw()
    assert {s: sum(q["strate"] == s for q in qs) for s in ev.STRATA} == STRATA
    assert len({q["id"] for q in qs}) == len(qs)


def test_identifier_draw_respects_exclusions_and_has_no_duplicate():
    excluded = {f"clinvar:{i}" for i in range(1, 25)}
    qs = [q for q in _draw(excluded=excluded) if q["strate"] == "I"]
    docs = [q["tirage"]["doc_id"] for q in qs]
    assert not set(docs) & excluded
    assert len(set(docs)) == len(docs)


def test_identifier_question_cites_its_variant_and_gene():
    for q in (q for q in _draw() if q["strate"] == "I"):
        assert q["tirage"]["identifiant"] in q["question"] and q["tirage"]["gene"] in q["question"]
        assert not q["tirage"]["identifiant"].startswith("rs-")


def test_uninformative_diseases_are_never_drawn():
    for q in (q for q in _draw() if q["strate"] in ("S", "M")):
        assert q["tirage"]["maladie"] not in ("not provided", "8 conditions")


def test_significance_class_is_present_for_the_pair():
    gold, diseases = _gold(), _diseases()
    for q in (q for q in _draw() if q["strate"] == "S"):
        assert q["relevant"]["significance"] == ev.SIGNIFICANCE_CLASSES[q["tirage"]["classe"]]
        assert ev.relevant_doc_ids(q, gold, diseases)  # au moins un document pertinent


def test_gene_questions_without_replacement():
    genes = [q["tirage"]["gene"] for q in _draw() if q["strate"] == "G"]
    assert len(set(genes)) == len(genes) == STRATA["G"]


def test_disease_pairs_not_repeated_between_s_and_m():
    qs = _draw()
    s_pairs = {(q["tirage"]["gene"], q["tirage"]["maladie"]) for q in qs if q["strate"] == "S"}
    m_pairs = [(q["tirage"]["gene"], q["tirage"]["maladie"]) for q in qs if q["strate"] == "M"]
    assert not s_pairs & set(m_pairs) and len(set(m_pairs)) == len(m_pairs)


def test_draft_roundtrips_through_the_loader(tmp_path):
    path = tmp_path / "q.yaml"
    path.write_text(ev.render_draft(_draw(), seed=7), encoding="utf-8")
    active = ev.load_questions(path, STRATA)
    assert len(active) == sum(STRATA.values())


# --- Contrôles bloquants du jeu ---------------------------------------------------------------

def _write(tmp_path, questions):
    path = tmp_path / "q.yaml"
    path.write_text(yaml.safe_dump(questions, allow_unicode=True), encoding="utf-8")
    return path


def test_out_of_scope_question_is_refused(tmp_path):
    qs = _draw()
    qs[0]["question"] = "Combien de variants pathogènes compte BRCA1 ?"
    with pytest.raises(SystemExit, match="hors périmètre"):
        ev.load_questions(_write(tmp_path, qs), STRATA)


def test_identifier_question_must_still_cite_the_drawn_variant(tmp_path):
    qs = _draw()
    first = next(q for q in qs if q["strate"] == "I")
    first["question"] = f"Que sait-on du variant rs1 de {first['tirage']['gene']} ?"
    with pytest.raises(SystemExit, match="ne cite plus"):
        ev.load_questions(_write(tmp_path, qs), STRATA)


def test_wrong_counts_are_refused(tmp_path):
    with pytest.raises(SystemExit, match="effectifs"):
        ev.load_questions(_write(tmp_path, _draw()[1:]), STRATA)


def test_duplicate_ids_are_refused(tmp_path):
    qs = _draw()
    qs[1]["id"] = qs[0]["id"]
    with pytest.raises(SystemExit, match="double"):
        ev.load_questions(_write(tmp_path, qs), STRATA)


def test_excluded_question_needs_a_reason_and_is_inactive(tmp_path):
    qs = _draw()
    qs[0]["ecartee"] = "maladie mal nommée dans ClinVar"
    assert len(ev.load_questions(_write(tmp_path, qs), STRATA)) == sum(STRATA.values()) - 1
    qs[0]["ecartee"] = " "
    with pytest.raises(SystemExit, match="motif"):
        ev.load_questions(_write(tmp_path, qs), STRATA)


# --- Vérité terrain -----------------------------------------------------------------------------

def test_identifier_truth_is_the_exact_match():
    q = next(q for q in _draw() if q["strate"] == "I")
    relevant = ev.relevant_doc_ids(q, _gold(), _diseases())
    assert q["tirage"]["doc_id"] in relevant


def test_identifier_truth_refuses_a_lost_variant():
    q = next(q for q in _draw() if q["strate"] == "I")
    q = {**q, "tirage": {**q["tirage"], "doc_id": "clinvar:999999"}}
    with pytest.raises(SystemExit, match="correspondance exacte"):
        ev.relevant_doc_ids(q, _gold(), _diseases())


def test_gene_truth():
    q = next(q for q in _draw() if q["strate"] == "G")
    assert ev.relevant_doc_ids(q, _gold(), _diseases()) == [q["relevant"]["doc_id"]]


def test_tirer_never_overwrites(tmp_path):
    target = tmp_path / "q.yaml"
    target.write_text("déjà là", encoding="utf-8")
    with pytest.raises(SystemExit, match="existe déjà"):
        ev.main(["tirer", "--sortie", str(target)])
    assert target.read_text(encoding="utf-8") == "déjà là"


def test_atomic_write(tmp_path):
    path = tmp_path / "x" / "f.json"
    ev._write_json_atomic(path, {"a": "é"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": "é"}
    assert not list(path.parent.glob("*.tmp"))
