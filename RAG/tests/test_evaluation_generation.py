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


# --- Budget, caches, enregistrement, génération sur recherche figée (Tâche 6) -------------------

from RAG.src.llm.common import LlmCall  # noqa: E402
from RAG.src.retrieval.analysis import QueryAnalysis  # noqa: E402
from RAG.src.retrieval.identifiers import extract_identifiers  # noqa: E402
from RAG.src.retrieval.retriever import RetrievedDocument, SearchResult, SearchTrace  # noqa: E402
from RAG.src.utils.config import LlmProfile  # noqa: E402
from RAG.src.utils.errors import LlmTruncatedError, LlmUnavailableError  # noqa: E402

PROFILE = LlmProfile("mistral-medium", "mistralai/mistral-medium-3-5", "mistral/zdr", "Mistral", None)
DOC_TEXT = "Variant c.5266dup, gene BRCA1. dbSNP rs80357906. Clinical significance: Pathogenic."


class FakeLlm:
    def __init__(self, content=None, cost=0.02, error=None):
        self.content, self.cost, self.error, self.calls, self.closed = content, cost, error, 0, False

    def complete_json(self, profile, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return LlmCall(self.content, "g", "Mistral", self.cost, 10, 5)

    def close(self):
        self.closed = True


def _kwargs(user="u", system="s"):
    return {"system": system, "user": user, "schema_name": "x", "schema": {}, "max_tokens": 3000}


def _doc(doc_id="clinvar:32716"):
    return RetrievedDocument(doc_id=doc_id, doc_type="variant", text=DOC_TEXT, gene_symbol="BRCA1",
                             clinical_significance="Pathogenic", review_status="reviewed by expert panel",
                             rs_dbsnp=80357906, hgvs_c="c.5266dup", hgvs_p="p.Gln1756fs",
                             clinvar_variation_id="17677", clinvar_url="https://example/17677",
                             source_version="2026-10", similarity=0.9, stage="exact")


def _result(question="Que sait-on de rs80357906 ?", docs=None, available=True):
    trace = SearchTrace(mode="full", identifiers=extract_identifiers(question),
                        analysis=QueryAnalysis("q", "none", None, available, "essai"))
    return SearchResult(question=question, documents=tuple(docs if docs is not None else [_doc()]), trace=trace)


Q = {"id": "E3-I01", "strate": "I", "question": "Que sait-on de rs80357906 ?"}


def test_budget_exact_boundaries(tmp_path):
    path = tmp_path / "depenses.json"
    budget = ev.Budget(path, limit_usd=1.0, reserve_usd=0.25)
    inner = FakeLlm({"a": 1}, cost=0.30)
    client = ev.BudgetedClient(inner, budget)
    for _ in range(3):
        client.complete_json(PROFILE, **_kwargs())    # dépensé 0 -> 0,3 -> 0,6 -> 0,9 (0,6 + 0,25 ≤ 1)
    with pytest.raises(ev.BudgetExceededError):
        client.complete_json(PROFILE, **_kwargs())    # 0,9 + 0,25 > 1 : refusé AVANT l'appel
    assert inner.calls == 3
    reloaded = ev.Budget(path, limit_usd=1.0, reserve_usd=0.25)
    assert reloaded.spent == pytest.approx(0.9) and reloaded.calls == 3


def test_billed_truncation_is_counted(tmp_path):
    budget = ev.Budget(tmp_path / "d.json", 10.0, 0.25)
    client = ev.BudgetedClient(FakeLlm(error=LlmTruncatedError("coupée", cost_usd=0.07)), budget)
    with pytest.raises(LlmTruncatedError):
        client.complete_json(PROFILE, **_kwargs())
    assert budget.spent == pytest.approx(0.07)


def test_cache_hits_cost_nothing_and_survive_restart(tmp_path):
    budget = ev.Budget(tmp_path / "d.json", 10.0, 0.25)
    inner = FakeLlm({"a": 1}, cost=0.5)
    cached = ev.CachedClient(ev.BudgetedClient(inner, budget), tmp_path / "c.json", "generation-p1")
    cached.complete_json(PROFILE, **_kwargs())
    assert not cached.last_hit
    again = ev.CachedClient(ev.BudgetedClient(inner, budget), tmp_path / "c.json", "generation-p1")
    assert again.complete_json(PROFILE, **_kwargs()).content == {"a": 1}
    assert again.last_hit and inner.calls == 1 and budget.spent == pytest.approx(0.5)


def test_each_passage_has_its_own_cache_namespace(tmp_path):
    inner = FakeLlm({"a": 1})
    for passage in (1, 2):
        ev.CachedClient(inner, tmp_path / "c.json", f"generation-p{passage}").complete_json(PROFILE, **_kwargs())
    assert inner.calls == 2


def test_cache_key_depends_on_system_prompt_and_message():
    base = ev.call_cache_key("n", PROFILE, system="s", user="u", schema_name="x", max_tokens=1)
    assert base != ev.call_cache_key("n", PROFILE, system="s2", user="u", schema_name="x", max_tokens=1)
    assert base != ev.call_cache_key("n", PROFILE, system="s", user="u2", schema_name="x", max_tokens=1)
    assert base != ev.call_cache_key("m", PROFILE, system="s", user="u", schema_name="x", max_tokens=1)


def test_failures_are_not_cached(tmp_path):
    inner = FakeLlm(error=LlmUnavailableError("503"))
    cached = ev.CachedClient(inner, tmp_path / "c.json", "n")
    with pytest.raises(LlmUnavailableError):
        cached.complete_json(PROFILE, **_kwargs())
    assert not (tmp_path / "c.json").exists()


def _stored(doc_ids=("clinvar:32716",)):
    return {"doc_ids": list(doc_ids), "llm_called": True}


def _clients(tmp_path, content):
    inner = FakeLlm(content)
    cached = ev.CachedClient(inner, tmp_path / "c.json", "generation-p1")
    return ev.RecordingClient(cached), cached, inner


def test_rejected_answer_keeps_the_raw_model_text(tmp_path):
    raw = {"status": "answered", "scope_reason": None, "citations": ["D1"],
           "answer": "Le variant rs80357906 est bénin."}  # contredit la fiche : rejet par les contrôles
    recorder, cached, _ = _clients(tmp_path, raw)
    record = ev.generate_record(Q, _stored(), _result(), recorder=recorder, cached=cached, profile=PROFILE,
                                max_tokens=3000, passage=1)
    assert record["status"] == "unverifiable"
    assert record["llm_status"] == "answered"
    assert record["llm_text"] == "Le variant rs80357906 est bénin."
    assert record["llm_citations"] == ["D1"]


def test_accepted_answer_record(tmp_path):
    raw = {"status": "answered", "scope_reason": None, "citations": ["D1"],
           "answer": "Le variant rs80357906 est pathogène."}
    recorder, cached, _ = _clients(tmp_path, raw)
    record = ev.generate_record(Q, _stored(), _result(), recorder=recorder, cached=cached, profile=PROFILE,
                                max_tokens=3000, passage=1)
    assert record["status"] == "answered" and record["rejected"] is None
    assert record["cost_usd"] == 0.02 and record["from_cache"] is False


def test_unavailable_generation_is_recorded_without_its_message(tmp_path):
    recorder, cached, _ = _clients(tmp_path, {"nonsense": True})  # hors schéma
    record = ev.generate_record(Q, _stored(), _result(), recorder=recorder, cached=cached, profile=PROFILE,
                                max_tokens=3000, passage=2)
    assert record["status"] == ev.UNAVAILABLE and record["error"] == "LlmUnavailableError"
    assert record["passage"] == 2 and record["llm_text"] is None


def test_changed_documents_stop_before_any_call(tmp_path):
    recorder, cached, inner = _clients(tmp_path, {})
    with pytest.raises(SystemExit, match="ne redonne pas"):
        ev.generate_record(Q, _stored(("clinvar:1",)), _result(), recorder=recorder, cached=cached,
                           profile=PROFILE, max_tokens=3000, passage=1)
    assert inner.calls == 0


def test_missing_cached_analysis_stops(tmp_path):
    recorder, cached, inner = _clients(tmp_path, {})
    with pytest.raises(SystemExit, match="analyse absente"):
        ev.generate_record(Q, _stored(), _result(available=False), recorder=recorder, cached=cached,
                           profile=PROFILE, max_tokens=3000, passage=1)
    assert inner.calls == 0


def test_search_record_flags_llm_and_fixed_cases():
    called = ev.search_record(Q, _result(), profile=PROFILE, max_tokens=3000)
    assert called["llm_called"] is True and called["fixed_status"] is None
    assert called["doc_ids"] == ["clinvar:32716"]
    assert '<document id="D1"' in called["context"]
    empty = ev.search_record(Q, _result(docs=[]), profile=PROFILE, max_tokens=3000)
    assert empty["llm_called"] is False and empty["fixed_status"] == "not_in_sources"


def test_repeats_are_deterministic_and_drawn_among_llm_questions():
    ids = [f"E3-S{i:02d}" for i in range(1, 31)]
    first = ev.select_repeats(ids, 20, 20261014)
    assert first == ev.select_repeats(list(reversed(ids)), 20, 20261014)
    assert len(set(first)) == 20 and set(first) <= set(ids)
    with pytest.raises(SystemExit):
        ev.select_repeats(ids[:5], 20, 1)


def test_manifest_mismatch_names_the_differing_fields(tmp_path):
    with pytest.raises(SystemExit, match="generation_prompt_sha"):
        ev.check_manifest(tmp_path / "f.json", {"generation_prompt_sha": "a", "k": 1},
                          {"generation_prompt_sha": "b", "k": 1})


# --- Jugement, échantillon, annotation (Tâche 7) -------------------------------------------------

def _gen(profile, passage, records):
    return {"manifest": {"profile": profile, "passage": passage}, "records": records}


def _rec(strate="I", llm_status="answered", text="Réponse."):
    return {"strate": strate, "llm_status": llm_status, "llm_text": text}


def test_only_model_answers_are_judged():
    generations = {("a", 1): _gen("a", 1, {"q1": _rec(), "q2": _rec(llm_status="not_in_sources"),
                                           "q3": _rec(llm_status=None, text=None), "q4": _rec(text="  ")}),
                   ("a", 2): _gen("a", 2, {"q1": _rec(llm_status="partial")})}
    keys = [k for k, _ in ev.answers_to_judge(generations)]
    assert keys == ["a|p1|q1|r1", "a|p2|q1|r1"]


def test_judge_key_roundtrip():
    assert ev.parse_judge_key(ev.judge_key("gpt-oss-120b", 3, "E3-S01", 2)) == ("gpt-oss-120b", 3, "E3-S01", 2)


def test_load_generations_reads_every_series(tmp_path):
    ev._write_json_atomic(tmp_path / "a__p1.json", _gen("a", 1, {}))
    ev._write_json_atomic(tmp_path / "b__p2.json", _gen("b", 2, {}))
    assert set(ev.load_generations(tmp_path)) == {("a", 1), ("b", 2)}


def _eligible(n_per=(30, 30, 30), candidates=("a", "b", "c")):
    out = []
    for name, n in zip(candidates, n_per):
        for i in range(n):
            out.append({"key": f"{name}|p1|q{i:02d}|r1", "profile": name, "strate": "ISGM"[i % 4]})
    return out


def test_sample_quotas_strata_and_determinism():
    keys = ev.draw_sample(_eligible(), size=40, seed=20261014, candidates=("a", "b", "c"))
    assert len(keys) == len(set(keys)) == 40
    counts = {c: sum(k.startswith(f"{c}|") for k in keys) for c in "abc"}
    assert counts == {"a": 14, "b": 13, "c": 13}
    assert keys == ev.draw_sample(_eligible(), size=40, seed=20261014, candidates=("a", "b", "c"))
    a_strata = sorted(k.split("|")[2] for k in keys if k.startswith("a|"))
    assert len({int(q[1:]) % 4 for q in a_strata}) == 4  # les quatre strates représentées


def test_sample_order_is_shuffled_across_candidates():
    keys = ev.draw_sample(_eligible(), size=40, seed=1, candidates=("a", "b", "c"))
    assert [k[0] for k in keys] != sorted(k[0] for k in keys)


def test_sample_refuses_too_few_answers():
    with pytest.raises(SystemExit, match="requises"):
        ev.draw_sample(_eligible((30, 5, 30)), size=40, seed=1, candidates=("a", "b", "c"))


def test_allocate_largest_remainder():
    # Parts exactes 1,86 / 4,64 / 1,86 / 4,64 : planchers 1/4/1/4, restes à G, M (égalité : nom), puis I.
    assert ev._allocate(13, {"G": 10, "I": 25, "M": 10, "S": 25}) == {"G": 2, "I": 5, "M": 2, "S": 4}
    assert sum(ev._allocate(14, {"I": 3, "S": 3, "G": 1}).values()) == 14


ITEMS = [{"n": 1, "question": "Q1 ?", "context": '<document id="D1">c.1A&gt;G &lt;x</document>',
          "answer": "R1", "claims": ["a", "b"]},
         {"n": 2, "question": "Q2 ?", "context": "C2", "answer": "R2", "claims": ["c"]}]


def _scripted(answers):
    answers = list(answers)
    return lambda _prompt: answers.pop(0)


def test_annotation_records_verdicts_flags_and_relevance():
    shown, saved = [], []
    done = ev.annotate(ITEMS, {}, ask=_scripted(["s", "nm", "n", "2", "s", "o", "1"]), show=shown.append,
                       save=lambda d: saved.append(json.loads(json.dumps(d))))
    assert done["1"] == {"verdicts": [True, False], "mal_decoupees": [2], "oubliee": False, "pertinence": 2}
    assert done["2"] == {"verdicts": [True], "mal_decoupees": [], "oubliee": True, "pertinence": 1}
    assert len(saved) == 2  # enregistré après chaque réponse


def test_annotation_is_blind_and_readable():
    shown = []
    ev.annotate(ITEMS[:1], {}, ask=_scripted(["s", "s", "n", "2"]), show=shown.append, save=lambda d: None)
    text = "\n".join(shown)
    assert "c.1A>G <x" in text  # documents désechappés pour la lecture
    for hidden in ("gpt-oss", "mistral", "claude", "soutenue\"", "faithfulness"):
        assert hidden not in text


def test_invalid_input_is_asked_again():
    shown = []
    done = ev.annotate(ITEMS[1:], {}, ask=_scripted(["x", "s", "peut-être", "n", "3", "0"]), show=shown.append,
                       save=lambda d: None)
    assert done["2"]["pertinence"] == 0
    assert sum("saisie attendue" in line for line in shown) == 3


def test_annotation_resumes_and_quits_cleanly():
    done = ev.annotate(ITEMS, {}, ask=_scripted(["s", "s", "n", "2", "q"]), show=lambda _: None, save=lambda d: None)
    assert set(done) == {"1"}
    done = ev.annotate(ITEMS, done, ask=_scripted(["n", "n", "0"]), show=lambda _: None, save=lambda d: None)
    assert set(done) == {"1", "2"} and done["2"]["verdicts"] == [False]


def _small_settings(monkeypatch):
    import dataclasses

    from RAG.src.evaluation import settings as settings_module
    real = settings_module.load_settings()
    small = dataclasses.replace(real, strata=STRATA, budget_usd=5.0)
    monkeypatch.setattr(settings_module, "load_settings", lambda *a, **k: small)
    return small


def _setup_outputs(monkeypatch, tmp_path):
    for name in ("OUT", "SEARCHES", "JUDGEMENTS", "JUDGE_CACHE", "SAMPLE", "ANNOTATIONS", "GENERATIONS",
                 "SPENDING", "QUESTIONS_PATH"):
        monkeypatch.setattr(ev, name, tmp_path / name.lower())
    questions = _draw()
    ev.QUESTIONS_PATH.write_text(ev.render_draft(questions, seed=1), encoding="utf-8")
    ev._write_json_atomic(ev.SEARCHES, {"manifest": {}, "records": {
        q["id"]: {"context": f"CTX {q['id']}", "llm_called": True} for q in questions}})
    first = questions[0]["id"]
    ev._write_json_atomic(ev.GENERATIONS / "mistral-medium__p1.json", _gen("mistral-medium", 1, {
        first: _rec(), questions[1]["id"]: _rec(llm_status="not_in_sources")}))
    return first


class JudgeLlm:
    """Faux OpenRouter du juge : sortie incohérente au premier appel de verdicts si `broken`."""

    instances = []

    def __init__(self, *args, broken=False, **kwargs):
        self.broken, self.calls = JudgeLlm.broken, 0
        JudgeLlm.instances.append(self)

    def complete_json(self, profile, *, system, user, schema_name, schema, max_tokens):
        self.calls += 1
        content = {"affirmations": {"affirmations": ["a"]},
                   "verdicts": {"verdicts": [] if self.broken else
                                [{"numero": 1, "justification": "D1", "verdict": "soutenue"}]},
                   "pertinence": {"justification": "ok", "note": 2}}[schema_name]
        return LlmCall(content, "g", "Google", 0.001, 1, 1)

    def close(self):
        pass


def test_juger_records_judgements_and_skips_incoherent_ones(tmp_path, monkeypatch):
    import RAG.src.llm.openrouter as openrouter
    _small_settings(monkeypatch)
    first = _setup_outputs(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(openrouter, "OpenRouterClient", JudgeLlm)
    JudgeLlm.broken = True
    ev.main(["juger"])
    assert not ev.JUDGEMENTS.exists()  # une sortie incohérente n'est jamais un score
    JudgeLlm.broken = False
    ev.main(["juger"])
    records = json.loads(ev.JUDGEMENTS.read_text(encoding="utf-8"))["records"]
    assert list(records) == [f"mistral-medium|p1|{first}|r1"]  # not_in_sources jamais jugé
    assert records[f"mistral-medium|p1|{first}|r1"]["faithfulness"] == 1.0
    calls_before = JudgeLlm.instances[-1].calls
    ev.main(["juger"])  # tout est fait : aucun appel
    assert JudgeLlm.instances[-1].calls == 0 and calls_before == 2
    spent = json.loads(ev.SPENDING.read_text(encoding="utf-8"))
    # Payés : découpage + verdicts refusés au 1er passage ; au 2e, découpage relu du cache,
    # verdicts rappelés (la sortie refusée a quitté le cache), pertinence.
    assert spent["total_usd"] == pytest.approx(0.001 * (2 + 2))


def test_forget_last_removes_only_the_refused_output(tmp_path):
    inner = FakeLlm({"a": 1})
    cached = ev.CachedClient(inner, tmp_path / "c.json", "juge-r1")
    cached.complete_json(PROFILE, **_kwargs(user="bon"))
    cached.complete_json(PROFILE, **_kwargs(user="refusé"))
    cached.forget_last()
    reloaded = ev.CachedClient(inner, tmp_path / "c.json", "juge-r1")
    reloaded.complete_json(PROFILE, **_kwargs(user="bon"))
    assert reloaded.last_hit
    reloaded.complete_json(PROFILE, **_kwargs(user="refusé"))
    assert not reloaded.last_hit and inner.calls == 3
