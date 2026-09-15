from __future__ import annotations

from transformations.raw_to_bronze import SPEC


def bronze_to_silver(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Construit les tables Silver (Delta) du panel à partir du Bronze.

    Tables : clinvar_variant, clinvar_variant_gene, ncbi_gene, refseq_transcript,
    medgen_concept, medgen_mim, medgen_inheritance, hpo_gene_phenotype, hpo_term.
    Partition : `panel`. Une ligne par entité, aucun agrégat.

    Traitements : typage, filtre panel, filtre GRCh38, dédoublonnage sur `#AlleleID`,
    éclatement des lignes multi-gènes, parsing du XML MedGen, normalisation HGVS via
    le catalogue RefSeq, historisation SCD2 des reclassifications par `MERGE`.

    Interdits : filtrer sur la signification clinique (les variants bénins sont
    conservés) ; modifier la casse des HGVS, accessions et symboles de gènes.
    `RS# (dbSNP)` est un entier, `-1` quand absent.
    """
    raise NotImplementedError(f"bronze_to_silver : implémenté par le sous-projet C ({SPEC}, §7)")
