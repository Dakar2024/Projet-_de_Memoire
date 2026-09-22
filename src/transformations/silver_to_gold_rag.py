"""Passage silver -> gold/rag : un document textuel par variant et par gène.
Voir docs/superpowers/specs/2026-09-22-sous-projet-d-silver-gold-design.md.

Les fonctions de rendu ci-dessous sont pures (aucune E/S, aucune lecture du lac) :
c'est le gabarit, la partie la plus sujette aux retouches, qui doit être testable
sans lac. L'orchestration (lecture du Silver, écriture Delta par `MERGE`) est la
tâche 4 du sous-projet D et vit dans `silver_to_gold_rag` ci-dessous, qui reste un
stub tant que cette tâche n'est pas faite.
"""

from __future__ import annotations

import hashlib

import polars as pl
from deltalake import DeltaTable

from ingestion.config import PANEL_GENES
from ingestion.storage import layer_uri, storage_options
from transformations.silver_io import read_silver

# BioBERT tronque au-delà de 512 tokens : un document plus long serait vectorisé
# amputé, sans erreur visible. Ces plafonds sont à revoir si le modèle change.
MAX_DISEASES = 5
MAX_PHENOTYPES = 10

# Le contrôle qualité Gold (tâche 7) rejette tout texte de document de plus de
# 2000 caractères. Le plus long résumé NCBI réel de ce panel fait 1253 caractères ;
# ajouté à l'en-tête, à 5 maladies et à 10 phénotypes, cela ne laisserait aucune
# marge. La troncature est déterministe (coupe sur une frontière de mot) : la même
# entrée produit toujours le même texte, car le SHA-256 du document (`chunk_id`)
# sert à décider si l'étape RAG doit ré-embedder.
MAX_SUMMARY_CHARS = 800

CLINVAR_VARIATION_URL = "https://www.ncbi.nlm.nih.gov/clinvar/variation/{variation_id}/"


def chunk_id(text: str) -> str:
    """Hash déterministe du contenu : il change si et seulement si le texte change,
    ce qui permet à l'étape RAG de ne ré-embedder que les documents modifiés."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def format_list(values: list[str], cap: int) -> str:
    """Joint jusqu'à `cap` valeurs, et dit combien ont été omises."""
    if not values:
        return ""
    kept = "; ".join(values[:cap])
    remainder = len(values) - cap
    return f"{kept}; and {remainder} more" if remainder > 0 else kept


def _format_disease(disease: dict) -> str:
    details = []
    if disease.get("omim_id"):
        details.append(f"OMIM {disease['omim_id']}")
    if disease.get("mode_inheritance"):
        details.append(f"inheritance: {disease['mode_inheritance']}")
    name = disease.get("disease_name") or "unnamed condition"
    return f"{name} ({', '.join(details)})" if details else name


def _truncate_summary(summary: str) -> str:
    """Coupe `summary` à `MAX_SUMMARY_CHARS` caractères au plus, sur une frontière de
    mot, suivi de " …" quand une coupe a eu lieu. Déterministe : dépend uniquement de
    `summary`, jamais d'un état externe (horloge, aléa, ordre d'itération).

    Cas limite explicite : si les `MAX_SUMMARY_CHARS` premiers caractères ne
    contiennent aucun espace (liste d'identifiants, texte sans espaces,
    enregistrement malformé...), il n'existe aucune frontière de mot à respecter
    dans la fenêtre autorisée ; on coupe alors au caractère `MAX_SUMMARY_CHARS`
    tel quel plutôt que de chercher au-delà (ce qui romprait le plafond de
    longueur). C'est un choix assumé, pas un repli silencieux : la coupe reste au
    plus stricte à `MAX_SUMMARY_CHARS` caractères dans tous les cas."""
    if len(summary) <= MAX_SUMMARY_CHARS:
        return summary
    cut = summary[:MAX_SUMMARY_CHARS]
    last_space = cut.rfind(" ")
    if last_space != -1:
        cut = cut[:last_space]
    # Sinon (`last_space == -1`) : pas d'espace trouvé, coupe brute assumée au
    # caractère `MAX_SUMMARY_CHARS` — voir la docstring ci-dessus.
    return f"{cut} …"


def render_variant_document(
    variant: dict,
    diseases: list[dict],
    phenotypes: list[str],
    previous_significance: tuple[str, str] | None,
) -> str:
    """Texte anglais d'un document `variant`. Fonction pure : aucune E/S, pour que le
    gabarit — la partie la plus sujette aux retouches — soit testable sans lac."""
    lines = [
        f"Variant {variant['name']}, gene {variant['gene_symbol']}, "
        f"chromosome {variant['cytogenetic']}.",
        f"dbSNP rs{variant['rs_dbsnp']}. ClinVar Variation ID {variant['variationid']}. "
        f"Type: {variant['type']}.",
        f"Clinical significance: {variant['clinicalsignificance']}.",
        f"Review status: {variant['reviewstatus']} ({variant['numbersubmitters']} submitters).",
        f"Last evaluated: {variant['lastevaluated']}.",
    ]
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
    return f"{layer_uri('gold', lake_uri=lake_uri)}/rag/documents"


def _previous_significance(variants: pl.DataFrame) -> dict[str, tuple[str, str]]:
    """Dernière signification clôturée de chaque alleleid, d'après l'historique SCD2.
    Un variant jamais reclassé est absent du dictionnaire."""
    closed = variants.filter(pl.col("valid_to").is_not_null())
    if closed.is_empty():
        return {}
    latest = closed.sort("valid_to").group_by("alleleid").last()
    return {
        row["alleleid"]: (row["clinicalsignificance"], row["valid_to"])
        for row in latest.iter_rows(named=True)
    }


def _phenotypes_by_disease(hpo_gene_phenotype: pl.DataFrame) -> dict[tuple[str, str], list[str]]:
    """(gène, identifiant de maladie) -> noms de phénotypes, triés. `disease_id` est
    préfixé `OMIM:` ou `ORPHA:` — les deux formes existent dans HPO."""
    mapping: dict[tuple[str, str], list[str]] = {}
    for row in hpo_gene_phenotype.sort("hpo_id").iter_rows(named=True):
        key = (row["gene_symbol"], row["disease_id"])
        mapping.setdefault(key, []).append(row["hpo_name"])
    return mapping


def build_documents(logical_date: str, panel: str, lake_uri: str | None = None) -> pl.DataFrame:
    """Un document par variant courant, plus un par gène du panel."""
    variants = read_silver("clinvar_variant", panel, lake_uri)
    variant_gene = read_silver("clinvar_variant_gene", panel, lake_uri)
    variant_disease = read_silver("clinvar_variant_disease", panel, lake_uri)
    inheritance = read_silver("medgen_inheritance", panel, lake_uri)
    genes_table = read_silver("ncbi_gene", panel, lake_uri)
    gene_phenotype = read_silver("hpo_gene_phenotype", panel, lake_uri)

    history = _previous_significance(variants)
    current = variants.filter(pl.col("is_current"))
    gene_of = dict(variant_gene.select("alleleid", "gene_symbol").iter_rows())
    inheritance_of = dict(inheritance.select("cui", "mode_inheritance").iter_rows())
    phenotypes_of = _phenotypes_by_disease(gene_phenotype)

    diseases_of: dict[str, list[dict]] = {}
    for row in variant_disease.sort("disease_name", "medgen_cui").iter_rows(named=True):
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


# Schéma explicite : sans lui, une colonne entièrement nulle (rs_dbsnp sur un run
# sans variant, par exemple) serait typée Null et ferait échouer le MERGE.
_DOCUMENT_SCHEMA = {
    "doc_id": pl.Utf8, "chunk_id": pl.Utf8, "doc_type": pl.Utf8, "text": pl.Utf8,
    "gene_symbol": pl.Utf8, "clinical_significance": pl.Utf8, "review_status": pl.Utf8,
    "rs_dbsnp": pl.Int64, "hgvs_c": pl.Utf8, "hgvs_p": pl.Utf8,
    "clinvar_variation_id": pl.Utf8, "clinvar_url": pl.Utf8, "source_version": pl.Utf8,
    "collected_at": pl.Utf8, "panel": pl.Utf8,
}


def write_documents(documents: pl.DataFrame, panel: str, lake_uri: str | None = None) -> None:
    """`MERGE` sur `doc_id`, restreint au panel : un document inchangé n'est pas
    réécrit, un document disparu du Silver est supprimé. Vérifié à la main sur
    delta-rs 1.6.3, y compris l'absence de nouvelle version Delta sur un rejeu."""
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
    """Construit `gold/rag/documents` pour ce panel. Lit le Silver, jamais
    `gold/analytique`. Ne nettoie rien : une donnée incorrecte se corrige dans
    `bronze_to_silver`."""
    write_documents(build_documents(logical_date, panel, lake_uri), panel, lake_uri)
