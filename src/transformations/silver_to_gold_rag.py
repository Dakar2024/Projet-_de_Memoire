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

from transformations import SPEC

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


def silver_to_gold_rag(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Construit `gold/rag/` (Delta) : un document par variant pour le RAG.

    Chaque document porte le contexte du gène, des maladies et des phénotypes, et ses
    références de citation (accession ClinVar, version, date de collecte).
    `chunk_id` est un hash déterministe du contenu, pour ne ré-embedder par `MERGE`
    que les documents modifiés. Lit le Silver, jamais `gold/analytique/`.

    Interdit : nettoyer. Le Silver est la seule couche qui nettoie ; une donnée qui
    arrive ici incorrecte se corrige dans `bronze_to_silver`, pas dans le Gold.
    """
    raise NotImplementedError(f"silver_to_gold_rag : implémenté par le sous-projet D ({SPEC}, §7)")
