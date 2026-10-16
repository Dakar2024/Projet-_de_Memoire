"""Exporte un modèle épinglé (safetensors, ONNX, export.json avec empreintes) pour rag-embeddings."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

PINNED_REVISIONS = {
    "NeuML/pubmedbert-base-embeddings": "b79526d6ef3645e0df4530322e266f24c829f5ef",
    "dmis-lab/biobert-base-cased-v1.2": "67c9c25b46986521ca33df05d8540da1210b3256",
}


def sha256(path: Path) -> str:
    """Calcule le SHA-256 d'un fichier, par blocs."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _previous(final: Path) -> Path:
    """Renvoie le dossier où l'ancien export attend pendant le remplacement."""
    return final.with_name(f".{final.name}.previous")


def restore_interrupted_swap(final: Path) -> None:
    """Remet en place l'ancien export si un remplacement s'est arrêté entre ses deux renommages."""
    previous = _previous(final)
    if previous.exists() and not final.exists():
        previous.rename(final)


def swap_in(partial: Path, final: Path) -> None:
    """Remplace l'export servi par deux renommages ; l'ancien n'est supprimé qu'une fois le nouveau en place."""
    previous = _previous(final)
    if previous.exists():
        shutil.rmtree(previous)
    if final.exists():
        final.rename(previous)
    partial.rename(final)
    if previous.exists():
        shutil.rmtree(previous)


def main() -> int:
    """Exporte dans un dossier temporaire puis le renomme : un export interrompu n'est jamais servi."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(PINNED_REVISIONS))
    parser.add_argument("--output-root", type=Path, default=Path("/models"))
    parser.add_argument("--force", action="store_true", help="remplace un export existant")
    args = parser.parse_args()
    # Imports lourds ici : le module reste importable par les tests sans optimum ni transformers.
    from optimum.exporters.onnx import main_export
    from transformers import AutoModel, AutoTokenizer

    revision = PINNED_REVISIONS[args.model]
    name = args.model.split("/", 1)[1]
    final = args.output_root / name
    partial = args.output_root / f".{name}.partial"
    restore_interrupted_swap(final)
    if final.exists() and not args.force:
        sys.exit(f"{final} existe déjà : relancer avec --force pour le remplacer")
    shutil.rmtree(partial, ignore_errors=True)

    model = AutoModel.from_pretrained(args.model, revision=revision)
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=revision)
    model.save_pretrained(partial, safe_serialization=True)
    tokenizer.save_pretrained(partial)
    main_export(model_name_or_path=str(partial), output=partial / "onnx", task="feature-extraction")

    files = {
        str(path.relative_to(partial)): sha256(path)
        for path in sorted(partial.rglob("*")) if path.is_file()
    }
    fingerprint = f"{args.model}@{revision[:12]}+onnx:{files['onnx/model.onnx'][:16]}"
    manifest = {"model_id": args.model, "revision": revision, "fingerprint": fingerprint, "files": files}
    (partial / "export.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    swap_in(partial, final)
    print(fingerprint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
