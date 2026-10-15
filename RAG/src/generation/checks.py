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


# Formes d'identifiants ramenées à la forme extraite (revue finale n° 2, m1) : « dbSNP 80357999 »
# (numéro sans « rs »), « rs-12345 », protéine prédite entre parenthèses « p.(Gln1756Profs*74) »,
# espaces parasites « c. 5266dup » / « c.5266 dup ». Sans cela, un identifiant inventé écrit ainsi
# échapperait à l'extraction.
_VARIANT_FORMS = (
    (re.compile(r"\bdbSNP\s*[:#]?\s*(?:rs\s*)?(\d+)", re.IGNORECASE), r"rs\1"),
    (re.compile(r"\brs\s*-\s*(\d+)", re.IGNORECASE), r"rs\1"),
    (re.compile(r"\bp\.\s*\(([^()\s]+)\)"), r"p.\1"),
    (re.compile(r"\b([cp])\.\s+(?=[\d*+-]|[A-Z][a-z]{2}\d)"), r"\1."),
    (re.compile(r"\b(c\.[0-9_+*-]+)\s+(?=(?:del|dup|ins)|[ACGT]>)", re.IGNORECASE), r"\1"),
)
# HGVS mitochondrial (« m.3243A>G ») : aucun gène du panel n'est mitochondrial ; contrôlé comme
# un c. (présent dans un texte transmis, sinon rejeté), sous sa propre forme.
_MITO = re.compile(r"\bm\.\d+(?:_\d+)?(?:[ACGT]>[ACGT]|del[ACGT]*|dup[ACGT]*|ins[ACGT]+)", re.IGNORECASE)
# Notation de répétition (« c.569CTC[1] ») : ses crochets ne sont pas de la mise en forme.
_REPEAT = re.compile(r"\bc\.[0-9_+*-]+[ACGT]+\[\d+\]", re.IGNORECASE)
# Délétion, duplication ou insertion protéique en phase (« p.Pro191del », « p.Val218_Ile219del »,
# « p.Leu230_Ser231insTer ») : non extraites par retrieval/identifiers.py (re-relecture de la
# vague n° 2, N5) ; contrôlées ici sous leur forme écrite, comme la répétition.
_P_INFRAME = re.compile(
    r"\bp\.\(?([A-Z][a-z]{2}\d+(?:_[A-Z][a-z]{2}\d+)?(?:delins(?:[A-Z][a-z]{2})+|del|dup|ins(?:[A-Z][a-z]{2})+))"
    r"\)?(?![\w*])")


def _local_spans(text: str) -> list[tuple[int, int, str]]:
    """Répétitions et délétions protéiques en phase : (début, fin, forme), bases en majuscules."""
    return ([(m.start(), m.end(), "c." + m.group()[2:].upper()) for m in _REPEAT.finditer(text)]
            + [(m.start(), m.end(), "p." + m.group(1)) for m in _P_INFRAME.finditer(text)])


def _normalize_variant_forms(text: str) -> str:
    for pattern, replacement in _VARIANT_FORMS:
        text = pattern.sub(replacement, text)
    return text


def _text_ids(text: str) -> _VariantIds:
    text = _normalize_variant_forms(text)
    ids = extract_identifiers(text)
    local = _local_spans(text)
    return _VariantIds(frozenset(f"rs{r}" for r in ids.rs),
                       frozenset(ids.hgvs_c) | frozenset(m.group() for m in _MITO.finditer(text))
                       | frozenset(key for _, _, key in local if key.startswith("c.")),
                       frozenset(ids.hgvs_p) | frozenset(key for _, _, key in local if key.startswith("p.")),
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


# Mise en forme collée à un identifiant (re-relecture de la vague n° 2, N1) : l'extraction
# (retrieval/identifiers.py, mesurée en E2a et non modifiée) n'accepte après un identifiant
# qu'une espace ou une ponctuation courante ; « **c.9999A>G** », « `c.9999A>G` »,
# « "c.9999A>G" », « [c.9999A>G] » ou « c.9999A>G</b> » n'étaient donc pas extraits, et un
# identifiant inventé ou une signification d'une autre fiche passaient. Ici, dans les seuls
# contrôles, tout caractère hors d'une liste blanche (lettres, chiffres, espaces, ponctuation
# courante et signes du HGVS) devient une espace, ainsi que les « * » et « _ » de mise en forme
# (gras, italique) ; ceux du HGVS restent (« c.*123A>G », « p.Arg337* », « fs*74 », « c.68_69del »).
# Remplacement caractère pour caractère : les positions des termes et des identifiants ne
# bougent pas. La notation de répétition (« c.569CTC[1] ») garde ses crochets.
_MARKUP_KEEP = set(".,;:?!()/+-*>=%#°'’_")
_MARKUP_STARS = re.compile(r"\*{2,}|_{2,}")
_ITALIC_OPEN = re.compile(r"(?<![\w.*])[*_](?=\S)")
_ITALIC_CLOSE = re.compile(r"(?<=[A-Za-zÀ-ÿ>)\]])[*_](?![\w*])")
# Apostrophe ASCII qui n'est pas entre deux lettres (« 'c.9999A>G' ») : guillemet simple.
_QUOTE = re.compile(r"(?<![A-Za-zÀ-ÿ])'|'(?![A-Za-zÀ-ÿ])")


def _blank(match: re.Match) -> str:
    return " " * len(match.group())


def _stars(match: re.Match) -> str:
    """Gras fermé juste après un « p.Arg337* » (« **p.Arg337*** ») : l'étoile du HGVS reste."""
    run = match.group()
    before = match.string[match.start() - 1] if match.start() else ""
    if run[0] == "*" and before.isdigit() and len(run) % 2:
        return "*" + " " * (len(run) - 1)
    return " " * len(run)


def _unmark(text: str, *, quotes: bool = True) -> str:
    """Délimiteurs de mise en forme ramenés à des espaces (longueur inchangée). `quotes` :
    l'apostrophe ASCII hors d'un mot l'est aussi (pas pour le test de négation, où « n' »
    doit rester)."""
    protected = {i for m in _REPEAT.finditer(text) for i in range(m.start(), m.end())}
    chars = [c if (c.isalnum() or c.isspace() or c in _MARKUP_KEEP or i in protected) else " "
             for i, c in enumerate(text)]
    text = "".join(chars)
    text = _MARKUP_STARS.sub(_stars, text)
    text = _ITALIC_OPEN.sub(_blank, text)
    text = _ITALIC_CLOSE.sub(_blank, text)
    return _QUOTE.sub(_blank, text) if quotes else text


def _answer_text(answer: str) -> str:
    """Réponse prête pour l'extraction des identifiants : nettoyée, typographie française
    (guillemets, apostrophe, espaces insécables) et mise en forme (_unmark) ramenées à des
    espaces."""
    return _unmark(_clean(answer).translate(_TYPOGRAPHY))


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
# Mot de renvoi facultatif à l'intérieur d'une parenthèse : « (voir D2) », « (cf. D3) »,
# « (voir par ex. D1, D2) », « (selon D4) ».
_PAREN_LEAD = (r"(?:(?:voir|cf\.?|selon)(?:\s+par\s+ex(?:emple|\.)?)?\s+"
               r"|(?:documents?|sources?|fiches?)\s*:?\s*)?")
_LABEL_REFERENCE = re.compile(
    rf"[(\[]\s*{_PAREN_LEAD}(?P<paren>{_LABEL_LIST})\s*[)\]]"
    rf"|(?<![\w-])(?:documents?|sources?|fiches?|voir|selon|cf\.?)\s+(?P<keyword>{_LABEL_LIST})(?![\w-])"
    rf"|(?:^|[.!?]\s+)(?P<head>{_LABEL})\s*:",
    re.IGNORECASE | re.MULTILINE)


# Correctif post-recette n° 1 (2026-10-14) : 6 des 17 rejets de la recette E2b étaient des
# réponses justes, rejetées parce que le modèle recopiait ses citations dans le texte
# (« pathogène [D3] », « (voir D2) »). Une référence ENTRE PARENTHÈSES OU CROCHETS est une
# incise : la retirer ne tronque pas la phrase. Elle est donc retirée par le code, à une
# condition : chacune de ses étiquettes est déjà dans la liste des citations du modèle (le
# retrait ne change pas les fiches citées, donc rien de ce que contrôlent les étapes suivantes).
# Une référence dans la phrase (« Selon D2, … », « D3 : … ») ou une étiquette non citée reste
# rejetée par check_document_labels : la retirer pourrait laisser une phrase tronquée.
_PAREN_REFERENCE = re.compile(rf"[ \t]*[(\[]\s*{_PAREN_LEAD}(?P<labels>{_LABEL_LIST})\s*[)\]]", re.IGNORECASE)


def _label_set(text: str) -> set[str]:
    return {re.sub(r"\s", "", m).upper() for m in re.findall(_LABEL, text, re.IGNORECASE)}


def strip_cited_labels(answer: str, citations: Sequence[str]) -> str:
    """Retire les références entre parenthèses ou crochets dont toutes les étiquettes sont
    citées (`citations` : étiquettes D_k rendues par le modèle). Le reste du texte est inchangé."""
    cited = {re.sub(r"\s", "", c).upper() for c in citations}

    def replace(match: re.Match) -> str:
        return "" if _label_set(match.group("labels")) <= cited else match.group()

    stripped = _PAREN_REFERENCE.sub(replace, answer)
    # Espaces laissés en fin de ligne par un retrait (« … (voir la fiche ClinVar) [D1] »).
    return stripped if stripped == answer else re.sub(r"[ \t]+$", "", stripped, flags=re.MULTILINE)


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
    r"\bclasse\s+(?:ACMG\s+)?[1-5]\b"
    # N4 : « classé 5 », « classé V », « classé en classe V », « de classe V » (« classe I » reste :
    # vocabulaire de biologie, « protéine de classe I »).
    r"|\bclass(?:é|ee)e?s?\s+(?:en\s+)?(?:classe\s+)?(?:[1-5]|IV|V|I{1,3})\b|\bclasse\s+(?:IV|V)\b",
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
    # N4 : « classé b » (minuscule) après un verbe de classement.
    r"|(?i:\bclass[ée]e?s?\s+(?:en\s+|comme\s+)?[pb])(?![\w/-]|\.\w)"
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
    r"|\br[ée]fut\w*|\binfirm(?!i[eè]r)\w*"
    # Re-relecture de la vague n° 2 (N4) : « erreur », « contesté », « discutable », « douteux »,
    # « remis en cause », « obsolète », « ancien(ne) » (classification).
    r"|\berreur\w*|\bcontest\w*|\bdiscutable\w*|\bdouteu\w*|\bremis\w*\s+en\s+cause"
    r"|\bobsol[èe]te\w*|\bancien(?:ne)?s?\b",
    re.IGNORECASE)
# Atténuations : une signification ClinVar est affirmée telle quelle, jamais rétrogradée en
# hypothèse (« potentiellement pathogène ») ni renforcée (« hautement pathogène »).
_SENTENCE_HEDGE = re.compile(
    r"\b(?:potentiellement|possiblement|[ée]ventuellement|hautement|pourrai\w*)\b|\bpeut[- ]être\b"
    # N4 : « présumé », « supposé », « suspecté », « semble », « serait », « faiblement »,
    # « plutôt », « a priori ».
    r"|\bpr[ée]sum\w*|\bsuppos\w*|\bsuspect\w*|\bsembl\w*|\bserai\w*|\bfaiblement\b"
    r"|\bplut[ôo]t\b|\ba\s+priori\b",
    re.IGNORECASE)
# N6 : « pourrait » sur une CONSÉQUENCE, écrit après tous les termes de la phrase (« X est
# pathogène et pourrait augmenter le risque de cancer ») ne porte pas sur la signification.
# Liste fermée de verbes ; « pourrait l'être », « pourrait être », ou « pourrait » avant le
# terme restent rejetés.
_CONSEQUENCE_COULD = re.compile(
    r"\bpourrai\w*\s+(?:augmenter|accro[îi]tre|favoriser|entra[îi]ner|contribuer|expliquer|pr[ée]disposer)\b",
    re.IGNORECASE)
# Temps passé dans une phrase qui porte un terme (N4) : « était pathogène », « On a longtemps
# cru… » raconteraient une classification passée ; l'historique est restitué par le code.
_SENTENCE_PAST = re.compile(r"\b(?:[ée]tai(?:t|ent)|fut|furent|longtemps)\b", re.IGNORECASE)
# Phrase réduite à une réfutation (« Pathogène ? Non. », « … Faux. ») : le découpage sur « ? »
# sépare le terme de sa négation ; elle est rejetée quand la phrase précédente porte un terme.
_REFUTATION = re.compile(
    r"^\W*(?:(?:absolument|totalement|compl[èe]tement|tout\s+[àa]\s+fait|c['’]est)\s+)?"
    r"(?:non|faux|fausse|inexact\w*|incorrect\w*|erron[ée]\w*|(?:que\s+)?nenni|ou\s+pas)\W*$", re.IGNORECASE)
_SENTENCES = re.compile(r"(?<=[.!?;])\s+")
# Formules exactes masquées (remplacées par des espaces) avant le test de négation. Elles
# recopient le statut de revue ClinVar (« no conflicts », « no assertion criteria provided »),
# la phrase imposée par le prompt pour les fiches maigres, la mention d'une liste tronquée et un
# nom de maladie (« nonspherocytic hemolytic anemia ») : leur « aucun », « sans », « ne … pas »
# ou « non » ne porte jamais sur la signification. Liste fermée. La formule de liste tronquée
# (« d'autres variantes non listées ici ») est masquée à part, phrase par phrase
# (_mask_truncated_list).
_NEUTRAL_PHRASES = re.compile(
    r"\b(?:aucun|sans|pas\s+de)\s+conflits?(?:\s+d['’]\s*interpr[ée]tations?)?\b"
    r"|\baucune?\s+crit[èe]res?\s+(?:d['’]\s*[ée]valuation\s+)?fournie?s?\b"
    r"|\bclinvar\s+ne\s+documente\s+pas\s+de\s+ph[ée]notypes?\s+pour\s+ce\s+variant\b"
    r"|\bnon[- ]sph[ée]rocytaires?\b"
    # Correctif post-recette n° 3 (P1-B21) : « condition : Neurodevelopmental delay (sans mention
    # de syndrome) » précise la condition déposée, jamais la signification. Liste fermée de noms.
    r"|\bsans\s+(?:mention|pr[ée]cision)\s+(?:de\s+|d['’]\s*|du\s+|des\s+)"
    r"(?:syndromes?|maladies?|conditions?|ph[ée]notypes?|pathologies?|affections?|sous[- ]types?)\b",
    re.IGNORECASE,
)


# Liste tronquée : masquée seulement si suivie ni de « comme » / « en tant » (« Ce variant non
# listé ici comme pathogène » reste rejeté, comme « non listé » seul), ni d'un terme de
# signification dans la même phrase : « d'autres variantes non listées ici sont pathogènes »
# affirmerait la signification de variants qu'aucune fiche transmise ne décrit.
_TRUNCATED_LIST = re.compile(
    r"\bautres\s+variant(?:e)?s?\s+non\s+list[ée]e?s?\s+ici\b(?!\s+(?:comme|en\s+tant))", re.IGNORECASE)


def _mask_truncated_list(sentence: str) -> str:
    for match in reversed(list(_TRUNCATED_LIST.finditer(sentence))):
        tail = sentence[match.end():]
        if any(pattern.search(tail) for _, pattern in _TERMS) or re.search(r"\bincertain", tail, re.IGNORECASE):
            continue
        sentence = sentence[:match.start()] + " " * (match.end() - match.start()) + sentence[match.end():]
    return sentence


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


# Correctif post-recette n° 2 (2026-10-14) : P1-B09 et P1-C20 ont été rejetées parce que la
# réponse reprenait la paraphrase de la question, « syndrome de multiples excroissances
# bénignes », où « bénignes » qualifie des tumeurs, pas un variant. Un terme de signification
# est neutralisé quand le mot qui le précède et le terme lui-même figurent côte à côte, tels
# quels, dans la question, SAUF si ce mot désigne un variant ou introduit une classification
# (« variants pathogènes », « classé bénin », « est pathogène ») : là, le terme porte sur un
# variant et reste contrôlé, même recopié de la question.
_VARIANT_CARRIERS = re.compile(
    r"^(?:variant\w*|mutation\w*|all[èe]le\w*|forme\w*|modification\w*|changement\w*|alt[ée]ration\w*"
    r"|substitution\w*|d[ée]l[ée]tion\w*|insertion\w*|duplication\w*|class\w*|cat[ée]goris\w*"
    r"|consid[ée]r\w*|jug[ée]\w*|reconnu\w*|signification\w*|statut\w*|interpr[ée]t\w*"
    r"|est|sont|[êe]tre|comme|et|ou|tr[èe]s|plus|moins)$", re.IGNORECASE)
_WORD_BEFORE = re.compile(r"([^\W\d_][\w'’-]*)\s+$")


def _fold(text: str) -> str:
    """Minuscules, sans accents, espaces réduits : comparaison avec la question."""
    folded = unicodedata.normalize("NFD", text.lower())
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", folded).strip()


def _mask_question_phrases(text: str, question: str) -> str:
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
    """Remplace par des espaces les occurrences exactes (insensibles à la casse) d'un nom de
    maladie des documents cités qui contient un terme de signification : seule cette portion
    est neutralisée, le reste de la phrase reste contrôlé."""
    for name in _disease_names(cited):
        pattern = re.compile(rf"(?<!\w){_spaced(_unmark(_clean(name), quotes=False))}(?!\w)", re.IGNORECASE)
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


def _mentions(sentence: str, names: Sequence[str] = ()) -> list[tuple[int, int, str]]:
    """Identifiants de variant d'une phrase (début, fin, forme) : rs, c., p. et Variation ID ;
    plus les noms historiques des fiches citées (`names`, voir _doc_name)."""
    spans = (variant_spans(sentence) + _local_spans(sentence)
             + [(m.start(), m.end(), m.group(1)) for m in _VARIATION_ID.finditer(sentence)])
    for name in names:
        pattern = re.compile(rf"(?<![\w-]){_spaced(name)}(?![\w-])", re.IGNORECASE)
        spans += [(m.start(), m.end(), _name_key(name)) for m in pattern.finditer(sentence)]
    return sorted(spans)


# Correctif post-recette n° 4 (2026-10-14) : P1-B19 a été rejetée alors qu'elle était exacte.
# Certaines fiches n'ont pas d'expression HGVS : leur titre Gold est un nom historique
# (« Variant G6PD ZURICH, gene G6PD »). Faute de reconnaître ce nom comme un variant, le segment
# « G6PD ZURICH (Pathogenic/Likely pathogenic) ; » héritait du variant du segment précédent
# (c.1478G>A, Pathogenic) et était déclaré non conforme. Le nom de la fiche CITÉE devient un
# identifiant de l'appariement, au même titre qu'un HGVS : la signification écrite à côté est
# comparée à celle de SA fiche (règle plus précise qu'avant, pas plus permissive).
_DOC_TITLE = re.compile(r"^Variant (?P<name>[^,\n]+), gene\b")


def _doc_name(d: RetrievedDocument) -> str | None:
    """Nom historique d'une fiche sans HGVS dans son titre (« G6PD ZURICH »), sinon None. Un nom
    trop court ou sans majuscule n'est pas retenu : il pourrait apparaître par hasard."""
    match = _DOC_TITLE.match(d.text)
    if not match:
        return None
    name = match.group("name").strip()
    if re.search(r"[cpgmn]\.|[:()]", name) or len(name) < 6 or not re.search(r"[A-Z]", name) or " " not in name:
        return None
    return name


def _name_key(name: str) -> str:
    return "nom:" + " ".join(name.lower().split())


_RESPECTIVELY = re.compile(r"\brespectivement\b", re.IGNORECASE)
# Terme placé dans une parenthèse ouverte juste après le variant : « W (signification incertaine) ».
_INSIDE_PARENTHESIS = re.compile(r"[(\[][^()\[\]]*$")
_OTHERS = re.compile(r"\bautres?\b", re.IGNORECASE)
_TERM_BREAK = re.compile(r"[()\[\]]|\bautres?\b", re.IGNORECASE)
# Terme écrit AVANT son variant (re-relecture de la vague n° 2, N3) : début de ligne (puce,
# numéro, titre), écart réduit à des espaces, « : » ou « ( » jusqu'au variant, nom porteur
# (« le variant pathogène X »), en-tête de section (« Variants bénins : » seul sur sa ligne).
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
    """Fin du terme de signification qui commence à `pos` (le plus long qui y correspond)."""
    ends = [m.end() for _, pattern in _TERMS if (m := pattern.match(sentence, pos))]
    if (m := _INCERTAIN.match(sentence, pos)):
        ends.append(m.end())
    return max(ends, default=pos)


def _check_variant_pairing(sentence: str, terms: list[tuple[int, str]],
                           keyed: Sequence[tuple[_VariantIds, set[str], str]], names: Sequence[str] = ()) -> None:
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

    5. Terme AVANT son variant sur la même ligne (« - pathogène : X », « le variant pathogène
       X et le variant bénin Y », « Pathogène : X, bénin : Y ») : il porte sur la suite de
       variants qui le suit (détail dans le code).
    6. En-tête de section seul sur sa ligne (« Variants bénins : ») : il vaut pour les variants
       qui le suivent sans signification propre, jusqu'à l'en-tête suivant.

    Raison du sens « termes après le variant » par défaut : c'est la forme de toutes les listes
    acceptées de la recette ; regarder des deux côtés laisserait passer une permutation entre
    voisins (« X1 pathogène, X2 bénin, X3 pathogène » avec X2 et X3 inversés). Le sens « avant »
    n'est retenu que sur les formes 5 et 6 ; quand un terme peut porter sur les deux voisins
    (« X : pathogène (Y) »), les deux doivent concorder.

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

    def pair(variants: list[list[str]], group: list[str]) -> None:
        """Bloc de termes appliqué à une suite de variants ; « respectivement » avec autant
        de termes que de variants : dans l'ordre."""
        # Variants comptés par fiche (N5) : un rs d'une autre fiche intercalé (« X et Y (rs de X) »)
        # ne doit pas fausser le compte.
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

    # Un identifiant qu'aucune fiche citée ne porte relève des contrôles d'identifiants
    # (check_identifiers_cited, appelé avant dans verify_answer) : ignoré ici.
    mentions = [(start, end, key) for start, end, key in _mentions(sentence, names) if docs_of(key)]
    if not mentions:
        return
    events = sorted([(start, end, "v", key) for start, end, key in mentions]
                    + [(pos, pos, "t", term) for pos, term in terms])
    # Blocs : ("v", [variants], [début de chaque variant], fin du dernier identifiant) ou
    # ("t", [termes], [position de chaque terme], fin du dernier terme).
    blocks: list[list] = []
    for start, end, kind, value in events:
        # Deux termes séparés par une parenthèse ou par « autres » ne forment pas un même bloc :
        # « W (bénin) et d'autres variantes probablement pathogènes ».
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
        # 5. Terme AVANT son variant, sur la même ligne : en début de ligne (« - pathogène :
        #    X »), ou séparé du variant par des espaces, « : » ou « ( » seulement (« le variant
        #    pathogène X », « bénin : Y »). Il porte sur la suite de variants qui le SUIT. Il
        #    porte aussi sur celle qui le précède (les deux doivent concorder : « X : pathogène
        #    (Y) »), sauf en début de ligne, après un nom porteur (« le variant ») ou si cette
        #    suite a déjà sa propre signification (« Pathogène : X, bénin : Y »).
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
        # 6. En-tête de section (« Variants bénins : », « ### Variants pathogènes ») : seul
        #    sur sa ligne avec un nom ou un titre, sans « : » avant lui ; il ne porte pas sur
        #    le variant qui le précède, il vaut en-tête pour les variants qui le suivent.
        elif (i and next_run is not None and ":" not in before and _SECTION_TAIL.fullmatch(after)
              and _SECTION_NOUN.search(before)
              and not any(line_start <= start < line_end for start, _, _ in mentions)):
            sections.add(i)
            continue
        if i == 0:
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
        _, variants, starts, last_end = blocks[i - 1]
        between = sentence[starts[-1]:positions[0]]
        if _OTHERS.search(sentence[last_end:positions[0]]):
            # « X et d'autres duplications de signification incertaine » : le terme porte sur
            # d'autres variants, non nommés ; X reçoit l'en-tête, à défaut ce bloc (« X et
            # d'autres variants pathogènes » : X doit être pathogène).
            others[i - 1] = group
            continue
        # Parenthèse juste après un variant : ce seul variant, sauf terme au pluriel après une
        # liste (« X et Y (pathogènes) », N5) : toute la suite.
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
    """Chaque signification de la réponse est la signification actuelle d'un document cité
    (champ `clinical_significance` et ligne « Clinical significance ») ; dans une phrase qui
    nomme des variants, elle est en plus celle de la fiche du variant auquel elle se rapporte
    (_check_variant_pairing). Un libellé de la ligne « Classification history » est rejeté :
    l'historique est restitué par le code."""
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
    context: list[str] = []  # variants nommés par la dernière phrase qui en nomme (N2)
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


# Phrase suivante (re-relecture de la vague n° 2, N2) : l'appariement est fait par phrase, et
# « ; » coupe aussi. Sans les deux règles ci-dessous, « Le variant X est décrit. Il est
# pathogène. » ou « Y est pathogène ; le variant X aussi. » livraient la signification d'une
# autre fiche citée pour X.
# 1. Une phrase qui porte des termes sans nommer de variant (« Il est pathogène »,
#    « Signification : pathogène », « Tous deux sont pathogènes ») porte sur les variants
#    nommés par la dernière phrase qui en nomme ; une phrase sans variant ni terme coupe ce
#    contexte. Exception : « autres », « plusieurs », « certains » parlent d'autres variants.
# 2. Une phrase qui nomme des variants sans terme mais avec « aussi », « également », « de
#    même », « idem », « pareillement » ou « l'est » reprend les termes de la phrase précédente.
# Sens prudent : une phrase générale qui suit une liste (« Les variants pathogènes de BRCA1
# augmentent le risque ») est rejetée si l'un des variants de la liste n'a pas ce terme.
_ANAPHORA_SKIP = re.compile(r"\bautres?\b|\bplusieurs\b|\bcertain", re.IGNORECASE)
_SAME = re.compile(r"\b(?:aussi|[ée]galement|de\s+m[êe]me|idem|pareillement|l['’]\s*est)\b", re.IGNORECASE)


def _check_inherited(variants: list[str], said: list[str], keyed, sentence: str) -> None:
    """Chaque variant hérité a l'un des termes `said` dans sa fiche, et chaque terme est
    celui d'au moins un de ces variants (même règle qu'un bloc de termes dans la phrase)."""
    def significances(key: str) -> set[str]:
        return {sig for ids, sigs, _ in keyed if key in ids for sig in sigs}

    for key in variants:
        if not significances(key) & set(said):
            raise GenerationRejectedError("significance_not_in_sources", [
                f"signification non conforme à la fiche du variant {key} (phrase voisine) : {', '.join(said)} "
                f"(fiche : {', '.join(sorted(significances(key))) or 'aucune'} ; phrase : {sentence.strip()})"])
    for term in said:
        if not any(term in significances(key) for key in variants):
            raise GenerationRejectedError("significance_not_in_sources", [
                f"signification non conforme aux variants de la phrase voisine : {term} "
                f"(variants : {', '.join(variants)} ; phrase : {sentence.strip()})"])


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
                  status: str, question: str = "") -> None:
    """Chaîne complète des contrôles, dans l'ordre : la seule définition, utilisée par la
    génération et par le diagnostic hors ligne. Statut `not_in_sources` : le texte libre est
    contrôlé contre aucun document (sert seulement à consigner un code de rejet)."""
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
    """Pourquoi la réponse est rejetée : {"reason": code, "detail": [éléments déclencheurs]},
    ou None si elle passe. Même chaîne que la génération (verify_answer), aucune divergence."""
    try:
        verify_answer(text, documents, citations, status, question)
    except GenerationRejectedError as exc:
        return {"reason": str(exc), "detail": list(exc.detail)}
    return None
