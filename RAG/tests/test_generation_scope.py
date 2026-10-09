"""Règles hors périmètre. Écrites et testées avec la série de développement et des phrases
inventées ; la série de contrôle (questions_recette_e2b_controle.yaml) n'est jamais lue ici."""

from pathlib import Path

import pytest
import yaml

from RAG.src.generation.scope import detect_out_of_scope, normalize

EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments"
DEVELOPMENT = yaml.safe_load((EXPERIMENTS / "questions_recette_e2b.yaml").read_text(encoding="utf-8"))
SEARCH = yaml.safe_load((EXPERIMENTS / "questions_recherche.yaml").read_text(encoding="utf-8"))
# Détections réelles parmi les questions de la recherche (examinées une à une) : P3-05 demande
# une fréquence (« est-elle fréquente ? »), absente des sources.
GENUINE_IN_SEARCH_SET = {"P3-05": "frequency"}


@pytest.mark.parametrize("q", DEVELOPMENT, ids=[q["id"] for q in DEVELOPMENT])
def test_development_set_reasons(q):
    expected = q["expected_scope_reason"]
    # « other » (hors domaine) n'a pas de règle : il reste au LLM.
    assert detect_out_of_scope(q["question"]) == (None if expected == "other" else expected)


def test_no_false_positive_on_the_search_questions():
    detected = {q["id"]: detect_out_of_scope(q["question"]) for q in SEARCH}
    assert len(SEARCH) == 89
    assert {k: v for k, v in detected.items() if v} == GENUINE_IN_SEARCH_SET


@pytest.mark.parametrize("question,reason", [
    ("Combien de variants de HBB sont bénins ?", "counting"),
    ("Quel est le nombre de variants pathogènes de PALB2 ?", "counting"),
    ("Donne la liste exhaustive des variants de CDH1.", "counting"),
    ("Cite tous les variants de TP53 associés au syndrome de Li-Fraumeni.", "counting"),
    ("Énumère les variants probablement pathogènes de ATM.", "counting"),
    ("Quelle maladie a le moins de variants dans le panel ?", "counting"),
    ("Quels gènes portent le plus grand nombre de variants bénins ?", "counting"),
    ("Quelle gène du panel est le plus souvent cité ?", "counting"),
    ("Ce variant de BRCA2 remplit-il le critère PM2 ?", "acmg"),
    ("Le critère BA1 s'applique-t-il à rs334 ?", "acmg"),
    ("Selon ACMG/AMP, comment classer c.5266dup ?", "acmg"),
    ("Quels sont les critères de classification de ce variant ?", "acmg"),
    ("Peux-tu classer ce variant de BRCA1 selon les règles du laboratoire ?", "acmg"),
    ("Quelle est la prévalence de la drépanocytose au Sénégal ?", "frequency"),
    ("Ce variant est-il frequent en Europe ?", "frequency"),
    ("Quelle proportion de la population porte rs334 ?", "frequency"),
    ("Quelle est la fréquence de l'allèle S dans la population africaine ?", "frequency"),
    ("Doit-on proposer un dépistage aux apparentés ?", "clinical_advice"),
    ("Quel médicament éviter chez un porteur de variant G6PD ?", "clinical_advice"),
    ("Quelle prise en charge pour une patiente porteuse de c.5266dup ?", "clinical_advice"),
    ("Quel suivi recommander à une porteuse de PALB2 ?", "clinical_advice"),
    ("Une chirurgie prophylactique est-elle indiquée ?", "clinical_advice"),
    ("Comment traiter une crise vaso-occlusive ?", "clinical_advice"),
    ("FAUT-IL PRESCRIRE de l'hydroxyurée ?", "clinical_advice"),
])
def test_invented_out_of_scope_questions(question, reason):
    assert detect_out_of_scope(question) == reason


@pytest.mark.parametrize("question", [
    "Que sait-on de rs80357906 ?",
    "Le variant c.5266dup de BRCA1 est-il pathogène ?",
    "Quelles maladies sont associées au gène PALB2 ?",
    "Comment ce variant est-il classé selon ClinVar ?",
    "Quel est le statut de revue du variant rs334 ?",
    "Quels phénotypes sont décrits pour les variants pathogènes de STK11 ?",
    "Que sait-on du gène HBS1L ?",
    "Quelle est la capitale du Sénégal ?",
])
def test_ordinary_or_unruled_questions_are_not_detected(question):
    assert detect_out_of_scope(question) is None


def test_normalization_tolerates_accents_case_and_typographic_apostrophes():
    assert normalize("  Énumère   l’ensemble ") == "enumere l'ensemble"
    assert detect_out_of_scope("Quelle est la FREQUENCE de rs334 ?") == "frequency"
    assert detect_out_of_scope("Ｃombien de variants ?") == "counting"  # pleine chasse (NFKC)
