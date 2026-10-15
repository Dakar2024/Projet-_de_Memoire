"""Extraction déterministe (sans LLM) des identifiants de variants et des gènes, normalisés comme dans ClinVar."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ingestion.config import ALL_GENES

_PANEL = {gene.upper(): gene for gene in ALL_GENES}

_AA3 = {
    "A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu",
    "G": "Gly", "H": "His", "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe",
    "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp", "Y": "Tyr", "V": "Val", "*": "Ter", "X": "Ter",
}

_END = r"(?=[\s,;:.?!)/]|$)"
_RS = re.compile(r"\brs\s?(\d{1,10})\b", re.IGNORECASE)
# Préfixe de transcrit facultatif, son gène capturé (groupe 1) pour ne pas être perdu.
_HGVS_C = re.compile(
    r"(?:N[MRG]_\d+(?:\.\d+)?(?:\(([A-Za-z0-9-]+)\))?:)?"
    r"(c\.[0-9_+\-*]+(?:[ACGT]>[ACGT]|delins[ACGT]+|del[ACGT]*|dup[ACGT]*|ins[ACGT]+))" + _END,
    re.IGNORECASE,
)
_HGVS_P3 = re.compile(r"\bp\.\(?([A-Z][a-z]{2}\d+(?:[A-Z][a-z]{2}(?:fs[\w*]*|\w*)|fs[\w*]*|=|\*|X))\)?" + _END)
_HGVS_P1 = re.compile(r"\bp\.\(?([ARNDCQEGHILKMFPSTWYV])(\d+)([ARNDCQEGHILKMFPSTWYV*X])\)?" + _END)
_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z0-9]{1,9}\b")
_AFTER_GENE_WORD = re.compile(r"\b[gG][eèEÈ]nes?\s+([A-Za-z][A-Za-z0-9]{1,9})\b")
_GENE_LIKE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


@dataclass(frozen=True)
class Identifiers:
    """Identifiants et gènes extraits d'une question."""

    rs: tuple[int, ...]
    hgvs_c: tuple[str, ...]
    hgvs_p: tuple[str, ...]
    genes: tuple[str, ...]
    out_of_panel: tuple[str, ...]

    @property
    def has_variant_identifier(self) -> bool:
        """Indique si la question cite au moins un identifiant de variant."""
        return bool(self.rs or self.hgvs_c or self.hgvs_p)

    def as_dict(self) -> dict[str, list]:
        """Sérialise les identifiants pour la trace."""
        return {
            "rs": list(self.rs), "hgvs_c": list(self.hgvs_c), "hgvs_p": list(self.hgvs_p),
            "genes": list(self.genes), "out_of_panel": list(self.out_of_panel),
        }


def _unique(values) -> tuple:
    """Dédoublonne en gardant l'ordre."""
    return tuple(dict.fromkeys(values))


def _normalize_c(raw: str) -> str:
    """Normalise un HGVS codant comme ClinVar (séquence retirée après del/dup)."""
    position, change = re.match(r"(c\.[0-9_+\-*]+)(.*)", "c." + raw[2:], re.IGNORECASE).groups()
    upper = change.upper()
    if upper.startswith("DELINS"):
        return f"{position}delins{upper[6:]}"
    if upper.startswith("DEL"):
        return f"{position}del"
    if upper.startswith("DUP"):
        return f"{position}dup"
    if upper.startswith("INS"):
        return f"{position}ins{upper[3:]}"
    return f"{position}{upper}"


def _normalize_p3(raw: str) -> str:
    """Normalise un HGVS protéique comme ClinVar (p.Glu23ValfsTer17 → p.Glu23fs, * → Ter)."""
    raw = re.sub(r"(?:[A-Z][a-z]{2})?fs[\w*]*$", "fs", raw)
    return "p." + re.sub(r"(\d+)(?:\*|X)$", r"\1Ter", raw)


def extract_identifiers(question: str) -> Identifiers:
    """Extrait rs, HGVS, gènes du panel et symboles hors panel d'une question."""
    rs = _unique(int(match) for match in _RS.findall(question))
    coding = list(_HGVS_C.finditer(question))
    hgvs_c = _unique(_normalize_c(match.group(2)) for match in coding)
    hgvs_p = _unique(
        [_normalize_p3(match) for match in _HGVS_P3.findall(question)]
        + [f"p.{_AA3[a]}{pos}{_AA3[b]}" for a, pos, b in _HGVS_P1.findall(question)]
    )
    # Identifiants masqués par des espaces (positions gardées) pour que « R1443 » ne passe pas pour un gène.
    rest = question
    for pattern in (_RS, _HGVS_C, _HGVS_P3, _HGVS_P1):
        rest = pattern.sub(lambda match: " " * len(match.group()), rest)
    tokens = sorted([(match.start(), match.group()) for match in _TOKEN.finditer(rest)]
                    + [(match.start(1), match.group(1)) for match in coding if match.group(1)])
    genes = _unique(_PANEL[token.upper()] for _, token in tokens if token.upper() in _PANEL)
    # Hors panel : majuscules avec chiffre (MLH1), majuscules après « gène » (APC), ou gène d'un transcrit.
    suspects = [token for token in _TOKEN.findall(rest)
                if _GENE_LIKE.match(token) and any(ch.isdigit() for ch in token)]
    suspects += [token for token in _AFTER_GENE_WORD.findall(rest) if _GENE_LIKE.match(token)]
    suspects += [match.group(1) for match in coding if match.group(1)]
    out_of_panel = _unique(token for token in suspects if token.upper() not in _PANEL)
    return Identifiers(rs=rs, hgvs_c=hgvs_c, hgvs_p=hgvs_p, genes=genes, out_of_panel=out_of_panel)


def variant_spans(text: str) -> list[tuple[int, int, str]]:
    """Renvoie (début, fin, forme normalisée) de chaque identifiant de variant du texte, dans l'ordre."""
    spans = [(m.start(), m.end(), f"rs{int(m.group(1))}") for m in _RS.finditer(text)]
    spans += [(m.start(), m.end(), _normalize_c(m.group(2))) for m in _HGVS_C.finditer(text)]
    spans += [(m.start(), m.end(), _normalize_p3(m.group(1))) for m in _HGVS_P3.finditer(text)]
    spans += [(m.start(), m.end(), f"p.{_AA3[m.group(1)]}{m.group(2)}{_AA3[m.group(3)]}")
              for m in _HGVS_P1.finditer(text)]
    return sorted(spans)
