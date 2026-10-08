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


def render_document(doc: RetrievedDocument) -> str:
    header = (f'<document id="{_attr(doc.doc_id, "none")}" gene="{_attr(doc.gene_symbol, "none")}" '
              f'significance="{_attr(doc.clinical_significance, "none")}" '
              f'archive="{_attr(doc.source_version, "unknown")}">')
    return f"{header}\n{escape_data(doc.text)}\n</document>"


def build_context(documents: Sequence[RetrievedDocument]) -> str:
    return "\n".join(render_document(doc) for doc in documents)
