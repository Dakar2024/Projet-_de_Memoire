"""Passages entre les couches du médaillon. `raw_to_bronze` livré (sous-projet B) ;
`bronze_to_silver`/`silver_to_gold_rag`/`silver_to_gold_analytique` restent des stubs
(sous-projets C et D)."""

# Référence commune des messages d'erreur. Elle vit dans le paquet et non dans un
# module de transformation : le sous-projet B réécrira raw_to_bronze.py, et les stubs
# de C et D ne doivent pas casser à cette occasion.
SPEC = "docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md"
