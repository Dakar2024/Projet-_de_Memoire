"""Contexte transmis au LLM de génération : un bloc par document, dont l'en-tête est
produit par le code. Le texte Gold est échappé : il ne peut ni fermer son bloc ni en
ouvrir un autre (injection dans les données)."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from RAG.src.retrieval.retriever import RetrievedDocument


def escape_data(text: str) -> str:
    """Échappe un texte de donnée : seuls « & » et « < » le sont, jamais « > », pour que les
    substitutions HGVS (c.68A>G) restent lisibles et comparables ; sans « < », rien ne peut
    fermer ni ouvrir une balise."""
    return text.replace("&", "&amp;").replace("<", "&lt;")


def _attr(value: str | None, missing: str) -> str:
    return escape(value, quote=True) if value else missing


def document_labels(documents: Sequence[RetrievedDocument]) -> dict[str, str]:
    """Table identifiant neutre -> doc_id réel, construite par le code seul, dans l'ordre de
    transmission (D1, D2…). Le LLM ne voit jamais les doc_id réels : ils ressemblent à un
    identifiant ClinVar (« clinvar:NNN » est l'AlleleID interne, pas le Variation ID affiché)
    et il les recopiait dans ses réponses."""
    return {f"D{index}": doc.doc_id for index, doc in enumerate(documents, start=1)}


UNKNOWN_CITATION_PREFIX = "<inconnue>:"


def resolve_citations(citations: Sequence[str], documents: Sequence[RetrievedDocument]) -> list[str]:
    """Convertit les citations du LLM (D_k) en doc_id réels. Une citation qui n'est pas une
    étiquette transmise (inconnue, ou un doc_id réel recopié) devient une valeur inutilisable
    comme doc_id : elle sera rejetée par check_citations, jamais une erreur d'index."""
    mapping = document_labels(documents)
    return [mapping.get(c, UNKNOWN_CITATION_PREFIX + c) for c in citations]


def render_document(doc: RetrievedDocument, label: str) -> str:
    """Bloc d'un document ; `label` (D_k) est produit par le code (document_labels)."""
    header = (f'<document id="{label}" gene="{_attr(doc.gene_symbol, "none")}" '
              f'significance="{_attr(doc.clinical_significance, "none")}" '
              f'archive="{_attr(doc.source_version, "unknown")}">')
    return f"{header}\n{escape_data(doc.text)}\n</document>"


def build_context(documents: Sequence[RetrievedDocument]) -> str:
    return "\n".join(render_document(doc, f"D{index}") for index, doc in enumerate(documents, start=1))
