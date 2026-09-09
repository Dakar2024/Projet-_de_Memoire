from __future__ import annotations

from pathlib import Path

import requests

from ingestion.download import download_to_file
from ingestion.http_client import build_retrying_session

GENES_TO_PHENOTYPE_URL = "https://purl.obolibrary.org/obo/hp/hpoa/genes_to_phenotype.txt"

# HPO publie des releases taguées (`v2026-09-01`). La PURL pointe sur « latest »,
# qui change : on résout le tag une fois, on l'enregistre au manifest, et on
# télécharge l'URL taguée — un rejeu retéléchargera exactement le même fichier.
HPO_LATEST_RELEASE_URL = (
    "https://github.com/obophenotype/human-phenotype-ontology/releases/latest"
)
HPO_RELEASE_URL_TEMPLATE = (
    "https://github.com/obophenotype/human-phenotype-ontology/releases/"
    "download/{release_tag}/genes_to_phenotype.txt"
)

# Service public ontology.jax.org (sans clé) : détails d'un terme HPO (definition, synonyms,
# xrefs) — absents de genes_to_phenotype.txt, qui ne porte que l'id et le nom du terme.
HP_TERMS_URL = "https://ontology.jax.org/api/hp/terms"

# Le paramètre `filter` de cette API est limité à 250 caractères côté serveur (spec OpenAPI
# publiée sur /api/hp/docs) ; "HP:0000000," fait 11 caractères, 20 IDs par lot garde une
# marge confortable.
HP_TERMS_BATCH_SIZE = 20


def release_url_for(release_tag: str) -> str:
    """URL de téléchargement de `genes_to_phenotype.txt` pour un tag de release."""
    return HPO_RELEASE_URL_TEMPLATE.format(release_tag=release_tag)


def resolve_release_tag(session: requests.Session | None = None) -> str:
    """Résout le tag de la release HPO courante via la redirection de `/releases/latest`."""
    session = session or build_retrying_session()
    response = session.get(HPO_LATEST_RELEASE_URL, allow_redirects=False, timeout=30)
    location = response.headers["Location"]
    return location.rstrip("/").rsplit("/", 1)[-1]


def parse_genes_to_phenotype(path: Path, genes: list[str]) -> list[dict]:
    """Parse genes_to_phenotype.txt et filtre sur les gènes cibles."""
    genes_set = set(genes)
    rows = []
    with open(path, encoding="utf-8") as fh:
        next(fh, None)  # header (absent si le fichier est vide)
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
    """Récupère definition/synonyms/xrefs pour des IDs HPO, par lots de `HP_TERMS_BATCH_SIZE`.

    Les IDs sont dédupliqués avant l'appel — un même terme (ex. un HPO partagé par plusieurs
    gènes du panel) n'est demandé qu'une fois. Un ID que l'API ne reconnaît plus (terme
    retiré/fusionné côté HPO) est simplement absent du résultat plutôt que de faire échouer
    l'appel — géré côté appelant via `enrich_hpo_rows`.
    """
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
    """Ajoute definition/synonyms/xrefs à chaque ligne HPO à partir de `term_details`.

    Un `hpo_id` absent de `term_details` garde des champs d'enrichissement vides plutôt que
    de faire échouer l'assemblage — cohérent avec le traitement des CUI MedGen non résolus.
    """
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
    """Télécharge les fichiers HPO publics utilisés par la collecte dans `destination_dir`.

    `phenotype.hpoa` (annotations par maladie, ~35 Mo) n'est volontairement pas téléchargé :
    rien dans ce module ne le consomme, faute d'une jointure disease_id -> gène — l'ajouter
    reviendrait à payer un téléchargement pour rien. `genes_to_phenotype.txt` porte déjà un
    `disease_id` par ligne gène/HPO ; une future étape qui voudrait exploiter les fréquences
    et l'âge d'apparition de `phenotype.hpoa` pourra joindre dessus.
    """
    return {
        "genes_to_phenotype": download_file(
            GENES_TO_PHENOTYPE_URL, destination_dir / "genes_to_phenotype.txt", force=force
        ),
    }
