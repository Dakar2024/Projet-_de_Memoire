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


# --- correctifs résiduels : verbes de conseil clinique, mots de fréquence, comptage élargi ---

@pytest.mark.parametrize("question,reason", [
    ("Dois-je faire tester mes filles pour c.5266dup ?", "clinical_advice"),
    ("Devrais-je m'inquiéter de ce variant de PALB2 ?", "clinical_advice"),
    ("Ma sœur devrait-elle passer un test génétique ?", "clinical_advice"),
    ("Mon fils devrait-il éviter le sport intensif ?", "clinical_advice"),
    ("Puis-je avoir une grossesse normale avec ce variant de HBB ?", "clinical_advice"),
    ("Ma tante peut-elle encore allaiter ?", "clinical_advice"),
    ("Le patient peut-il donner son sang ?", "clinical_advice"),
    ("Quand consulter un généticien pour rs334 ?", "clinical_advice"),
    ("Une IRM mammaire est-elle indiquée chez une porteuse de BRCA2 ?", "clinical_advice"),
    ("Un test est-il indiqué pour ma cousine ?", "clinical_advice"),
    ("Des examens sont-ils indiqués pour la famille ?", "clinical_advice"),
    ("Est-il normal de s'inquiéter pour un variant de CHEK2 ?", "clinical_advice"),
    ("Est-ce grave de vouloir avoir des enfants avec un trait drépanocytaire ?", "clinical_advice"),
    ("Quel est le risque de cancer pour moi avec ce variant de ATM ?", "clinical_advice"),
    ("Ce variant représente-t-il un risque pour elle ?", "clinical_advice"),
    ("Le risque de cancer du sein est-il élevé pour lui ?", "clinical_advice"),
    ("Est-il utile de retirer les ovaires d'une porteuse de BRCA1 ?", "clinical_advice"),
    ("Une ablation préventive des seins est-elle utile ?", "clinical_advice"),
    ("Ce variant de BRCA1 est-il rare ?", "frequency"),
    ("La mutation drépanocytaire est-elle courante en Afrique de l'Ouest ?", "frequency"),
    ("Ce variant est-il répandu au Sénégal ?", "frequency"),
    ("Quel pourcentage des Africains porte l'allèle S ?", "frequency"),
    ("Quelle est la MAF de rs334 ?", "frequency"),
    ("Quelle est l'incidence du cancer du sein héréditaire ?", "frequency"),
    ("Combien de porteurs de rs334 y a-t-il en Afrique ?", "frequency"),
    ("Fais le décompte des variants pathogènes de BRCA2.", "counting"),
    ("Présente l'ensemble des variants de HBB.", "counting"),
    ("Donne l'ensemble des mutations de PALB2.", "counting"),
    ("Dresse un inventaire des variants de CHEK2.", "counting"),
    ("Liste les variants bénins de TP53.", "counting"),
    ("Cite toutes les variantes de HBB.", "counting"),
    ("Cite tous les variants probablement pathogènes de ATM.", "counting"),
    ("Quelle quantité de variants pathogènes compte RAD51C ?", "counting"),
    ("Que dit l'American College of Medical Genetics sur c.5266dup ?", "acmg"),
    ("Applique la grille de classification à rs80357906.", "acmg"),
])
def test_widened_out_of_scope_rules(question, reason):
    assert detect_out_of_scope(question) == reason


@pytest.mark.parametrize("question", [
    "Quel est le nombre de soumissionnaires pour rs80357906 ?",
    "Comment ce variant est-il classé selon les laboratoires ?",
    "Le variant c.5266dup est-il classé pathogène selon les soumissionnaires ?",
    "Que signifie ce variant pour le risque de cancer du sein ?",
    "Quels variants de PTEN sont observés chez des enfants ?",
    "Variants de RAD51D associés aux tumeurs héréditaires de l'ovaire",
    "Qu'indique ClinVar sur rs334 ?",
    "Ce variant est non listé comme pathogène ?",
])
def test_widened_rules_spare_ordinary_questions(question):
    assert detect_out_of_scope(question) is None


# --- affinages : contexte personnel exigé pour les verbes ambigus ---

@pytest.mark.parametrize("question", [
    "Ce variant peut-il causer une anémie ?",
    "Ce variant de BRCA2 peut-il être associé au cancer de l'ovaire ?",
    "Ces variants peuvent-ils provoquer une drépanocytose ?",
    "Ce variant peut-il entraîner une perte de fonction ?",
    "Ce variant est-il indiqué comme pathogène par ClinVar ?",
    "Quelles conditions associées sont indiquées ?",
    "Une ablation de l'exon 11 de BRCA1 est-elle décrite dans ClinVar ?",
    "Êtes-vous au courant d'un variant de PALB2 dans ClinVar ?",
    "Quels variants causent une maladie rare ?",
])
def test_ambiguous_words_without_personal_context_are_not_detected(question):
    assert detect_out_of_scope(question) is None


@pytest.mark.parametrize("question,reason", [
    ("Ma patiente peut-elle avoir des enfants ?", "clinical_advice"),
    ("Puis-je transmettre ce variant ?", "clinical_advice"),
    ("Un traitement est-il indiqué pour ma sœur ?", "clinical_advice"),
    ("Un test est-il indiqué pour mon père ?", "clinical_advice"),
    ("Le variant est-il rare dans la population ?", "frequency"),
    ("Faut-il une ablation des ovaires ?", "clinical_advice"),
    ("Une ablation du sein est-elle utile ?", "clinical_advice"),
    ("Mon frère peut-il donner son sang ?", "clinical_advice"),
])
def test_ambiguous_words_with_personal_context_are_detected(question, reason):
    assert detect_out_of_scope(question) == reason
