"""Contrôles déterministes de la réponse générée, en plus du prompt : citations parmi
les documents transmis, identifiants (rs, HGVS, ClinVar, gènes) présents dans ces documents,
significations conformes aux documents cités. Un échec lève GenerationRejectedError
avec un code court ; la réponse est alors remplacée par un message fixe.

Règle de l'historique de classification : le LLM ne le raconte pas, le code le restitue
(tâche 5) à partir de la ligne Gold « Classification history ». La réponse ne peut donc
citer que la signification ACTUELLE des documents cités. Raison : trois tours de motifs
(« auparavant », « jusqu'en <date> », « précédemment »…) ont montré qu'un historique raconté
en langue libre n'est pas contrôlable de façon sûre, chaque assouplissement rouvrant un
contournement (« Comme indiqué précédemment, il est de signification incertaine »)."""

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

# Identifiant ClinVar : « Variation ID », « ClinVar ID/n°/# », « VCV », « /variation/ ». Un nombre
# nu après « ClinVar » n'en est pas un s'il ressemble à une année, une date ou un effectif.
_VARIATION_ID = re.compile(
    r"(?:Variation(?:\s+ID)?|ClinVar(?:\s+(?:ID|n°|no\.?|#)|(?!\s*[:#°]?\s*(?:19|20)\d\d\b))|VCV0*|/variation/)"
    r"\s*[:#°]?\s*(\d{2,9})\b(?!-\d)(?!\s*(?:soumett|laborat|submitter|centre))",
    re.IGNORECASE,
)
_LABELS = sorted(SIGNIFICANCE_FR, key=len, reverse=True)
_TYPOGRAPHY = str.maketrans({c: " " for c in "«»’‘“”…\u00a0\u202f"})
# Tirets Unicode (U+2010 à U+2015, signe moins U+2212, tirets doubles et triples U+2E3A/U+2E3B,
# signe moins modificateur U+02D7, moins épais U+2796, petit tiret cadratin U+FE58) ramenés à
# « - » : « c.68‑2A>G » écrit avec un trait d'union insécable reste un HGVS intronique contrôlé.
_DASHES = str.maketrans({c: "-" for c in
                         "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2e3a\u2e3b\u02d7\u2796\ufe58"})
_PANEL_STATUSES = ("answered", "partial")


def _clean(answer: str) -> str:
    """Réponse remise sous forme comparable : entités HTML décodées (c.69A&gt;G), Unicode
    normalisé (NFKC : pleine chasse, ligatures) et caractères de format (Cf : largeur nulle,
    trait d'union conditionnel, liant de mots) retirés, car ils casseraient « rs12345 » ;
    tirets Unicode ramenés à « - »."""
    text = unicodedata.normalize("NFKC", html.unescape(answer))
    return "".join(c for c in text if unicodedata.category(c) != "Cf").translate(_DASHES)


def check_citations(citations: Sequence[str], documents: Sequence[RetrievedDocument], status: str) -> None:
    transmitted = {d.doc_id for d in documents}
    unknown = [c for c in citations if c not in transmitted]
    if unknown:
        raise GenerationRejectedError("citation_not_transmitted", unknown)
    if status in ("answered", "partial") and not citations:
        raise GenerationRejectedError("no_citation")


@dataclass(frozen=True)
class _VariantIds:
    """Identifiants de variant d'un texte ou d'un document, sous forme normalisée
    (« rs123 », « c.… », « p.… », Variation ID en chiffres)."""
    rs: frozenset = frozenset()
    c: frozenset = frozenset()
    p: frozenset = frozenset()
    vid: frozenset = frozenset()

    def __or__(self, other: "_VariantIds") -> "_VariantIds":
        return _VariantIds(self.rs | other.rs, self.c | other.c, self.p | other.p, self.vid | other.vid)

    def __contains__(self, key: str) -> bool:
        return key in self.rs or key in self.c or key in self.p or key in self.vid


def _text_ids(text: str) -> _VariantIds:
    ids = extract_identifiers(text)
    return _VariantIds(frozenset(f"rs{r}" for r in ids.rs), frozenset(ids.hgvs_c), frozenset(ids.hgvs_p),
                       frozenset(_VARIATION_ID.findall(text)))


def _doc_ids(d: RetrievedDocument) -> _VariantIds:
    """Identifiants que porte un document : ceux de son texte et ceux de ses champs."""
    fields = _VariantIds(frozenset({f"rs{d.rs_dbsnp}"} if d.rs_dbsnp is not None else ()),
                         frozenset({d.hgvs_c} if d.hgvs_c else ()), frozenset({d.hgvs_p} if d.hgvs_p else ()),
                         frozenset({d.clinvar_variation_id} if d.clinvar_variation_id else ()))
    return _text_ids(d.text) | fields


def _docs_ids(documents: Sequence[RetrievedDocument]) -> _VariantIds:
    out = _VariantIds()
    for d in documents:
        out |= _doc_ids(d)
    return out


def _missing(found: _VariantIds, allowed: _VariantIds) -> list[str]:
    return (sorted(found.rs - allowed.rs, key=lambda r: r[2:]) + sorted(found.c - allowed.c)
            + sorted(found.p - allowed.p) + [f"ClinVar {v}" for v in sorted(found.vid - allowed.vid)])


def _answer_text(answer: str) -> str:
    """Réponse prête pour l'extraction des identifiants : nettoyée, typographie française
    (guillemets, apostrophe, espaces insécables) ramenée à des espaces."""
    return _clean(answer).translate(_TYPOGRAPHY)


def check_identifiers(answer: str, documents: Sequence[RetrievedDocument], status: str = "answered") -> None:
    """Tout identifiant de la réponse (rs, HGVS, ClinVar, gène) figure dans les documents
    transmis. La typographie française (guillemets, apostrophe, espaces insécables) est
    ramenée à des espaces avant extraction : elle ne doit pas cacher un identifiant inventé."""
    answer = _answer_text(answer)
    found = extract_identifiers(answer)
    offending = _missing(_text_ids(answer), _docs_ids(documents))
    if offending:
        raise GenerationRejectedError("identifier_not_in_sources", offending)
    if status in _PANEL_STATUSES:
        # Symboles autorisés : ceux que les textes transmis contiennent (« group D1 », RAD51,
        # CD4 recopiés fidèlement) et les gènes des documents.
        allowed_genes = {d.gene_symbol for d in documents if d.gene_symbol}
        for d in documents:
            ids = extract_identifiers(d.text)
            allowed_genes |= set(ids.genes) | set(ids.out_of_panel)
        unknown_genes = (set(found.genes) | set(found.out_of_panel)) - allowed_genes
        if unknown_genes:
            raise GenerationRejectedError("identifier_not_in_sources", [f"gène {g}" for g in sorted(unknown_genes)])


def check_identifiers_cited(answer: str, cited: Sequence[RetrievedDocument]) -> None:
    """Statuts `answered` / `partial` : tout identifiant DE VARIANT de la réponse (rs, c., p.,
    Variation ID) appartient à un document CITÉ. Sinon un variant d'une fiche transmise mais non
    citée pourrait recevoir la signification d'une autre fiche, citée, sans que rien ne le
    relie à sa propre fiche (revue finale n° 2, C1). Les gènes restent contrôlés contre les
    textes transmis (check_identifiers)."""
    offending = _missing(_text_ids(_answer_text(answer)), _docs_ids(cited))
    if offending:
        raise GenerationRejectedError("identifier_not_cited", offending)


# Une étiquette (D1, « D 1 », « d1 ») n'est une référence que dans trois emplois : entre
# parenthèses ou crochets (seule ou en liste), derrière un mot de renvoi (document, source,
# fiche, voir, selon, cf.), ou en tête de phrase suivie de « : ». Ailleurs (« cycline D1 »,
# « vitamine D3 », « récepteur D2 », « groupe D ») c'est du vocabulaire médical.
_LABEL = r"D\s?\d+"
_LABEL_LIST = rf"{_LABEL}(?:\s*(?:[,;]|et|ou|and)\s*{_LABEL})*"
_LABEL_REFERENCE = re.compile(
    rf"[(\[]\s*(?:(?:voir|cf\.?|selon)\s+)?(?P<paren>{_LABEL_LIST})\s*[)\]]"
    rf"|(?<![\w-])(?:documents?|sources?|fiches?|voir|selon|cf\.?)\s+(?P<keyword>{_LABEL_LIST})(?![\w-])"
    rf"|(?:^|[.!?]\s+)(?P<head>{_LABEL})\s*:",
    re.IGNORECASE | re.MULTILINE)


def check_document_labels(answer: str, documents: Sequence[RetrievedDocument]) -> None:
    """Un identifiant neutre de document (D1, D2… transmis au LLM) utilisé comme référence dans
    le texte de la réponse est rejeté, pas retiré : le retrait par le code pourrait laisser une
    phrase tronquée ou changer son sens, et un lecteur ne doit jamais voir une étiquette interne.
    Seuls les emplois en référence comptent (voir _LABEL_REFERENCE) : « cycline D1 » ou
    « vitamine D3 » sont du vocabulaire, pas des étiquettes."""
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
    """Motif d'une expression : les espaces deviennent \\s+ (plusieurs espaces tolérés)."""
    return r"\s+".join(re.escape(word) for word in text.split())


def _french_pattern(term: str) -> str:
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
    """Termes de signification reconnus dans une réponse : (clé française, motif), en
    français et avec le libellé ClinVar anglais, du plus long au plus court pour que
    « probablement pathogène » masque le « pathogène » qu'il contient."""
    entries: list[tuple[int, str, str]] = []
    for term in significance_terms_fr():
        entries.append((len(term), term, _french_pattern(term)))
    for label, fr in SIGNIFICANCE_FR.items():
        if label in ("other", "not provided"):
            continue
        # Libellé anglais : mots séparés par espaces, tirets ou soulignés (« Uncertain-significance »).
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
    r"\bclasse\s+(?:ACMG\s+)?[1-5]\b",
    re.IGNORECASE,
)
# Abréviations de signification (P, LP, B, LB, P/LP, B/LB), hors table et sans terme reconnu :
# sans ce motif, « classé B » pour un variant pathogène passerait. Sensible à la casse ; une
# lettre seule ne compte qu'après un verbe de classement ou entre parenthèses (« lymphocytes B »,
# « vitamine B12 » passent).
_ABBREVIATIONS = re.compile(
    r"(?<![\w./-])(?:P/LP|LP/P|B/LB|LB/B|LP|LB)(?![\w/-])"
    r"|(?:\b(?:class[ée]e?s?|cat[ée]goris[ée]e?s?|est|sont)|:)\s+(?:en\s+|comme\s+)?[PB](?![\w/-]|\.\w)"
    r"|\(\s*[PB]\s*\)"
)
_NEGATIONS = {"pas", "non", "ni", "jamais", "plus", "aucun", "aucune"}
# Négation n'importe où dans une phrase qui porte un terme de signification : la phrase est
# rejetée sans chercher ce que la négation porte (« Il ne s'agit en aucun cas d'un variant
# pathogène », « pathogène selon un laboratoire, mais pas selon les autres »).
_SENTENCE_NEGATION = re.compile(
    r"\b(?:ne|pas|aucune?s?|jamais|rien|sans|ni|non)\b|\bn'"
    # Inversions lexicales (revue finale n° 2) : « loin d'être », « tout sauf », « peu probable »,
    # « écarté », « exclu » (pas « exclusivement »), « à tort », « faux / faussement »,
    # « contrairement », « réfuté », « infirmé » (pas « infirmière »).
    r"|\bloin\s+d|\btout\s+sauf\b|\bpeu\s+probable\w*|\bimprobable\w*|\b[ée]cart[ée]\w*"
    r"|\bexclu(?!sivement)\w*|\bà\s+tort\b|\bfaux\b|\bfausse\w*|\bcontrairement\b"
    r"|\br[ée]fut\w*|\binfirm(?!i[eè]r)\w*",
    re.IGNORECASE)
# Atténuations : une signification ClinVar est affirmée telle quelle, jamais rétrogradée en
# hypothèse (« potentiellement pathogène ») ni renforcée (« hautement pathogène »).
_SENTENCE_HEDGE = re.compile(
    r"\b(?:potentiellement|possiblement|[ée]ventuellement|hautement|pourrai\w*)\b|\bpeut[- ]être\b",
    re.IGNORECASE)
# Phrase réduite à une réfutation (« Pathogène ? Non. », « … Faux. ») : le découpage sur « ? »
# sépare le terme de sa négation ; elle est rejetée quand la phrase précédente porte un terme.
_REFUTATION = re.compile(r"^\W*(?:non|faux|fausse|inexact\w*|incorrect\w*|erron[ée]\w*)\W*$", re.IGNORECASE)
_SENTENCES = re.compile(r"(?<=[.!?;])\s+")
# Formules exactes masquées (remplacées par des espaces) avant le test de négation. Elles
# recopient le statut de revue ClinVar (« no conflicts », « no assertion criteria provided »),
# la phrase imposée par le prompt pour les fiches maigres, la mention d'une liste tronquée et un
# nom de maladie (« nonspherocytic hemolytic anemia ») : leur « aucun », « sans », « ne … pas »
# ou « non » ne porte jamais sur la signification. Liste fermée : seule la formule « d'autres
# variantes non listées ici » est masquée, et pas si elle est suivie de « comme » / « en tant »
# (« Ce variant non listé ici comme pathogène » reste rejeté, comme « non listé » seul).
_NEUTRAL_PHRASES = re.compile(
    r"\b(?:aucun|sans|pas\s+de)\s+conflits?(?:\s+d['’]\s*interpr[ée]tations?)?\b"
    r"|\baucune?\s+crit[èe]res?\s+(?:d['’]\s*[ée]valuation\s+)?fournie?s?\b"
    r"|\bclinvar\s+ne\s+documente\s+pas\s+de\s+ph[ée]notypes?\s+pour\s+ce\s+variant\b"
    r"|\bautres\s+variant(?:e)?s?\s+non\s+list[ée]e?s?\s+ici\b(?!\s+(?:comme|en\s+tant))"
    r"|\bnon[- ]sph[ée]rocytaires?\b",
    re.IGNORECASE,
)


def _negated(text: str, start: int) -> bool:
    words = re.findall(r"[\wéèêàçùô']+", text[:start].lower())[-3:]
    return any(word in _NEGATIONS for word in words)


def _term_spans(sentence: str) -> list[tuple[int, str]]:
    """Termes de signification d'une phrase avec leur position, sans double compte. Une
    négation dans la phrase (n'importe où) la rend invérifiable dès qu'elle porte un terme
    (conservateur)."""
    found: list[tuple[int, str]] = []
    remaining = sentence
    for term, pattern in _TERMS:
        for match in pattern.finditer(remaining):
            if _negated(sentence, match.start()):
                raise GenerationRejectedError(
                    "significance_not_in_sources", [f"négation devant « {match.group()} » : {sentence.strip()}"])
            found.append((match.start(), term))
        remaining = pattern.sub(lambda m: " " * len(m.group()), remaining)
    # « incertain » isolé, sous toutes ses formes, vaut « signification incertaine » (« Sa
    # signification clinique est encore incertaine », « classé incertain »).
    for match in re.finditer(r"\bincertain\w*", remaining, re.IGNORECASE):
        found.append((match.start(), "signification incertaine"))
    negation = _SENTENCE_NEGATION.search(sentence.replace("’", "'")) if found else None
    if negation:
        raise GenerationRejectedError(
            "significance_not_in_sources", [f"négation « {negation.group()} » dans la phrase : {sentence.strip()}"])
    hedge = _SENTENCE_HEDGE.search(sentence) if found else None
    if hedge:
        raise GenerationRejectedError(
            "significance_not_in_sources", [f"atténuation « {hedge.group()} » dans la phrase : {sentence.strip()}"])
    return sorted(found)


def _terms_in(sentence: str) -> set[str]:
    return {term for _, term in _term_spans(sentence)}


def _labels_in(text: str) -> set[str]:
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
    """Noms de maladie ou de phénotype des documents cités qui contiennent eux-mêmes un terme
    de signification (« Benign familial hematuria »), du plus long au plus court. Séparateur
    Gold « ; », détails entre parenthèses (OMIM, hérédité) retirés. Au moins deux mots : un
    mot isolé (« benign ») ne doit jamais neutraliser un terme."""
    names: set[str] = set()
    for d in cited:
        for line in _NAME_LISTS.findall(d.text):
            for raw in line.rstrip(".").split("; "):
                name = _TRAILING_DETAILS.sub("", raw).strip().rstrip(".")
                if len(name.split()) >= 2 and any(p.search(name) for _, p in _TERMS):
                    names.add(name)
    return sorted(names, key=len, reverse=True)


def _mask_disease_names(text: str, cited: Sequence[RetrievedDocument]) -> str:
    """Remplace par des espaces les occurrences exactes (insensibles à la casse) d'un nom de
    maladie des documents cités qui contient un terme de signification : seule cette portion
    est neutralisée, le reste de la phrase reste contrôlé."""
    for name in _disease_names(cited):
        pattern = re.compile(rf"(?<!\w){_spaced(_clean(name))}(?!\w)", re.IGNORECASE)
        text = pattern.sub(lambda m: " " * len(m.group()), text)
    return text


# Ligne de la signification actuelle ; elle s'arrête avant une éventuelle ligne d'historique.
_CURRENT_LINE = re.compile(r"Clinical significance:\s*(.*?)(?:\.(?:\s|$)|\n|Classification history:|$)")


def _translated(labels: set[str]) -> set[str]:
    """Traduction française des libellés ClinVar, composites découpés (« Pathogenic/Likely
    pathogenic »)."""
    out: set[str] = set()
    for label in labels:
        for part in re.split(r"/|; |, ", label):
            translated = translate_significance(part.strip())
            if translated:
                out.add(translated)
    return out


def _current(d: RetrievedDocument) -> set[str]:
    """Significations actuelles d'un document, en français : champ `clinical_significance` et
    ligne « Clinical significance » (jamais la ligne « Classification history »)."""
    labels = {d.clinical_significance} if d.clinical_significance else set()
    for match in _CURRENT_LINE.finditer(d.text):
        labels |= _labels_in(match.group(1))
    return _translated(labels)


def _mentions(sentence: str) -> list[tuple[int, int, str]]:
    """Identifiants de variant d'une phrase (début, fin, forme) : rs, c., p. et Variation ID."""
    spans = variant_spans(sentence) + [(m.start(), m.end(), m.group(1)) for m in _VARIATION_ID.finditer(sentence)]
    return sorted(spans)


_RESPECTIVELY = re.compile(r"\brespectivement\b", re.IGNORECASE)
# Terme placé dans une parenthèse ouverte juste après le variant : « W (signification incertaine) ».
_INSIDE_PARENTHESIS = re.compile(r"[(\[][^()\[\]]*$")
_OTHERS = re.compile(r"\bautres?\b", re.IGNORECASE)
_TERM_BREAK = re.compile(r"[()\[\]]|\bautres?\b", re.IGNORECASE)


def _check_variant_pairing(sentence: str, terms: list[tuple[int, str]],
                           keyed: Sequence[tuple[_VariantIds, set[str], str]]) -> None:
    """Relie chaque terme de signification au(x) variant(s) nommé(s) à côté de lui dans la phrase.

    Les identifiants d'une même fiche qui se suivent (« c.4837A>G (p.Ser1613Gly, rs1799966) »)
    forment un variant. La phrase est découpée, dans l'ordre, en blocs alternés : suites de
    variants et suites de termes (« pathogène », « pathogène ou probablement pathogène »).

    1. Signification propre : un bloc de termes porte sur la suite de variants qui le PRÉCÈDE
       (« X : pathogène », « X est pathogène, tandis que Y est bénin », « X, Y et Z sont
       pathogènes ») ; placé dans une parenthèse ouverte juste après un variant (« X, Y, W
       (signification incertaine) »), sur ce seul variant. Chaque variant visé doit avoir l'un
       des termes du bloc parmi les significations actuelles de sa fiche citée, et chaque terme
       doit être celui d'au moins un des variants visés. Avec « respectivement » et autant de
       termes que de variants, appariement dans l'ordre.
    2. En-tête : un bloc de termes en tête de phrase, sans variant avant lui (« Les variants
       pathogènes sont X, Y », « répertoriés comme pathogènes sont : - X – probablement
       pathogène »), vaut pour les variants de la phrase qui n'ont pas de signification propre.
    3. Sans en-tête, un variant sans signification propre reçoit celle du bloc « d'autres … »
       qui le suit (« X et d'autres variants pathogènes »), sinon celle du bloc de termes qui le
       précède (« X est pathogène, de même que Y »).
    4. Un bloc de termes détaché du précédent par une parenthèse vise les mêmes variants
       (« X : pathogène (bénin selon …) ») ; détaché par « autres », il porte sur des variants
       non nommés (« W (bénin) et d'autres variantes probablement pathogènes ») et reste soumis
       à la seule règle des documents cités.

    Raison du sens « termes après le variant » : c'est la forme de toutes les listes acceptées
    de la recette ; regarder des deux côtés laisserait passer une permutation entre voisins
    (« X1 pathogène, X2 bénin, X3 pathogène » avec X2 et X3 inversés). Sens prudent : une
    construction mêlée (« le variant pathogène X et le variant bénin Y ») est rejetée.

    `keyed` : pour chaque document cité, (identifiants, significations actuelles, doc_id)."""

    def docs_of(key: str) -> frozenset[str]:
        return frozenset(doc_id for ids, _, doc_id in keyed if key in ids)

    def significances(variant: list[str]) -> set[str]:
        return {sig for key in variant for ids, sigs, _ in keyed if key in ids for sig in sigs}

    def reject(variant: list[str], said) -> None:
        raise GenerationRejectedError("significance_not_in_sources", [
            f"signification non conforme à la fiche du variant {variant[0]} : {', '.join(said)} "
            f"(fiche : {', '.join(sorted(significances(variant))) or 'aucune'} ; phrase : {sentence.strip()})"])

    def check(variants: list[list[str]], group: list[str], *, every_term: bool) -> None:
        for variant in variants:
            if not significances(variant) & set(group):
                reject(variant, group)
        if every_term:
            for term in group:
                if not any(term in significances(v) for v in variants):
                    reject(variants[-1], [term])

    # Un identifiant qu'aucune fiche citée ne porte relève des contrôles d'identifiants
    # (check_identifiers_cited, appelé avant dans verify_answer) : ignoré ici.
    mentions = [(start, end, key) for start, end, key in _mentions(sentence) if docs_of(key)]
    if not mentions:
        return
    events = sorted([(start, end, "v", key) for start, end, key in mentions]
                    + [(pos, pos, "t", term) for pos, term in terms])
    # Blocs : ("v", [variants], [début de chaque variant]) ou ("t", [termes], [position de chaque terme]).
    blocks: list[list] = []
    for start, _end, kind, value in events:
        # Deux termes séparés par une parenthèse ou par « autres » ne forment pas un même bloc :
        # « W (bénin) et d'autres variantes probablement pathogènes ».
        split = (kind == "t" and blocks and blocks[-1][0] == "t"
                 and _TERM_BREAK.search(sentence[blocks[-1][2][-1]:start]))
        if not blocks or blocks[-1][0] != kind or split:
            blocks.append([kind, [], []])
        block = blocks[-1]
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
    for i, (kind, group, positions) in enumerate(blocks):
        if kind != "t" or i == 0:
            continue
        if blocks[i - 1][0] == "t":
            # Bloc détaché du précédent par une parenthèse (« X : pathogène (bénin) ») : mêmes
            # variants que lui ; détaché par « autres » : d'autres variants, non nommés (règle
            # des documents cités seulement).
            previous = scopes.get(i - 1)
            if previous and not _OTHERS.search(sentence[blocks[i - 1][2][-1]:positions[0]]):
                scopes[i] = previous
                check(previous, group, every_term=True)
            continue
        _, variants, starts = blocks[i - 1]
        between = sentence[starts[-1]:positions[0]]
        last_end = max(end for start, end, _ in mentions if starts[-1] <= start < positions[0])
        if _OTHERS.search(sentence[last_end:positions[0]]):
            # « X et d'autres duplications de signification incertaine » : le terme porte sur
            # d'autres variants, non nommés ; X reçoit l'en-tête, à défaut ce bloc (« X et
            # d'autres variants pathogènes » : X doit être pathogène).
            others[i - 1] = group
            continue
        if _INSIDE_PARENTHESIS.search(between):
            variants = variants[-1:]
        scopes[i] = variants
        own |= {id(v) for v in variants}
        if _RESPECTIVELY.search(sentence) and len(group) >= 2 and len(group) == len(variants):
            for variant, term in zip(variants, group):
                if term not in significances(variant):
                    reject(variant, [term])
            continue
        check(variants, group, every_term=True)
    previous_terms = None
    for i, (kind, group, _) in enumerate(blocks):
        if kind == "t":
            previous_terms = group
            continue
        orphans = [v for v in group if id(v) not in own]
        governing = header if header is not None else others.get(i, previous_terms)
        if orphans and governing is not None:
            check(orphans, governing, every_term=False)


def check_significances(answer: str, cited: Sequence[RetrievedDocument]) -> None:
    """Chaque signification de la réponse est la signification actuelle d'un document cité
    (champ `clinical_significance` et ligne « Clinical significance ») ; dans une phrase qui
    nomme des variants, elle est en plus celle de la fiche du variant auquel elle se rapporte
    (_check_variant_pairing). Un libellé de la ligne « Classification history » est rejeté :
    l'historique est restitué par le code."""
    keyed = [(_doc_ids(d), _current(d), d.doc_id) for d in cited]
    current: set[str] = set()
    for _ids, sigs, _doc_id in keyed:
        current |= sigs
    text = _clean(answer)
    off_table = _OFF_TABLE.search(text) or _ABBREVIATIONS.search(text)
    if off_table:
        raise GenerationRejectedError("significance_not_in_sources",
                                      [f"qualificatif hors table : {off_table.group()}"])
    text = _mask_disease_names(text, cited)
    text = _NEUTRAL_PHRASES.sub(lambda m: " " * len(m.group()), text)
    previous_terms: list = []
    for sentence in _SENTENCES.split(text):
        if previous_terms and _REFUTATION.match(sentence):
            raise GenerationRejectedError(
                "significance_not_in_sources", [f"réfutation après un terme de signification : {sentence.strip()}"])
        terms = previous_terms = _term_spans(sentence)
        unsourced = {t for _, t in terms} - current
        if unsourced:
            raise GenerationRejectedError(
                "significance_not_in_sources",
                [f"terme absent des documents cités : {t} (phrase : {sentence.strip()})" for t in sorted(unsourced)])
        if terms:
            _check_variant_pairing(sentence.translate(_TYPOGRAPHY), terms, keyed)


# Marqueurs d'un historique raconté. Volontairement large : « comme indiqué précédemment »
# est rejeté aussi (faux positif accepté, la réponse devient « non vérifiable »).
_HISTORY_NARRATION = re.compile(
    r"\b(?:auparavant|pr[ée]c[ée]demment|initialement|anciennement|ant[ée]rieur\w*|reclass\w*)"
    r"|\bjusqu['’]\s*(?:en|au|à|a)\s+\S*\s*(?:19|20)\d\d",
    re.IGNORECASE,
)


def check_no_history_narration(answer: str) -> None:
    """La réponse ne raconte pas l'historique de classification : le code le restitue
    à partir de la ligne Gold « Classification history » (voir answer.py)."""
    match = _HISTORY_NARRATION.search(_clean(answer))
    if match:
        raise GenerationRejectedError("history_narrated", [f"marqueur d'historique : {match.group()}"])


def check_not_empty(text: str) -> None:
    if not text.strip():
        raise GenerationRejectedError("empty_answer")


def verify_answer(text: str, documents: Sequence[RetrievedDocument], citations: Sequence[str],
                  status: str) -> None:
    """Chaîne complète des contrôles, dans l'ordre : la seule définition, utilisée par la
    génération et par le diagnostic hors ligne. Statut `not_in_sources` : le texte libre est
    contrôlé contre aucun document (sert seulement à consigner un code de rejet)."""
    check_not_empty(text)
    if status == "not_in_sources":
        check_identifiers(text, [], status=status)
        check_no_history_narration(text)
        check_significances(text, [])
        return
    by_id = {d.doc_id: d for d in documents}
    check_citations(citations, documents, status)
    check_document_labels(text, documents)
    check_identifiers(text, documents, status=status)
    cited = [by_id[c] for c in citations]
    check_identifiers_cited(text, cited)
    check_no_history_narration(text)
    check_significances(text, cited)


def explain_rejection(text: str, documents: Sequence[RetrievedDocument], citations: Sequence[str],
                      status: str) -> dict | None:
    """Pourquoi la réponse est rejetée : {"reason": code, "detail": [éléments déclencheurs]},
    ou None si elle passe. Même chaîne que la génération (verify_answer), aucune divergence."""
    try:
        verify_answer(text, documents, citations, status)
    except GenerationRejectedError as exc:
        return {"reason": str(exc), "detail": list(exc.detail)}
    return None
