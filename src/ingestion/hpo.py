from __future__ import annotations

from pathlib import Path

import requests

GENES_TO_PHENOTYPE_URL = "https://purl.obolibrary.org/obo/hp/hpoa/genes_to_phenotype.txt"
PHENOTYPE_HPOA_URL = "https://purl.obolibrary.org/obo/hp/hpoa/phenotype.hpoa"


def parse_genes_to_phenotype(path: Path, genes: list[str]) -> list[dict]:
    """Parse genes_to_phenotype.txt et filtre sur les gènes cibles."""
    genes_set = set(genes)
    rows = []
    with open(path, encoding="utf-8") as fh:
        next(fh)  # header
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


def download_file(url: str, destination: Path) -> Path:
    """Télécharge un fichier public HPO (pas de clé, pas de rate limit)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def download_hpo_files(destination_dir: Path) -> dict[str, Path]:
    """Télécharge les deux fichiers HPO publics dans `destination_dir`."""
    return {
        "genes_to_phenotype": download_file(
            GENES_TO_PHENOTYPE_URL, destination_dir / "genes_to_phenotype.txt"
        ),
        "phenotype_hpoa": download_file(
            PHENOTYPE_HPOA_URL, destination_dir / "phenotype.hpoa"
        ),
    }
