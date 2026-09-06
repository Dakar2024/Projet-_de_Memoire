# Choix de la méthode d'ingestion — contexte, alternatives et justification

**Projet :** Pipeline de Data Engineering pour un système RAG d'interrogation de variants ADN
**Date :** 2026-09-06
**Objet :** justifier le choix d'une ingestion par scripts Python, comparée à Apache NiFi et
Apache Kafka, sur la base de mesures réalisées sur les sources réelles du projet.

Document destiné à être repris en annexe du mémoire. Tous les chiffres cités ont été mesurés
sur la machine de développement ; le protocole est donné en annexe A pour permettre leur
reproduction.

---

## 1. Résumé exécutif

L'ingestion du projet est assurée par des **scripts Python**, ordonnancés par **Apache
Airflow**. Apache NiFi a été implémenté puis retiré ; Apache Kafka a été évalué et écarté.

La raison est unique et tient à la nature des sources : ce projet consomme **deux fichiers
plats publiés une fois par mois et quelques centaines d'appels REST soumis à un quota**. Il
n'existe aucun flux continu, aucun producteur d'événements, aucun problème de débit. NiFi et
Kafka sont conçus pour résoudre des problèmes que ce projet n'a pas, et leur coût
opérationnel est mesurable alors que leur apport ne l'est pas.

Ce document ne conclut pas que NiFi et Kafka sont de mauvais outils. Il établit **à quelles
conditions ils deviendraient le bon choix** (sections 6 et 7), afin que la décision reste
révisable si les sources du projet changent de nature.

---

## 2. Le déterminant : le profil réel des sources

Toute l'argumentation repose sur ce tableau. Il décrit ce que le projet ingère réellement.

| Source | Nature technique | Volume | Cadence de publication | Facteur limitant |
|---|---|---|---|---|
| **ClinVar** | Fichier plat, snapshot complet | 442 Mo compressé | **Mensuelle**, archives versionnées | Débit disque et réseau |
| **NCBI Gene** | API REST, dimension lente | 18 enregistrements | Quasi jamais | **Quota : 3 req/s** |
| **MedGen** | API REST + blob XML imbriqué | ~600 concepts | Rare | **Quota : 3 req/s** |
| **RefSeq** | API REST | ~110 transcrits | Rare | **Quota : 3 req/s** |
| **HPO** | Fichier plat + API, ontologie (graphe) | Quelques Mo | 2 à 4 fois par an | Quota |

Trois conséquences en découlent, et ce sont elles qui commandent le choix d'outil.

### 2.1 Le pipeline est limité par la latence, pas par le volume

Les appels séquentiels aux E-utilities du NCBI, plafonnés à 3 requêtes par seconde sans clé
d'API, représentent environ **7 minutes** — c'est-à-dire la quasi-totalité de la durée d'un
run. Le traitement des 97 000 lignes retenues prend moins d'une seconde.

Le goulot d'étranglement est donc une **politique de quota imposée par un tiers**. Aucun
outil d'ingestion, quel qu'il soit, ne peut le lever. Cette observation disqualifie à elle
seule tout argument de performance en faveur d'une infrastructure distribuée.

### 2.2 Il n'existe pas d'événements

Kafka, NiFi et l'ensemble des architectures orientées flux supposent un **producteur qui
émet en continu**. Ici, ClinVar publie un fichier par mois. Il n'y a rien à consommer entre
deux publications. Un broker resterait inactif 99,99 % du temps.

### 2.3 La difficulté est structurelle, pas volumétrique

Les données sont semi-structurées et fortement liées : un blob XML (`conceptmeta` de MedGen),
un champ multivalué empaqueté (`PhenotypeIDS`), une ontologie en graphe (HPO), et une chaîne
de jointures `variant → gène → maladie → phénotype`. L'effort d'ingénierie porte sur le
**parsing, la normalisation et l'intégrité référentielle** — des tâches qui s'écrivent en
code, et qu'aucun outil graphique ne simplifie.

---

## 3. Ce que chaque candidat est réellement conçu pour faire

Comparer des outils suppose d'abord de rappeler le problème que chacun résout.

**Scripts Python.** Du code d'intégration : appels HTTP, gestion de quota, retries, parsing
de formats hétérogènes, écriture de fichiers. Aucun démon, aucun état résident.

**Apache NiFi.** Un outil de *dataflow* : déplacer des données d'un point A vers un point B,
avec routage conditionnel, backpressure entre étapes de vitesses différentes, et traçabilité
par flowfile. Son interface graphique permet à un opérateur non-développeur de modifier un
flux en production.

**Apache Kafka.** Un journal distribué, ordonné et rejouable. Il découple des producteurs de
plusieurs consommateurs indépendants, absorbe des débits élevés, et garantit l'ordre par
partition.

Aucune de ces trois descriptions n'est fausse. La question est de savoir **laquelle décrit le
problème de ce projet**.

---

## 4. Benchmark comparatif

### 4.1 Coût opérationnel — mesuré

Mesures réalisées le 2026-09-06, conteneurs Docker au repos, configuration par défaut.

| Critère | Scripts Python | Apache NiFi 2.6.0 | Apache Kafka (KRaft) |
|---|---|---|---|
| Taille de l'image / des dépendances | **436 Mo** (venv) | 2,25 Go | 686 Mo |
| RAM au repos | **0** (aucun démon) | **1,37 Gio** (flow **vide**) | **296 Mio** |
| Temps de démarrage | **0 s** | **61,6 s** | quelques secondes |
| Heap JVM par défaut | sans objet | `-Xmx1g` | JVM également |
| Processus résident à maintenir | aucun | 1 (JVM) | 1 broker minimum |

Deux précisions d'honnêteté intellectuelle :

- Le chiffre de 1,37 Gio pour NiFi est un **plancher absolu** : il correspond à une instance
  sans aucun processeur configuré. Un flow réel consomme davantage. Une estimation antérieure
  de ce projet avançait « 2 à 4 Go » sans mesure ; la mesure la contredit partiellement et
  c'est la mesure qui fait foi.
- Kafka à 296 Mio est plus léger que NiFi. Sa disqualification pour ce projet n'est donc
  **pas** un argument d'empreinte mémoire, mais un argument d'adéquation (section 4.2).

Sur un VPS de 12 Go accueillant déjà Airflow, PostgreSQL et MinIO, chaque gigaoctet compte.
Les scripts Python n'ont pas d'empreinte au repos parce qu'ils **n'existent que pendant leur
exécution** — propriété qu'aucun système à démon ne peut offrir.

### 4.2 Adéquation fonctionnelle aux sources du projet

| Capacité de l'outil | Le projet en a-t-il besoin ? | Justification |
|---|---|---|
| Streaming continu | **Non** | Publication mensuelle ; aucun producteur d'événements |
| Backpressure | **Non** | Aucune étape rapide n'alimente une étape lente |
| Partitionnement / ordre garanti | **Non** | Aucune contrainte d'ordre entre variants |
| Consommateurs multiples indépendants | **Non** | Un seul consommateur : le médaillon |
| Rejeu depuis un journal | **Non** | Le rejeu se fait depuis Bronze sur MinIO, permanent |
| Routage conditionnel sans code | **Non** | Un seul chemin, exprimé en 15 lignes de Python |
| Interface graphique pour non-développeurs | **Non** | Un développeur unique, un dépôt versionné |
| Gestion de quota d'API | **Oui** | Assurée par `RateLimiter`, testable unitairement |
| Parsing XML / ontologies | **Oui** | Code Python ; aucun outil graphique ne le simplifie |
| Retries sur 429/5xx | **Oui** | Assurée par `urllib3.Retry`, testable unitairement |

Les trois capacités dont le projet a réellement besoin sont **toutes** couvertes par du code,
et aucune n'est fournie par NiFi ou Kafka.

### 4.3 Deux obstacles techniques dirimants pour Kafka

Vérifiés sur un broker Kafka en configuration par défaut :

| Paramètre par défaut | Valeur mesurée | Conséquence pour ce projet |
|---|---|---|
| `message.max.bytes` | **1 048 588 octets** (≈ 1 Mo) | Le bulk ClinVar (442 Mo) est **421 fois** au-dessus de la limite. Il faudrait le découper artificiellement, puis le réassembler — une complexité pure. |
| `log.retention.hours` | **168 heures** (7 jours) | La couche Bronze doit être **permanente et rejouable**. Kafka purgerait les données après une semaine. Il faudrait donc *quand même* MinIO : Kafka ne serait pas un stockage, seulement un saut réseau supplémentaire. |

Ces deux valeurs sont ajustables, mais les augmenter jusqu'à absorber un fichier de 442 Mo
en rétention infinie revient à détourner Kafka de sa conception pour lui faire imiter un
stockage objet — que MinIO fournit déjà, mieux et pour moins cher.

### 4.4 Testabilité — le critère décisif

| Critère | Scripts Python | NiFi | Kafka |
|---|---|---|---|
| Logique testable sans infrastructure | **Oui** | Non | Non |
| Suite de tests actuelle | **63 tests, 1,7 s, sans réseau** | — | — |
| Versionnement de la logique dans Git | **Oui**, en clair | Flow exporté en JSON, illisible en revue | Sans objet |
| Revue de code possible | **Oui** | Difficilement | Sans objet |

C'est le point le plus structurant. La logique d'ingestion du projet est **entièrement
couverte par 63 tests unitaires s'exécutant en 1,7 seconde sans réseau ni conteneur**. Un
flow NiFi ne se teste pas ainsi : il se vérifie en l'exécutant, dans une instance démarrée en
61,6 secondes, et son contenu versionné est un JSON généré que personne ne relit.

### 4.5 Synthèse

| | Scripts Python | NiFi | Kafka |
|---|---|---|---|
| Adéquation au profil des sources | ★★★ | ★ | ☆ |
| Coût opérationnel | ★★★ | ★ | ★★ |
| Testabilité | ★★★ | ★ | ★ |
| Traçabilité et revue | ★★★ | ★ | ★★ |
| Capacité à grossir (avec le médaillon) | ★★ | ★★ | ★★★ |
| **Retenu pour ce projet** | **Oui** | Non | Non |

---

## 5. Pourquoi les scripts Python l'emportent ici

Quatre arguments, par ordre de solidité devant un jury.

**Le problème est un problème de code, pas de flux.** Gérer un quota de 3 requêtes par
seconde, réessayer sur un HTTP 429, parser un XML imbriqué, aplatir une ontologie : ce sont
des opérations qui s'expriment naturellement en code et se vérifient par des tests. Les
exprimer dans une interface graphique les rend plus difficiles à écrire, à relire et à
tester.

**Le coût est nul au repos.** Un script n'existe que pendant son exécution. Sur une
infrastructure contrainte, c'est un avantage structurel qu'aucun démon ne peut égaler.

**La logique est vérifiable sans infrastructure.** 63 tests, 1,7 seconde, aucun réseau. Cette
propriété permet d'affirmer la justesse du pipeline en la démontrant, et non en l'affirmant.

**La décision reste réversible.** Les scripts sont appelés par Airflow comme des unités
d'exécution paramétrées. Si les sources changeaient de nature, ces mêmes scripts pourraient
être appelés depuis un processeur NiFi ou devenir des producteurs Kafka, sans que la logique
métier change.

---

## 6. Dans quel contexte NiFi deviendrait le bon choix

NiFi n'est pas écarté par principe. Il le serait par erreur si l'une de ces conditions
apparaissait. Ces scénarios sont réalistes pour une extension du projet.

**Réception de fichiers déposés par des laboratoires partenaires.** Si des laboratoires
déposaient des fichiers VCF par SFTP, à des rythmes irréguliers et dans des variantes de
format, NiFi deviendrait pertinent : ses processeurs `ListSFTP`/`FetchSFTP`, son routage par
attribut et sa **provenance par fichier** répondent exactement à ce problème. Retracer « d'où
vient ce fichier, quand est-il arrivé, par quelles étapes est-il passé » est une exigence
réglementaire courante en biologie médicale, et c'est nativement ce que NiFi fournit.

**Sources multiples et hétérogènes en protocole.** Dès que l'on combine SFTP, HL7, JMS, une
file d'attente et plusieurs APIs, écrire et maintenir un connecteur par protocole devient
coûteux. NiFi les fournit et les fait cohabiter dans un flux unique.

**Exploitation par un opérateur non-développeur.** Si le pipeline devait être ajusté en
production par un bio-informaticien ou un technicien sans passer par un cycle de
développement, l'interface graphique de NiFi devient un avantage réel et non un gadget.

**Backpressure entre étapes de vitesses différentes.** Si une étape rapide alimentait une
étape lente, la gestion automatique de la contre-pression éviterait d'écrire à la main une
logique de file d'attente et de reprise.

**Aucune de ces conditions n'est réunie aujourd'hui :** une source de fichiers en HTTPS, des
APIs REST, un seul développeur, un dépôt Git, et aucune étape lente en aval.

---

## 7. Dans quel contexte Kafka deviendrait le bon choix

**Flux continu depuis un séquenceur.** Si un automate de séquençage produisait des résultats
en continu, Kafka fournirait le tampon durable entre production et traitement.

**Plusieurs consommateurs indépendants de la même donnée.** C'est le scénario le plus
plausible pour ce projet. Si un même événement devait alimenter simultanément l'indexation
RAG, un tableau de bord épidémiologique et un système d'alerte, Kafka permettrait à chaque
consommateur de progresser à son rythme et de rejouer l'historique indépendamment.

**Notification de reclassification de variants.** Extension concrète et scientifiquement
pertinente : lorsqu'un variant change de signification clinique (VUS → pathogène), les
laboratoires ayant rendu un compte-rendu sur ce variant devraient être notifiés. C'est un
véritable flux d'événements, avec plusieurs destinataires et une exigence de rejeu — le cas
d'usage canonique de Kafka.

**Découplage à haut débit.** Si le volume atteignait un rythme où producteurs et
consommateurs ne peuvent plus être synchrones.

**Aujourd'hui :** un producteur (un fichier mensuel), un consommateur (le médaillon), aucune
contrainte de débit. Introduire Kafka reviendrait à ajouter un intermédiaire entre deux
composants qui n'ont pas besoin d'être découplés.

---

## 8. Pourquoi Airflow pour l'orchestration

Retenir des scripts Python pour l'ingestion et Airflow pour l'orchestration n'est pas une
contradiction : ce sont deux rôles distincts.

**Ce qu'Airflow apporte et qu'un script ne fournit pas :** l'ordonnancement déclaratif et le
backfill par date logique, la reprise sélective d'une tâche en échec sans rejouer les
précédentes, les dépendances explicites entre étapes, la visualisation de l'état des runs, la
politique de retries paramétrable par tâche, et — en version 3 — les **Assets**, qui
déclenchent un DAG par la disponibilité d'une donnée plutôt que par l'horloge.

**Ce qu'Airflow ne fait pas, et ne doit pas faire :** transporter des données, ni transformer
quoi que ce soit. Il déclenche, ordonne, surveille et rejoue. La règle appliquée dans ce
projet est stricte : **aucune logique métier dans un DAG.** Les tâches appellent des fonctions
de `src/`, ce qui préserve la testabilité sans infrastructure.

**Pourquoi Airflow plutôt que NiFi pour ce rôle :** NiFi est un outil de dataflow, pas un
ordonnanceur de tâches hétérogènes. Il ne fournit ni backfill par date logique, ni reprise
partielle de graphe, ni dépendances entre jobs de natures différentes. Dans l'implémentation
NiFi initiale de ce projet, le flow se réduisait à un `ExecuteStreamCommand` lançant un script
Python, plus un routage sur le code de sortie : un sous-ensemble strict de ce qu'Airflow
fournit, pour 1,37 Gio de RAM supplémentaires.

---

## 9. Faiblesses et failles des scripts d'ingestion actuels

Cette section est le pendant critique des précédentes. Choisir les scripts Python n'implique
pas que leur implémentation actuelle soit exempte de défauts : elle est dimensionnée pour 18
gènes et le restera jusqu'à la soutenance, mais elle présente des limites identifiées et
mesurées. Les exposer et les corriger est ce qui distingue un choix d'ingénierie d'un choix
par défaut.

Priorité : **P1** = à corriger avant la mise en production sur VPS · **P2** = à corriger
avant tout élargissement du panel · **P3** = dette technique à traiter.

### 9.1 Idempotence — P1

| Faille | Preuve | Impact | Correctif |
|---|---|---|---|
| Les URL de source pointent sur « latest » | ClinVar et HPO exposent des archives versionnées ; les scripts utilisent l'URL mouvante | Rejouer un run de `dt=2026-08-01` téléchargerait le fichier de septembre : le rejeu n'est pas reproductible | Épingler `variant_summary_YYYY-MM.txt.gz` et la release HPO taguée sur la date logique |
| La provenance utilise l'horloge murale | `_provenance.collected_at = datetime.now()` | Deux exécutions du même run produisent des documents différents | Faire porter à la provenance la date logique `{{ ds }}` |
| Le cache ignore la version demandée | `download_to_file` saute le téléchargement si le fichier existe, sans vérifier de quelle release il provient | Une partition peut être silencieusement remplie avec les données d'un autre mois | Indexer le cache par version de source |

### 9.2 Robustesse — P1

| Faille | Preuve | Impact | Correctif |
|---|---|---|---|
| Aucun point de reprise | Rien n'est écrit avant la fin du run | Une coupure au 1 100ᵉ appel sur 1 200 perd la totalité du travail ; avec `retries=3`, Airflow relancerait trois collectes complètes | Persister les réponses d'API au fil de l'eau et reprendre là où le run s'est arrêté |
| Aucun contrôle d'intégrité au téléchargement | Le serveur renvoie `Content-Length: 442495433`, jamais vérifié | Un fichier tronqué est indiscernable d'un fichier complet et sera mis en cache comme valide | Comparer la taille reçue à la taille annoncée avant le renommage atomique |
| Erreur de configuration traitée comme transitoire | `SystemExit` levé pour `NCBI_EMAIL` absent | Une erreur permanente serait retentée trois fois inutilement | Exception dédiée, `retries=0` sur ce cas |
| Verdict qualité rendu par l'ingestion | `sys.exit(1)` après écriture des fichiers si des gènes sont incomplets | Un résultat partiel mais déterministe déclenche trois relances, soit ~21 minutes d'appels inutiles | Déplacer `find_empty_genes` vers une tâche `check_bronze` distincte |

### 9.3 Passage à l'échelle — P2

| Faille | Mesure | Impact | Correctif |
|---|---|---|---|
| Tout est matérialisé en mémoire | **4,71 Ko par ligne** mesurés sur 43 colonnes ; `to_dicts()` puis tous les documents conservés en RAM | 0,4 Go aujourd'hui, ~2,5 Go pour 100 gènes, **~27 Go pour ClinVar complet** — arrêt par l'OOM killer | Écriture en flux par partition, sans matérialisation Python |
| Refiltrage du jeu complet une fois par gène | À volume constant (400 000 lignes), le temps est multiplié par **7,6** entre 25 et 6 400 gènes | Coût pur, sans contrepartie | Une seule passe par `partition_by` |
| Absence de batching des appels `esummary` | L'API accepte `id=uid1,uid2,…` ; le code envoie un identifiant par requête | Volume d'appels environ **100 fois** supérieur au nécessaire ; ~11 h estimées pour ClinVar complet | Regrouper les identifiants par lot |
| Déduplication en O(n²) | `if cui not in all_cuis` sur une **liste**, à trois endroits (`run_collection.py:64`, `orchestrate.py:89`, `medgen.py:15`) | Négligeable à 600 CUI, ~5 × 10⁹ comparaisons à 100 000 | Utiliser un `set` d'appoint tout en conservant l'ordre |
| Format de sortie non interrogeable | **6,5 Mo** pour un gène de 4 000 variants ; JSON indenté, non compressé, sans schéma | Lecture intégrale obligatoire pour un seul champ ; pas de projection ni de filtrage | Résolu par le passage à Parquet/Delta en Silver |

### 9.4 Qualité de code — P3

| Faille | Preuve | Impact | Correctif |
|---|---|---|---|
| Règle métier implémentée deux fois | `extract_medgen_cuis` (Python) n'est **appelée par aucun code de production** — uniquement par les tests ; le chemin réel passe par `add_medgen_cuis` (vectorisé) | Deux implémentations de la même règle d'extraction de CUI, susceptibles de diverger ; une fonction testée qui ne protège rien | Choisir une implémentation de référence et supprimer ou réorienter l'autre |
| Aucune journalisation structurée | Uniquement `print()` (`run_collection.py`, `orchestrate.py:31`) | Sous Airflow, pas de niveaux, pas de contexte, pas de filtrage | Passer au module `logging` |
| Chemins figés | `config.py` ancre les chemins sur `parents[2]`, sans surcharge possible | Empêche le passage d'une destination S3 et d'une date logique | Variable d'environnement `LAKE_URI` avec valeur par défaut locale |
| Dépendance retirée de PyPI | `polars==1.43.0` est marquée *yanked* | Une installation peut échouer sans préavis | Réépingler sur une version valide |
| Absence de client S3 | Ni `boto3` ni `s3fs` dans `requirements.txt` | Écriture vers MinIO impossible en l'état | Ajouter `boto3` |

### 9.5 Ce qui, à l'inverse, est solide et ne doit pas être réécrit

L'audit serait déséquilibré sans cette contrepartie. Les éléments suivants sont corrects et
resteront valides à toute échelle :

- `download.py` — téléchargement en flux, écriture dans un `.part` puis renommage atomique :
  une coupure ne laisse jamais un fichier partiel réutilisable comme complet.
- `http_client.py` — `RateLimiter` à horloge et fonction de sommeil injectables, donc
  testable sans attente réelle ; retries sur 429/5xx par `urllib3.Retry`.
- Les parseurs `medgen.py` et `hpo.py` — logique pure, indépendante du volume.
- Le traitement des cas dégradés — CUI non résolvable, XML malformé, terme HPO retiré : tous
  traités comme des données manquantes légitimes plutôt que comme des erreurs.
- La couverture de tests — 63 tests en 1,7 s sans réseau.

**Les défauts sont concentrés dans `orchestrate.py` et dans le format de sortie**, c'est-à-dire
exactement la frontière que l'architecture médaillon remplace. La migration vers Bronze/Silver
/Gold n'est donc pas un exercice imposé : c'est le correctif des sections 9.1 à 9.3.

---

## 10. Pourquoi cette architecture est défendable

L'argumentaire à présenter au jury tient en quatre propositions, chacune adossée à une mesure.

**Le choix découle d'un diagnostic, pas d'une préférence.** Le profil des sources a été
caractérisé avant que l'outil ne soit choisi : publication mensuelle, quota de 3 requêtes par
seconde, absence de flux. Le goulot mesuré est une politique de quota, qu'aucune
infrastructure ne peut lever.

**Les alternatives ont été implémentées et mesurées, pas écartées par principe.** NiFi a été
déployé, son flow construit, son chemin d'échec vérifié de bout en bout, son empreinte
mesurée à 1,37 Gio. Kafka a été instancié et ses limites de configuration relevées sur un
broker réel. Les conditions de leur retour sont explicitées (sections 6 et 7).

**La justesse du pipeline est démontrable, pas affirmée.** 63 tests s'exécutent en 1,7 seconde
sans réseau ni conteneur. Cette propriété est vérifiable en direct devant un jury et
constitue le meilleur argument de fiabilité du projet.

**Les limites sont connues et chiffrées.** La section 9 documente les failles de
l'implémentation actuelle avec leurs mesures et leurs correctifs. Une architecture dont
l'auteur connaît les seuils de rupture est plus solide qu'une architecture présentée comme
sans défaut.

### Formulation proposée pour la soutenance

> « J'ai caractérisé mes sources avant de choisir mes outils. Elles publient une fois par
> mois et imposent un quota de trois requêtes par seconde : mon goulot est une politique de
> quota, pas un problème de débit. J'ai implémenté NiFi, mesuré son coût à 1,37 Gio pour un
> flow vide, et constaté que son apport — planification, routage, journalisation — est un
> sous-ensemble de ce qu'Airflow me fournit déjà. J'ai évalué Kafka et relevé que le fichier
> ClinVar dépasse de 421 fois la taille de message par défaut, et que sa rétention de sept
> jours est incompatible avec une couche Bronze permanente. J'ai retenu des scripts Python
> ordonnancés par Airflow, dont la logique est couverte par 63 tests qui s'exécutent en
> 1,7 seconde sans infrastructure. Et j'ai documenté les conditions dans lesquelles NiFi ou
> Kafka deviendraient le bon choix. »

---

## Annexe A — Protocole de mesure

Toutes les mesures ont été réalisées le 2026-09-06 sur la machine de développement
(16 cœurs, 31 Gio de RAM, Linux), afin de permettre leur reproduction.

**Empreintes NiFi et Kafka.** Conteneurs Docker officiels en configuration par défaut,
mesurés au repos après stabilisation complète du démarrage, via
`docker stats --no-stream`. NiFi : `apache/nifi:2.6.0`, aucun processeur configuré. Kafka :
`apache/kafka:latest` en mode KRaft mono-nœud. Les paramètres par défaut du broker ont été
relevés par `kafka-configs.sh --describe --all`.

**Coût mémoire par ligne.** Mesure de la RSS du processus avant et après l'appel à
`build_gene_documents`, sur 200 000 lignes de 43 colonnes de largeur réaliste. Les
extrapolations vers 550 000 et 6 000 000 de lignes sont linéaires et signalées comme telles.

**Effet du refiltrage par gène.** Volume total maintenu constant à 400 000 lignes ; seul le
nombre de gènes distincts varie, de 25 à 6 400. Isole le terme en O(gènes × lignes).

**Cadence de publication des sources.** Relevée sur les en-têtes HTTP et le listing d'archives
du serveur FTP du NCBI, ainsi que sur les redirections de la PURL du projet HPO.

---

## Annexe B — Tableaux réutilisables dans le mémoire

### B.1 Comparatif des méthodes d'ingestion

| Critère | Scripts Python | Apache NiFi | Apache Kafka |
|---|---|---|---|
| Empreinte au repos | 0 | 1,37 Gio | 296 Mio |
| Image / dépendances | 436 Mo | 2,25 Go | 686 Mo |
| Démarrage | 0 s | 61,6 s | quelques s |
| Logique testable hors infrastructure | Oui | Non | Non |
| Adapté à une source mensuelle | Oui | Surdimensionné | Inadapté |
| Adapté à un flux continu | Non | Oui | Oui |
| Taille de message maximale | sans objet | sans objet | 1 Mo par défaut |
| Rétention | permanente (MinIO) | sans objet | 7 jours par défaut |
| **Verdict pour ce projet** | **Retenu** | Écarté | Écarté |

### B.2 Limites mesurées de l'implémentation actuelle

| Mesure | Valeur | Seuil de rupture |
|---|---|---|
| Coût mémoire par ligne | 4,71 Ko | ~27 Go pour ClinVar complet |
| Durée d'une collecte (18 gènes) | ~7 min | ~11 h estimées pour ClinVar complet |
| Surcoût du refiltrage par gène | ×7,6 de 25 à 6 400 gènes | linéaire en nombre de gènes |
| Taille d'un document de sortie | 6,5 Mo pour 4 000 variants | lecture intégrale obligatoire |
| Suite de tests | 63 tests, 1,7 s, sans réseau | — |

### B.3 Conditions de révision de la décision

| Si… | Alors reconsidérer |
|---|---|
| des fichiers arrivent en continu par SFTP depuis des laboratoires | **NiFi** |
| plusieurs protocoles hétérogènes doivent cohabiter (HL7, JMS, SFTP) | **NiFi** |
| un opérateur non-développeur doit modifier le flux en production | **NiFi** |
| plusieurs consommateurs indépendants doivent rejouer la même donnée | **Kafka** |
| les reclassifications de variants doivent être diffusées en notifications | **Kafka** |
| les données dépassent la mémoire d'une machine | moteur distribué |

---

## Références internes

- `docs/superpowers/specs/2026-09-04-pipeline-medaillon-airflow-minio-design.md` — design de
  l'architecture médaillon Bronze/Silver/Gold sur MinIO, ordonnancée par Airflow.
- `fichiers de base /guide_recuperation_donnees.md` — méthode vérifiée d'accès à chaque source.
- `nifi/README.md` — implémentation NiFi conservée comme alternative évaluée.
- `src/ingestion/` — modules d'ingestion et leur couverture de tests.
