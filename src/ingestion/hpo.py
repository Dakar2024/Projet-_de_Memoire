from __future__ import annotations

from pathlib import Path

from ingestion.download import download_to_file

GENES_TO_PHENOTYPE_URL = "https://purl.obolibrary.org/obo/hp/hpoa/genes_to_phenotype.txt"
PHENOTYPE_HPOA_URL = "https://purl.obolibrary.org/obo/hp/hpoa/phenotype.hpoa"


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
    """Télécharge les deux fichiers HPO publics dans `destination_dir`."""
    return {
        "genes_to_phenotype": download_file(
            GENES_TO_PHENOTYPE_URL, destination_dir / "genes_to_phenotype.txt", force=force
        ),
        "phenotype_hpoa": download_file(
            PHENOTYPE_HPOA_URL, destination_dir / "phenotype.hpoa", force=force
        ),
    }
