"""Métadonnées NCBI Gene d'un gène."""
from __future__ import annotations

from ingestion.http_client import NcbiClient


def fetch_gene_info(client: NcbiClient, gene_symbol: str) -> dict:
    """Récupère les métadonnées NCBI Gene pour un symbole de gène (esearch puis esummary)."""
    uids = client.esearch(
        db="gene",
        term=f"{gene_symbol}[gene] AND human[organism] AND alive[property]",
    )
    if not uids:
        return {}
    return client.esummary(db="gene", uid=uids[0])
