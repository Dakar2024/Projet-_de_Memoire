"""Contexte du LLM de génération : un bloc par document, en-tête produit par le code, texte échappé contre l'injection."""
from __future__ import annotations

from collections.abc import Sequence
from html import escape

from RAG.src.retrieval.retriever import RetrievedDocument


def escape_data(text: str) -> str:
    """Échappe « & » et « < » (jamais « > », pour garder c.68A>G lisible) : aucune balise ne peut s'ouvrir."""
    return text.replace("&", "&amp;").replace("<", "&lt;")


def _attr(value: str | None, missing: str) -> str:
    """Échappe une valeur d'attribut, ou renvoie la valeur par défaut."""
    return escape(value, quote=True) if value else missing


def document_labels(documents: Sequence[RetrievedDocument]) -> dict[str, str]:
    """Associe les étiquettes neutres D1, D2… aux doc_id réels, jamais montrés au LLM (il les recopiait)."""
    return {f"D{index}": doc.doc_id for index, doc in enumerate(documents, start=1)}


UNKNOWN_CITATION_PREFIX = "<inconnue>:"


def resolve_citations(citations: Sequence[str], documents: Sequence[RetrievedDocument]) -> list[str]:
    """Convertit les citations D_k en doc_id réels ; une citation inconnue est marquée pour être rejetée."""
    mapping = document_labels(documents)
    return [mapping.get(c, UNKNOWN_CITATION_PREFIX + c) for c in citations]


def render_document(doc: RetrievedDocument, label: str) -> str:
    """Rend le bloc d'un document sous son étiquette D_k."""
    header = (f'<document id="{label}" gene="{_attr(doc.gene_symbol, "none")}" '
              f'significance="{_attr(doc.clinical_significance, "none")}" '
              f'archive="{_attr(doc.source_version, "unknown")}">')
    return f"{header}\n{escape_data(doc.text)}\n</document>"


def build_context(documents: Sequence[RetrievedDocument]) -> str:
    """Rend le contexte complet, documents étiquetés D1…Dn dans l'ordre."""
    return "\n".join(render_document(doc, f"D{index}") for index, doc in enumerate(documents, start=1))
