"""Passage silver → gold/rag : un document textuel anglais par variant et par gène."""
from __future__ import annotations

import hashlib

import polars as pl
from deltalake import DeltaTable

from ingestion.config import PANEL_GENES
from ingestion.storage import layer_uri, storage_options
from transformations.silver_io import read_silver

# Plafonds de listes : le modèle d'embedding tronque silencieusement au-delà de 512 tokens.
MAX_DISEASES = 5
MAX_PHENOTYPES = 10

# Garde chaque document sous les 2 000 caractères du contrôle qualité Gold.
MAX_SUMMARY_CHARS = 800

CLINVAR_VARIATION_URL = "https://www.ncbi.nlm.nih.gov/clinvar/variation/{variation_id}/"


def chunk_id(text: str) -> str:
    """Renvoie le SHA-256 du texte, qui permet au RAG de ne ré-embedder que les documents modifiés."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def format_list(values: list[str], cap: int) -> str:
    """Joint jusqu'à `cap` valeurs et indique combien ont été omises."""
    if not values:
        return ""
    kept = "; ".join(values[:cap])
    remainder = len(values) - cap
    return f"{kept}; and {remainder} more" if remainder > 0 else kept


def _blank(value: object) -> bool:
    """Indique une valeur à ne pas rendre : nulle, vide, « - » de ClinVar ou `-1` (pas d'identifiant dbSNP)."""
    return value is None or value == "" or value == "-" or value == -1


def _format_disease(disease: dict) -> str:
    """Rend une maladie avec son OMIM et son mode de transmission."""
    details = []
    if disease.get("omim_id"):
        details.append(f"OMIM {disease['omim_id']}")
    if disease.get("mode_inheritance"):
        details.append(f"inheritance: {disease['mode_inheritance']}")
    name = disease.get("disease_name") or "unnamed condition"
    return f"{name} ({', '.join(details)})" if details else name


def _truncate_summary(summary: str) -> str:
    """Coupe le résumé de façon déterministe sur une frontière de mot (sinon au plafond), suivi de « … »."""
    if len(summary) <= MAX_SUMMARY_CHARS:
        return summary
    cut = summary[:MAX_SUMMARY_CHARS]
    last_space = cut.rfind(" ")
    if last_space != -1:
        cut = cut[:last_space]
    return f"{cut} …"


def render_variant_document(
    variant: dict,
    diseases: list[dict],
    phenotypes: list[str],
    previous_significance: tuple[str, str] | None,
) -> str:
    """Rend le texte anglais d'un document variant (fonction pure), en omettant les clauses vides."""
    header = f"Variant {variant['name']}, gene {variant['gene_symbol']}"
    if not _blank(variant.get("cytogenetic")):
        header += f", chromosome {variant['cytogenetic']}"
    header += "."

    id_line = ""
    if not _blank(variant.get("rs_dbsnp")):
        id_line += f"dbSNP rs{variant['rs_dbsnp']}. "
    id_line += f"ClinVar Variation ID {variant['variationid']}. Type: {variant['type']}."

    lines = [header, id_line]
    if not _blank(variant.get("clinicalsignificance")):
        lines.append(f"Clinical significance: {variant['clinicalsignificance']}.")
    if not _blank(variant.get("reviewstatus")):
        lines.append(
            f"Review status: {variant['reviewstatus']} ({variant['numbersubmitters']} submitters)."
        )
    if not _blank(variant.get("lastevaluated")):
        lines.append(f"Last evaluated: {variant['lastevaluated']}.")
    if previous_significance is not None:
        previous, closed_on = previous_significance
        lines.append(f"Classification history: previously {previous} until {closed_on}.")
    if diseases:
        rendered = [_format_disease(disease) for disease in diseases]
        lines.append(f"Associated conditions: {format_list(rendered, MAX_DISEASES)}.")
    if phenotypes:
        lines.append(f"Related phenotypes (HPO): {format_list(phenotypes, MAX_PHENOTYPES)}.")
    return "\n".join(lines)


def render_gene_document(gene: dict, diseases: list[str], phenotypes: list[str]) -> str:
    """Rend le texte anglais d'un document gène (fonction pure)."""
    lines = [
        f"Gene {gene['gene_symbol']} ({gene.get('description') or gene['gene_symbol']}), "
        f"location {gene.get('maplocation') or 'unknown'}.",
    ]
    if gene.get("summary"):
        lines.append(_truncate_summary(gene["summary"]))
    if diseases:
        lines.append(f"Associated conditions: {format_list(diseases, MAX_DISEASES)}.")
    if phenotypes:
        lines.append(f"Related phenotypes (HPO): {format_list(phenotypes, MAX_PHENOTYPES)}.")
    return "\n".join(lines)


def documents_uri(lake_uri: str | None = None) -> str:
    """Renvoie l'URI de la table `gold/rag/documents`."""
    return f"{layer_uri('gold', lake_uri=lake_uri)}/rag/documents"


def _previous_significance(variants: pl.DataFrame) -> dict[str, tuple[str, str]]:
    """Renvoie, par variant reclassé, la dernière signification différente de l'actuelle et sa date de fin."""
    closed = variants.filter(pl.col("valid_to").is_not_null())
    if closed.is_empty():
        return {}
    # Ordre stable : un choix instable ferait varier le texte, donc le hash du document.
    latest = (
        closed.sort("valid_to", maintain_order=True)
        .group_by("alleleid", maintain_order=True)
        .last()
    )
    current = dict(
        variants.filter(pl.col("is_current"))
        .select("alleleid", "clinicalsignificance")
        .iter_rows()
    )
    return {
        row["alleleid"]: (row["clinicalsignificance"], row["valid_to"])
        for row in latest.iter_rows(named=True)
        if row["clinicalsignificance"] != current.get(row["alleleid"])
    }


def _phenotypes_by_disease(hpo_gene_phenotype: pl.DataFrame) -> dict[tuple[str, str], list[str]]:
    """Associe (gène, `OMIM:`/`ORPHA:` maladie) aux noms de phénotypes, triés par identifiant HPO."""
    mapping: dict[tuple[str, str], list[str]] = {}
    for row in hpo_gene_phenotype.sort("hpo_id").iter_rows(named=True):
        key = (row["gene_symbol"], row["disease_id"])
        mapping.setdefault(key, []).append(row["hpo_name"])
    return mapping


def build_documents(logical_date: str, panel: str, lake_uri: str | None = None) -> pl.DataFrame:
    """Construit un document par variant courant, plus un par gène du panel."""
    variants = read_silver("clinvar_variant", panel, lake_uri)
    variant_gene = read_silver("clinvar_variant_gene", panel, lake_uri)
    variant_disease = read_silver("clinvar_variant_disease", panel, lake_uri)
    inheritance = read_silver("medgen_inheritance", panel, lake_uri)
    genes_table = read_silver("ncbi_gene", panel, lake_uri)
    gene_phenotype = read_silver("hpo_gene_phenotype", panel, lake_uri)

    history = _previous_significance(variants)
    current = variants.filter(pl.col("is_current"))
    gene_of = dict(variant_gene.select("alleleid", "gene_symbol").iter_rows())
    # Tous les modes d'une maladie, triés, comme `dim_disease` : un `dict` des lignes ne gardait
    # que le dernier lu, donc un mode choisi par l'ordre des lignes (défaut D-E3b-4).
    inheritance_of = dict(
        inheritance.group_by("cui")
        .agg(pl.col("mode_inheritance").drop_nulls().unique().sort().str.join("; "))
        .filter(pl.col("mode_inheritance") != "")
        .iter_rows()
    )
    phenotypes_of = _phenotypes_by_disease(gene_phenotype)

    diseases_of: dict[str, list[dict]] = {}
    # Tri stable : un ordre instable ferait varier le texte, donc le hash du document.
    for row in variant_disease.sort("disease_name", "medgen_cui", maintain_order=True).iter_rows(
        named=True
    ):
        diseases_of.setdefault(row["alleleid"], []).append({
            "disease_name": row["disease_name"],
            "omim_id": row["omim_id"],
            "orpha_id": row["orpha_id"],
            "mode_inheritance": inheritance_of.get(row["medgen_cui"]),
        })

    source_version = logical_date[:7]
    rows = []
    for variant in current.iter_rows(named=True):
        allele = variant["alleleid"]
        gene_symbol = gene_of.get(allele, variant["genesymbol"])
        diseases = diseases_of.get(allele, [])
        phenotypes: list[str] = []
        for disease in diseases:
            for prefix, key in (("OMIM:", "omim_id"), ("ORPHA:", "orpha_id")):
                if disease[key]:
                    phenotypes += phenotypes_of.get((gene_symbol, f"{prefix}{disease[key]}"), [])
        phenotypes = sorted(dict.fromkeys(phenotypes))
        text = render_variant_document(
            {**variant, "gene_symbol": gene_symbol}, diseases, phenotypes, history.get(allele)
        )
        rows.append({
            "doc_id": f"clinvar:{allele}", "chunk_id": chunk_id(text), "doc_type": "variant",
            "text": text, "gene_symbol": gene_symbol,
            "clinical_significance": variant["clinicalsignificance"],
            "review_status": variant["reviewstatus"],
            "rs_dbsnp": variant["rs_dbsnp"], "hgvs_c": variant["hgvs_c"],
            "hgvs_p": variant["hgvs_p"], "clinvar_variation_id": variant["variationid"],
            "clinvar_url": CLINVAR_VARIATION_URL.format(variation_id=variant["variationid"]),
            "source_version": source_version, "collected_at": logical_date, "panel": panel,
        })

    gene_rows = {row["gene_symbol"]: row for row in genes_table.iter_rows(named=True)}
    for gene_symbol in PANEL_GENES[panel]:
        gene = gene_rows.get(gene_symbol, {"gene_symbol": gene_symbol})
        gene_diseases = sorted({
            disease["disease_name"]
            for allele, diseases in diseases_of.items()
            for disease in diseases
            if gene_of.get(allele) == gene_symbol and disease["disease_name"]
        })
        gene_phenotypes = sorted({
            name
            for (symbol, _), names in phenotypes_of.items() if symbol == gene_symbol
            for name in names
        })
        text = render_gene_document({**gene, "gene_symbol": gene_symbol}, gene_diseases, gene_phenotypes)
        rows.append({
            "doc_id": f"gene:{gene_symbol}", "chunk_id": chunk_id(text), "doc_type": "gene",
            "text": text, "gene_symbol": gene_symbol, "clinical_significance": None,
            "review_status": None, "rs_dbsnp": None, "hgvs_c": None, "hgvs_p": None,
            "clinvar_variation_id": None, "clinvar_url": None,
            "source_version": source_version, "collected_at": logical_date, "panel": panel,
        })

    return pl.DataFrame(rows, schema=_DOCUMENT_SCHEMA)


# Schéma explicite : une colonne entièrement nulle serait typée `Null` et ferait échouer le MERGE.
_DOCUMENT_SCHEMA = {
    "doc_id": pl.Utf8, "chunk_id": pl.Utf8, "doc_type": pl.Utf8, "text": pl.Utf8,
    "gene_symbol": pl.Utf8, "clinical_significance": pl.Utf8, "review_status": pl.Utf8,
    "rs_dbsnp": pl.Int64, "hgvs_c": pl.Utf8, "hgvs_p": pl.Utf8,
    "clinvar_variation_id": pl.Utf8, "clinvar_url": pl.Utf8, "source_version": pl.Utf8,
    "collected_at": pl.Utf8, "panel": pl.Utf8,
}


def write_documents(documents: pl.DataFrame, panel: str, lake_uri: str | None = None) -> None:
    """Fusionne les documents du panel sur `doc_id` : inchangés non réécrits, disparus supprimés."""
    uri = documents_uri(lake_uri)
    options = storage_options(uri)
    if not DeltaTable.is_deltatable(uri, storage_options=options):
        documents.write_delta(
            uri, mode="overwrite", storage_options=options,
            delta_write_options={"partition_by": ["panel"]},
        )
        return

    merger = documents.write_delta(
        uri, mode="merge", storage_options=options,
        delta_merge_options={
            "predicate": "target.doc_id = source.doc_id AND target.panel = source.panel",
            "source_alias": "source", "target_alias": "target",
        },
    )
    (
        merger.when_matched_update(
            updates={column: f"source.{column}" for column in _DOCUMENT_SCHEMA},
            predicate="target.chunk_id <> source.chunk_id",
        )
        .when_not_matched_insert_all()
        .when_not_matched_by_source_delete(predicate=f"target.panel = '{panel}'")
        .execute()
    )


def silver_to_gold_rag(logical_date: str, panel: str, lake_uri: str | None = None) -> None:
    """Construit `gold/rag/documents` du panel depuis le Silver, sans nettoyage."""
    write_documents(build_documents(logical_date, panel, lake_uri), panel, lake_uri)
