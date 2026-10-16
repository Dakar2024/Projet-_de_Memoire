# Theme:                                              Conception d'un Pipeline de Data Engineering pour un Système RAG pour l'Interrogation Intelligente de Données Génomiques : Application à l'Interprétation des Variants ADN

---

> **Version révisée du 5 octobre 2026.** Cette version aligne la problématique sur ce qui est
> réellement conçu, implémenté et mesuré dans le dépôt. Chaque modification est listée, avec sa
> raison, dans la **partie V — Journal des révisions**. Le texte d'origine est conservé tel quel
> dans l'**Annexe — Version initiale**, à la fin de ce fichier.

---

## Problématique

---

## I. Avant le projet — La situation actuelle et ses limites

### 1.1 Le contexte mondial : une révolution génomique inaccessible en pratique

Les avancées technologiques en biologie moléculaire ont permis, au cours des deux dernières décennies, de séquencer l'ADN humain à une vitesse et à un coût sans précédent. Aujourd'hui, le séquençage du génome entier d'un patient produit des millions de données génomiques sous la forme de **variants ADN** — des différences entre la séquence génétique du patient et la séquence humaine de référence (GRCh38). Ces variants peuvent être la clé du diagnostic de maladies héréditaires, de cancers génétiques, ou de résistances à certains traitements.

Pour accompagner cette révolution, la communauté scientifique internationale a constitué des bases de données génomiques mondiales d'une richesse considérable :

- **ClinVar** (NCBI, USA) : plus d'un million de variants humains annotés avec leur signification clinique, leur statut de revue et les maladies associées
- **dbSNP** : l'ensemble des variations génétiques connues chez l'humain, chacune identifiée par un rsID unique
- **MedGen et HPO** : les maladies et les phénotypes, décrits dans des vocabulaires contrôlés
- **NCBI Gene et RefSeq** : la description des gènes et de leurs transcrits de référence
- **OMIM, gnomAD, PharmGKB** : bases complémentaires sur les maladies génétiques, les fréquences populationnelles et les interactions médicament-gène

Ces ressources sont publiques, gratuites et continuellement mises à jour. Elles représentent l'état de l'art mondial en matière de connaissance génomique.

---

### 1.2 Le problème central : un processus d'interprétation long, technique et inaccessible

Malgré la richesse de ces bases de données, leur exploitation dans un contexte clinique quotidien reste **laborieuse**. Lorsqu'un biologiste médical reçoit un fichier de résultats de séquençage (format VCF) pour un patient, il doit interpréter chaque variant retenu en suivant un processus manuel en plusieurs étapes :

| Étape | Action requise | Outils utilisés | Ordre de grandeur indicatif par variant |
|-------|---------------|-----------------|--------------------------|
| 1 | Vérifier si le variant est déjà répertorié | ClinVar (interface web manuelle) | 10 à 15 minutes |
| 2 | Rechercher les publications scientifiques associées | PubMed, Google Scholar | 15 à 30 minutes |
| 3 | Vérifier la fréquence du variant dans la population générale | gnomAD, dbSNP | 5 à 10 minutes |
| 4 | Analyser l'impact fonctionnel sur la protéine produite | PolyPhen-2, SIFT, CADD | 10 à 15 minutes |
| 5 | Identifier les maladies associées au gène concerné | OMIM, Orphanet, MedGen | 10 à 15 minutes |
| 6 | Classer le variant selon les critères ACMG | Jugement expert | 15 à 30 minutes |
| 7 | Rédiger le rapport d'interprétation clinique | Word, Excel | 30 à 60 minutes |

**Ces durées sont des ordres de grandeur indicatifs, non mesurés dans ce travail.** Elles servent à situer le problème, pas à chiffrer un gain. Le projet ne traite qu'une partie de ce processus : les étapes **1 et 5** (le variant est-il répertorié, quelle est sa signification clinique, à quelles maladies et à quels phénotypes est-il associé). Les étapes 2, 3, 4, 6 et 7 restent hors de son périmètre (voir §2.5).

Dans les structures de biologie médicale et de recherche génomique comme l'Institut Pasteur de Dakar ou l'IRESSEF, ce type d'analyse est un travail hautement qualifié, qui mobilise un personnel rare.

---

### 1.3 Les barrières spécifiques en Afrique de l'Ouest

En Afrique de l'Ouest, cette problématique est amplifiée par plusieurs facteurs structurels :

**Une barrière technologique forte.** L'accès programmatique aux bases génomiques (via des scripts Python ou des APIs REST) nécessite une expertise en bioinformatique que la majorité des biologistes médicaux et cliniciens ne possèdent pas. Ces compétences appartiennent à un profil rare — le bioinformaticien — dont le nombre est insuffisant dans la région.

**Une barrière linguistique.** Les bases de référence (ClinVar, MedGen, HPO) sont rédigées exclusivement en anglais technique, alors que la langue de travail des professionnels de santé de la région est majoritairement le français.

**Une sous-représentation des données africaines.** Les bases mondiales comme ClinVar ont été historiquement alimentées par des données issues de populations européennes et nord-américaines. Les variants spécifiques aux populations d'Afrique subsaharienne — pourtant porteurs d'informations cruciales sur des maladies prévalentes comme la **drépanocytose** (causée par le variant HbS, rs334 sur le gène HBB, noté p.Glu7Val en nomenclature HGVS et Glu6Val en nomenclature historique), le paludisme ou les maladies métaboliques — sont encore sous-représentés et sous-étudiés. **Ce projet s'appuie sur ces bases mondiales : il hérite de ce biais et ne le corrige pas** (voir §2.5).

**Un manque d'outils adaptés au contexte local.** À notre connaissance, il n'existe pas d'outil permettant aux professionnels de santé de la région d'interroger ces bases en français et en langage naturel, sans barrière technique.

**Un retard dans la prise de décision clinique.** L'ensemble de ces obstacles se traduit concrètement par des délais de rendu de résultats rallongés et une sous-utilisation des données génomiques disponibles.

---

### 1.4 Synthèse : la problématique identifiée

> **Comment concevoir un pipeline de données fiable, reproductible et mis à jour automatiquement, qui rende les connaissances de ClinVar et des bases associées interrogeables en français et en langage naturel par un professionnel de santé — biologiste médical, clinicien ou chercheur — sans expertise en bioinformatique, avec des réponses fidèles aux sources et traçables, dans un contexte de ressources humaines et techniques limitées comme celui de l'Afrique de l'Ouest ?**

Le projet est démontré sur un **panel de 18 gènes** : 12 gènes du cancer du sein héréditaire et 6 gènes de la drépanocytose et des modificateurs de l'hémoglobine fœtale (§2.1).

---

## II. Après le projet — La solution apportée et ses impacts

### 2.1 La solution proposée : un pipeline de Data Engineering couplé à un système RAG

Pour répondre à cette problématique, ce projet propose la **conception et l'implémentation d'un pipeline de Data Engineering et d'un système RAG (Retrieval-Augmented Generation)** dédié à l'interrogation intelligente des données génomiques.

**Panel de gènes.**

| Panel | Gènes |
|---|---|
| Cancer du sein héréditaire (`brca`) | BRCA1, BRCA2, TP53, PALB2, PTEN, CDH1, STK11, ATM, CHEK2, BARD1, RAD51C, RAD51D |
| Drépanocytose et modificateurs HbF (`sickle`) | HBB, BCL11A, HBS1L, MYB, KLF1, G6PD |

L'architecture de la solution repose sur deux composantes majeures et indissociables. La colonne « État » indique où en est chaque élément au 5 octobre 2026.

#### Composante 1 — Le Pipeline de Data Engineering

| Fonction | Ce qui est fait | État |
|---|---|---|
| **Ingestion** | Archive mensuelle de ClinVar (`variant_summary.txt.gz`, ~440 Mo), fichier HPO d'une version étiquetée, appels aux E-utilities du NCBI (Gene, RefSeq, MedGen) et à l'API HPO (`ontology.jax.org`) | ✅ livré |
| **Architecture en couches** | `raw` (format de la source) → `bronze` (Parquet) → `silver` (Delta) → `gold` (Delta), un bucket MinIO par couche, moteur Polars | ✅ livré |
| **Transformation** | Normalisation des colonnes et des identifiants (rs, HGVS), jointures entre sources, **historique des reclassifications ClinVar** (SCD de type 2) | ✅ livré |
| **Couche `gold/rag`** | Un document texte par variant et par gène : 96 910 documents (96 892 variants + 18 gènes), archive ClinVar de septembre 2026 | ✅ livré |
| **Couche `gold/analytique`** | Modèle en étoile (faits variant, variant-maladie, reclassification ; dimensions ; agrégats) pour les questions de comptage et d'exhaustivité | ✅ livré |
| **Contrôles qualité** | Contrôles intégrés à chaque passage de couche, qui arrêtent le pipeline en cas d'anomalie | ✅ livré |
| **Orchestration** | Apache Airflow 3 : un DAG d'acquisition mensuel des sources partagées, puis un DAG par panel | ✅ livré |
| **Déploiement** | Docker Compose (Airflow, PostgreSQL, MinIO, services du RAG) | ✅ livré |

NiFi a été implémenté puis écarté au profit d'Airflow seul, après mesure (`reference/choix_contexte.md`).

Ce pipeline constitue **le socle Data Engineering** du projet, directement aligné avec la spécialité du Master 2.

#### Composante 2 — Le Système RAG (Retrieval-Augmented Generation)

| Fonction | Ce qui est fait | État |
|---|---|---|
| **Vectorisation** | Modèle `NeuML/pubmedbert-base-embeddings` (768 dimensions), servi par Text Embeddings Inference, exporté en ONNX. Retenu **par mesure** contre BioBERT (`reference/choix_embedding.md`) | ✅ livré (E1) |
| **Base vectorielle** | PostgreSQL + **pgvector**, service dédié, comptes séparés pour l'indexation (Airflow) et la lecture (API) | ✅ livré (E1) |
| **Indexation** | Tâche en fin de DAG de panel, incrémentale : seuls les documents modifiés sont recalculés | ✅ livré (E1) |
| **Analyse de la question** | Règles déterministes pour les identifiants (rs, HGVS, gène) ; LLM à sortie structurée pour la reformulation en anglais et l'intention (signification, maladie) | ✅ implémenté (E2a) |
| **Recherche hybride** | Cascade « correspondance exacte (rs/HGVS) → filtres (gène, signification) → similarité », avec repli signalé | ✅ implémenté (E2a) |
| **Accès au LLM** | Via OpenRouter : fournisseur et précision figés, zéro rétention des données, basculement coupé. Modèle d'analyse choisi par mesure parmi trois candidats | 🟡 mesure officielle en attente |
| **Génération de la réponse** | Réponse en français fondée uniquement sur les documents retrouvés, avec citations | ⏳ à venir (E2b) |
| **API** | API REST **Litestar**, connectée en lecture seule à la base vectorielle | ⏳ à venir (E2b) |
| **Évaluation** | RAGAS et audit du RAG | ⏳ à venir (E3) |
| **Interface utilisateur** | Application web accessible sans connaissance technique | ⏳ à venir, hors E2 |

**Pourquoi une recherche hybride et pas seulement la similarité.** La mesure de E1 montre que la similarité vectorielle seule ne sépare pas un variant pathogène d'un variant bénin : sur les questions qui combinent signification et maladie, seuls 30,5 % des dix premiers documents sont pertinents. Les filtres et la correspondance exacte corrigent ce défaut (§2.4).

**Pourquoi traduire la question.** Les documents sont en anglais et le modèle d'embedding n'est pas multilingue : la question française est reformulée en anglais avant la recherche.

---

### 2.2 Ce que le projet change concrètement

#### Pour le biologiste médical

**Avant** — Pour répondre à la question *« Le variant rs80357906 sur le gène BRCA1 est-il pathogène ? »*, le biologiste devait :
1. Ouvrir ClinVar dans son navigateur
2. Saisir manuellement le rsID ou les coordonnées génomiques
3. Naviguer dans les fiches de résultats, en anglais
4. Consulter MedGen, OMIM ou HPO pour les maladies et les phénotypes associés
5. Reconstituer, s'il en a besoin, l'historique de classification du variant

**Après** — Le biologiste pose sa question en français :
> *« Le variant rs80357906 sur BRCA1 est-il pathogène ? Quelles maladies lui sont associées ? »*

Le système retrouve la fiche du variant par correspondance exacte sur l'identifiant, puis génère une réponse en français qui donne :
- la signification clinique ClinVar et son statut de revue ;
- les maladies et les phénotypes associés ;
- l'historique de classification quand le variant a été reclassé ;
- les sources : identifiant de variation ClinVar et date de l'archive utilisée.

Quand l'information manque, la réponse le dit (*« ClinVar ne documente pas de phénotype pour ce variant »*) au lieu de combler le vide.

**Ce qui est déjà mesuré :** sur 20 questions citant un identifiant, la recherche retrouve le bon variant dans **20 cas sur 20** ; l'analyse de la question prend **environ 2 secondes** (médiane, essai sur un modèle gratuit). **Le temps de réponse complet sera mesuré en E2b.** Aucun gain de temps par rapport au processus manuel n'est revendiqué tant qu'il n'a pas été mesuré auprès d'utilisateurs.

Le système peut aussi répondre à des questions **sans identifiant**, formulées par description clinique (*« variants de CDH1 prédisposant à un cancer de l'estomac à cellules en bague à chaton »*), ce que la recherche par mots-clés de ClinVar fait mal.

---

#### Pour la structure d'accueil (Institut Pasteur de Dakar, IRESSEF, laboratoires)

| Indicateur | Avant le projet | Après le projet |
|------------|----------------|-----------------|
| Langue de consultation | Anglais technique | Questions et réponses en français |
| Expertise requise pour interroger les bases | Navigation experte ou scripts (bioinformaticien) | Question en langage naturel ; l'interprétation clinique reste celle du biologiste |
| Sources consultées en une requête | Une base à la fois | ClinVar, MedGen, HPO, NCBI Gene, réunis dans un même document |
| Historique des reclassifications | À reconstituer à la main | Conservé mois après mois par le pipeline et cité dans la réponse |
| Traçabilité des sources | Dépend du biologiste | Identifiant ClinVar et date de l'archive cités dans chaque réponse |
| Mise à jour des données | Manuelle et irrégulière | Mensuelle et automatisée par Airflow, avec contrôles qualité |
| Confidentialité | — | Seule la question est envoyée au LLM, sans donnée patient, chez un fournisseur à zéro rétention |

---

### 2.3 L'impact en Afrique de l'Ouest — perspectives

Les points suivants sont des **perspectives** ouvertes par l'architecture, pas des résultats démontrés.

**Accès à la connaissance génomique en français.** En supprimant la barrière technique et linguistique entre les professionnels de santé et les bases mondiales, le système permet à des structures sans bioinformaticien de consulter la même information que les grands centres.

**Un panel tourné vers une maladie prévalente en Afrique.** Le panel inclut déjà la drépanocytose (HBB) et ses modificateurs de l'hémoglobine fœtale (BCL11A, HBS1L, MYB, KLF1), ainsi que G6PD, dont le déficit est fréquent dans les zones d'endémie palustre. D'autres pathologies prévalentes (variants APOL1 et maladie rénale, pharmacogénétique des antipaludéens) pourraient être ajoutées comme de nouveaux panels.

**Réplicabilité et adaptabilité.** Un panel n'est qu'une liste de gènes : en ajouter un ne demande pas de modifier le code. De nouvelles sources (fréquences gnomAD, cohortes africaines H3Africa, données locales) pourraient s'ajouter comme de nouvelles entrées de la couche `raw`, sans modifier l'architecture en couches.

**Formation et montée en compétences.** L'interface conversationnelle peut servir d'outil pédagogique pour les étudiants en biologie médicale et en médecine.

---

### 2.4 Évaluation de la solution

Le projet distingue trois objets d'évaluation : les données produites par le pipeline, la recherche, et la réponse générée. Chaque choix technique a été fait **par une mesure**, avec une règle de décision fixée avant de mesurer.

#### Mesures déjà réalisées

| Objet | Mesure | Résultat | Référence |
|---|---|---|---|
| Pipeline | Exécution de bout en bout, rejeu sans effet de bord, contrôles qualité | 96 910 documents produits ; rejeu vérifié | `reference/evaluation.md` |
| Modèle d'embedding | NeuML PubMedBERT contre BioBERT, 59 questions, intervalle de confiance par bootstrap | Écart +0,361, IC 95 % [+0,257 ; +0,469] : NeuML retenu | `reference/choix_embedding.md` |
| Recherche hybride | Essai complet sur un modèle gratuit (gpt-oss-120b via Groq), questions en français | Identifiants : 20/20 ; pièges : 10/10 ; signification + maladie : 0,305 → 0,495 grâce aux filtres | `data/experiments/e2a-essai/resultat.md` |

L'essai de la recherche **valide la chaîne mais ne sert pas au choix du modèle** : la mesure officielle sur les trois modèles candidats reste à faire.

#### Mesures à venir

- **Vérification manuelle de la justesse des données** : 11 variants du Gold confrontés à leur fiche ClinVar, champ par champ (`reference/evaluation.md` §8).
- **Tests de panne et de restauration** du pipeline (`reference/evaluation.md` §6 et §7).
- **Mesure officielle de la recherche** sur les trois modèles d'analyse, puis choix du modèle.
- **Évaluation RAGAS (E3)** de la réponse générée :

| Métrique | Ce qu'elle mesure | Cible initiale |
|----------|-------------------|--------------|
| **Faithfulness** | Les réponses sont-elles fidèles aux documents retrouvés ? (absence d'hallucinations) | > 0.80 |
| **Answer Relevancy** | Les réponses répondent-elles précisément aux questions posées ? | > 0.75 |
| **Context Recall** | Le système récupère-t-il les bons variants pour chaque question ? | > 0.70 |
| **Context Precision** | Les variants récupérés sont-ils tous pertinents ? | > 0.65 |

Ces cibles sont des valeurs initiales. Elles seront justifiées et figées dans la spec de E3, **avant** la mesure, comme pour les mesures précédentes.

---

### 2.5 Périmètre et limites

Le système est une **aide à la consultation** des bases génomiques. **Ce n'est pas un outil d'interprétation clinique** et il ne remplace pas le jugement du biologiste. Il ne fait pas, et ne prétend pas faire :

- **la classification ACMG** d'un variant (étape 6 du §1.2) ;
- **le traitement d'un fichier VCF** : les variants sont interrogés un par un, par une question ;
- **les fréquences en population** (gnomAD), ni **les prédictions d'impact fonctionnel** (SIFT, PolyPhen-2, CADD) ;
- **la recherche bibliographique** (PubMed) ;
- **la couverture du génome entier** : seuls les 18 gènes du panel sont indexés.

Limites héritées des données :

- **Biais populationnel.** ClinVar sous-représente les populations africaines ; le système hérite de ce biais.
- **Une archive à une date donnée.** Les réponses reflètent l'archive mensuelle de ClinVar utilisée (septembre 2026 à ce jour), pas l'état courant du site.
- **Documents maigres.** 4,8 % des documents ne décrivent aucun phénotype : la réponse doit alors le dire, sans compléter.
- **Noms historiques des variants.** Un biologiste dit « Glu6Val » pour la mutation drépanocytaire ; ClinVar la note p.Glu7Val (nomenclature HGVS). La correspondance entre noms historiques et HGVS n'est pas encore gérée.
- **Questions d'exhaustivité.** « Combien de variants pathogènes compte BRCA2 ? » relève de la couche `gold/analytique` (requête), pas du RAG, qui ne retourne que les documents les plus pertinents.

---

## III. Résumé — Avant / Après en un coup d'œil

| Dimension | Avant le projet | Après le projet |
|-----------|----------------|-----------------|
| **Accès aux données** | Navigation manuelle sur plusieurs sites web distincts | Une seule question en langage naturel, sur un panel de 18 gènes |
| **Langue** | Anglais technique | Français naturel |
| **Recherche** | Par identifiant ou mots-clés exacts | Par identifiant, par gène et signification, ou par description clinique |
| **Expertise requise pour interroger** | Bioinformaticien ou navigation experte | Tout professionnel de santé ; l'interprétation reste celle du biologiste |
| **Traçabilité** | Manuelle | Identifiant ClinVar et date de l'archive cités dans chaque réponse |
| **Historique des reclassifications** | À reconstituer | Conservé par le pipeline et restitué |
| **Mise à jour des données** | Irrégulière et manuelle | Mensuelle et automatisée via Airflow, avec contrôles qualité |
| **Fiabilité** | Non mesurée | Choix techniques mesurés, évaluation RAGAS prévue (E3) |
| **Portabilité** | Outil dédié à une seule base | Nouveaux panels et nouvelles sources sans changer l'architecture |

---

## IV. État d'avancement (5 octobre 2026)

| Sous-projet | Contenu | État |
|---|---|---|
| A à D | Collecte, couches `raw` → `bronze` → `silver` → `gold` | ✅ livré |
| E1 | Indexation RAG (PubMedBERT, pgvector) | ✅ livré |
| E2a | Analyse de la question et recherche hybride | ✅ implémenté ; mesure officielle en attente |
| E2b | Génération de la réponse, API Litestar | ⏳ à venir |
| E3 | Évaluation RAGAS et audit du RAG | ⏳ à venir |
| — | Interface web | ⏳ à venir |

---

## V. Journal des révisions

### Révision du 5 octobre 2026

Le texte d'origine est conservé intégralement dans l'annexe ci-dessous. Chaque ligne indique ce
qui a changé, et pourquoi.

| # | Emplacement | Avant | Après | Raison |
|---|---|---|---|---|
| R1 | En-tête | — | Note de version renvoyant au journal et à l'annexe | Garder la trace de la version initiale |
| R2 | §1.1, liste des bases | ClinVar « plus de 1,2 million de variants » ; GenBank cité | ClinVar « plus d'un million de variants » ; GenBank retiré ; MedGen, HPO, NCBI Gene et RefSeq ajoutés | GenBank n'est pas utilisé ; MedGen, HPO, Gene et RefSeq le sont. Le chiffre de ClinVar évolue chaque mois : une borne basse reste vraie |
| R3 | §1.2, tableau | « Temps estimé par variant » présenté comme un fait | « Ordre de grandeur indicatif », avec mention « non mesuré » ; MedGen ajouté à l'étape 5 | Durées sans source ni mesure : non défendables comme chiffres |
| R4 | §1.2 | « Pour 10 variants, 2 à 5 heures » | Retiré ; ajout : le projet ne couvre que les étapes 1 et 5 | Chiffre non mesuré ; préciser le périmètre réellement couvert |
| R5 | §1.2 | « des dizaines de dossiers chaque semaine » à Pasteur et à l'IRESSEF | Retiré ; formulation qualitative | Volume non vérifié auprès de ces structures |
| R6 | §1.3 | « requêtes SPARQL » | Retiré | Aucune des sources utilisées ne s'interroge en SPARQL |
| R7 | §1.3 | — | Ajout d'une barrière linguistique | C'est la raison de la reformulation des questions en anglais (contrainte n° 2 du RAG) |
| R8 | §1.3, drépanocytose | « premier variant causé par rs334 sur le gène HBB » | « causée par le variant HbS, rs334, p.Glu7Val (HGVS) / Glu6Val (historique) » | Formulation incorrecte ; la double nomenclature est une vraie difficulté pour la recherche |
| R9 | §1.3 | — | Ajout : le projet hérite du biais populationnel de ClinVar | Éviter de présenter comme corrigé un problème que le système ne traite pas |
| R10 | §1.3 | « Il n'existe aujourd'hui aucun système… » | « À notre connaissance, il n'existe pas d'outil… » | Affirmation absolue invérifiable |
| R11 | §1.4, question de recherche | « interpréter les variants ADN de ses patients » à partir des « bases mondiales » | « rendre ClinVar et les bases associées interrogeables en français », avec un pipeline « fiable, reproductible et mis à jour automatiquement » et des réponses « fidèles et traçables » ; panel de 18 gènes | Le système aide à la consultation, il n'interprète pas ; la question met en avant la contribution de Data Engineering |
| R12 | §2.1 | — | Ajout du tableau des 18 gènes et d'une colonne « État » | Préciser le périmètre et l'avancement réel |
| R13 | §2.1, ingestion | ClinVar « via NCBI Entrez », GenBank, dbSNP | Archive mensuelle ClinVar, fichier HPO, E-utilities (Gene, RefSeq, MedGen), API HPO | ClinVar est lu dans son archive mensuelle, pas par Entrez ; GenBank et dbSNP ne sont pas interrogés (le rsID vient de ClinVar) |
| R14 | §2.1, stockage | « base relationnelle » pour les métadonnées | Lac MinIO en quatre couches (Parquet puis Delta), `gold/rag` et `gold/analytique` | Architecture réellement implémentée (spec du 15/09/2026) |
| R15 | §2.1, base vectorielle | ChromaDB | PostgreSQL + pgvector | Choix fait en E1 : filtres SQL pour la recherche hybride, comptes à droits séparés |
| R16 | §2.1, embedding | BioBERT | NeuML PubMedBERT | BioBERT n'est pas entraîné pour la similarité ; écart mesuré +0,361, IC 95 % [+0,257 ; +0,469] |
| R17 | §2.1, recherche | « similarité vectorielle » seule | Recherche hybride : exact → filtres → similarité | La similarité seule ne sépare pas pathogène et bénin (0,305 en famille C) |
| R18 | §2.1, LLM | « un LLM » | Analyse de la question par LLM via OpenRouter, modèle choisi par mesure ; génération en E2b | Préciser le rôle du LLM et l'état de l'implémentation |
| R19 | §2.1, interface | Streamlit + API FastAPI | API Litestar (E2b) ; interface web à venir, technologie non arrêtée | Choix de Litestar dans le cadrage de E2 ; l'interface est hors E2 |
| R20 | §2.1 | — | Ajout de la justification de la recherche hybride et de la traduction | Deux contraintes de conception mesurées |
| R21 | §2.2, « Avant » | Étape « Croiser avec PubMed » | Retirée ; ajout de l'historique de classification | PubMed n'est pas couvert par le système : comparer ce qui est comparable |
| R22 | §2.2, durées | « 45 min à 1 h 30 » avant, « moins de 30 secondes » après | Retirées ; remplacées par les mesures réelles (20/20, ~2 s pour l'analyse) et « temps complet mesuré en E2b » | Aucune de ces durées n'a été mesurée |
| R23 | §2.2 | — | Contenu de la réponse détaillé ; comportement face au manque d'information ; recherche par description clinique | Décrire ce que le système fait réellement |
| R24 | §2.2, tableau de la structure | « < 1 minute » ; « Tout professionnel de santé » ; « ClinVar + GenBank + dbSNP » | Lignes sur la langue, l'historique, la traçabilité, la confidentialité ; sources réelles | Retirer les chiffres non mesurés et les sources non utilisées |
| R25 | §2.3 | Impacts présentés comme acquis ; « peut être configuré pour prioriser » | Présentés comme perspectives ; panel drépanocytose et G6PD déjà inclus | Distinguer le démontré du possible |
| R26 | §2.3, réplicabilité | « sans modifier l'architecture fondamentale » | Un panel = une liste de gènes ; une source = une entrée `raw` | Formulation vérifiable dans le code |
| R27 | §2.4 | RAGAS seul, cibles présentées comme acquises | Mesures déjà réalisées + mesures à venir ; cibles RAGAS « initiales », à figer avant la mesure | Trois mesures existent déjà ; méthode de décision fixée d'avance |
| R28 | §2.5 | — | Nouvelle section « Périmètre et limites » | Délimiter l'outil : aide à la consultation, pas interprétation clinique |
| R29 | §III, résumé | Lignes « Temps < 30 s », « Impact local : solution adaptée » | Retirées ; lignes Recherche, Historique, Fiabilité ajoutées | Cohérence avec les révisions R22, R25 et R27 |
| R30 | §IV | — | Nouvelle section « État d'avancement » | Situer le projet à la date de la révision |

---

## Annexe — Version initiale (conservée telle quelle)

<details>
<summary>Afficher le texte d'origine, antérieur à la révision du 5 octobre 2026</summary>

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

</details>

---

*Master 2 Intelligence Artificielle — Option Data Engineering*
*Dakar Institute of Technology | Dakar, Sénégal — 2025/2026*
