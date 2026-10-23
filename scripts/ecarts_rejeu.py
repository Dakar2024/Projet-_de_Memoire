"""Écarts d'un lac après rejeu, par rapport à sa copie d'avant : lignes ajoutées et retirées, par table.

Critères R4 à R6 de la spec E3b : bronze et tables Delta (Silver, Gold) du mois rejoué, colonnes
techniques du bronze exclues. Usage, dans l'image Airflow sur le réseau de la pile rejouée :
  python scripts/ecarts_rejeu.py --lac s3:// --copie file:///sauvegarde --date 2026-10-01
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl
from deltalake import DeltaTable

from ingestion.config import BRONZE, PANEL_GENES
from ingestion.storage import partition_uri, scan_parquet, storage_options
from scripts.verifier_restauration_lac import DELTA_LAYERS, tables_by_name

# Une seule définition : celle que bronze_to_silver retire déjà avant d'écrire le Silver.
from transformations.bronze_to_silver import _BRONZE_TECHNICAL_COLUMNS as TECHNICAL_COLUMNS

SHARED_SOURCES = ("clinvar", "hpo")
PANEL_SOURCES = ("ncbi_gene", "refseq", "medgen", "hpo_terms")


@dataclass(frozen=True)
class Ecart:
    ajoutees: int
    retirees: int
    schema: str = ""


def ecart_lignes(avant: pl.DataFrame | pl.LazyFrame, apres: pl.DataFrame | pl.LazyFrame) -> Ecart:
    """Compare deux tables comme des multiensembles de lignes (pas de clé commune à toutes les tables).

    Une ligne modifiée compte pour un retrait et un ajout. Seules les empreintes des lignes sont
    gardées, lot par lot : le bronze ClinVar (9,2 M lignes, 46 colonnes) tient ainsi sous 2 Gio.
    """
    avant, apres = avant.lazy(), apres.lazy()
    colonnes_avant = set(avant.collect_schema().names()) - set(TECHNICAL_COLUMNS)
    colonnes_apres = set(apres.collect_schema().names()) - set(TECHNICAL_COLUMNS)
    if colonnes_avant != colonnes_apres:
        parties = []
        if ajout := sorted(colonnes_apres - colonnes_avant):
            parties.append("colonnes ajoutées : " + ", ".join(ajout))
        if retrait := sorted(colonnes_avant - colonnes_apres):
            parties.append("colonnes retirées : " + ", ".join(retrait))
        return Ecart(ajoutees=0, retirees=0, schema="; ".join(parties))

    colonnes = sorted(colonnes_avant)

    def compte(lf: pl.LazyFrame, nom: str) -> pl.DataFrame:
        empreintes = [lot.select(pl.struct(colonnes).hash().alias("h")) for lot in lf.collect_batches(chunk_size=200_000)]
        frame = pl.concat(empreintes) if empreintes else pl.DataFrame(schema={"h": pl.UInt64})
        # Int64 : `pl.len()` est non signé, et `1 - 2` y déborderait au lieu de donner -1.
        return frame.group_by("h").agg(pl.len().cast(pl.Int64).alias(nom))

    joint = (
        compte(avant, "avant").join(compte(apres, "apres"), on="h", how="full", coalesce=True)
        .fill_null(0)
        .select(
            (pl.col("apres") - pl.col("avant")).clip(lower_bound=0).sum().alias("ajoutees"),
            (pl.col("avant") - pl.col("apres")).clip(lower_bound=0).sum().alias("retirees"),
        )
    )
    return Ecart(ajoutees=int(joint["ajoutees"][0]), retirees=int(joint["retirees"][0]))


def _version(uri: str) -> int:
    return DeltaTable(uri, storage_options=storage_options(uri)).version()


def _bronze_partitions(date: str) -> list[tuple[str, str | None]]:
    """(source, panel) des partitions bronze du mois : sources partagées, puis sources par panel."""
    return [(s, None) for s in SHARED_SOURCES] + [(s, p) for p in sorted(PANEL_GENES) for s in PANEL_SOURCES]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lac", required=True, help="racine du lac rejoué (ex. s3://)")
    parser.add_argument("--copie", required=True, help="racine de la copie d'avant le rejeu (ex. file:///sauvegarde)")
    parser.add_argument("--date", required=True, help="partition rejouée, AAAA-MM-01")
    args = parser.parse_args()

    print(f"== bronze dt={args.date} (colonnes techniques exclues : {', '.join(TECHNICAL_COLUMNS)})")
    for source, panel in _bronze_partitions(args.date):
        nom = f"bronze/{source}" + (f"/panel={panel}" if panel else "")
        avant = scan_parquet(partition_uri(BRONZE, source, args.date, panel=panel, lake_uri=args.copie) + "/*.parquet")
        apres = scan_parquet(partition_uri(BRONZE, source, args.date, panel=panel, lake_uri=args.lac) + "/*.parquet")
        _afficher(nom, ecart_lignes(avant, apres))

    for layer in DELTA_LAYERS:
        print(f"== {layer} (version courante de chaque table)")
        copie, lac = tables_by_name(args.copie, layer), tables_by_name(args.lac, layer)
        for nom in sorted(copie.keys() | lac.keys()):
            if nom not in copie or nom not in lac:
                print(f"   {nom:52} absente {'du lac rejoué' if nom not in lac else 'de la copie'}")
                continue
            ecart = ecart_lignes(
                pl.scan_delta(copie[nom], storage_options=storage_options(copie[nom])),
                pl.scan_delta(lac[nom], storage_options=storage_options(lac[nom])),
            )
            _afficher(nom, ecart, f"v{_version(copie[nom])} → v{_version(lac[nom])}")
    return 0


def _afficher(nom: str, ecart: Ecart, versions: str = "") -> None:
    detail = ecart.schema or f"+{ecart.ajoutees} -{ecart.retirees}"
    etat = "identique" if not ecart.schema and ecart.ajoutees == ecart.retirees == 0 else "DIFFÉRENT"
    print(f"   {nom:52} {versions:10} {etat:10} {detail}")


if __name__ == "__main__":
    raise SystemExit(main())
