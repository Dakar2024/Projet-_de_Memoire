"""Textes fixes de la réponse (E2b), écrits par nous et non par le LLM : messages hors
périmètre, absence de document, réponse non vérifiable, avertissement, et traduction
des significations ClinVar. Une traduction médicale n'est jamais improvisée."""

from __future__ import annotations

import re

SIGNIFICANCE_FR: dict[str, str] = {
    "Pathogenic": "pathogène",
    "Likely pathogenic": "probablement pathogène",
    "Benign": "bénin",
    "Likely benign": "probablement bénin",
    "Uncertain significance": "signification incertaine",
    "Conflicting classifications of pathogenicity": "interprétations contradictoires",
    "other": "autre",
    "not provided": "non renseignée",
    "risk factor": "facteur de risque",
    "low penetrance": "faible pénétrance",
}

_SPLIT = re.compile(r"(/|; |, )")


def translate_significance(label: str | None) -> str | None:
    """Traduit terme à terme un libellé ClinVar, y compris composite (« Pathogenic/Likely
    pathogenic », « Pathogenic; other ») ; un terme inconnu est gardé tel quel."""
    if label is None:
        return None
    parts = _SPLIT.split(label)
    out = []
    for part in parts:
        if part == "/":
            out.append(" / ")
        elif part in ("; ", ", "):
            out.append(" ; " if part == "; " else ", ")
        else:
            out.append(SIGNIFICANCE_FR.get(part.strip(), part.strip()))
    return "".join(out)


def significance_terms_fr() -> tuple[str, ...]:
    """Termes français de signification, du plus long au plus court (pour la recherche
    dans une réponse : « probablement pathogène » avant « pathogène »)."""
    main = [SIGNIFICANCE_FR[k] for k in ("Pathogenic", "Likely pathogenic", "Benign", "Likely benign",
                                         "Uncertain significance",
                                         "Conflicting classifications of pathogenicity")]
    return tuple(sorted(main, key=len, reverse=True))


def disclaimer(archive: str | None) -> str:
    label = f"archive {archive}" if archive else "archive inconnue"
    return (f"Aide à la consultation de ClinVar ({label}) ; ne remplace pas l'interprétation "
            "clinique d'un biologiste.")


OUT_OF_SCOPE: dict[str, str] = {
    "counting": ("Cet outil retrouve les fiches ClinVar les plus pertinentes pour une question ; "
                 "il ne compte pas les variants et ne dresse pas de liste exhaustive. Un comptage "
                 "relève d'une analyse dédiée de ClinVar."),
    "acmg": ("Cet outil ne classe pas les variants selon les critères ACMG : il restitue la "
             "classification déposée dans ClinVar. La classification reste l'acte du biologiste."),
    "frequency": ("Les fréquences en population (gnomAD, cohortes africaines) ne font pas partie "
                  "des sources de cet outil, qui s'appuie sur ClinVar, MedGen, HPO et NCBI Gene."),
    "clinical_advice": ("Cet outil ne donne pas de conseil de prise en charge ni d'interprétation "
                        "clinique : il restitue ce que ClinVar documente."),
    "other": "Cette question sort du périmètre de l'outil, limité aux données ClinVar du panel de 18 gènes.",
    "gene_out_of_panel": ("Ce gène ne fait pas partie du panel de l'outil (12 gènes du cancer du sein "
                          "héréditaire, 6 gènes de la drépanocytose et des modificateurs de l'hémoglobine "
                          "fœtale) : aucune fiche n'est disponible."),
}

NO_DOCUMENT = "Aucune fiche ClinVar du panel ne correspond à cette question."
UNVERIFIABLE = ("La réponse générée n'a pas pu être vérifiée contre les fiches ClinVar retrouvées ; "
                "elle n'est pas affichée. Consultez directement les sources ci-dessous.")


def identifiers_not_found(identifiers: list[str]) -> str:
    listed = ", ".join(identifiers)
    return (f"Aucune fiche ClinVar du panel ne correspond à : {listed}. Vérifiez l'identifiant "
            "(les noms historiques comme « 5382insC » ou « Glu6Val » ne sont pas reconnus).")


def history_sentence(doc_id: str, previous_fr: str, until: str) -> str:
    """Phrase d'historique écrite par le code, jamais par le LLM, pour une source citée."""
    return (f"Historique ClinVar ({doc_id}) : classé « {previous_fr} » jusqu'au {until}, "
            "avant la classification actuelle.")
