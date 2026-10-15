"""Canari : vérifie, avant chaque indexation, que le service sert bien le modèle
attendu.

Le service ne renvoie pas l'empreinte du modèle qu'il sert (`/info` indique
seulement `"model_id": "/model"`). La seule vérification de bout en bout consiste à
vectoriser des phrases fixes et à comparer le résultat à des vecteurs de référence,
produits une fois par le modèle validé. Trois phrases plutôt qu'une : un seul texte
pourrait, par hasard, rester proche d'un modèle à l'autre.

Le canari prouve que le service sert **le même modèle que la référence**. L'identité de
la référence, elle, tient à l'égalité vérifiée entre l'empreinte de `export.json` du
dossier servi et celle de `config.yaml` (`check_served_model`), contrôlée à la
production du canari comme avant chaque indexation.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from RAG.src.embeddings.embedder import EMBEDDING_DIM, EmbeddingClient
from RAG.src.utils.config import (
    check_served_model,
    load_config,
    load_service_settings,
    served_fingerprint,
)
from RAG.src.utils.errors import CanaryMismatchError, RagConfigurationError

CANARY_PHRASES: tuple[str, ...] = (
    "BRCA1 pathogenic variant associated with hereditary breast and ovarian cancer syndrome.",
    "Sickle cell disease caused by the HBB Glu6Val substitution.",
    "Variant of uncertain significance in the PALB2 gene.",
)


@dataclass(frozen=True)
class Canary:
    fingerprint: str
    phrases: tuple[str, ...]
    vectors: np.ndarray


def build_canary(client, fingerprint: str) -> Canary:
    return Canary(fingerprint, CANARY_PHRASES, client.embed(list(CANARY_PHRASES)))


def canary_to_json(canary: Canary) -> str:
    return json.dumps(
        {
            "fingerprint": canary.fingerprint,
            "phrases": list(canary.phrases),
            "vectors": canary.vectors.astype(float).tolist(),
        },
        indent=1,
    )


def load_canary(path: Path) -> Canary:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        phrases = tuple(str(p) for p in raw["phrases"])
        vectors = np.asarray(raw["vectors"], dtype=np.float32)
        fingerprint = str(raw["fingerprint"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise RagConfigurationError(f"canari illisible ({path}) : {exc!r}") from exc
    if not phrases or vectors.shape != (len(phrases), EMBEDDING_DIM):
        raise RagConfigurationError(
            f"canari invalide ({path}) : {len(phrases)} phrases, vecteurs de forme {vectors.shape}"
        )
    return Canary(fingerprint, phrases, vectors)


def _row_cosines(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return (a * b).sum(axis=1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))


def verify_canary(client, canary: Canary, expected_fingerprint: str, min_cosine: float) -> float:
    """Renvoie le cosinus le plus faible, ou lève `CanaryMismatchError`."""
    if canary.fingerprint != expected_fingerprint:
        raise CanaryMismatchError(
            f"empreinte du canari « {canary.fingerprint} » différente de celle de "
            f"config.yaml « {expected_fingerprint} » : régénérer le canari (RAG/README.md)"
        )
    cosines = _row_cosines(client.embed(list(canary.phrases)), canary.vectors)
    if not np.all(np.isfinite(cosines)):
        raise CanaryMismatchError("cosinus non fini : le service renvoie des vecteurs dégénérés")
    worst = float(cosines.min())
    if worst < min_cosine:
        raise CanaryMismatchError(
            f"cosinus minimal {worst:.6f} < {min_cosine} : le service ne sert pas le modèle "
            f"« {expected_fingerprint} »"
        )
    return worst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Produit le canari du modèle servi, étiqueté de l'empreinte de son export.json."
    )
    parser.parse_args(argv)
    try:
        config = load_config()
        services = load_service_settings()
        fingerprint = served_fingerprint(services.served_model_dir)
        check_served_model(config.embedding.fingerprint, fingerprint)
    except RagConfigurationError as exc:
        sys.stderr.write(f"canari non produit : {exc}\n")
        return 1
    client = EmbeddingClient(services.embeddings_url, services.embeddings_api_key)
    sys.stdout.write(canary_to_json(build_canary(client, fingerprint)) + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
