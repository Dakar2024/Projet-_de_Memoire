# Problématique du mémoire

**Thème :** Conception d'un pipeline de Data Engineering pour un système RAG d'interrogation
intelligente de données génomiques : application à l'interprétation des variants ADN.

> **Version du 6 novembre 2026, alignée sur l'introduction validée par le directeur de mémoire.**
> En cas d'écart, c'est l'introduction qui fait foi. La version précédente (5 octobre 2026), avec
> son journal de révisions, reste consultable dans l'historique git (`git show a21f61a:reference/Problematique_Projet_RAG_Genomique.md`).
>
> Ce document fixe le **cadre** du mémoire (problème, question, objectifs, périmètre, plan). Il ne
> contient volontairement aucun résultat chiffré : les chiffres changent à chaque archive ClinVar et
> sont rapportés dans les chapitres 3 à 5, avec leur date et leur source.

---

## 1. Le constat

**Les données existent.** Le séquençage de l'ADN produit, pour chaque patient, une liste de
variants génétiques. Pour savoir si un variant est associé à une maladie, à une prédisposition ou
à une différence d'expression clinique, il faut le confronter aux connaissances déjà établies. Ces
connaissances sont publiques : ClinVar (signification clinique des variants), NCBI Gene et RefSeq
(gènes et transcrits), MedGen (maladies), Human Phenotype Ontology (phénotypes).

**Mais elles sont difficiles à exploiter**, pour trois raisons :

| Difficulté | Ce qu'elle signifie concrètement |
|---|---|
| **Hétérogénéité** | Chaque source a son format, ses identifiants et son niveau de détail. Un même variant peut être désigné par un rsID, une notation HGVS ou un nom d'usage. |
| **Dispersion** | Les informations sur un même variant sont réparties entre plusieurs bases : leur mise en relation est longue et manuelle. |
| **Évolution** | Les sources sont versionnées ; ClinVar publie une archive chaque mois et un variant peut être reclassé. Il faut savoir de quelle version provient une information. |

**Les grands modèles de langage (LLM)** permettent d'interroger ces connaissances en langage
naturel, mais, utilisés seuls, ils peuvent produire des réponses inexactes ou des références
inexistantes. La génération augmentée par récupération (RAG) les oblige à répondre à partir de
documents retrouvés. **Sa fiabilité dépend alors entièrement de la qualité, de l'organisation et
de l'actualisation des données qui l'alimentent** : c'est là que se situe la contribution de Data
Engineering de ce mémoire.

## 2. La question de recherche

> **Comment concevoir un pipeline de Data Engineering générique, reproductible et sobre en
> ressources, capable de collecter, normaliser et structurer des données génomiques publiques
> hétérogènes, afin de constituer une base de connaissances fiable, traçable et actualisable,
> permettant à un système RAG de fournir aux professionnels de santé des réponses en langage
> naturel, pertinentes, sourcées et fidèles aux données scientifiques sur les variants ADN
> d'intérêt clinique ?**

Lecture de la question, terme par terme, et où chaque terme est démontré :

| Exigence | Ce qu'elle veut dire dans ce travail | Démontrée au |
|---|---|---|
| Générique | Les maladies et les gènes sont des paramètres ; en ajouter ne modifie pas le code | Chapitre 3 |
| Reproductible | Une même archive rejouée produit le même résultat, sans effet de bord | Chapitre 3 |
| Sobre en ressources | Une seule machine, conteneurs Docker, sans processeur graphique obligatoire | Chapitres 3 et 5 |
| Fiable | Contrôles qualité à chaque couche ; justesse vérifiée contre les fiches sources | Chapitres 3 et 4 |
| Traçable | Chaque information garde sa source, son identifiant et sa version | Chapitres 3 et 4 |
| Actualisable | Mise à jour mensuelle automatisée ; historique des reclassifications conservé | Chapitre 3 |
| Pertinentes, sourcées, fidèles | La recherche retrouve les bons documents ; la réponse cite ses sources et ne dit rien qu'elles ne disent | Chapitre 4 |

## 3. Objectifs

**Objectif général :** concevoir, mettre en œuvre et évaluer une chaîne de traitement de données
génomiques destinée à alimenter un système RAG d'aide documentaire à la consultation des variants
ADN.

| Objectif spécifique | Énoncé | Traité au |
|---|---|---|
| **OS1** | Identifier et collecter des données génomiques publiques pertinentes, issues de sources complémentaires, afin de constituer un ensemble documentaire adapté aux cas d'étude | Chapitres 2 et 3 |
| **OS2** | Normaliser, structurer et contrôler les données collectées, tout en préservant leur provenance et les informations nécessaires à leur actualisation | Chapitre 3 |
| **OS3** | Construire une base de connaissances exploitable par un système RAG et mettre en place un mécanisme de recherche permettant de retrouver les informations pertinentes en fonction des questions formulées | Chapitre 4 |
| **OS4** | Évaluer la qualité des données produites, la pertinence des informations récupérées, la fidélité des réponses générées et les ressources nécessaires au fonctionnement de la solution | Chapitres 3, 4 et 5 |

## 4. Cas d'application

La démarche est mise à l'épreuve sur deux domaines génétiquement différents, qui servent de **cas
d'étude** et ne limitent pas la conception du pipeline :

| Cas d'étude | Gènes du panel |
|---|---|
| Cancer du sein  | BRCA1, BRCA2, TP53, PALB2, PTEN, CDH1, STK11, ATM, CHEK2, BARD1, RAD51C, RAD51D |
| Drépanocytose et modificateurs de l'hémoglobine fœtale | HBB, BCL11A, HBS1L, MYB, KLF1, G6PD |

## 5. Périmètre

Le système est une **aide à la consultation documentaire**. Il ne se substitue ni à l'expertise du
biologiste ni à la classification clinique complète des variants. En particulier, il ne fait pas :

- la classification d'un variant selon les critères ACMG/AMP ;
- le traitement d'un fichier VCF de patient (les variants sont interrogés par des questions) ;
- l'analyse des fréquences en population ni la prédiction d'impact fonctionnel ;
- la recherche bibliographique.

Il hérite en outre des limites de ses sources, notamment la sous-représentation des populations
africaines dans ClinVar.

## 6. Plan du mémoire

Le plan suit la recommandation du directeur de mémoire : l'implémentation est répartie en trois
chapitres (pipeline, RAG, intégration), et sa rédaction s'appuie sur une lecture en **couches**
(0 à 6), des sources de données jusqu'à leur usage par les acteurs.

| Chapitre | Contenu | Couches |
|---|---|---|
| Introduction générale | Contexte, problématique, objectifs, structure | — |
| 1. État de l'art | Domaine, ressources génomiques, Data Engineering, LLM et RAG, évaluation, positionnement | — |
| 2. Analyse des besoins et méthodologie | Acteurs et besoins, sources retenues et critères de choix, démarche, protocoles d'évaluation | (cadre) |
| 3. Pipeline de données | Sources et provenance, description des données, collecte et transformations par couches, qualité, orchestration | 0, 1, 2 |
| 4. Système RAG | Base de connaissances et vectorisation, modèles retenus, recherche hybride, génération, choix par mesure et évaluation | 2 (embeddings), 3, 4 |
| 5. Intégration, résultats et discussion | Système de bout en bout, déploiement, exploitation des résultats, usage par les acteurs (application), discussion et limites | 5, 6 |
| Conclusion générale | Bilan des objectifs, perspectives | — |

Le projet n'entraîne aucun modèle : les couches 3 et 4 portent sur la **sélection**, la
**configuration** et l'**évaluation** de modèles pré-entraînés, pas sur un entraînement ou un
réglage fin.

---

*Master 2 Intelligence Artificielle — Option Data Engineering*
*Dakar Institute of Technology | Dakar, Sénégal — 2025/2026*
