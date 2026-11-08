# Projets similaires — références à consulter

Recherche faite le 06/11/2026. Aucun projet ne reprend exactement la combinaison du nôtre
(données génomiques publiques + médaillon raw → bronze → silver → gold + Airflow / MinIO /
Delta Lake + RAG en bout de chaîne). Les références sont donc regroupées par point commun.

> Liens issus de recherches : seules les descriptions et les extraits de README ont été lus,
> pas l'intégralité du code de chaque dépôt.

## 1. Mêmes sources de données (ClinVar, HPO, NCBI, MedGen) — le plus utile

| Projet | Pourquoi le regarder |
|---|---|
| [monarch-initiative/clinvar-ingest](https://github.com/monarch-initiative/clinvar-ingest) | Pipeline d'ingestion ClinVar professionnel ; gère les liens entre identifiants HPO, MedGen, OMIM et MONDO, proche de notre travail de jointure en Silver. |
| [monarch-initiative/monarch-phenotype-profile-ingest](https://github.com/monarch-initiative/monarch-phenotype-profile-ingest) | Ingestion des annotations HPO (fichier HPOA), à comparer avec notre traitement HPO. |
| [Doc monarch-ingest](https://monarch-initiative.github.io/monarch-documentation/Repositories/monarch-ingest/) et [fiche ClinVar](https://monarch-app.monarchinitiative.org/Sources/clinvar/) | Expliquent, source par source, comment les données sont transformées ; bon modèle pour documenter nos couches dans le mémoire. |
| [monarch-initiative/dipper](https://github.com/monarch-initiative/dipper) | Ancien pipeline de Monarch, un script par source comme nos `scripts/ingest_*.py` ; intéressant pour comprendre pourquoi ils l'ont remplacé par l'outil Koza. |
| [Open Targets — pipeline de données](https://platform-docs.opentargets.org/data-access/data-pipeline) | Pipeline génomique en production orchestré par **Airflow**, découpé en acquisition → transformation → publication ; la référence « industrielle » la plus proche de notre orchestration. |

## 2. Même architecture technique (médaillon, Airflow, MinIO, Delta Lake)

| Projet | Pourquoi le regarder |
|---|---|
| [sambett/spotify](https://github.com/sambett/spotify) | Médaillon bronze/silver/gold sur **Spark + Delta Lake + MinIO**, avec Docker Compose ; techniquement le plus proche du nôtre. |
| [adarsxh/nyc-taxi-de-pipeline](https://github.com/adarsxh/nyc-taxi-de-pipeline) | Médaillon Delta + Airflow, traitement incrémental et **alertes e-mail** ; à comparer avec notre traitement « mois en cours » et nos alertes Resend. |
| [vutrinh274/local_lakehouse](https://github.com/vutrinh274/local_lakehouse) | MinIO + Iceberg + Nessie + Trino + dbt + Airflow ; utile pour justifier dans le mémoire le choix de Delta Lake plutôt qu'Iceberg. |
| [caesarmario/dibimbing-case-study-etl](https://github.com/caesarmario/dibimbing-case-study-etl) | Airflow + MinIO, DAG **rejouables** (idempotents) et contrôles qualité simples ; petit projet, facile à lire. |
| [Article Medium — Airflow + Spark + Iceberg sur MinIO](https://medium.com/@hufs0529/building-a-scalable-medallion-pipeline-airflow-spark-and-apache-iceberg-328dd05c68bd) | Explication du médaillon complet sur MinIO, avec le lien vers le dépôt. |

## 3. Génomique + IA (partie RAG, en complément)

| Projet | Pourquoi le regarder |
|---|---|
| [eduramosalves/variantscribe](https://github.com/eduramosalves/variantscribe) | RAG + LLM pour interpréter des variants, **évalué par rapport aux classifications ClinVar** ; très proche de notre évaluation E3. |
| [natecostello/genechat-mcp](https://github.com/natecostello/genechat-mcp) | Assistant appuyé sur ClinVar, avec une section sur la vérification des réponses du LLM. |
| [exon-research/genomi](https://github.com/exon-research/genomi) | Outils spécialisés par source (ClinVar, HPO, GWAS…). |

## Par où commencer (partie pipeline)

1. `clinvar-ingest` et la doc Open Targets pour le métier génomique.
2. `sambett/spotify` pour l'architecture technique.

Points de comparaison à relever dans chaque projet :

- comment sont gérées les mises à jour mensuelles des sources ;
- où se trouvent les contrôles qualité entre les couches (chez nous, le Silver est contrôlé avant écriture) ;
- comment ils garantissent qu'une source déjà traitée n'est pas ingérée deux fois (idempotence).
