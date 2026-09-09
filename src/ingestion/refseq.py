from __future__ import annotations

from ingestion.http_client import NcbiClient

# Les variants ClinVar sont nommés en HGVS (`NM_000059.4:c.1234A>G`). La
# normalisation HGVS prévue en Silver a besoin du catalogue des transcrits de
# référence — accession, version, longueur — qu'aucune autre source du projet ne
# fournit. Les filtres restreignent aux ARNm RefSeq humains, seuls porteurs des
# accessions `NM_` citées par ClinVar.
REFSEQ_SEARCH_TEMPLATE = (
    "{gene}[gene] AND human[orgn] AND srcdb_refseq[prop] AND biomol_mrna[prop]"
)


def fetch_transcripts(client: NcbiClient, gene_symbol: str) -> list[dict]:
    """Récupère les transcrits RefSeq d'un gène (esearch nuccore puis esummary).

    Un gène sans transcrit RefSeq renvoie une liste vide plutôt qu'une erreur :
    c'est le cas légitime des loci GWAS du panel (HBS1L, MYB), traité comme
    l'absence de terme HPO ou de CUI MedGen résolvable.
    """
    uids = client.esearch(
        db="nuccore", term=REFSEQ_SEARCH_TEMPLATE.format(gene=gene_symbol)
    )
    return [client.esummary(db="nuccore", uid=uid) for uid in uids]
