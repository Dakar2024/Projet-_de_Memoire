# INTRODUCTION

## 1. Contexte et justification

### 1.1 Une connaissance génomique publique, mais difficile à exploiter

**La génomique est entrée dans la pratique médicale.** En deux décennies, le séquençage de l'ADN
est passé du laboratoire de recherche au laboratoire de biologie médicale. Le séquençage ciblé
d'un panel de gènes produit, pour chaque patient, une liste de **variants** : des différences
entre son ADN et la séquence humaine de référence. Certains expliquent une maladie, en prédisent
le risque ou en modulent la sévérité ; la plupart sont sans conséquence clinique. Distinguer les
uns des autres est au cœur du travail du biologiste, et ce travail ne repose pas sur l'intuition :
il repose sur la connaissance accumulée par la communauté scientifique sur chaque variant.

**Cette connaissance existe, elle est publique, mais elle est difficile à exploiter.** Des bases de
référence internationales la mettent gratuitement à disposition : **ClinVar** recense la
signification clinique de plus d'un million de variants humains (Landrum et al.), **MedGen**
décrit les maladies, la **Human Phenotype Ontology (HPO)** leurs manifestations cliniques
(Köhler et al.), **NCBI Gene** et **RefSeq** les gènes et leurs transcrits. Mais ces sources sont
**hétérogènes** : chacune a son format, ses conventions et ses identifiants, si bien qu'un même
variant peut être désigné par un identifiant dbSNP, par une description HGVS ou par son nom
d'usage clinique. Elles sont **dispersées** : la signification d'un variant se trouve dans une
base, la description de la maladie dans une autre, les phénotypes dans une troisième, et c'est
au professionnel de santé de les croiser. Elles sont enfin **en évolution permanente** : ClinVar
publie une nouvelle version chaque mois, et un variant jugé de signification incertaine peut être
reclassé pathogène, ou l'inverse. Une information juste aujourd'hui peut ne plus l'être demain ;
savoir de quelle version provient une information est aussi important que l'information
elle-même.

### 1.2 Des barrières de compétences, de langue et de ressources

**Leur consultation suppose des compétences et une langue que tous n'ont pas.** Ces bases sont
rédigées en anglais technique, et leur interrogation avancée — interfaces spécialisées, API,
fichiers de plusieurs centaines de mégaoctets — relève de la bioinformatique. En Afrique de
l'Ouest francophone, cette situation pèse doublement : la langue de travail des professionnels de
santé est le français, et les bioinformaticiens sont rares. Une partie de l'expertise est donc
déléguée à l'étranger. À l'Institut Pasteur de Dakar, par exemple, l'analyse des gènes BRCA1 et
BRCA2, impliqués dans le cancer du sein héréditaire, est aujourd'hui sous-traitée à un laboratoire
français, alors que le laboratoire dispose d'un séquenceur capable de la réaliser. Internaliser
cette analyse suppose de disposer, sur place, des moyens d'en interpréter les résultats.

**Ces structures disposent aussi de ressources techniques limitées.** Les solutions d'intelligence
artificielle les plus visibles reposent sur des infrastructures en nuage coûteuses, des
processeurs graphiques puissants et des abonnements onéreux. Un laboratoire public ou une
structure de recherche régionale ne peut pas toujours les financer ni les maintenir. Une solution
qui exigerait de tels moyens resterait inaccessible à ceux qui en ont le plus besoin : elle doit
pouvoir fonctionner sur une infrastructure modeste, avec un coût d'exploitation maîtrisé.

### 1.3 Les grands modèles de langage : une promesse et un risque

Les grands modèles de langage (LLM) comprennent une question posée en français et y répondent en
langage naturel ; ils semblent lever d'un coup les barrières de la langue et de la technique.
Interrogés seuls, ils produisent pourtant des réponses plausibles mais non vérifiables, parfois
fausses : un identifiant de variant inventé, une signification clinique inversée, une référence
inexistante. En génétique médicale, une telle erreur peut orienter une décision clinique. Une
réponse utile au professionnel de santé doit donc être **pertinente** — elle répond à la question
posée —, **sourcée** — elle indique d'où vient chaque information — et **fidèle** — elle
n'affirme rien que les sources ne disent pas.

### 1.4 Un système RAG ne vaut que ce que valent ses données

L'approche **RAG** (*Retrieval-Augmented Generation*, génération augmentée par la recherche)
répond à ce risque (Lewis et al., 2020) : le modèle de langage ne répond plus de mémoire, il
s'appuie sur des documents retrouvés dans une base de connaissances et les cite. Mais sa
fiabilité dépend alors entièrement de cette base. Des données incomplètes, mal reliées entre
elles, dupliquées ou périmées produisent des réponses incomplètes, incohérentes ou dépassées —
avec l'apparence de rigueur que leur donne la citation. **La qualité d'un système RAG se joue donc
en amont, dans la chaîne qui produit ses données** : collecter les sources, normaliser leurs
formats et leurs identifiants, structurer et relier leurs contenus, contrôler leur qualité,
conserver la trace de leur origine et de leur version, et les mettre à jour au rythme des
sources.

**Cette chaîne doit enfin pouvoir servir au-delà d'un cas particulier.** Les variants d'intérêt
clinique concernent des centaines de maladies et des milliers de gènes. Une chaîne conçue pour une
seule maladie serait à reconstruire pour chaque nouvelle maladie. Elle doit au contraire être
**générique** — accueillir de nouveaux gènes ou de nouvelles maladies sans être réécrite — et
**reproductible** — produire les mêmes résultats à partir des mêmes versions des sources,
condition de la confiance et de la vérification.

### 1.5 Deux cas d'application : le cancer du sein héréditaire et la drépanocytose

Pour concevoir et évaluer cette démarche générique sur des données réelles, nous l'appliquons à
deux cas d'étude, dont les gènes ont été choisis et validés avec un spécialiste du domaine,
biologiste à l'Institut Pasteur de Dakar.

**Le cancer du sein héréditaire, cas principal.** Selon le spécialiste consulté, une
prédisposition héréditaire est en cause dans 2 à 5 % des cancers du sein, et jusqu'à 15 % des
cancers dits « triple négatifs » [référence bibliographique à ajouter]. Sa recherche porte sur une
dizaine de gènes de prédisposition, au premier rang desquels BRCA1 et BRCA2. Ces gènes sont
abondamment documentés dans ClinVar, avec des niveaux de preuve élevés et des reclassifications
fréquentes : ils constituent un terrain d'évaluation exigeant. Le besoin local est concret :
l'analyse BRCA1/BRCA2 de l'Institut Pasteur de Dakar est sous-traitée pour un coût d'environ
400 000 FCFA, alors que le laboratoire dispose d'un séquenceur Illumina MiSeq compatible avec un
panel BRCA germinal.

**La drépanocytose, cas secondaire.** Maladie génétique à forte prévalence en Afrique
subsaharienne, la drépanocytose est causée par un variant du gène HBB, et sa sévérité est modulée
par des gènes modificateurs du taux d'hémoglobine fœtale (BCL11A, HBS1L, MYB, KLF1). Ce cas
apporte une autre forme de relation entre gène et maladie (gène causal et gènes modificateurs) et
une difficulté propre : le variant causal est connu des cliniciens sous le nom « Glu6Val », alors
que la nomenclature HGVS utilisée par ClinVar le note p.Glu7Val. Il met aussi en évidence une
limite connue des bases mondiales : les populations africaines y sont sous-représentées
(Popejoy et Fullerton, 2016).

Le panel étudié compte ainsi **18 gènes** : 12 gènes de prédisposition au cancer du sein
héréditaire, et 6 gènes liés à la drépanocytose (le gène causal, quatre gènes modificateurs et
G6PD, dont le déficit est une comorbidité fréquente en zone d'endémie palustre).

### 1.6 Ce que recouvre « interprétation des variants » dans ce mémoire

L'interprétation clinique complète d'un variant suit un processus en plusieurs étapes, qui
aboutit à une classification selon les critères de l'ACMG (Richards et al., 2015) et à un compte
rendu signé par le biologiste. Dans ce mémoire, « interprétation des variants » désigne **l'étape
documentaire** de ce processus : réunir, pour un variant donné, sa signification clinique, son
niveau de preuve, son historique de classification, et les maladies et phénotypes associés.

Le système conçu est une **aide à l'interprétation**. Il ne classe pas les variants, ne traite
pas les fichiers de séquençage (VCF), et ne remplace pas le jugement du professionnel de santé,
qui reste seul responsable de la conclusion clinique.

## 2. Problématique

Les connaissances nécessaires à l'interprétation des variants existent dans des bases publiques,
mais leur hétérogénéité, leur dispersion, leur évolution et leur langue en rendent la
consultation longue et réservée à des profils spécialisés, dans des structures qui disposent de
moyens techniques limités. Les modèles de langage rendent possible une interrogation en langage
naturel, dans la langue de l'utilisateur, mais ils ne sont fiables que s'ils s'appuient sur des données elles-mêmes fiables. La question
n'est donc pas seulement de brancher un modèle de langage sur une base génomique, mais de
construire la chaîne de données qui rend cette interrogation digne de confiance, à un coût
soutenable. Ce constat relève directement du data engineering, et conduit à la question
centrale de ce mémoire :

> **Comment concevoir un pipeline de Data Engineering générique, reproductible et sobre en
> ressources, capable de collecter, normaliser et structurer des données génomiques publiques
> hétérogènes, afin de constituer une base de connaissances fiable, traçable et actualisable,
> permettant à un système RAG de fournir aux professionnels de santé des réponses en langage
> naturel, pertinentes, sourcées et fidèles aux données scientifiques sur les variants ADN d'intérêt
> clinique ?**

Cette question se décline en cinq questions spécifiques :

- **QS1 — Collecte et intégration.** Comment collecter, normaliser, contrôler et historiser
  automatiquement des sources hétérogènes, de façon reproductible, extensible à de nouveaux
  panels de gènes et sobre en ressources ?
- **QS2 — Représentation.** Comment transformer ces données en documents exploitables par un
  moteur de recherche, et quel modèle de représentation vectorielle choisir pour des textes
  biomédicaux ?
- **QS3 — Recherche.** Comment retrouver les bons documents, que la question cite un identifiant
  de variant, un gène, une signification clinique ou une description clinique ?
- **QS4 — Génération.** Comment garantir que la réponse générée reste fidèle aux sources, les
  cite, et signale l'absence d'information plutôt que de la combler ?
- **QS5 — Évaluation.** Comment mesurer objectivement la fiabilité du système et son coût
  d'exploitation ?

Nous formulons trois hypothèses, que le travail cherche à confirmer ou à infirmer par la mesure :

- **H1.** Un modèle de représentation biomédical entraîné pour la similarité de textes retrouve
  mieux les documents pertinents qu'un modèle biomédical qui n'a pas été entraîné pour cette
  tâche.
- **H2.** Une recherche hybride, qui combine correspondance exacte sur les identifiants, filtres
  sur les métadonnées (gène, signification clinique) et similarité sémantique, surpasse la
  recherche par similarité seule.
- **H3.** Un système RAG alimenté par des données curées produit des réponses plus fidèles aux
  sources qu'un modèle de langage interrogé seul.

## 3. Objectifs de la recherche

### 3.1 Objectif général

Concevoir, implémenter et évaluer un pipeline de data engineering générique et sobre en
ressources, qui alimente un système RAG fiable d'aide à l'interprétation des variants, et le
démontrer sur le cancer du sein héréditaire et la drépanocytose.

### 3.2 Objectifs spécifiques

| Objectif | Description | Question |
|---|---|---|
| **OS1** | Construire un pipeline de collecte automatisé (ClinVar, MedGen, HPO, NCBI Gene, RefSeq), organisé en architecture médaillon (`raw` → `bronze` → `silver` → `gold`), orchestré par Apache Airflow et doté de contrôles qualité à chaque couche | QS1 |
| **OS2** | Conserver l'historique des classifications ClinVar et garantir la reproductibilité des traitements (versions des sources épinglées, rejeu sans effet de bord) | QS1 |
| **OS3** | Montrer que l'ajout d'un panel de gènes ne demande qu'une modification de configuration | QS1 |
| **OS4** | Concevoir une solution déployable sur une seule machine, sans processeur graphique obligatoire, et mesurer son empreinte : mémoire, durée d'un cycle de mise à jour, coût par question | QS1, QS5 |
| **OS5** | Produire des documents textuels par variant et par gène, choisir par la mesure le modèle de représentation vectorielle, et les indexer dans une base vectorielle | QS2 |
| **OS6** | Concevoir une recherche hybride et une génération contrainte, exposées par une API, qui répondent en français en citant leurs sources | QS3, QS4 |
| **OS7** | Évaluer le système avec des métriques reconnues (dont le cadre RAGAS ; Es et al.) et le comparer à un modèle de langage interrogé seul | QS5 |

Chaque choix technique de ce travail est fait **par la mesure**, avec une règle de décision fixée
avant de mesurer, afin que le résultat ne puisse pas orienter la règle.

## 4. Structure du mémoire

Le mémoire est organisé en trois chapitres.

**Le chapitre I — État de l'art** présente le domaine d'application (variants, bases génomiques,
interprétation clinique, cas du cancer du sein héréditaire et de la drépanocytose), puis les
travaux de recherche sur le data engineering appliqué aux données biomédicales, les systèmes RAG
et leur évaluation, et les assistants conversationnels en génomique. Il en tire les zones de
recherche manquantes auxquelles ce travail répond.

**Le chapitre II — Analyse des besoins et méthodologie** spécifie les besoins des professionnels
de santé et les données : sources, processus de collecte, pré-traitement à travers les couches du
pipeline. Il expose ensuite la méthodologie : choix des modèles et de l'architecture de recherche,
leur justification, leur paramétrage, ainsi que les métriques et le protocole d'évaluation.

**Le chapitre III — Implémentation** présente les résultats (analyse exploratoire des données,
résultats des mesures, interprétation, comparaison avec la littérature et discussion), puis les
outils de développement, l'architecture de la solution et son déploiement.

**La conclusion générale** dresse le bilan du travail au regard de la problématique et ouvre des
perspectives : extension à d'autres gènes et à d'autres maladies, intégration de nouvelles
sources (fréquences populationnelles, cohortes africaines, données somatiques) et interface
destinée aux professionnels de santé.

## 5. Conclusion

Ce travail part d'un constat simple : les connaissances nécessaires à l'interprétation des
variants sont publiques, mais leur consultation reste longue, technique, en anglais, et les
structures qui en ont besoin disposent de moyens limités. Les modèles de langage permettent de les
interroger en français, à condition de les adosser à des données fiables. Ce mémoire défend
l'idée que **la fiabilité d'un assistant génomique se construit d'abord dans sa chaîne de
données**, et qu'elle peut l'être à un coût soutenable ; il le démontre sur deux cas
d'application. Le chapitre suivant situe cette démarche par rapport aux travaux existants.

---

<!--
Notes pour l'auteur (à supprimer avant export) :

1. Références à vérifier et à compléter dans la bibliographie (année et revue exactes) :
   - Landrum M. J. et al. — articles de présentation de ClinVar, Nucleic Acids Research.
   - Köhler S. et al. — articles de présentation de la Human Phenotype Ontology, Nucleic Acids Research.
   - Lewis P. et al. (2020) — « Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks », NeurIPS.
   - Richards S. et al. (2015) — recommandations ACMG/AMP pour l'interprétation des variants, Genetics in Medicine.
   - Popejoy A. B., Fullerton S. M. (2016) — « Genomics is failing on diversity », Nature.
   - Es S. et al. — RAGAS : « Automated Evaluation of Retrieval Augmented Generation ».
   - Une source publiée pour « 2 à 5 % des cancers du sein héréditaires, jusqu'à 15 % des triple négatifs ».
   - Une source publiée sur la prévalence de la drépanocytose en Afrique de l'Ouest.

2. Le constat (§1.1 à §1.4) n'utilise volontairement aucune mesure du projet : les mesures
   (précision 0,305 de la similarité seule, 4,8 % de documents sans phénotype, écart +0,361
   entre modèles d'embedding) prouvent la solution et vont au chapitre III.

3. « Sobre en ressources » (OS4) engage à fournir des chiffres au chapitre III : RAM au repos de
   la stack, durée d'un cycle complet sur CPU, temps d'indexation CPU, coût par question.
   Déjà disponibles : NiFi écarté pour 1,37 Gio de RAM au repos (reference/choix_contexte.md),
   coût observé ~0,000025 $/question avec gpt-oss. À mesurer : le reste.

4. Si l'OS3 est conservé, prévoir sa démonstration (ajout d'un petit panel de test) ;
   sinon, le déplacer en perspective.
5. H3 et OS7 supposent que l'évaluation E3 et la comparaison avec un LLM seul soient faites.
6. Le texte cite « Glu6Val » comme difficulté : le système ne gère pas encore ce nom.
   Soit la correspondance est implémentée, soit le chapitre III la présente comme limite.
7. Vérifier avec le spécialiste de l'Institut Pasteur qu'il accepte la mention de la
   sous-traitance BRCA et de son coût dans un mémoire public.
-->
