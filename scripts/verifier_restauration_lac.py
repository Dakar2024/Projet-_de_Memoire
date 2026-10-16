"""Compare les tables Delta d'un lac restauré à celles de sa sauvegarde : mêmes tables, mêmes nombres de lignes."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import polars as pl

from ingestion.storage import find_delta_tables, layer_uri, storage_options

# Seules couches en Delta ; `raw` et `bronze` sont comparées octet par octet par le script shell.
DELTA_LAYERS = ("silver", "gold")


def _tables_by_name(lake: str, layer: str) -> dict[str, str]:
    """Indexe les tables Delta d'une couche par leur chemin relatif (`gold/rag/documents`)."""
    root = layer_uri(layer, lake)
    return {f"{layer}{uri[len(root):]}": uri for uri in find_delta_tables(root)}


def _row_count(uri: str) -> int:
    """Compte les lignes de la version courante d'une table, sans la charger."""
    return pl.scan_delta(uri, storage_options=storage_options(uri)).select(pl.len()).collect().item()


def compare_lakes(restored_lake: str, reference_lake: str) -> list[str]:
    """Renvoie les écarts, triés par table, entre lac restauré et sauvegarde (absence, nombre de lignes)."""
    gaps: list[str] = []
    for layer in DELTA_LAYERS:
        restored = _tables_by_name(restored_lake, layer)
        reference = _tables_by_name(reference_lake, layer)
        for name in sorted(restored.keys() | reference.keys()):
            if name not in restored:
                gaps.append(f"{name} : absente du lac restauré")
            elif name not in reference:
                gaps.append(f"{name} : absente de la sauvegarde")
            else:
                try:
                    restored_rows, reference_rows = _row_count(restored[name]), _row_count(reference[name])
                except Exception as exc:  # noqa: BLE001 — toute erreur de lecture est un écart, nommé et compté
                    gaps.append(f"{name} : illisible ({type(exc).__name__} : {str(exc).splitlines()[0][:120]})")
                    continue
                if restored_rows != reference_rows:
                    gaps.append(f"{name} : {restored_rows} lignes restaurées, {reference_rows} sauvegardées")
    return sorted(gaps)


def main() -> int:
    """Affiche les écarts et renvoie 1 s'il y en a, 0 sinon (code de sortie du script shell)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restaure", required=True, help="racine du lac restauré (ex. s3://)")
    parser.add_argument("--sauvegarde", required=True, help="racine de la sauvegarde (ex. file:///sauvegarde)")
    args = parser.parse_args()
    tables = sum(len(_tables_by_name(args.sauvegarde, layer)) for layer in DELTA_LAYERS)
    gaps = compare_lakes(args.restaure, args.sauvegarde)
    for gap in gaps:
        print(f"   ÉCART  {gap}")
    if not gaps:
        print(f"   OK     {tables} tables Delta relues, nombres de lignes identiques")
    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
