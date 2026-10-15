"""Catalogue des transcrits RefSeq d'un gène, utilisé par la normalisation HGVS."""
from __future__ import annotations

from ingestion.http_client import NcbiClient

# ARNm RefSeq humains : seuls porteurs des accessions `NM_` citées par ClinVar.
REFSEQ_SEARCH_TEMPLATE = (
    "{gene}[gene] AND human[orgn] AND srcdb_refseq[prop] AND biomol_mrna[prop]"
)


def fetch_transcripts(client: NcbiClient, gene_symbol: str) -> list[dict]:
    """Récupère les transcrits RefSeq d'un gène ; liste vide si le symbole n'est pas résolu."""
    uids = client.esearch(
        db="nuccore", term=REFSEQ_SEARCH_TEMPLATE.format(gene=gene_symbol)
    )
    return [client.esummary(db="nuccore", uid=uid) for uid in uids]
