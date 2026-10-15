"""Fichier HPO genes_to_phenotype (release épinglée) et enrichissement des termes via ontology.jax.org."""
from __future__ import annotations

from pathlib import Path

import requests

from ingestion.download import download_to_file
from ingestion.http_client import build_retrying_session

GENES_TO_PHENOTYPE_URL = "https://purl.obolibrary.org/obo/hp/hpoa/genes_to_phenotype.txt"

# Le tag de la release courante est résolu puis épinglé : un rejeu retélécharge le même fichier.
HPO_LATEST_RELEASE_URL = (
    "https://github.com/obophenotype/human-phenotype-ontology/releases/latest"
)
HPO_RELEASE_URL_TEMPLATE = (
    "https://github.com/obophenotype/human-phenotype-ontology/releases/"
    "download/{release_tag}/genes_to_phenotype.txt"
)

# API publique sans clé : definition, synonyms et xrefs absents de genes_to_phenotype.txt.
HP_TERMS_URL = "https://ontology.jax.org/api/hp/terms"

# `filter` est limité à 250 caractères : 20 identifiants de 11 caractères laissent de la marge.
HP_TERMS_BATCH_SIZE = 20


class ReleaseTagResolutionError(RuntimeError):
    """GitHub n'a pas renvoyé la redirection attendue vers la release courante."""


def release_url_for(release_tag: str) -> str:
    """Renvoie l'URL de `genes_to_phenotype.txt` pour un tag de release."""
    return HPO_RELEASE_URL_TEMPLATE.format(release_tag=release_tag)


def resolve_release_tag(session: requests.Session | None = None) -> str:
    """Résout le tag de la release HPO courante via la redirection de `/releases/latest`."""
    session = session or build_retrying_session()
    response = session.get(HPO_LATEST_RELEASE_URL, allow_redirects=False, timeout=30)
    location = response.headers.get("Location")
    if not location:
        raise ReleaseTagResolutionError(
            f"{HPO_LATEST_RELEASE_URL} : réponse HTTP {response.status_code} sans en-tête "
            "Location — GitHub indisponible, en limitation de débit, ou format changé."
        )
    return location.rstrip("/").rsplit("/", 1)[-1]


def parse_genes_to_phenotype(path: Path, genes: list[str]) -> list[dict]:
    """Lit genes_to_phenotype.txt et garde les lignes des gènes cibles."""
    genes_set = set(genes)
    rows = []
    with open(path, encoding="utf-8") as fh:
        next(fh, None)  # en-tête
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            gene_symbol = parts[1]
            if gene_symbol not in genes_set:
                continue
            rows.append(
                {"gene_symbol": gene_symbol, "hpo_id": parts[2], "hpo_name": parts[3]}
            )
    return rows


def fetch_hpo_term_details(
    hpo_ids: list[str], session: requests.Session | None = None
) -> dict[str, dict]:
    """Récupère definition/synonyms/xrefs des IDs HPO dédoublonnés, par lots ; un terme retiré est absent."""
    session = session or build_retrying_session()
    unique_ids = list(dict.fromkeys(hpo_ids))
    details: dict[str, dict] = {}
    for start in range(0, len(unique_ids), HP_TERMS_BATCH_SIZE):
        batch = unique_ids[start : start + HP_TERMS_BATCH_SIZE]
        response = session.get(HP_TERMS_URL, params={"filter": ",".join(batch)}, timeout=30)
        response.raise_for_status()
        for term in response.json():
            details[term["id"]] = {
                "definition": term.get("definition", ""),
                "synonyms": term.get("synonyms", []),
                "xrefs": term.get("xrefs", []),
            }
    return details


def enrich_hpo_rows(rows: list[dict], term_details: dict[str, dict]) -> list[dict]:
    """Ajoute definition/synonyms/xrefs à chaque ligne HPO ; champs vides si le terme est inconnu."""
    enriched = []
    for row in rows:
        details = term_details.get(row["hpo_id"], {})
        enriched.append(
            {
                **row,
                "definition": details.get("definition", ""),
                "synonyms": details.get("synonyms", []),
                "xrefs": details.get("xrefs", []),
            }
        )
    return enriched


def download_file(url: str, destination: Path, force: bool = False) -> Path:
    """Télécharge un fichier public HPO (pas de clé, pas de rate limit)."""
    return download_to_file(url, destination, force=force)


def download_hpo_files(destination_dir: Path, force: bool = False) -> dict[str, Path]:
    """Télécharge les fichiers HPO utilisés par la collecte (`phenotype.hpoa` n'est consommé par rien)."""
    return {
        "genes_to_phenotype": download_file(
            GENES_TO_PHENOTYPE_URL, destination_dir / "genes_to_phenotype.txt", force=force
        ),
    }
