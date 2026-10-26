"""Refuse une configuration de la pile isolée qui partagerait un nom, un port ou des données avec la principale.

Usage (racine du dépôt) :
  docker compose -p genomique-e3b -f docker-compose.yml -f docker/e3b/docker-compose.e3b.yml \
    --env-file .env config --format json | python3 docker/e3b/verifier_isolation.py
"""
from __future__ import annotations

import json
import sys

PROJET = "genomique-e3b"
PORTS_AUTORISES = {("127.0.0.1", "8081")}
SOUS_RESEAUX_PRINCIPAUX = {"172.31.250.0/24", "172.31.251.0/24"}
DONNEES = "/opt/projet/data"


def ecarts(config: dict) -> list[str]:
    """Renvoie un message par fuite vers la pile principale ; liste vide si la pile est isolée."""
    trouves = []
    if config.get("name") != PROJET:
        trouves.append(f"projet {config.get('name')!r} au lieu de {PROJET!r}")
    for nom, service in config.get("services", {}).items():
        conteneur = service.get("container_name")
        # Les outils à la demande n'ont pas de nom fixe : Compose les préfixe par le projet.
        if conteneur is not None and not conteneur.startswith(f"{PROJET}-"):
            trouves.append(f"{nom} : conteneur {conteneur!r}")
        for port in service.get("ports", []):
            publie = (port.get("host_ip", ""), str(port.get("published", "")))
            if publie not in PORTS_AUTORISES:
                trouves.append(f"{nom} : port publié {publie[0]}:{publie[1]}")
        for montage in service.get("volumes", []):
            if montage.get("target") == DONNEES and not montage.get("source", "").endswith("/data/e3b"):
                trouves.append(f"{nom} : {DONNEES} monté depuis {montage.get('source')!r}")
    for nom, volume in config.get("volumes", {}).items():
        if not volume.get("name", "").startswith(f"{PROJET}_"):
            trouves.append(f"volume {nom} : {volume.get('name')!r}")
    for nom, reseau in config.get("networks", {}).items():
        if not reseau.get("name", "").startswith(f"{PROJET}_"):
            trouves.append(f"réseau {nom} : {reseau.get('name')!r}")
        for bloc in (reseau.get("ipam") or {}).get("config", []):
            if bloc.get("subnet") in SOUS_RESEAUX_PRINCIPAUX:
                trouves.append(f"réseau {nom} : sous-réseau {bloc['subnet']} de la pile principale")
    return trouves


if __name__ == "__main__":
    problemes = ecarts(json.load(sys.stdin))
    for probleme in problemes:
        print(f"FUITE  {probleme}")
    if problemes:
        sys.exit(1)
    print("isolée : aucun nom, port, volume, réseau ni dossier de données partagé avec la pile principale")
