"""Extraction déterministe des identifiants de variants et des gènes d'une question.

Aucun LLM ici : un identifiant recopié avec un chiffre faux trouverait le mauvais
variant, sans erreur visible. Les formes sont normalisées comme ClinVar les stocke
dans l'index (vérifié le 04/10/2026) : HGVS sans transcrit, séquence retirée après
`del`/`dup`, protéine en code à trois lettres. Les noms historiques (« 5382insC »,
« Glu6Val ») ne sont pas traduits : une table de correspondance serait une source
d'erreurs médicales à maintenir.
"""

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
# Le préfixe de transcrit est facultatif ; le gène qu'il cite entre parenthèses est
# capturé (groupe 1) pour ne pas être perdu avec l'identifiant. Côté protéine, aucun
# préfixe n'est accepté : il reste dans le texte, et son gène avec.
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
    rs: tuple[int, ...]
    hgvs_c: tuple[str, ...]
    hgvs_p: tuple[str, ...]
    genes: tuple[str, ...]
    out_of_panel: tuple[str, ...]

    @property
    def has_variant_identifier(self) -> bool:
        return bool(self.rs or self.hgvs_c or self.hgvs_p)

    def as_dict(self) -> dict[str, list]:
        return {
            "rs": list(self.rs), "hgvs_c": list(self.hgvs_c), "hgvs_p": list(self.hgvs_p),
            "genes": list(self.genes), "out_of_panel": list(self.out_of_panel),
        }


def _unique(values) -> tuple:
    return tuple(dict.fromkeys(values))


def _normalize_c(raw: str) -> str:
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
    # ClinVar stocke un décalage du cadre de lecture tronqué après « fs », sans l'acide
    # aminé substitué : p.Glu23ValfsTer17 devient p.Glu23fs.
    raw = re.sub(r"(?:[A-Z][a-z]{2})?fs[\w*]*$", "fs", raw)
    return "p." + re.sub(r"(\d+)(?:\*|X)$", r"\1Ter", raw)


def extract_identifiers(question: str) -> Identifiers:
    rs = _unique(int(match) for match in _RS.findall(question))
    coding = list(_HGVS_C.finditer(question))
    hgvs_c = _unique(_normalize_c(match.group(2)) for match in coding)
    hgvs_p = _unique(
        [_normalize_p3(match) for match in _HGVS_P3.findall(question)]
        + [f"p.{_AA3[a]}{pos}{_AA3[b]}" for a, pos, b in _HGVS_P1.findall(question)]
    )
    # Les gènes se cherchent dans la question privée de ses identifiants : sinon
    # « R1443 » (p.R1443*) ou « RS334 » passeraient pour des symboles de gènes. Les
    # identifiants sont remplacés par autant d'espaces, pour garder les positions et donc
    # l'ordre d'apparition des gènes, préfixes de transcrit compris.
    rest = question
    for pattern in (_RS, _HGVS_C, _HGVS_P3, _HGVS_P1):
        rest = pattern.sub(lambda match: " " * len(match.group()), rest)
    tokens = sorted([(match.start(), match.group()) for match in _TOKEN.finditer(rest)]
                    + [(match.start(1), match.group(1)) for match in coding if match.group(1)])
    genes = _unique(_PANEL[token.upper()] for _, token in tokens if token.upper() in _PANEL)
    # Hors panel : un symbole en majuscules avec un chiffre (MLH1), ou en majuscules
    # juste après « gène » (APC), ou tout symbole cité dans un préfixe de transcrit
    # (NM_000249.4(MLH1):). Un mot en minuscules n'est jamais un gène.
    suspects = [token for token in _TOKEN.findall(rest)
                if _GENE_LIKE.match(token) and any(ch.isdigit() for ch in token)]
    suspects += [token for token in _AFTER_GENE_WORD.findall(rest) if _GENE_LIKE.match(token)]
    suspects += [match.group(1) for match in coding if match.group(1)]
    out_of_panel = _unique(token for token in suspects if token.upper() not in _PANEL)
    return Identifiers(rs=rs, hgvs_c=hgvs_c, hgvs_p=hgvs_p, genes=genes, out_of_panel=out_of_panel)
