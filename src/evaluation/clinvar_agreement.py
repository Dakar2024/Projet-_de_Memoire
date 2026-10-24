"""Comparaison d'un variant du Silver avec son résumé `esummary` ClinVar (niveau 7b d'E3b).

Fonctions pures, sans réseau ni lac : `scripts/verifier_justesse.py` fournit les deux côtés.
Les six comparaisons et la règle du piège 1 sont celles de `reference/evaluation.md` § 8.1 et 8.3.
"""
from __future__ import annotations

import datetime as dt
import enum
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

# Sentinelles « non renseigné » : `-` dans le fichier ClinVar, une date à l'an 1 dans l'API.
_MISSING_DATES = {"", "-", "1/01/01 00:00"}
_DATE_FORMATS = ("%b %d, %Y", "%Y/%m/%d %H:%M")
# Libellés « sans maladie », exclus des deux côtés comme dans `bronze_to_silver`.
_PLACEHOLDER_DISEASES = {"not provided", "not specified"}
# Seuls ces champs peuvent changer légitimement après notre archive (piège 1).
_UPDATABLE_FIELDS = {"significance", "review_status"}


class Verdict(enum.Enum):
    AGREES = "conforme"
    LATER_UPDATE = "mise_a_jour"
    MISMATCH = "ecart"
    MISSING = "absente"


def parse_date(text: str | None) -> dt.date | None:
    """Lit une date du Silver (`Jul 14, 2026`) ou de l'API (`2026/07/14 00:00`) ; `None` si absente."""
    if text is None or text.strip() in _MISSING_DATES:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"date ClinVar illisible : {text!r}")


def _text(value: str) -> str:
    """Valeur textuelle comparée : le `-` du fichier vaut la chaîne vide de l'API (piège 3)."""
    return "" if value.strip() == "-" else value


def _real_diseases(names: frozenset[str]) -> frozenset[str]:
    return frozenset(name for name in names if name.lower() not in _PLACEHOLDER_DISEASES)


def parse_rcv_conditions(vcv_xml: str) -> dict[str, frozenset[str]]:
    """Lit les maladies des RCV de chaque variation dans un XML VCV (`efetch`, `rettype=vcv`).

    C'est le périmètre de `PhenotypeList` du fichier, qui liste les maladies RCV par RCV ; le
    `trait_set` de l'esummary ne garde que celles de la classification germinale agrégée.
    """
    return {
        archive.get("VariationID"): _real_diseases(
            frozenset(
                condition.text.strip()
                for rcv in archive.iter("RCVAccession")
                for condition in rcv.iter("ClassifiedCondition")
                if condition.text
            )
        )
        for archive in ET.fromstring(vcv_xml).iter("VariationArchive")
    }


@dataclass(frozen=True)
class SilverVariant:
    """Les six valeurs comparées d'un variant courant du Silver, maladies issues de `clinvar_variant_disease`."""

    variation_id: str
    name: str
    significance: str
    review_status: str
    last_evaluated: str
    # `-1` : pas d'identifiant dbSNP (piège 3).
    rs_dbsnp: int
    diseases: frozenset[str]


@dataclass(frozen=True)
class ClinvarSummary:
    """Les mêmes valeurs, lues dans un résumé `esummary` (`db=clinvar`), maladies issues des RCV."""

    variation_id: str
    title: str
    significance: str
    review_status: str
    last_evaluated: dt.date | None
    # Un haplotype porte plusieurs allèles, donc parfois plusieurs dbSNP.
    rs_dbsnp: frozenset[int]
    diseases: frozenset[str]

    @classmethod
    def from_esummary(cls, record: dict, rcv_diseases: frozenset[str]) -> ClinvarSummary | None:
        """Construit le résumé ; `None` si l'API n'a pas de fiche pour cet identifiant."""
        if record.get("error"):
            return None
        germline = record["germline_classification"]
        return cls(
            variation_id=record["uid"],
            title=record["title"],
            significance=germline["description"],
            review_status=germline["review_status"],
            last_evaluated=parse_date(germline["last_evaluated"]),
            rs_dbsnp=frozenset(
                int(xref["db_id"])
                for allele in record["variation_set"]
                for xref in allele["variation_xrefs"]
                if xref["db_source"] == "dbSNP"
            ),
            diseases=rcv_diseases,
        )


@dataclass(frozen=True)
class FieldCheck:
    field: str
    ours: str
    theirs: str
    ok: bool


@dataclass(frozen=True)
class Comparison:
    variation_id: str
    verdict: Verdict
    checks: tuple[FieldCheck, ...]


def _check_dates(ours: dt.date | None, theirs: dt.date | None) -> tuple[bool, bool]:
    """Renvoie (date acceptable, date de l'API postérieure) ; une date de l'API antérieure est un écart."""
    if theirs is None:
        return ours is None, False
    if ours is None:
        return True, True
    return theirs >= ours, theirs > ours


def compare(ours: SilverVariant, theirs: ClinvarSummary | None) -> Comparison:
    """Confronte les six champs et classe le variant (piège 1 : seuls signification et statut sont excusés)."""
    if theirs is None:
        return Comparison(ours.variation_id, Verdict.MISSING, ())
    our_date = parse_date(ours.last_evaluated)
    date_ok, api_later = _check_dates(our_date, theirs.last_evaluated)
    our_diseases = _real_diseases(ours.diseases)
    dbsnp_ok = (
        not theirs.rs_dbsnp if ours.rs_dbsnp == -1 else ours.rs_dbsnp in theirs.rs_dbsnp
    )
    checks = (
        FieldCheck("name", ours.name, theirs.title, ours.name == theirs.title),
        FieldCheck(
            "significance", ours.significance, theirs.significance,
            _text(ours.significance) == _text(theirs.significance),
        ),
        FieldCheck(
            "review_status", ours.review_status, theirs.review_status,
            _text(ours.review_status) == _text(theirs.review_status),
        ),
        FieldCheck(
            "last_evaluated", str(our_date or "-"), str(theirs.last_evaluated or "-"), date_ok
        ),
        FieldCheck(
            "rs_dbsnp", str(ours.rs_dbsnp), "|".join(map(str, sorted(theirs.rs_dbsnp))) or "-",
            dbsnp_ok,
        ),
        FieldCheck(
            "diseases",
            "|".join(sorted(our_diseases - theirs.diseases)),
            "|".join(sorted(theirs.diseases)),
            our_diseases <= theirs.diseases,
        ),
    )
    failed = {check.field for check in checks if not check.ok}
    if not failed:
        verdict = Verdict.AGREES
    elif api_later and failed <= _UPDATABLE_FIELDS:
        verdict = Verdict.LATER_UPDATE
    else:
        verdict = Verdict.MISMATCH
    return Comparison(ours.variation_id, verdict, checks)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de score de Wilson d'une proportion (95 % par défaut)."""
    if n <= 0:
        raise ValueError("intervalle de Wilson sur un échantillon vide")
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)
