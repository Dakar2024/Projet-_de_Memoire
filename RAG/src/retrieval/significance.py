"""Traduction déterministe de la signification choisie par le LLM (cinq valeurs) en libellés ClinVar."""
from __future__ import annotations

from collections.abc import Iterable

SIGNIFICANCE_VALUES: tuple[str, ...] = ("pathogenic", "benign", "uncertain", "conflicting", "none")

_EXACT = {
    "pathogenic": ("Pathogenic", "Likely pathogenic", "Pathogenic/Likely pathogenic"),
    "benign": ("Benign", "Likely benign", "Benign/Likely benign"),
    "uncertain": ("Uncertain significance",),
    "conflicting": ("Conflicting classifications of pathogenicity",),
}


def clinvar_labels(value: str, known_labels: Iterable[str]) -> tuple[str, ...]:
    """Renvoie les libellés ClinVar présents dans l'index pour `value` ; vide pour `none`."""
    if value not in SIGNIFICANCE_VALUES:
        raise ValueError(f"signification inconnue : {value!r}")
    if value == "none":
        return ()
    known = set(known_labels)
    labels = [label for label in _EXACT[value] if label in known]
    if value == "pathogenic":
        labels += sorted(label for label in known if label.startswith("Pathogenic") and label not in labels)
    return tuple(labels)
