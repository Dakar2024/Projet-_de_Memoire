# Contenu du mémoire — suivi de rédaction

Fichier de pilotage de la rédaction : où l'on en est, ce qui est écrit, validé, et ce qui reste.
Le cadre (question, objectifs, plan) est dans `reference/Problematique_Projet_RAG_Genomique.md`.

**Échéance :** 12 novembre 2026 — l'essentiel des chapitres rédigé et soumis au directeur.

## Légende

| Case | Signification |
|---|---|
| `[ ]` | À faire |
| `[~]` | Rédigé, en relecture par l'étudiant |
| `[x]` | Rédigé **et validé** par le directeur de mémoire |

Une section n'est cochée `[x]` qu'après validation du directeur. Chaque texte produit indique
l'emplacement où il est rangé (à fixer par l'étudiant).

---

## Vue d'ensemble

| Partie | État | Emplacement du texte | Soumis le | Validé le |
|---|---|---|---|---|
| Introduction générale | `[x]` (hors §3 Structure, à remplacer) | *à préciser* | — | avant le 06/11 |
| Chapitre 1 — État de l'art | `[ ]` plan proposé le 06/11 | *à préciser* | | |
| Chapitre 2 — Analyse des besoins et méthodologie | `[ ]` | | | |
| Chapitre 3 — Pipeline de données | `[ ]` | | | |
| Chapitre 4 — Système RAG | `[ ]` | | | |
| Chapitre 5 — Intégration, résultats et discussion | `[ ]` | | | |
| Conclusion générale | `[ ]` | | | |
| Résumé / Abstract | `[ ]` | | | |
| Bibliographie | `[ ]` (tenue au fil de l'eau, voir plus bas) | | | |

---

## Introduction générale

- [x] 1. Contexte et justification
- [x] Problématique
- [x] 2. Objectifs de la recherche (OS1 à OS4)
- [~] 3. Structure du mémoire — **à remplacer** par la version en 5 chapitres (texte proposé le 06/11)

## Chapitre 1 — État de l'art (plan proposé, à valider)

- [ ] 1.1 Le domaine : des variants ADN à leur interprétation
  - [ ] 1.1.1 Variants, référence GRCh38, nomenclatures (HGVS, rsID)
  - [ ] 1.1.2 Interprétation clinique : le cadre ACMG/AMP et ses cinq classes
  - [ ] 1.1.3 Les deux cas d'étude : cancer du sein héréditaire, drépanocytose
- [ ] 1.2 Les ressources génomiques publiques
  - [ ] 1.2.1 ClinVar, MedGen, NCBI Gene, RefSeq, HPO, dbSNP
  - [ ] 1.2.2 Hétérogénéité des identifiants et des formats
  - [ ] 1.2.3 Versions et reclassifications des variants
  - [ ] 1.2.4 Biais populationnels et populations africaines
- [ ] 1.3 L'ingénierie des données appliquée aux données biomédicales
  - [ ] 1.3.1 ETL, ELT ; entrepôt, lac, lakehouse ; architecture en médaillon
  - [ ] 1.3.2 Formats et tables transactionnelles (Parquet, Delta Lake)
  - [ ] 1.3.3 Historisation (dimensions à évolution lente)
  - [ ] 1.3.4 Qualité des données, provenance, principes FAIR
  - [ ] 1.3.5 Orchestration et pipelines biomédicaux existants (Monarch, Open Targets)
- [ ] 1.4 Grands modèles de langage et génération augmentée par récupération
  - [ ] 1.4.1 LLM et hallucinations
  - [ ] 1.4.2 Le RAG ; recherche lexicale, dense et hybride
  - [ ] 1.4.3 Modèles d'embedding biomédicaux
  - [ ] 1.4.4 Bases vectorielles et recherche approximative des plus proches voisins
- [ ] 1.5 RAG et LLM appliqués à la biomédecine et à la génomique
- [ ] 1.6 Évaluation des systèmes RAG (métriques de recherche, RAGAS, LLM juge)
- [ ] 1.7 Synthèse et positionnement du travail (tableau comparatif, manque identifié)

## Chapitre 2 — Analyse des besoins et méthodologie (proposition, à détailler)

- [ ] 2.1 Acteurs du système et besoins (biologiste, clinicien, chercheur, administrateur)
- [ ] 2.2 Exigences fonctionnelles et non fonctionnelles (traçabilité, sobriété, confidentialité)
- [ ] 2.3 Sources retenues et critères de choix (le *pourquoi* ; le *comment* est au chapitre 3)
- [ ] 2.4 Démarche de travail (itérations, décisions prises par mesure, règle fixée avant la mesure)
- [ ] 2.5 Protocoles d'évaluation (données, recherche, réponses, ressources)

## Chapitre 3 — Pipeline de données (couches 0, 1, 2)

- [ ] 3.1 Couche 0 — Sources et provenance
- [ ] 3.2 Couche 1 — Description des données et des variables
- [ ] 3.3 Couche 2 — Collecte, transformations raw → bronze → silver → gold
- [ ] 3.4 Contrôles qualité et historisation des reclassifications
- [ ] 3.5 Orchestration (Airflow), idempotence, reprise sur panne
- [ ] 3.6 Résultats propres au pipeline (volumes, rejeu, justesse)

## Chapitre 4 — Système RAG (couches 2 embeddings, 3, 4)

- [ ] 4.1 Base de connaissances : du Gold aux documents, vectorisation, indexation
- [ ] 4.2 Couche 3 — Modèles retenus (embedding, LLM) et leur rôle
- [ ] 4.3 Analyse de la question et recherche hybride
- [ ] 4.4 Génération de la réponse et vérification des citations
- [ ] 4.5 Couche 4 — Choix par mesure et évaluation (recherche, fidélité, justesse)

## Chapitre 5 — Intégration, résultats et discussion (couches 5, 6)

- [ ] 5.1 Architecture de bout en bout et déploiement
- [ ] 5.2 Couche 5 — Exploitation des résultats (réponses sourcées, couche analytique)
- [ ] 5.3 Couche 6 — Usage par les acteurs : l'application
- [ ] 5.4 Ressources consommées et sobriété
- [ ] 5.5 Discussion : réponse à la question de recherche, OS1 à OS4
- [ ] 5.6 Limites

## Conclusion générale

- [ ] Bilan, perspectives

---

## Bibliographie — suivi des références

Une référence n'entre dans le mémoire qu'une fois **vérifiée** (titre, auteurs, revue, année, DOI
ou URL contrôlés sur la source) **et lue** au moins dans son résumé par l'étudiant.

| Clé | Référence | Utilisée en | Vérifiée | Lue |
|---|---|---|---|---|
| *(remplie au fil de la rédaction du chapitre 1)* | | | | |

---

## Journal

| Date | Ce qui a été fait |
|---|---|
| 06/11/2026 | Problématique réécrite à partir de l'introduction ; plan en 5 chapitres ; plan du chapitre 1 proposé |
