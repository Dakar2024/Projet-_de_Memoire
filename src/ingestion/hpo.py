from __future__ import annotations

from pathlib import Path

from ingestion.download import download_to_file

GENES_TO_PHENOTYPE_URL = "https://purl.obolibrary.org/obo/hp/hpoa/genes_to_phenotype.txt"


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
