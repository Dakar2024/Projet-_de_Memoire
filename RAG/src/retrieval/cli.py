"""Essai manuel d'une recherche : python -m RAG.src.retrieval.cli « Le variant rs80357906 est-il pathogène ? »"""
from __future__ import annotations

import argparse
import json
import sys

from RAG.src.retrieval.retriever import MODES, Searcher
from RAG.src.utils.errors import RagPermanentError


def main(argv: list[str] | None = None) -> int:
    """Affiche les documents retrouvés (texte tronqué) et la trace."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--mode", choices=MODES, default="full")
    parser.add_argument("--profile", default=None)
    args = parser.parse_args(argv)
    try:
        with Searcher(profile_name=args.profile) as searcher:
            result = searcher.search(args.question, mode=args.mode).as_dict()
    except RagPermanentError as exc:
        sys.stderr.write(f"recherche refusée : {exc}\n")
        return 1
    for document in result["documents"]:
        document["text"] = document["text"][:160]
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
