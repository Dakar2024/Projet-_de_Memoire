"""Passages entre les couches du médaillon (stubs tant que les sous-projets B à D
ne sont pas livrés)."""

# Référence commune des messages d'erreur. Elle vit dans le paquet et non dans un
# module de transformation : le sous-projet B réécrira raw_to_bronze.py, et les stubs
# de C et D ne doivent pas casser à cette occasion.
SPEC = "docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md"
