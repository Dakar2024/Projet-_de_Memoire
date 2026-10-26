"""Contrôles déterministes de la réponse : citations, identifiants, significations actuelles."""
from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from RAG.src.generation.messages import SIGNIFICANCE_FR, significance_terms_fr, translate_significance
from RAG.src.retrieval.identifiers import extract_identifiers, variant_spans
from RAG.src.retrieval.retriever import RetrievedDocument
from RAG.src.utils.errors import GenerationRejectedError

# Variation ID ClinVar sous ses formes écrites, hors année, date ou effectif après « ClinVar ».
_VARIATION_ID = re.compile(
    r"(?:Variation(?:\s+ID)?|ClinVar(?:\s+(?:ID|n°|no\.?|#)|(?!\s*[:#°]?\s*(?:19|20)\d\d\b))|VCV0*|/variation/)"
    r"\s*[:#°]?\s*(\d{2,9})\b(?!-\d)(?!\s*(?:soumett|laborat|submitter|centre))",
    re.IGNORECASE,
)
_LABELS = sorted(SIGNIFICANCE_FR, key=len, reverse=True)
_TYPOGRAPHY = str.maketrans({c: " " for c in "«»’‘“”…\u00a0\u202f"})
# Tirets Unicode ramenés à « - » : « c.68‑2A>G » (trait d'union insécable) reste un HGVS contrôlé.
_DASHES = str.maketrans({c: "-" for c in
                         "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2e3a\u2e3b\u02d7\u2796\ufe58"})
_PANEL_STATUSES = ("answered", "partial")


def _clean(answer: str) -> str:
    """Rend la réponse comparable : entités HTML décodées, NFKC, caractères de format retirés, tirets unifiés."""
    text = unicodedata.normalize("NFKC", html.unescape(answer))
    return "".join(c for c in text if unicodedata.category(c) != "Cf").translate(_DASHES)


def check_citations(citations: Sequence[str], documents: Sequence[RetrievedDocument], status: str) -> None:
    """Exige des citations parmi les documents transmis, et au moins une pour une réponse."""
    transmitted = {d.doc_id for d in documents}
    unknown = [c for c in citations if c not in transmitted]
    if unknown:
        raise GenerationRejectedError("citation_not_transmitted", unknown)
    if status in ("answered", "partial") and not citations:
        raise GenerationRejectedError("no_citation")


@dataclass(frozen=True)
class _VariantIds:
    """Identifiants de variant normalisés d'un texte ou d'un document (rs, c., p., Variation ID)."""
    rs: frozenset = frozenset()
    c: frozenset = frozenset()
    p: frozenset = frozenset()
    vid: frozenset = frozenset()

    def __or__(self, other: _VariantIds) -> _VariantIds:
        return _VariantIds(self.rs | other.rs, self.c | other.c, self.p | other.p, self.vid | other.vid)

    def __contains__(self, key: str) -> bool:
        return key in self.rs or key in self.c or key in self.p or key in self.vid


# Variantes d'écriture (« dbSNP 80357999 », « rs-12345 », « p.(…) », « c. 5266 dup ») ramenées à la forme extraite.
_VARIANT_FORMS = (
    (re.compile(r"\bdbSNP\s*[:#]?\s*(?:rs\s*)?(\d+)", re.IGNORECASE), r"rs\1"),
    (re.compile(r"\brs\s*-\s*(\d+)", re.IGNORECASE), r"rs\1"),
    (re.compile(r"\bp\.\s*\(([^()\s]+)\)"), r"p.\1"),
    (re.compile(r"\b([cp])\.\s+(?=[\d*+-]|[A-Z][a-z]{2}\d)"), r"\1."),
    (re.compile(r"\b(c\.[0-9_+*-]+)\s+(?=(?:del|dup|ins)|[ACGT]>)", re.IGNORECASE), r"\1"),
)
# HGVS mitochondrial (« m.3243A>G »), contrôlé comme un c.
_MITO = re.compile(r"\bm\.\d+(?:_\d+)?(?:[ACGT]>[ACGT]|del[ACGT]*|dup[ACGT]*|ins[ACGT]+)", re.IGNORECASE)
# Notation de répétition (« c.569CTC[1] ») : crochets conservés.
_REPEAT = re.compile(r"\bc\.[0-9_+*-]+[ACGT]+\[\d+\]", re.IGNORECASE)
# Indels protéiques en phase (« p.Pro191del »), absents de l'extraction de la recherche.
_P_INFRAME = re.compile(
    r"\bp\.\(?([A-Z][a-z]{2}\d+(?:_[A-Z][a-z]{2}\d+)?(?:delins(?:[A-Z][a-z]{2})+|del|dup|ins(?:[A-Z][a-z]{2})+))"
    r"\)?(?![\w*])")


def _local_spans(text: str) -> list[tuple[int, int, str]]:
    """Renvoie (début, fin, forme) des répétitions et indels protéiques en phase."""
    return ([(m.start(), m.end(), "c." + m.group()[2:].upper()) for m in _REPEAT.finditer(text)]
            + [(m.start(), m.end(), "p." + m.group(1)) for m in _P_INFRAME.finditer(text)])


def _normalize_variant_forms(text: str) -> str:
    """Ramène les variantes d'écriture d'identifiants à la forme extraite."""
    for pattern, replacement in _VARIANT_FORMS:
        text = pattern.sub(replacement, text)
    return text


def _text_ids(text: str) -> _VariantIds:
    """Extrait les identifiants de variant d'un texte."""
    text = _normalize_variant_forms(text)
    ids = extract_identifiers(text)
    local = _local_spans(text)
    return _VariantIds(frozenset(f"rs{r}" for r in ids.rs),
                       frozenset(ids.hgvs_c) | frozenset(m.group() for m in _MITO.finditer(text))
                       | frozenset(key for _, _, key in local if key.startswith("c.")),
                       frozenset(ids.hgvs_p) | frozenset(key for _, _, key in local if key.startswith("p.")),
                       frozenset(_VARIATION_ID.findall(text)))


def _doc_ids(d: RetrievedDocument) -> _VariantIds:
    """Renvoie les identifiants d'un document : texte et champs."""
    fields = _VariantIds(frozenset({f"rs{d.rs_dbsnp}"} if d.rs_dbsnp is not None else ()),
                         frozenset({d.hgvs_c} if d.hgvs_c else ()), frozenset({d.hgvs_p} if d.hgvs_p else ()),
                         frozenset({d.clinvar_variation_id} if d.clinvar_variation_id else ()))
    return _text_ids(d.text) | fields


def _docs_ids(documents: Sequence[RetrievedDocument]) -> _VariantIds:
    """Réunit les identifiants de plusieurs documents."""
    out = _VariantIds()
    for d in documents:
        out |= _doc_ids(d)
    return out


def _missing(found: _VariantIds, allowed: _VariantIds) -> list[str]:
    """Liste les identifiants trouvés mais non autorisés."""
    return (sorted(found.rs - allowed.rs, key=lambda r: r[2:]) + sorted(found.c - allowed.c)
            + sorted(found.p - allowed.p) + [f"ClinVar {v}" for v in sorted(found.vid - allowed.vid)])


# Mise en forme (gras, code, guillemets, balises) remplacée par des espaces, positions inchangées, signes HGVS gardés.
_MARKUP_KEEP = set(".,;:?!()/+-*>=%#°'’_")
_MARKUP_STARS = re.compile(r"\*{2,}|_{2,}")
_ITALIC_OPEN = re.compile(r"(?<![\w.*])[*_](?=\S)")
_ITALIC_CLOSE = re.compile(r"(?<=[A-Za-zÀ-ÿ>)\]])[*_](?![\w*])")
# Apostrophe ASCII hors d'un mot : guillemet simple.
_QUOTE = re.compile(r"(?<![A-Za-zÀ-ÿ])'|'(?![A-Za-zÀ-ÿ])")


def _blank(match: re.Match) -> str:
    """Remplace une correspondance par autant d'espaces."""
    return " " * len(match.group())


def _stars(match: re.Match) -> str:
    """Efface un gras ou italique en gardant l'étoile d'un « p.Arg337* »."""
    run = match.group()
    before = match.string[match.start() - 1] if match.start() else ""
    if run[0] == "*" and before.isdigit() and len(run) % 2:
        return "*" + " " * (len(run) - 1)
    return " " * len(run)


def _unmark(text: str, *, quotes: bool = True) -> str:
    """Ramène la mise en forme à des espaces, longueur inchangée ; `quotes` traite aussi l'apostrophe hors mot."""
    protected = {i for m in _REPEAT.finditer(text) for i in range(m.start(), m.end())}
    chars = [c if (c.isalnum() or c.isspace() or c in _MARKUP_KEEP or i in protected) else " "
             for i, c in enumerate(text)]
    text = "".join(chars)
    text = _MARKUP_STARS.sub(_stars, text)
    text = _ITALIC_OPEN.sub(_blank, text)
    text = _ITALIC_CLOSE.sub(_blank, text)
    return _QUOTE.sub(_blank, text) if quotes else text


def _answer_text(answer: str) -> str:
    """Prépare la réponse à l'extraction : nettoyée, typographie et mise en forme ramenées à des espaces."""
    return _unmark(_clean(answer).translate(_TYPOGRAPHY))


def check_identifiers(answer: str, documents: Sequence[RetrievedDocument], status: str = "answered") -> None:
    """Exige que tout identifiant de la réponse (rs, HGVS, ClinVar, gène) figure dans les documents transmis."""
    answer = _answer_text(answer)
    found = extract_identifiers(answer)
    offending = _missing(_text_ids(answer), _docs_ids(documents))
    if offending:
        raise GenerationRejectedError("identifier_not_in_sources", offending)
    if status in _PANEL_STATUSES:
        # Gènes autorisés : ceux des documents et ceux cités dans leurs textes.
        allowed_genes = {d.gene_symbol for d in documents if d.gene_symbol}
        for d in documents:
            ids = extract_identifiers(d.text)
            allowed_genes |= set(ids.genes) | set(ids.out_of_panel)
        unknown_genes = (set(found.genes) | set(found.out_of_panel)) - allowed_genes
        if unknown_genes:
            raise GenerationRejectedError("identifier_not_in_sources", [f"gène {g}" for g in sorted(unknown_genes)])


def check_identifiers_cited(answer: str, cited: Sequence[RetrievedDocument]) -> None:
    """Exige que tout identifiant de variant de la réponse appartienne à un document cité."""
    offending = _missing(_text_ids(_answer_text(answer)), _docs_ids(cited))
    if offending:
        raise GenerationRejectedError("identifier_not_cited", offending)


# Étiquette D_k en référence : entre parenthèses, après un mot de renvoi, ou en tête de phrase (« cycline D1 » exclue).
_LABEL = r"D\s?\d+"
_LABEL_LIST = rf"{_LABEL}(?:\s*(?:[,;]|et|ou|and)\s*{_LABEL})*"
# Mot de renvoi facultatif dans une parenthèse : « (voir D2) », « (cf. D3) », « (selon D4) ».
_PAREN_LEAD = (r"(?:(?:voir|cf\.?|selon)(?:\s+par\s+ex(?:emple|\.)?)?\s+"
               r"|(?:documents?|sources?|fiches?)\s*:?\s*)?")
_LABEL_REFERENCE = re.compile(
    rf"[(\[]\s*{_PAREN_LEAD}(?P<paren>{_LABEL_LIST})\s*[)\]]"
    rf"|(?<![\w-])(?:documents?|sources?|fiches?|voir|selon|cf\.?)\s+(?P<keyword>{_LABEL_LIST})(?![\w-])"
    rf"|(?:^|[.!?]\s+)(?P<head>{_LABEL})\s*:",
    re.IGNORECASE | re.MULTILINE)


# Référence en incise dont toutes les étiquettes sont citées : retirable sans tronquer la phrase.
_PAREN_REFERENCE = re.compile(rf"[ \t]*[(\[]\s*{_PAREN_LEAD}(?P<labels>{_LABEL_LIST})\s*[)\]]", re.IGNORECASE)


def _label_set(text: str) -> set[str]:
    """Renvoie les étiquettes D_k d'un texte, normalisées."""
    return {re.sub(r"\s", "", m).upper() for m in re.findall(_LABEL, text, re.IGNORECASE)}


def strip_cited_labels(answer: str, citations: Sequence[str]) -> str:
    """Retire les références en incise dont toutes les étiquettes sont citées ; le reste est inchangé."""
    cited = {re.sub(r"\s", "", c).upper() for c in citations}

    def replace(match: re.Match) -> str:
        """Retire la référence si toutes ses étiquettes sont citées."""
        return "" if _label_set(match.group("labels")) <= cited else match.group()

    stripped = _PAREN_REFERENCE.sub(replace, answer)
    # Espaces laissés en fin de ligne par un retrait.
    return stripped if stripped == answer else re.sub(r"[ \t]+$", "", stripped, flags=re.MULTILINE)


def check_document_labels(answer: str, documents: Sequence[RetrievedDocument]) -> None:
    """Rejette une étiquette D_k restée en référence dans le texte (la retirer pourrait tronquer la phrase)."""
    labels = {f"D{index}" for index in range(1, len(documents) + 1)}
    if not labels:
        return
    found: set[str] = set()
    for match in _LABEL_REFERENCE.finditer(_clean(answer)):
        group = match.group("paren") or match.group("keyword") or match.group("head")
        found |= {re.sub(r"\s", "", m).upper() for m in re.findall(_LABEL, group, re.IGNORECASE)}
    offending = sorted(found & labels)
    if offending:
        raise GenerationRejectedError("document_label_in_text", offending)


def _spaced(text: str) -> str:
    """Construit le motif d'une expression, espaces multiples tolérés."""
    return r"\s+".join(re.escape(word) for word in text.split())


def _french_pattern(term: str) -> str:
    """Construit le motif d'un terme français, accords féminin et pluriel compris."""
    for key, pattern in _FEMININE_PLURAL.items():
        if term.endswith(key):
            prefix = term[: -len(key)].strip()
            lead = _spaced(prefix) + r"\s+" if prefix else ""
            return rf"\b{lead}(?:{pattern})\b"
    return rf"\b{_spaced(term)}\b"


_FEMININE_PLURAL = {"bénin": r"b[ée]nin(?:e|s|es)?|b[ée]nigne(?:s)?",
                    "pathogène": r"pathog[èe]ne(?:s)?",
                    "signification incertaine": r"signification(?:s)?\s+(?:\S+\s+){0,2}?incertaine(?:s)?",
                    "interprétations contradictoires":
                        r"interpr[ée]tation(?:s)?\s+(?:\S+\s+){0,3}?contradictoire(?:s)?"}


def _build_terms() -> list[tuple[str, re.Pattern]]:
    """Construit les motifs de signification (français et anglais), du plus long au plus court."""
    entries: list[tuple[int, str, str]] = []
    for term in significance_terms_fr():
        entries.append((len(term), term, _french_pattern(term)))
    for label, fr in SIGNIFICANCE_FR.items():
        if label in ("other", "not provided"):
            continue
        english = r"[\s_-]+".join(re.escape(word) for word in label.split())
        entries.append((len(label), fr, rf"\b{english}\b"))
    entries.append((len("facteur de risque"), "facteur de risque", r"\bfacteurs?\s+de\s+risque\b"))
    entries.append((len("faible pénétrance"), "faible pénétrance", r"\bfaible\s+p[ée]n[ée]trance\b"))
    entries.sort(key=lambda e: e[0], reverse=True)
    return [(fr, re.compile(pat, re.IGNORECASE)) for _, fr, pat in entries]


_TERMS = _build_terms()
# Qualificatifs hors table : rejetés d'office, qu'ils figurent ou non dans les documents.
_OFF_TABLE = re.compile(
    r"\bVUS\b|\bd[ée]l[ée]t[èe]res?\b|\bneutres?\b|\bind[ée]termin[ée]e?s?\b|"
    r"\bsignification\s+inconnue\b|\bpathog[ée]niques?\b|\bvraisemblablement\b|\bà\s+risque\b|"
    r"\binoffensi\w*|\banodin\w*|\bsans\s+(?:danger|risque|cons[ée]quence)\w*|\bb[ée]n[ée]fique\w*|"
    # Classes ACMG chiffrées (« classe 5 », « classé en classe 3 », « classe ACMG 4 »).
    r"\bclasse\s+(?:ACMG\s+)?[1-5]\b"
    # « classé 5 / V », « de classe V » (« classe I » reste, vocabulaire de biologie).
    r"|\bclass(?:é|ee)e?s?\s+(?:en\s+)?(?:classe\s+)?(?:[1-5]|IV|V|I{1,3})\b|\bclasse\s+(?:IV|V)\b",
    re.IGNORECASE,
)
# Abréviations P, LP, B, LB (lettre seule après un verbe de classement ou entre parenthèses).
_ABBREVIATIONS = re.compile(
    r"(?<![\w./-])(?:P/LP|LP/P|B/LB|LB/B|LP|LB)(?![\w/-])"
    r"|(?:\b(?:class[ée]e?s?|cat[ée]goris[ée]e?s?|est|sont)|:)\s+(?:en\s+|comme\s+)?[PB](?![\w/-]|\.\w)"
    r"|\(\s*[PB]\s*\)"
    # « classé b » en minuscule.
    r"|(?i:\bclass[ée]e?s?\s+(?:en\s+|comme\s+)?[pb])(?![\w/-]|\.\w)"
)
_NEGATIONS = {"pas", "non", "ni", "jamais", "plus", "aucun", "aucune"}
# Négation ou inversion lexicale n'importe où dans une phrase à signification : phrase rejetée (prudent).
_SENTENCE_NEGATION = re.compile(
    r"\b(?:ne|pas|aucune?s?|jamais|rien|sans|ni|non)\b|\bn'"
    r"|\bloin\s+d|\btout\s+sauf\b|\bpeu\s+probable\w*|\bimprobable\w*|\b[ée]cart[ée]\w*"
    r"|\bexclu(?!sivement)\w*|\bà\s+tort\b|\bfaux\b|\bfausse\w*|\bcontrairement\b"
    r"|\br[ée]fut\w*|\binfirm(?!i[eè]r)\w*"
    r"|\berreur\w*|\bcontest\w*|\bdiscutable\w*|\bdouteu\w*|\bremis\w*\s+en\s+cause"
    r"|\bobsol[èe]te\w*|\bancien(?:ne)?s?\b",
    re.IGNORECASE)
# Atténuations et renforcements : une signification ClinVar est affirmée telle quelle.
_SENTENCE_HEDGE = re.compile(
    r"\b(?:potentiellement|possiblement|[ée]ventuellement|hautement|pourrai\w*)\b|\bpeut[- ]être\b"
    r"|\bpr[ée]sum\w*|\bsuppos\w*|\bsuspect\w*|\bsembl\w*|\bserai\w*|\bfaiblement\b"
    r"|\bplut[ôo]t\b|\ba\s+priori\b",
    re.IGNORECASE)
# « pourrait » + verbe de conséquence après tous les termes : ne porte pas sur la signification.
_CONSEQUENCE_COULD = re.compile(
    r"\bpourrai\w*\s+(?:augmenter|accro[îi]tre|favoriser|entra[îi]ner|contribuer|expliquer|pr[ée]disposer)\b",
    re.IGNORECASE)
# Temps passé : raconterait une classification passée, que seul le code restitue.
_SENTENCE_PAST = re.compile(r"\b(?:[ée]tai(?:t|ent)|fut|furent|longtemps)\b", re.IGNORECASE)
# Phrase réduite à une réfutation (« Pathogène ? Non. ») : rejetée si la précédente porte un terme.
_REFUTATION = re.compile(
    r"^\W*(?:(?:absolument|totalement|compl[èe]tement|tout\s+[àa]\s+fait|c['’]est)\s+)?"
    r"(?:non|faux|fausse|inexact\w*|incorrect\w*|erron[ée]\w*|(?:que\s+)?nenni|ou\s+pas)\W*$", re.IGNORECASE)
_SENTENCES = re.compile(r"(?<=[.!?;])\s+")
# Formules fermées dont la négation ne porte jamais sur la signification, masquées avant le test.
_NEUTRAL_PHRASES = re.compile(
    r"\b(?:aucun|sans|pas\s+de)\s+conflits?(?:\s+d['’]\s*interpr[ée]tations?)?\b"
    r"|\baucune?\s+crit[èe]res?\s+(?:d['’]\s*[ée]valuation\s+)?fournie?s?\b"
    r"|\bclinvar\s+ne\s+documente\s+pas\s+de\s+ph[ée]notypes?\s+pour\s+ce\s+variant\b"
    r"|\bnon[- ]sph[ée]rocytaires?\b"
    # « sans mention de syndrome… » précise la condition, jamais la signification.
    r"|\bsans\s+(?:mention|pr[ée]cision)\s+(?:de\s+|d['’]\s*|du\s+|des\s+)"
    r"(?:syndromes?|maladies?|conditions?|ph[ée]notypes?|pathologies?|affections?|sous[- ]types?)\b",
    re.IGNORECASE,
)


# « autres variantes non listées ici », masquée sauf si un terme de signification la suit.
_TRUNCATED_LIST = re.compile(
    r"\bautres\s+variant(?:e)?s?\s+non\s+list[ée]e?s?\s+ici\b(?!\s+(?:comme|en\s+tant))", re.IGNORECASE)


def _mask_truncated_list(sentence: str) -> str:
    """Masque la mention de liste tronquée quand aucune signification ne la suit."""
    for match in reversed(list(_TRUNCATED_LIST.finditer(sentence))):
        tail = sentence[match.end():]
        if any(pattern.search(tail) for _, pattern in _TERMS) or re.search(r"\bincertain", tail, re.IGNORECASE):
            continue
        sentence = sentence[:match.start()] + " " * (match.end() - match.start()) + sentence[match.end():]
    return sentence


def _negated(text: str, start: int) -> bool:
    """Indique une négation parmi les trois mots qui précèdent `start`."""
    words = re.findall(r"[\wéèêàçùô']+", text[:start].lower())[-3:]
    return any(word in _NEGATIONS for word in words)


def _term_spans(sentence: str) -> list[tuple[int, str]]:
    """Renvoie les termes de signification d'une phrase et leur position ; lève sur négation, atténuation ou passé."""
    found: list[tuple[int, str]] = []
    remaining = sentence
    for term, pattern in _TERMS:
        for match in pattern.finditer(remaining):
            if _negated(sentence, match.start()):
                raise GenerationRejectedError(
                    "significance_not_in_sources", [f"négation devant « {match.group()} » : {sentence.strip()}"])
            found.append((match.start(), term))
        remaining = pattern.sub(lambda m: " " * len(m.group()), remaining)
    # « incertain » isolé vaut « signification incertaine ».
    for match in re.finditer(r"\bincertain\w*", remaining, re.IGNORECASE):
        found.append((match.start(), "signification incertaine"))
    negation = _SENTENCE_NEGATION.search(sentence.replace("’", "'")) if found else None
    if negation:
        raise GenerationRejectedError(
            "significance_not_in_sources", [f"négation « {negation.group()} » dans la phrase : {sentence.strip()}"])
    last_term = max((pos for pos, _ in found), default=-1)
    consequence = [m.span() for m in _CONSEQUENCE_COULD.finditer(sentence) if m.start() > last_term]
    hedges = [m for m in _SENTENCE_HEDGE.finditer(sentence)
              if not any(start <= m.start() < end for start, end in consequence)] if found else []
    hedge = hedges[0] if hedges else None
    if hedge:
        raise GenerationRejectedError(
            "significance_not_in_sources", [f"atténuation « {hedge.group()} » dans la phrase : {sentence.strip()}"])
    past = _SENTENCE_PAST.search(sentence) if found else None
    if past:
        raise GenerationRejectedError(
            "significance_not_in_sources", [f"temps passé « {past.group()} » dans la phrase : {sentence.strip()}"])
    return sorted(found)


def _terms_in(sentence: str) -> set[str]:
    """Renvoie les termes de signification d'une phrase."""
    return {term for _, term in _term_spans(sentence)}


def _labels_in(text: str) -> set[str]:
    """Renvoie les libellés ClinVar d'un texte, du plus long au plus court."""
    found, remaining = set(), text
    for label in _LABELS:
        pattern = re.compile(rf"\b{re.escape(label)}\b")
        if pattern.search(remaining):
            found.add(label)
            remaining = pattern.sub(" ", remaining)
    return found


_NAME_LISTS = re.compile(r"^(?:Associated conditions|Related phenotypes \(HPO\)):\s*(.+)$", re.MULTILINE)
_TRAILING_DETAILS = re.compile(r"\s*\([^()]*\)\s*$")


def _disease_names(cited: Sequence[RetrievedDocument]) -> list[str]:
    """Renvoie les noms de maladie (≥ 2 mots) des documents cités qui contiennent un terme de signification."""
    names: set[str] = set()
    for d in cited:
        for line in _NAME_LISTS.findall(d.text):
            for raw in line.rstrip(".").split("; "):
                name = _TRAILING_DETAILS.sub("", raw).strip().rstrip(".")
                if len(name.split()) >= 2 and any(p.search(name) for _, p in _TERMS):
                    names.add(name)
    return sorted(names, key=len, reverse=True)


# Terme recopié de la question avec son mot précédent neutralisé, sauf si ce mot désigne un variant ou une classification.
_VARIANT_CARRIERS = re.compile(
    r"^(?:variant\w*|mutation\w*|all[èe]le\w*|forme\w*|modification\w*|changement\w*|alt[ée]ration\w*"
    r"|substitution\w*|d[ée]l[ée]tion\w*|insertion\w*|duplication\w*|class\w*|cat[ée]goris\w*"
    r"|consid[ée]r\w*|jug[ée]\w*|reconnu\w*|signification\w*|statut\w*|interpr[ée]t\w*"
    r"|est|sont|[êe]tre|comme|et|ou|tr[èe]s|plus|moins)$", re.IGNORECASE)
_WORD_BEFORE = re.compile(r"([^\W\d_][\w'’-]*)\s+$")


def _fold(text: str) -> str:
    """Replie un texte (minuscules, sans accents, espaces réduits) pour le comparer à la question."""
    folded = unicodedata.normalize("NFD", text.lower())
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", folded).strip()


def _mask_question_phrases(text: str, question: str) -> str:
    """Masque les termes recopiés tels quels de la question, hors porteurs de variant."""
    if not question:
        return text
    folded_question = f" {_fold(question)} "
    spans: list[tuple[int, int]] = []
    for _term, pattern in _TERMS:
        for match in pattern.finditer(text):
            before = _WORD_BEFORE.search(text[:match.start()])
            if not before or _VARIANT_CARRIERS.match(before.group(1)):
                continue
            if f" {_fold(before.group(1) + ' ' + match.group())} " in folded_question:
                spans.append(match.span())
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + " " * (end - start) + text[end:]
    return text


def _mask_disease_names(text: str, cited: Sequence[RetrievedDocument]) -> str:
    """Masque les noms de maladie des documents cités qui contiennent un terme de signification."""
    for name in _disease_names(cited):
        pattern = re.compile(rf"(?<!\w){_spaced(_unmark(_clean(name), quotes=False))}(?!\w)", re.IGNORECASE)
        text = pattern.sub(lambda m: " " * len(m.group()), text)
    return text


# Ligne de la signification actuelle ; elle s'arrête avant une éventuelle ligne d'historique.
_CURRENT_LINE = re.compile(r"Clinical significance:\s*(.*?)(?:\.(?:\s|$)|\n|Classification history:|$)")


def _translated(labels: set[str]) -> set[str]:
    """Traduit en français des libellés ClinVar, composites découpés."""
    out: set[str] = set()
    for label in labels:
        for part in re.split(r"/|; |, ", label):
            translated = translate_significance(part.strip())
            if translated:
                out.add(translated)
    return out


def _current(d: RetrievedDocument) -> set[str]:
    """Renvoie les significations actuelles d'un document en français (jamais l'historique)."""
    labels = {d.clinical_significance} if d.clinical_significance else set()
    for match in _CURRENT_LINE.finditer(d.text):
        labels |= _labels_in(match.group(1))
    return _translated(labels)


def _mentions(sentence: str, names: Sequence[str] = ()) -> list[tuple[int, int, str]]:
    """Renvoie les identifiants de variant d'une phrase, noms historiques des fiches citées compris."""
    spans = (variant_spans(sentence) + _local_spans(sentence)
             + [(m.start(), m.end(), m.group(1)) for m in _VARIATION_ID.finditer(sentence)])
    for name in names:
        pattern = re.compile(rf"(?<![\w-]){_spaced(name)}(?![\w-])", re.IGNORECASE)
        spans += [(m.start(), m.end(), _name_key(name)) for m in pattern.finditer(sentence)]
    return sorted(spans)


# Nom historique d'une fiche sans HGVS (« G6PD ZURICH »), apparié comme un identifiant.
_DOC_TITLE = re.compile(r"^Variant (?P<name>[^,\n]+), gene\b")


def _doc_name(d: RetrievedDocument) -> str | None:
    """Renvoie le nom historique d'une fiche sans HGVS, s'il est assez distinctif, sinon None."""
    match = _DOC_TITLE.match(d.text)
    if not match:
        return None
    name = match.group("name").strip()
    if re.search(r"[cpgmn]\.|[:()]", name) or len(name) < 6 or not re.search(r"[A-Z]", name) or " " not in name:
        return None
    return name


def _name_key(name: str) -> str:
    """Clé d'appariement d'un nom historique."""
    return "nom:" + " ".join(name.lower().split())


_RESPECTIVELY = re.compile(r"\brespectivement\b", re.IGNORECASE)
# Terme dans une parenthèse ouverte juste après le variant.
_INSIDE_PARENTHESIS = re.compile(r"[(\[][^()\[\]]*$")
_OTHERS = re.compile(r"\bautres?\b", re.IGNORECASE)
_TERM_BREAK = re.compile(r"[()\[\]]|\bautres?\b", re.IGNORECASE)
# Terme écrit avant son variant : début de ligne, écart, nom porteur, en-tête de section.
_LINE_PREFIX = re.compile(r"[\s\-+#>\d.)]*")
_FORWARD_GAP = re.compile(r"[ \t]*:?[ \t]*\(?[ \t]*")
_CARRIER_NOUN = re.compile(
    r"\b(?:variant|variante|mutation|all[èe]le|substitution|d[ée]l[ée]tion|duplication|insertion)s?\s*$",
    re.IGNORECASE)
_SECTION_TAIL = re.compile(r"[ \t]*:?[ \t]*")
_SECTION_NOUN = re.compile(r"#|\b(?:variant|variante|mutation)s?\b", re.IGNORECASE)
_INCERTAIN = re.compile(r"\bincertain\w*", re.IGNORECASE)
_PLURAL_TERM = re.compile(r"\b(?:pathog[èe]nes|b[ée]nins|b[ée]nignes|incertaines)\b", re.IGNORECASE)


def _term_end(sentence: str, pos: int) -> int:
    """Renvoie la fin du plus long terme de signification qui commence à `pos`."""
    ends = [m.end() for _, pattern in _TERMS if (m := pattern.match(sentence, pos))]
    if (m := _INCERTAIN.match(sentence, pos)):
        ends.append(m.end())
    return max(ends, default=pos)


def _check_variant_pairing(sentence: str, terms: list[tuple[int, str]],
                           keyed: Sequence[tuple[_VariantIds, set[str], str]], names: Sequence[str] = ()) -> None:
    """Relie chaque terme de signification aux variants voisins et le compare à la fiche citée de chacun."""
    # Phrase découpée en blocs alternés de variants et de termes ; `keyed` : (identifiants, significations, doc_id).
    # 1. Un bloc de termes porte sur les variants qui le précèdent (« respectivement » : dans l'ordre).
    # 2. Un bloc de termes en tête de phrase vaut pour les variants sans signification propre.
    # 3. Sinon un variant sans signification prend le bloc « d'autres … » qui suit, ou le bloc qui précède.
    # 4. Un bloc détaché par une parenthèse vise les mêmes variants ; par « autres », des variants non nommés.
    # 5. Un terme écrit avant son variant sur la même ligne porte sur les variants qui le suivent.
    # 6. Un en-tête de section seul sur sa ligne vaut jusqu'au suivant.
    # Sens « après » par défaut : regarder des deux côtés laisserait passer une permutation entre voisins.

    def docs_of(key: str) -> frozenset[str]:
        """Fiches citées qui portent un identifiant."""
        return frozenset(doc_id for ids, _, doc_id in keyed if key in ids)

    def significances(variant: list[str]) -> set[str]:
        """Significations actuelles des fiches d'un variant."""
        return {sig for key in variant for ids, sigs, _ in keyed if key in ids for sig in sigs}

    def reject(variant: list[str], said) -> None:
        """Rejette une signification non conforme à la fiche du variant."""
        raise GenerationRejectedError("significance_not_in_sources", [
            (f"signification non conforme à la fiche du variant {variant[0]} : {', '.join(said)} "
            f"(fiche : {', '.join(sorted(significances(variant))) or 'aucune'} ; phrase : {sentence.strip()})")])

    def check(variants: list[list[str]], group: list[str], *, every_term: bool) -> None:
        """Vérifie un bloc de termes contre des variants."""
        for variant in variants:
            if not significances(variant) & set(group):
                reject(variant, group)
        if every_term:
            for term in group:
                if not any(term in significances(v) for v in variants):
                    reject(variants[-1], [term])

    def pair(variants: list[list[str]], group: list[str]) -> None:
        """Applique un bloc de termes à une suite de variants, comptés par fiche."""
        cards: list[list] = []
        for variant in variants:
            docs = frozenset().union(*(docs_of(key) for key in variant))
            same = next((card for card in cards if card[0] & docs), None)
            if same is None:
                cards.append([docs, list(variant)])
            else:
                same[1].extend(variant)
        if _RESPECTIVELY.search(sentence) and len(group) >= 2 and len(group) == len(cards):
            for (_, variant), term in zip(cards, group):
                if term not in significances(variant):
                    reject(variant, [term])
            return
        check(variants, group, every_term=True)

    # Identifiants hors fiches citées : déjà traités par check_identifiers_cited.
    mentions = [(start, end, key) for start, end, key in _mentions(sentence, names) if docs_of(key)]
    if not mentions:
        return
    events = sorted([(start, end, "v", key) for start, end, key in mentions]
                    + [(pos, pos, "t", term) for pos, term in terms])
    # Bloc : [type "v"/"t", valeurs, positions de début, fin du dernier élément].
    blocks: list[list] = []
    for start, end, kind, value in events:
        # Une parenthèse ou « autres » entre deux termes ouvre un nouveau bloc.
        split = (kind == "t" and blocks and blocks[-1][0] == "t"
                 and _TERM_BREAK.search(sentence[blocks[-1][2][-1]:start]))
        if not blocks or blocks[-1][0] != kind or split:
            blocks.append([kind, [], [], end])
        block = blocks[-1]
        block[3] = _term_end(sentence, start) if kind == "t" else max(block[3], end)
        if kind == "t":
            block[1].append(value)
            block[2].append(start)
        elif block[1] and docs_of(value) & docs_of(block[1][-1][-1]):
            block[1][-1].append(value)
        else:
            block[1].append([value])
            block[2].append(start)
    header = blocks[0][1] if blocks[0][0] == "t" else None
    own: set[int] = set()  # variants (id()) ayant une signification propre
    others: dict[int, list[str]] = {}  # suite de variants -> bloc « d'autres … » qui la suit
    scopes: dict[int, list[list[str]]] = {}  # bloc de termes -> variants visés
    sections: set[int] = set()  # blocs de termes en-têtes de section
    for i, (kind, group, positions, end) in enumerate(blocks):
        if kind != "t":
            continue
        line_start = sentence.rfind("\n", 0, positions[0]) + 1
        line_end = sentence.find("\n", end)
        line_end = len(sentence) if line_end < 0 else line_end
        before, after = sentence[line_start:positions[0]], sentence[end:line_end]
        previous_run = blocks[i - 1] if i and blocks[i - 1][0] == "v" else None
        next_run = blocks[i + 1] if i + 1 < len(blocks) and blocks[i + 1][0] == "v" else None
        line_head = _LINE_PREFIX.fullmatch(before) is not None
        # Règle 5 : vise aussi les variants précédents, sauf en début de ligne, après un nom porteur ou s'ils sont déjà qualifiés.
        if next_run is not None and next_run[2][0] < line_end and (
                line_head or _FORWARD_GAP.fullmatch(sentence[end:next_run[2][0]])):
            targets = next_run[1]
            scopes[i] = targets
            pair(targets, group)
            forward_only = (previous_run is None or line_head
                            or _CARRIER_NOUN.search(sentence[previous_run[3]:positions[0]])
                            or all(id(v) in own for v in previous_run[1]))
            own |= {id(v) for v in targets}
            if forward_only:
                continue
        # Règle 6 : en-tête de section seul sur sa ligne, sans « : » avant lui.
        elif (i and next_run is not None and ":" not in before and _SECTION_TAIL.fullmatch(after)
              and _SECTION_NOUN.search(before)
              and not any(line_start <= start < line_end for start, _, _ in mentions)):
            sections.add(i)
            continue
        if i == 0:
            continue
        if blocks[i - 1][0] == "t":
            # Règle 4.
            previous = scopes.get(i - 1)
            if previous and not _OTHERS.search(sentence[blocks[i - 1][2][-1]:positions[0]]):
                scopes[i] = previous
                check(previous, group, every_term=True)
            continue
        _, variants, starts, last_end = blocks[i - 1]
        between = sentence[starts[-1]:positions[0]]
        if _OTHERS.search(sentence[last_end:positions[0]]):
            # Règle 3 : « X et d'autres variants pathogènes ».
            others[i - 1] = group
            continue
        # Parenthèse : ce seul variant, sauf terme au pluriel après une liste.
        if _INSIDE_PARENTHESIS.search(between) and not any(
                _PLURAL_TERM.search(sentence[pos:_term_end(sentence, pos)]) for pos in positions):
            variants = variants[-1:]
        scopes.setdefault(i, variants)
        own |= {id(v) for v in variants}
        pair(variants, group)
    previous_terms, governing_header = None, header
    for i, (kind, group, _, _) in enumerate(blocks):
        if kind == "t":
            previous_terms = group
            if i in sections:
                governing_header = group
            continue
        orphans = [v for v in group if id(v) not in own]
        governing = governing_header if governing_header is not None else others.get(i, previous_terms)
        if orphans and governing is not None:
            check(orphans, governing, every_term=False)


def check_significances(answer: str, cited: Sequence[RetrievedDocument], question: str = "") -> None:
    """Exige que chaque signification soit la signification actuelle d'un document cité, et de la fiche du variant visé."""
    names = [name for d in cited if (name := _doc_name(d))]
    keyed = [(_doc_ids(d) | _VariantIds(vid=frozenset({_name_key(n)} if (n := _doc_name(d)) else ())),
              _current(d), d.doc_id) for d in cited]
    current: set[str] = set()
    for _ids, sigs, _doc_id in keyed:
        current |= sigs
    text = _normalize_variant_forms(_unmark(_clean(answer), quotes=False))
    off_table = _OFF_TABLE.search(text) or _ABBREVIATIONS.search(text)
    if off_table:
        raise GenerationRejectedError("significance_not_in_sources",
                                      [f"qualificatif hors table : {off_table.group()}"])
    text = _mask_disease_names(text, cited)
    text = _mask_question_phrases(text, question)
    text = _NEUTRAL_PHRASES.sub(lambda m: " " * len(m.group()), text)
    previous_terms: list = []
    context: list[str] = []  # variants nommés par la dernière phrase qui en nomme
    for sentence in _SENTENCES.split(text):
        if previous_terms and _REFUTATION.match(sentence):
            raise GenerationRejectedError(
                "significance_not_in_sources", [f"réfutation après un terme de signification : {sentence.strip()}"])
        sentence = _mask_truncated_list(sentence)
        terms = _term_spans(sentence)
        unsourced = {t for _, t in terms} - current
        if unsourced:
            raise GenerationRejectedError(
                "significance_not_in_sources",
                [f"terme absent des documents cités : {t} (phrase : {sentence.strip()})" for t in sorted(unsourced)])
        plain = _unmark(sentence.translate(_TYPOGRAPHY))
        named = [key for _s, _e, key in _mentions(plain, names) if any(key in ids for ids, _, _ in keyed)]
        if terms and named:
            _check_variant_pairing(plain, terms, keyed, names)
        elif terms and context and not _ANAPHORA_SKIP.search(sentence):
            _check_inherited(context, [t for _, t in terms], keyed, sentence)
        elif named and previous_terms and _SAME.search(sentence):
            _check_inherited(named, [t for _, t in previous_terms], keyed, sentence)
        previous_terms = terms
        if named:
            context = named
        elif not terms:
            context = []


# Entre phrases : des termes sans variant visent les variants de la phrase précédente (sauf « autres »…).
# Des variants sans terme mais avec « aussi », « également »… reprennent les termes précédents.
_ANAPHORA_SKIP = re.compile(r"\bautres?\b|\bplusieurs\b|\bcertain", re.IGNORECASE)
_SAME = re.compile(r"\b(?:aussi|[ée]galement|de\s+m[êe]me|idem|pareillement|l['’]\s*est)\b", re.IGNORECASE)


def _check_inherited(variants: list[str], said: list[str], keyed, sentence: str) -> None:
    """Vérifie des termes hérités d'une phrase voisine contre les fiches des variants visés."""
    def significances(key: str) -> set[str]:
        """Significations actuelles des fiches d'un identifiant."""
        return {sig for ids, sigs, _ in keyed if key in ids for sig in sigs}

    for key in variants:
        if not significances(key) & set(said):
            raise GenerationRejectedError("significance_not_in_sources", [
                (f"signification non conforme à la fiche du variant {key} (phrase voisine) : {', '.join(said)} "
                f"(fiche : {', '.join(sorted(significances(key))) or 'aucune'} ; phrase : {sentence.strip()})")])
    for term in said:
        if not any(term in significances(key) for key in variants):
            raise GenerationRejectedError("significance_not_in_sources", [
                (f"signification non conforme aux variants de la phrase voisine : {term} "
                f"(variants : {', '.join(variants)} ; phrase : {sentence.strip()})")])


# Marqueurs d'historique raconté, volontairement larges (faux positifs acceptés).
_HISTORY_NARRATION = re.compile(
    r"\b(?:auparavant|pr[ée]c[ée]demment|initialement|anciennement|ant[ée]rieur\w*|reclass\w*)"
    r"|\bjusqu['’]\s*(?:en|au|à|a)\s+\S*\s*(?:19|20)\d\d",
    re.IGNORECASE,
)


def check_no_history_narration(answer: str) -> None:
    """Rejette une réponse qui raconte l'historique de classification (restitué par le code)."""
    match = _HISTORY_NARRATION.search(_clean(answer))
    if match:
        raise GenerationRejectedError("history_narrated", [f"marqueur d'historique : {match.group()}"])


def check_not_empty(text: str) -> None:
    """Rejette une réponse vide."""
    if not text.strip():
        raise GenerationRejectedError("empty_answer")


def verify_answer(text: str, documents: Sequence[RetrievedDocument], citations: Sequence[str],
                  status: str, question: str = "") -> None:
    """Applique toute la chaîne de contrôles, partagée par la génération et le diagnostic hors ligne."""
    check_not_empty(text)
    if status == "not_in_sources":
        check_identifiers(text, [], status=status)
        check_no_history_narration(text)
        check_significances(text, [], question)
        return
    by_id = {d.doc_id: d for d in documents}
    check_citations(citations, documents, status)
    check_document_labels(text, documents)
    check_identifiers(text, documents, status=status)
    cited = [by_id[c] for c in citations]
    check_identifiers_cited(text, cited)
    check_no_history_narration(text)
    check_significances(text, cited, question)


def explain_rejection(text: str, documents: Sequence[RetrievedDocument], citations: Sequence[str],
                      status: str, question: str = "") -> dict | None:
    """Renvoie le motif de rejet d'une réponse ({"reason", "detail"}), ou None si elle passe."""
    try:
        verify_answer(text, documents, citations, status, question)
    except GenerationRejectedError as exc:
        return {"reason": str(exc), "detail": list(exc.detail)}
    return None
