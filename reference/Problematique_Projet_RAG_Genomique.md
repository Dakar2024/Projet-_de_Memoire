# Theme:                                              Conception d'un Pipeline de Data Engineering pour un Système RAG pour l'Interrogation Intelligente de Données Génomiques : Application à l'Interprétation des Variants ADN

---

## Problématique

---

## I. Avant le projet — La situation actuelle et ses limites

### 1.1 Le contexte mondial : une révolution génomique inaccessible en pratique

Les avancées technologiques en biologie moléculaire ont permis, au cours des deux dernières décennies, de séquencer l'ADN humain à une vitesse et à un coût sans précédent. Aujourd'hui, le séquençage du génome entier d'un patient produit des millions de données génomiques sous la forme de **variants ADN** — des différences entre la séquence génétique du patient et la séquence humaine de référence (GRCh38). Ces variants peuvent être la clé du diagnostic de maladies héréditaires, de cancers génétiques, ou de résistances à certains traitements.

Pour accompagner cette révolution, la communauté scientifique internationale a constitué des bases de données génomiques mondiales d'une richesse considérable :

- **ClinVar** (NCBI, USA) : plus de 1,2 million de variants humains annotés avec leur signification clinique
- **GenBank** : des centaines de millions de séquences ADN issues de milliers d'organismes
- **dbSNP** : l'ensemble des variations génétiques connues chez l'humain, chacune identifiée par un rsID unique
- **OMIM, gnomAD, PharmGKB** : bases complémentaires sur les maladies génétiques, les fréquences populationnelles et les interactions médicament-gène

Ces ressources sont publiques, gratuites et continuellement mises à jour. Elles représentent l'état de l'art mondial en matière de connaissance génomique.

---

### 1.2 Le problème central : un processus d'interprétation long, technique et inaccessible

Malgré la richesse de ces bases de données, leur exploitation dans un contexte clinique quotidien reste **extrêmement laborieuse**. En effet, lorsqu'un biologiste médical reçoit un fichier de résultats de séquençage (format VCF) pour un patient, il doit interpréter chaque variant retenu en suivant un processus manuel en plusieurs étapes :

| Étape | Action requise | Outils utilisés | Temps estimé par variant |
|-------|---------------|-----------------|--------------------------|
| 1 | Vérifier si le variant est déjà répertorié | ClinVar (interface web manuelle) | 10 à 15 minutes |
| 2 | Rechercher les publications scientifiques associées | PubMed, Google Scholar | 15 à 30 minutes |
| 3 | Vérifier la fréquence du variant dans la population générale | gnomAD, dbSNP | 5 à 10 minutes |
| 4 | Analyser l'impact fonctionnel sur la protéine produite | PolyPhen-2, SIFT, CADD | 10 à 15 minutes |
| 5 | Identifier les maladies associées au gène concerné | OMIM, Orphanet | 10 à 15 minutes |
| 6 | Classer le variant selon les critères ACMG | Jugement expert | 15 à 30 minutes |
| 7 | Rédiger le rapport d'interprétation clinique | Word, Excel | 30 à 60 minutes |

**Pour un seul patient présentant 10 variants à analyser, ce processus mobilise entre 2 et 5 heures de travail hautement qualifié.**

Ce n'est pas un processus marginal : dans les structures de biologie médicale et de recherche génomique comme l'Institut Pasteur de Dakar ou l'IRESSEF, des dizaines de dossiers patients peuvent nécessiter ce type d'analyse chaque semaine.

---

### 1.3 Les barrières spécifiques en Afrique de l'Ouest

En Afrique de l'Ouest, cette problématique est amplifiée par plusieurs facteurs structurels :

**Une barrière technologique forte.** L'accès programmatique aux bases génomiques (via des scripts Python, des requêtes SPARQL ou des APIs REST) nécessite une expertise en bioinformatique que la majorité des biologistes médicaux et cliniciens ne possèdent pas. Ces compétences appartiennent à un profil rare — le bioinformaticien — dont le nombre est insuffisant dans la région.

**Un sous-représentation des données africaines.** Les bases mondiales comme ClinVar ont été historiquement alimentées par des données issues de populations européennes et nord-américaines. Les variants spécifiques aux populations d'Afrique subsaharienne — pourtant porteurs d'informations cruciales sur des maladies prévalentes comme la **drépanocytose** (premier variant causé par rs334 sur le gène HBB), le paludisme ou les maladies métaboliques — sont encore sous-représentés et sous-étudiés.

**Un manque d'outils adaptés au contexte local.** Il n'existe aujourd'hui, en Afrique de l'Ouest, aucun système permettant aux professionnels de santé d'interroger les bases génomiques mondiales de façon intuitive, en langage naturel, sans barrière technique. Les professionnels qui en ont le plus besoin sont précisément ceux qui ont le moins accès aux outils existants.

**Un retard dans la prise de décision clinique.** L'ensemble de ces obstacles se traduit concrètement par des délais de rendu de résultats rallongés, une sous-utilisation des données génomiques disponibles, et in fine, un impact négatif sur la qualité du diagnostic génétique et de la médecine personnalisée dans la région.

---

### 1.4 Synthèse : la problématique identifiée

> **Comment permettre à un professionnel de santé — biologiste médical, clinicien ou chercheur — d'interroger efficacement et en langage naturel les bases de données génomiques mondiales pour interpréter les variants ADN de ses patients, sans nécessiter d'expertise en bioinformatique, et dans un contexte de ressources humaines et techniques limitées comme celui de l'Afrique de l'Ouest ?**

---

## II. Après le projet — La solution apportée et ses impacts

### 2.1 La solution proposée : un pipeline de Data Engineering couplé à un système RAG

Pour répondre à cette problématique, ce projet propose la **conception et l'implémentation d'un pipeline de Data Engineering et d'un système RAG (Retrieval-Augmented Generation)** dédié à l'interrogation intelligente des données génomiques.

L'architecture de la solution repose sur deux composantes majeures et indissociables :

#### Composante 1 — Le Pipeline de Data Engineering

Un pipeline automatisé de bout en bout qui prend en charge :

- **L'ingestion** : téléchargement automatisé et périodique des données depuis les APIs publiques (ClinVar via NCBI Entrez, GenBank, dbSNP)
- **La transformation** : nettoyage, normalisation de la nomenclature des variants (standard HGVS), enrichissement croisé entre les bases, structuration en un format exploitable
- **Le stockage** : persistance dans une base de données relationnelle pour les métadonnées et dans une base vectorielle (ChromaDB) pour les représentations sémantiques
- **L'orchestration** : automatisation des mises à jour via Apache Airflow pour garantir la fraîcheur des données

Ce pipeline constitue **le socle Data Engineering** du projet, directement aligné avec la spécialité du Master 2.

#### Composante 2 — Le Système RAG (Retrieval-Augmented Generation)

Un système d'intelligence artificielle conversationnel qui permet d'interroger les données génomiques en langage naturel :

- **La vectorisation sémantique** : chaque variant génomique est encodé en vecteur numérique à l'aide d'un modèle d'embedding biomédical (BioBERT), capturant le sens médical et génomique du texte
- **La recherche sémantique (Retrieval)** : pour chaque question posée, le système identifie les variants les plus pertinents par similarité vectorielle dans ChromaDB
- **La génération augmentée (Generation)** : un LLM (Large Language Model) génère une réponse structurée, sourcée et contextualisée, en se basant exclusivement sur les données ClinVar récupérées
- **L'interface utilisateur** : une application web accessible, sans connaissance technique requise, déployée via Streamlit et exposée par une API REST FastAPI

---

### 2.2 Ce que le projet change concrètement

#### Pour le biologiste médical

**Avant** — Pour répondre à la question *"Le variant rs80357906 sur le gène BRCA1 est-il pathogène ?"*, le biologiste devait :
1. Ouvrir ClinVar dans son navigateur
2. Saisir manuellement le rsID ou les coordonnées génomiques
3. Naviguer dans les fiches de résultats
4. Croiser avec PubMed pour les preuves scientifiques
5. Consulter OMIM pour les maladies associées
6. Rédiger son interprétation

**Durée estimée : 45 minutes à 1h30 par variant**

**Après** — Le biologiste tape sa question en français dans l'interface :
> *"Le variant rs80357906 sur BRCA1 est-il pathogène ? Quelles maladies lui sont associées ?"*

Le système RAG récupère en quelques secondes les données ClinVar pertinentes et génère une réponse structurée avec les sources citées.

**Durée estimée : moins de 30 secondes**

---

#### Pour la structure d'accueil (Institut Pasteur de Dakar, IRESSEF, laboratoires)

| Indicateur | Avant le projet | Après le projet |
|------------|----------------|-----------------|
| Temps d'interprétation par variant | 45 min – 1h30 | < 1 minute |
| Expertise requise | Bioinformaticien spécialisé | Tout professionnel de santé |
| Bases consultées simultanément | 1 à la fois (navigation manuelle) | ClinVar + GenBank + dbSNP en une requête |
| Traçabilité des sources | Dépend du biologiste | Automatique, citée dans chaque réponse |
| Mise à jour des données | Manuelle et irrégulière | Automatisée via le pipeline Airflow |
| Accessibilité | Interface web complexe, en anglais | Interface conversationnelle, en français |

---

### 2.3 L'impact en Afrique de l'Ouest

Au-delà de la structure d'accueil, ce projet ouvre des perspectives plus larges pour la santé génomique en Afrique de l'Ouest :

**Démocratisation de l'accès à la connaissance génomique.** En supprimant la barrière technique entre les professionnels de santé et les bases de données mondiales, le système permet à des structures qui ne disposent pas de bioinformaticien d'accéder au même niveau d'information que les grands centres de recherche internationaux.

**Valorisation des maladies génétiques africaines.** Le système peut être configuré pour prioriser les variants liés à des pathologies prévalentes en Afrique subsaharienne — drépanocytose, trait drépanocytaire, variants APOL1 liés aux maladies rénales, résistance ou sensibilité aux antipaludéens — offrant une aide à l'interprétation directement pertinente pour le contexte local.

**Réplicabilité et adaptabilité.** L'architecture du pipeline et du système RAG est générique. Les données peuvent être remplacées ou enrichies avec d'autres bases (données épidémiologiques locales, cohortes africaines H3Africa) sans modifier l'architecture fondamentale. La solution est donc **portable d'une structure à une autre**.

**Formation et montée en compétences.** L'interface conversationnelle peut également servir d'outil pédagogique pour les étudiants en biologie médicale et en médecine, en leur permettant d'explorer la signification clinique des variants génétiques de façon interactive.

---

### 2.4 Evaluation de la solution

La qualité du système RAG est mesurée selon les métriques scientifiques du framework **RAGAS** (*RAG Assessment*), standard académique actuel :

| Métrique | Ce qu'elle mesure | Valeur cible |
|----------|-------------------|--------------|
| **Faithfulness** | Les réponses sont-elles fidèles aux données ClinVar ? (absence d'hallucinations) | > 0.80 |
| **Answer Relevancy** | Les réponses répondent-elles précisément aux questions posées ? | > 0.75 |
| **Context Recall** | Le système récupère-t-il les bons variants pour chaque question ? | > 0.70 |
| **Context Precision** | Les variants récupérés sont-ils tous pertinents ? | > 0.65 |

Ces métriques permettent de valider scientifiquement la pertinence et la fiabilité du système, et constituent une partie essentielle de la contribution académique du projet.

---

## III. Résumé — Avant / Après en un coup d'œil

| Dimension | Avant le projet | Après le projet |
|-----------|----------------|-----------------|
| **Accès aux données** | Navigation manuelle sur 5 à 6 sites web distincts | Une seule interface conversationnelle en langage naturel |
| **Temps d'interprétation** | 45 min à 1h30 par variant | Moins de 30 secondes |
| **Expertise requise** | Bioinformaticien spécialisé | Tout professionnel de santé |
| **Langue** | Anglais technique | Français naturel |
| **Traçabilité** | Manuelle | Automatique avec citation des sources ClinVar |
| **Mise à jour des données** | Irrégulière et manuelle | Automatisée via pipeline Airflow |
| **Portabilité** | Outil dédié à une seule base | Architecture adaptable à d'autres bases et contextes |
| **Impact local** | Nul — outils conçus pour contextes occidentaux | Solution adaptée aux réalités de l'Afrique de l'Ouest |

---

*Master 2 Intelligence Artificielle — Option Data Engineering*
*Dakar Institute of Technology | Dakar, Sénégal — 2025/2026*
