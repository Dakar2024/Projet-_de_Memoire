# RAG génomique — E1 : indexation, E2a : recherche, E2b : génération et API

E1 copie les documents de `gold/rag/documents` dans une base vectorielle (PostgreSQL +
pgvector), avec leurs vecteurs, de façon incrémentale, reprenable et vérifiée (§1 à §7).
E2a cherche dans cette base à partir d'une question en français (§8). E2b génère une réponse
vérifiée contre les fiches retrouvées et l'expose par une API locale Litestar, derrière une
passerelle et un proxy sortant filtrant (§9). Reste :

- **E3** (à venir) : évaluation RAGAS, choix du modèle de génération et audit.

Documents de référence :

- spec : `docs/superpowers/specs/2026-10-01-sous-projet-e1-indexation-rag-design.md` ;
- choix du modèle, mesuré : `reference/choix_embedding.md` ;
- spec de E2b : `docs/superpowers/specs/2026-10-08-sous-projet-e2b-generation-api-design.md`
  (amendements au §10).

## 1. Architecture

```
gold/rag/documents (MinIO, Delta)
        │  lu par la tâche Airflow index_rag_documents, après quality_check_gold
        ▼
RAG/src/ingestion/indexer.py ── canari ──► rag-embeddings (TEI, /embed, /tokenize)
        │
        ▼  une transaction par lot de 32
rag-postgres : table rag_documents (vector(768), index HNSW cosinus)
```

| Service | Rôle | Exposition |
|---|---|---|
| `rag-postgres` | base vectorielle, distincte de la base d'Airflow | aucun port sur l'hôte, réseau `rag-network` seul |
| `rag-postgres-init` | applique `RAG/sql/001_schema.sql` (idempotent) à chaque démarrage, puis s'arrête | — |
| `rag-embeddings` | sert le modèle exporté (CPU par défaut) | aucun port, utilisateur non root, racine en lecture seule, clé d'API obligatoire |
| `rag-model-export` | outil d'export ONNX à la demande (profil `outils`) | seul service du RAG à sortir sur Internet ; dépendances verrouillées par empreinte pour x86_64 seulement |

`rag-network` est un réseau **interne**, sans accès sortant. Les services Airflow y sont
rattachés pour joindre la base et le service d'embedding.

Comptes PostgreSQL :

| Compte | Utilisé par | Droits |
|---|---|---|
| `rag_owner` | `rag-postgres-init` | superutilisateur d'amorçage créé par l'image PostgreSQL, propriétaire du schéma |
| `rag_indexer` | Airflow | lecture et écriture de `rag_documents` uniquement |
| `rag_reader` | API de E2 | lecture seule |

**Le Gold est la source de vérité.** La base vectorielle se reconstruit entièrement depuis
lui : environ 9 minutes sur GPU, environ 4 heures sur CPU (§6).

## 2. Configuration

- **Secrets et adresses** : dans `.env` (voir `.env.example`) — `RAG_EMBEDDING_MODEL`,
  `RAG_EMBEDDINGS_API_KEY`, `RAG_OWNER_PASSWORD`, `RAG_INDEXER_PASSWORD`,
  `RAG_READER_PASSWORD`.
  - Ces cinq variables sont **obligatoires pour toute commande `docker compose`**, y compris
    celles du pipeline de données.
  - Elles s'ajoutent au `.env` **de la racine du dépôt**.
- **Réglages non secrets** : dans `RAG/config.yaml` — empreinte du modèle attendu, fichier du
  canari, seuil du canari (0,995), taille des lots (32), seuil de suppression (5 %).
- **Changement de dépendances** : reconstruire **toutes** les images Airflow, avec
  `docker compose --env-file .env build`. Chaque service Airflow a sa propre image : n'en
  reconstruire qu'une laisse les autres sans les bibliothèques du RAG.

## 3. Installer le modèle

Le modèle retenu est `NeuML/pubmedbert-base-embeddings`. La mesure qui justifie ce choix est
dans `reference/choix_embedding.md`.

```bash
cd ~/Documents/Projet-_de_Memoire

# 1. Export ONNX reproductible (dépendances verrouillées par empreinte, machine x86_64)
docker compose --env-file .env --profile outils build rag-model-export
docker compose --env-file .env --profile outils run --rm rag-model-export \
  --model NeuML/pubmedbert-base-embeddings
# → affiche l'empreinte, aussi écrite dans data/models/pubmedbert-base-embeddings/export.json

# 2. Recopier cette empreinte dans RAG/config.yaml (embedding.fingerprint),
#    et le nom du dossier dans RAG_EMBEDDING_MODEL (.env)

# 3. Démarrer le service sur CPU, puis produire le canari (référence de production).
#    L'empreinte est lue dans export.json du dossier servi : la commande refuse de
#    produire le canari si elle diffère de celle de RAG/config.yaml.
docker compose --env-file .env up -d rag-embeddings
docker compose --env-file .env exec -T airflow-scheduler \
  python -m RAG.src.embeddings.canary > RAG/canari.json
```

**Ce qui garantit le modèle servi** tient en deux contrôles, refaits avant chaque indexation :

- **L'identité de la référence.** `RAG_EMBEDDING_MODEL` désigne à la fois le dossier servi par
  `rag-embeddings` et celui dont l'indexation lit `export.json`. L'empreinte de ce fichier doit
  égaler celle de `RAG/config.yaml`, sinon l'indexation (et la production du canari) refuse
  de tourner.
- **L'égalité avec la référence : le canari.** Trois phrases fixes et leurs vecteurs de
  référence. Le service vectorise de nouveau ces phrases ; si un cosinus descend sous 0,995,
  l'indexation refuse de tourner. Le canari prouve que le service sert **le même modèle que
  la référence**, pas à lui seul quel modèle c'est : son `/info` renvoie seulement `/model`.

Sur CPU, le canari vaut 1,000000 **par construction** : la référence a été produite par ce même
service. Le chiffre informatif est celui du GPU (0,99999, §6).

## 4. Indexer

**Automatiquement** : la tâche `index_rag_documents` termine chaque DAG de panel, après
`quality_check_gold`.

- Elle passe par le pool `rag_index`, à un seul slot.
- Son délai maximal est de 6 heures.
- Un rejeu du même mois ne recalcule rien.

**À la main** :

```bash
docker compose --env-file .env exec airflow-scheduler python -c "
import logging; logging.basicConfig(level=logging.INFO)
from RAG.src.ingestion.indexer import run_index
for panel in ('brca', 'sickle'): print(run_index(panel))"
```

**Sur GPU**, pour une réindexation complète rapide : démarrer le service avec la variante GPU,
indexer, puis revenir au CPU.

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.gpu.yml up -d rag-embeddings
# … run_index …
docker compose --env-file .env up -d rag-embeddings
```

Indexer sur GPU puis interroger sur CPU est sûr. C'est mesuré : un même texte donne un cosinus
d'au moins 0,99897 sur les deux chemins, et le canari GPU a donné 0,99999 face à la référence
CPU.

### Ce que l'indexation refuse de faire

| Situation | Comportement |
|---|---|
| Une autre indexation du même panel tourne | échec immédiat (verrou PostgreSQL) |
| Le modèle servi n'est pas celui de `config.yaml` | échec définitif, aucune écriture |
| Un document dépasse 512 tokens | échec définitif, avec la liste des `doc_id` |
| Gold vide pour le panel | refus d'écrire, même forcé |
| Plus de 5 % de l'index à supprimer | refus d'écrire (voir ci-dessous) |
| Index différent du Gold après écriture | échec, avec le détail de l'écart |
| Service d'embedding injoignable | relances Airflow ; la reprise ne refait que le reste |

**Retrait massif légitime.** Si un mois retire réellement plus de 5 % des variants d'un panel,
vérifier d'abord le Gold, puis relancer à la main avec
`run_index(panel, force_deletions=True)`.

## 5. Changer de modèle

1. Exporter le nouveau modèle (§3, étape 1).
2. Mettre son dossier dans `RAG_EMBEDDING_MODEL` (`.env`) et son empreinte dans
   `RAG/config.yaml`.
3. Redémarrer `rag-embeddings`, puis régénérer `RAG/canari.json`.
4. Indexer. Tous les documents sont recalculés automatiquement, puisque l'empreinte a changé :
   des vecteurs issus de deux modèles ne cohabitent jamais dans l'index.

## 6. Mesures de référence (4 octobre 2026, i9-10885H, Quadro RTX 3000)

| Mesure | Valeur |
|---|---|
| Documents indexés | 96 910 (93 393 `brca`, 3 517 `sickle`) |
| Première indexation complète, GPU | 549 s (9 min 09) |
| Rejeu du même mois, CPU | 3 s, 0 document recalculé, 0 écriture |
| Débit mesuré du service sur CPU, ONNX | 7 documents/s, soit environ 4 h pour une réindexation complète |
| Canari | 0,99999 sur GPU, 1,000000 sur CPU |
| Taille de la table et de ses index | 871 Mo |
| Longueur des documents en tokens | médiane 145, maximum 257, pour une fenêtre de 512 |

## 7. Tests

```bash
pytest -q                 # logique, sans réseau ni conteneur
pytest tests_airflow -q   # structure des DAGs, dont la tâche index_rag_documents
```

Tests d'intégration contre le vrai `rag-postgres` : schéma, droits de chaque compte, écriture
tout-ou-rien, verrou. Ils se lancent depuis un conteneur du réseau interne, et seulement sur ce
fichier : les autres tests du RAG demandent `responses`, une dépendance de développement
absente de l'image Airflow. `-e RAG_READER_PASSWORD`, sans valeur, reprend la variable
exportée dans le shell : le secret n'apparaît pas dans les arguments du processus de l'hôte.

```bash
set -a; . ./.env; set +a
docker compose --env-file .env run --rm --no-deps \
  -e RAG_READER_PASSWORD \
  --entrypoint bash airflow-scheduler -c '
    pip install --quiet --target /tmp/pytest-lib pytest==9.1.1 &&
    export PYTHONPATH=/tmp/pytest-lib:$PYTHONPATH &&
    export RAG_TEST_PG_CONNINFO="host=rag-postgres dbname=rag user=rag_indexer password=$RAG_PG_PASSWORD" &&
    export RAG_TEST_PG_READER_CONNINFO="host=rag-postgres dbname=rag user=rag_reader password=$RAG_READER_PASSWORD" &&
    python -m pytest -p no:cacheprovider -m integration RAG/tests/test_vector_store_integration.py -q'
```

## 8. Recherche (E2a)

Spec : `docs/superpowers/specs/2026-10-04-sous-projet-e2a-recherche-rag-design.md` (amendements
au §9). La recherche ne génère pas de réponse : elle renvoie les 10 documents à transmettre au LLM
de génération (E2b) et une trace qui explique comment ils ont été trouvés.

### 8.1 Fonctionnement

```
question en français
  ├─ règles (RAG/src/retrieval/identifiers.py) : rs, HGVS c./p. normalisés comme ClinVar, gènes du panel
  ├─ LLM d'analyse (RAG/src/retrieval/analysis.py) : reformulation anglaise, signification demandée
  │    (énumération fermée, sortie JSON stricte), maladie ; indisponible → recherche dégradée signalée
  └─ cascade (RAG/src/retrieval/retriever.py), panel brca + sickle, compte rag_reader :
       1. étage exact : documents dont le rs ou le HGVS correspond (restreint au gène cité)
       2. filtres : gène cité, libellés ClinVar de la signification (relâchés sous 3 documents)
       3. similarité cosinus, toujours en recherche exacte (l'index HNSW est mesuré insuffisant, §8.5)
```

Indicateurs de la trace : `identifier_not_found`, `significance_relaxed`, `gene_out_of_panel`,
`analysis_unavailable`. La question n'atteint jamais le SQL : les filtres viennent des règles et
d'une énumération validée.

### 8.2 Service `rag-search`

Outil à la demande (profil `outils`), conservé à côté de l'API (`rag-api`, §9) : même image
(`docker/rag-api/`), mêmes réglages. Utilisateur non root, racine en lecture seule,
`no-new-privileges`, `cap_drop: ALL`, compte PostgreSQL `rag_reader`. Réseaux : `rag-network` (base,
embedding) et `rag-proxy-net` (interne) ; sa seule sortie Internet passe par le proxy filtrant
`rag-proxy` (§9.7), variables `HTTPS_PROXY` / `NO_PROXY`. Seuls `data/experiments/e2a` et
`data/experiments/e2a-essai` y sont montés en écriture : les créer sur l'hôte avant la première
mesure (`mkdir -p data/experiments/e2a data/experiments/e2a-essai`), sinon Docker les crée au nom de
root.

Au démarrage, la recherche vérifie que le service d'embedding sert le modèle de l'index (empreinte,
canari) et que toutes les lignes de l'index portent cette empreinte.

### 8.3 Clés

Dans le `.env` de la racine, facultatives pour le pipeline :

- `OPENROUTER_API_KEY` : profils officiels (`llm.profiles` de `RAG/config.yaml`), chacun figé sur
  un point d'accès OpenRouter sans basculement, en zéro rétention, sortie JSON stricte. Le
  fournisseur servi (champ `provider` de la réponse) et le coût (`usage.cost`) sont contrôlés ; une
  réponse d'un autre fournisseur est rejetée.
- `GROQ_API_KEY` : profil d'essai gratuit (`llm.trial_profiles`), zéro rétention à activer dans
  *Data Controls* de la console Groq. Il valide la chaîne ; il ne sert jamais au choix du modèle.

### 8.4 Essayer une question

```bash
docker compose --env-file .env --profile outils run --rm rag-search \
  -m RAG.src.retrieval.cli "Le variant rs80357906 sur BRCA1 est-il pathogène ?"
# --profile essai-groq-gpt-oss-120b pour l'essai gratuit ; --mode similarity|filters|full
```

### 8.5 Mesurer

Jeu de 89 questions validé par l'utilisateur (`RAG/experiments/questions_recherche.yaml`) :
59 questions de E1 traduites, 20 à identifiants tirés de l'index, 10 pièges.

```bash
# 1. Vérité terrain, sur l'hôte (lit le Gold dans MinIO)
set -a; . ./.env; set +a
export AWS_ENDPOINT_URL=http://127.0.0.1:${MINIO_API_PORT} AWS_ACCESS_KEY_ID=$MINIO_AIRFLOW_USER \
       AWS_SECRET_ACCESS_KEY=$MINIO_AIRFLOW_PASSWORD AWS_REGION=us-east-1 LAKE_URI=s3:// PYTHONPATH=src:.
venv/bin/python -m RAG.experiments.mesure_recherche verite-terrain

# 2. Séries, dans rag-search (le cache évite de repayer une analyse déjà faite)
R="docker compose --env-file .env --profile outils run --rm rag-search -m RAG.experiments.mesure_recherche"
for p in claude-opus-5.5 mistral-medium gpt-oss-120b; do $R mesurer --profile $p --mode full; done
venv/bin/python -m RAG.experiments.mesure_recherche evaluer        # désigne le profil retenu
for m in similarity filters; do $R mesurer --profile <retenu> --mode $m; done
$R mesurer --profile <retenu> --mode similarity --approx           # diagnostic de l'index HNSW
venv/bin/python -m RAG.experiments.mesure_recherche evaluer
# Essai gratuit : mêmes commandes avec --profile essai-groq-gpt-oss-120b, puis evaluer --essai
```

`evaluer` refuse de conclure si une série diverge (questions, prompt, configuration, corpus indexé,
modèle d'embedding), si un candidat manque, ou si les questions à identifiants ne sont pas réussies
à 100 %.

Répétition générale du 5 octobre 2026 (essai Groq, gpt-oss-120b, recherche exacte) :

| Version | P1-A | P1-B | P1-C | P2 | P3 |
|---|---|---|---|---|---|
| V0 E1 (questions anglaises) | 0,853 | 0,862 | 0,305 | — | — |
| V1 similarité seule | 0,838 | 0,729 | 0,330 | 0 | 0,70 |
| V2 + filtres | 0,907 | 0,829 | 0,495 | 0 | 0,70 |
| V3 complète | 0,907 | 0,829 | 0,495 | 1,000 | 1,000 |

Signification extraite juste dans 94 % des cas ; latence médiane : analyse 2,2 s, vectorisation
0,14 s, base 0,17 s (maximum 1,1 s). Rappel de l'index HNSW (`ef_search` 40) par rapport à la
recherche exacte : 0,515 — d'où la recherche toujours exacte. La mesure officielle (choix du modèle
d'analyse) sera consignée dans `reference/mesure_recherche_e2a.md`.

### 8.6 Tests d'intégration de la recherche

Depuis E2b, PyPI n'est plus joignable depuis `rag-search` (le proxy n'autorise que les LLM) : ces
tests se lancent avec `rag-api-test`, comme ceux de l'API (§9.9), en nommant
`RAG/tests/test_search_store_integration.py`.

Limites connues : les noms historiques de variants (« 5382insC », « Glu6Val ») ne sont pas traduits ;
un symbole en majuscules avec un chiffre (« CD4 ») peut être signalé à tort comme gène hors panel ;
le cache des analyses (`data/experiments/`, non versionné) contient la reformulation anglaise des
questions en clair.

## 9. Génération et API (E2b)

Spec : `docs/superpowers/specs/2026-10-08-sous-projet-e2b-generation-api-design.md` (amendements au
§10). L'API prend une question en français et renvoie une réponse **vérifiée** : le texte du LLM
n'est montré que s'il passe des contrôles faits par le code. Le modèle de génération est
**provisoire** (§9.3) ; le choix officiel relève de la mesure E2a puis de RAGAS en E3.

### 9.1 Architecture

```
hôte (127.0.0.1:8090)
  └─ rag-gateway (nginx, sans secret) ── rag-gateway-net ──► rag-api (Litestar, uvicorn)
                                                               ├─ rag-network ─► rag-postgres (rag_reader), rag-embeddings
                                                               └─ rag-proxy-net ─► rag-proxy (Squid) ─ rag-egress ─► OpenRouter / Groq

question ─► analyse (E2a) ─► recherche (E2a, 10 documents) ─► génération (LLM, JSON strict)
         ─► contrôles du code ─► réponse + sources + avertissement
```

| Service | Rôle | Exposition |
|---|---|---|
| `rag-gateway` | seul point d'entrée : relaie `GET /health`, `GET /ready`, `POST /v1/questions` | `127.0.0.1:8090` ; nginx non privilégié, racine en lecture seule, aucun secret |
| `rag-api` | API Litestar : analyse, recherche, génération, contrôles | aucun port publié (réseaux internes seulement) ; compte `rag_reader` |
| `rag-proxy` | Squid : seule sortie Internet du RAG | `CONNECT` vers `openrouter.ai:443` et `api.groq.com:443` seulement |
| `rag-search`, `rag-api-test` | outils à la demande (profil `outils`) : mesures, tests | même image que `rag-api` |

Pourquoi une passerelle : Docker ne publie aucun port pour un conteneur relié seulement à des
réseaux internes, et `rag-api` ne doit avoir aucune sortie directe. La passerelle publie le port sur
la boucle locale de l'hôte et joint `rag-api` par le réseau interne `rag-gateway-net`.

Démarrage : `docker compose --env-file .env up -d rag-gateway` (démarre aussi `rag-api`, `rag-proxy`
et leurs dépendances). Au démarrage, l'API refuse de tourner sans `RAG_API_KEY` valide, et vérifie que
le modèle d'embedding servi est celui de l'index (§8.2).

### 9.2 Ce qui est garanti sur une réponse

Le LLM rend un JSON strict (`status`, `scope_reason`, `answer`, `citations`). Le code accepte le texte
seulement si :

- **Identifiants neutres** : les documents transmis portent des étiquettes `D1`…`Dn` (ordre de
  transmission), jamais leur `doc_id` interne. Raison : `clinvar:NNN` est l'AlleleID interne, pas le
  Variation ID affiché dans la fiche ; le modèle le recopiait comme « ClinVar NNN » (10 des 18 rejets
  de la recette d'octobre) et induisait le lecteur en erreur. La table `Dk -> doc_id` est construite par
  le code seul (`context.document_labels`).
- **Citations** : chaque source citée est une étiquette `Dk` des documents transmis, convertie par le
  code en `doc_id` réel ; une étiquette inconnue (ou un `doc_id` recopié) est un rejet
  (`citation_not_transmitted`), jamais une erreur. La liste affichée des sources vient du code.
- **Étiquette dans le texte** : une étiquette `Dk` transmise écrite dans la réponse est **rejetée**
  (`document_label_in_text`), non retirée : un retrait par le code pourrait laisser une phrase tronquée
  ou en changer le sens. Exception : un symbole identique présent tel quel dans les fiches
  (« complementation group D1 »). Le Variation ID réel de la fiche reste accepté s'il est écrit.
- **Identifiants** : tout identifiant du texte (rs, HGVS c./p., identifiant ClinVar, gène) est présent
  dans un document cité ou dans les textes transmis ; un identifiant inventé rejette la réponse.
- **Signification actuelle** : toute signification clinique affirmée est celle du document cité ; une
  signification d'un autre libellé ou en anglais est rejetée, de même que toute phrase qui porte un
  terme de signification et une négation n'importe où (`ne`, `n'`, `pas`, `aucun`, `jamais`, `rien`,
  `sans`, `ni`, `non`) et tout qualificatif hors table (« VUS », « inoffensif », « sans danger »,
  « anodin », « bénéfique », « incertain » seul…). Avant ce test, une **liste fermée** de formules est
  masquée, parce que leur négation ne porte jamais sur la signification : « aucun / sans / pas de conflit(s) (d'interprétation(s)) »
  (statut de revue ClinVar « no conflicts » ; seule l'expression est masquée, « pas de conflit, il n'est
  pas pathogène » reste rejeté), « aucun critère (d'évaluation) fourni » (« no assertion
  criteria provided »), « ClinVar ne documente pas de phénotype pour ce variant » (phrase imposée par
  le prompt pour les fiches maigres), « d'autres variantes non listées ici » (liste tronquée ; seule cette
  formule est masquée, et pas si elle est suivie de « comme » ou « en tant ») et « non sphérocytaire » (nom de maladie). **Noms de maladie** : un terme de signification inclus dans
  un nom de maladie ou de phénotype des documents **cités** (lignes `Associated conditions` /
  `Related phenotypes`), recopié mot pour mot (insensible à la casse, au moins deux mots), n'est pas
  compté ; seule cette portion exacte est neutralisée (une traduction du modèle, comme « excroissances
  bénignes » pour *Macrocephaly-autism syndrome*, ne l'est pas). « non listé » seul n'est **pas** masqué :
  « Ce variant est non listé comme pathogène » reste rejeté. Un « \n » littéral émis par le modèle
  est ramené à un vrai retour à la ligne avant tout contrôle.
- **Historique restitué par le code** : le LLM ne raconte jamais l'historique de classification
  (« auparavant », « reclassé », « jusqu'en 2019 » sont rejetés) ; le code ajoute lui-même une phrase
  « Historique ClinVar … » depuis la ligne `Classification history` du Gold.
- **Hors périmètre détecté par règles, avant le LLM** (`RAG/src/generation/scope.py`) : comptage
  (« combien », « liste complète », « le plus de », « liste les », « inventaire », « l'ensemble des
  variants »…), ACMG (« ACMG », codes PVS1, PM2, « American College of Medical Genetics », « grille de
  classification »…), fréquences (« fréquence », « prévalence », « gnomAD », « rare » (sauf « maladie rare »), « courant » (sauf « au courant »),
  « répandu », « MAF », « incidence »…) et conseil clinique (« faut-il », « traitement », « dépistage »,
  « dois-je », « puis-je », « consulter », « s'inquiéter », « risque … pour moi », « ablation » (sauf
  « ablation de l'exon / du gène / du domaine / de la région ») et, **seulement si la question contient
  un contexte personnel** (« je », « ma », « sœur », « enfants », « patiente », « porteuse »…), « peut-il »
  et « indiqué(e)(s) » : « Ce variant peut-il causer une anémie ? » reste une question factuelle) reçoivent un message fixe sans appel au LLM ; « nombre de soumissionnaires » et « classé
  selon les laboratoires / les soumissionnaires » (données de la fiche) ne sont pas détectés ; la règle du prompt reste un second
  filet (questions hors domaine, `other`). Règles écrites avec la seule série de développement (§9.10).
- **Messages fixes** : hors périmètre, gène hors panel, document introuvable et réponse non vérifiable
  reçoivent un texte écrit par le code. Un `not_in_sources` du LLM reçoit **toujours** le message fixe
  « Aucune fiche ClinVar du panel ne correspond à cette question » : son texte libre n'est jamais livré
  (seule la recette le consigne, `llm_text_withheld`, pour examen).
- **Longueur** : réponse de 1 500 caractères au plus (prompt v6), 4 000 au maximum dur.

**Ce qui n'est PAS vérifié par le code** : les maladies et phénotypes cités, et le reste du texte
libre (reformulations, liens logiques). Seuls les identifiants, les citations et les significations
le sont. La fidélité de la réponse aux fiches (*faithfulness*) sera mesurée en E3 (RAGAS).

Statuts renvoyés (champ `status`) :

| Statut | Sens |
|---|---|
| `answered` | réponse complète, vérifiée, avec sources |
| `partial` | réponse vérifiée, mais les fiches ne couvrent qu'une partie de la question |
| `not_in_sources` | aucune fiche ne répond (identifiant introuvable, aucun document, ou ClinVar ne documente pas le point) |
| `out_of_scope` | hors périmètre, avec `scope_reason` ; message fixe |
| `unverifiable` | le texte généré a échoué un contrôle ; il n'est **pas affiché**, seules les sources le sont |

Un LLM injoignable ou hors quota, une sortie hors schéma ou une génération coupée par le plafond de
jetons ne produisent pas de statut : l'API répond 503 (§9.5). La recette (§9.10) enregistre ce cas
sous le nom `generation_unavailable`.

### 9.3 Profils LLM provisoires

`RAG/config.yaml`, section `llm` :

- `analysis_profile` et `generation_profile` valent `essai-groq-gpt-oss-120b` (API Groq, offre
  gratuite, zéro rétention à activer dans *Data Controls*). **Provisoires** : le profil d'analyse
  sera désigné par la mesure officielle de E2a (crédits OpenRouter), celui de génération par RAGAS en E3.
- Chaque réponse porte le modèle, le fournisseur et le coût réellement observés.
- Le quota gratuit de Groq est quotidien : la recette (§9.10) est reprenable sur plusieurs jours.

### 9.4 Configuration et clé d'API

Section `api` de `RAG/config.yaml` : `max_concurrency: 4` (au-delà, 429 ; chaque emplacement a sa
propre connexion PostgreSQL), `request_timeout_s: 120` (503), `max_body_bytes: 8192` (413),
`openapi: false`. Avec `openapi: true`, `/schema` est exposé **sans clé** : à ne jamais activer hors
d'un essai local.

`RAG_API_KEY` (`.env` de la racine) : **32 caractères au moins**, sinon l'API ne démarre pas. À
générer sans l'afficher :

```bash
printf 'RAG_API_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
```

Elle est comparée en temps constant et n'est jamais journalisée. La passerelle ne la connaît pas :
elle la transmet telle quelle, et c'est l'API qui la vérifie.

### 9.5 Appeler l'API

La clé est lue dans l'environnement du shell, jamais tapée en clair dans la commande :

```bash
set -a; . ./.env; set +a
curl -s http://127.0.0.1:8090/health                                   # {"status":"ok"}, sans clé
curl -s -H "X-API-Key: $RAG_API_KEY" http://127.0.0.1:8090/ready       # modèle d'embedding, base
curl -s -H "X-API-Key: $RAG_API_KEY" -H 'Content-Type: application/json' \
  -d '{"question": "Le variant rs80357906 sur BRCA1 est-il pathogène ?"}' \
  http://127.0.0.1:8090/v1/questions
# "trace": true dans le corps ajoute la trace de recherche (§8.1)
```

La réponse contient `status`, `answer`, `sources`, `disclaimer`, `request_id`, et les durées par
étape. Elle ne contient jamais de clé. Erreurs (corps fixe `{"error", "message", "request_id"}`) :

| Code | `error` | Cause |
|---|---|---|
| 401 | `unauthorized` | `X-API-Key` absente ou invalide (`/ready`, `/v1/questions`) |
| 404 | `not_found` | route inconnue ; **aussi, par la passerelle, toute requête avec chaîne de requête** (`?…`) ou méthode non prévue |
| 413 | `too_large` | corps supérieur à 8 192 octets |
| 415 | `unsupported_media_type` | corps non déclaré JSON (`Content-Type` autre que `application/json`, paramètre `charset` admis) |
| 422 | `invalid_question` | JSON illisible, champ inconnu, question vide ou de plus de 1 000 caractères |
| 429 | `busy` | 4 questions déjà en cours ; **ou, par la passerelle, plus de 30 questions par minute** : la passerelle répond alors par une page HTML de nginx, pas du JSON |
| 503 | `unavailable` / `timeout` | LLM, embedding ou base injoignable, quota épuisé (en-tête `Retry-After`), ou délai de 120 s dépassé |
| 500 | `internal` | erreur interne, journalisée avec le seul nom de la classe d'exception |

### 9.6 Journaux

Un événement JSON par question : identifiant de requête, statut, durées, coût, modèle, indicateurs de
recherche, nombre de sources. Une réponse arrivée après le délai (jamais livrée) est consignée par
`late_result` (statut, coût, modèle) ou `late_error` (classe de l'exception). Le journal d'accès
d'uvicorn est coupé (`--no-access-log`) : il répéterait chaque requête. **Ni la question, ni la
réponse, ni la clé, ni l'en-tête** : la
passerelle journalise `méthode chemin statut durée`, sans chaîne de requête ; le proxy journalise
l'hôte et le port, jamais l'URL complète. Les messages d'exception ne sont pas journalisés (ils
pourraient citer un extrait de la requête).

### 9.7 Architecture de sécurité

- **Proxy sortant** (`docker/rag-proxy/squid.conf`) : seuls clients admis, ceux du sous-réseau de
  `rag-proxy-net` ; seule méthode `CONNECT`, port 443, vers `openrouter.ai` et `api.groq.com`. L'option
  `-n` compare au nom demandé seul (pas de résolution inverse), et toute destination en IP littérale
  est refusée. Aucun cache, aucune inspection du contenu. **Le sous-réseau fixe `172.31.250.0/24` est
  écrit dans `squid.conf` ET dans `docker-compose.yml` (réseau `rag-proxy-net`) : les deux doivent
  rester synchronisés**, sinon le proxy refuse tout.
- **Passerelle sans secret, mais sur un pont non interne** (`rag-api-ingress`, nécessaire à la
  publication du port) : elle voit donc la clé et les questions en transit, **et elle a une sortie
  Internet** (ce pont n'est pas interne ; nginx n'y ouvre aucune connexion de lui-même). Risque
  résiduel accepté pour une API locale sur 127.0.0.1. Elle relaie une URI fixe par route (aucun `../` ni `%2F`
  transmis), refuse toute chaîne de requête, borne le corps à 8 Ko.
- **Limite de débit** : 30 questions par minute (rafale de 10), **partagées entre tous les clients et
  appliquées avant l'authentification**. Elle plafonne la dépense LLM si un processus local boucle,
  mais un flot local sans clé peut aussi affamer l'utilisateur légitime : limite de déni de service
  local connue. Cette limite ne vaut que par la passerelle : un conteneur relié à `rag-gateway-net`
  (comme `rag-api-test`) joint `rag-api:8000` directement, sans `limit_req` ; la clé reste exigée.
- **Base** (`RAG/sql/001_schema.sql`) : mots de passe lus par `\getenv` (absents de la liste des
  processus et de la ligne de commande psql ; variable manquante → erreur SQL et code de sortie 3) ;
  attributs des rôles remis à zéro à chaque amorçage (`NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  NOREPLICATION`) ; `REVOKE ALL` et `GRANT` dans une même transaction ; `REVOKE TEMPORARY, CREATE ON
  DATABASE rag FROM PUBLIC` et `REVOKE CONNECT, TEMPORARY ON DATABASE postgres, template1 FROM PUBLIC` ;
  `SET log_min_error_statement = panic` en tête du script (une instruction en échec, qui pourrait porter
  un mot de passe, n'est jamais recopiée dans le journal du serveur).
- **Airflow** : les secrets `RAG_*` ne sont que sur le scheduler (ancre `x-rag-indexer-env`, vérifié
  par `RAG/tests/test_compose_security.py`, qui contrôle aussi le sous-réseau du proxy) ;
  `data/models` est monté en lecture seule ; `rag-model-export` a son propre réseau `rag-export` et un
  plafond de 4 Gio.
- **Conteneurs** : `rag-api` ne monte ni `.env` ni le reste du dépôt ; clés LLM absentes de
  `rag-api-test` ; dépendances de l'image verrouillées par empreinte (`--require-hashes`,
  `docker/rag-api/requirements.lock`).

### 9.8 Mesures et essai rapide

`rag-search` reste l'outil d'essai en ligne de commande (§8.4). Mesure de l'essai réel du 8 octobre
2026 (Groq, gpt-oss-120b) : réponse `answered` avec une source, analyse 0,76 s, recherche 1,50 s,
génération 1,07 s, total 2,57 s. Depuis l'hôte, via la passerelle : `/health` 200, `/ready` sans clé
401, question réelle 200 en 2,1 s.

### 9.9 Tests d'intégration

Les tests d'intégration tournent dans `rag-api-test` (image de `rag-api` + `pytest` verrouillé :
derrière le proxy, PyPI n'est plus joignable). Cette image n'a pas `responses` : **nommer les fichiers**
au lieu de lancer tout le dossier.

```bash
set -a; . ./.env; set +a
docker compose --env-file .env --profile outils build rag-api-test
docker compose --env-file .env --profile outils run --rm --no-deps -e RAG_READER_PASSWORD -e RAG_INDEXER_PASSWORD \
  --entrypoint sh rag-api-test -c '
    export RAG_TEST_PG_READER_CONNINFO="host=rag-postgres dbname=rag user=rag_reader password=$RAG_READER_PASSWORD" &&
    export RAG_TEST_PG_CONNINFO="host=rag-postgres dbname=rag user=rag_indexer password=$RAG_INDEXER_PASSWORD" &&
    python -m pytest -p no:cacheprovider -m integration \
      RAG/tests/test_api_integration.py RAG/tests/test_hardening_integration.py \
      RAG/tests/test_search_store_integration.py RAG/tests/test_vector_store_integration.py -q'
```

`rag-api`, `rag-gateway` et `rag-proxy` doivent tourner. Ils vérifient le proxy (domaine hors liste,
autre port, HTTP clair, IP littérale), le filtrage de la passerelle, les droits des rôles (écritures
de l'indexeur exercées dans une transaction annulée, bases `postgres` et `template1` fermées) et le
durcissement de la base. `test_api_answers_end_to_end` pose une vraie question (un appel au LLM). Passe rapide : `pytest -q` (logique) et `pytest tests_airflow -q`.

### 9.10 Recette

Jeu de questions : les 89 de E2a (parties 1 à 3) et deux séries hors périmètre (partie 4), validées
par l'utilisateur :

- **série de développement** (`RAG/experiments/questions_recette_e2b.yaml`, 10 questions) : elle a
  servi à écrire les règles hors périmètre ; son score est rapporté à part, **sans seuil** ;
- **série de contrôle** (`RAG/experiments/questions_recette_e2b_controle.yaml`) : jamais consultée
  pour écrire les règles ; le seuil de la partie 4 (≥ 90 %, spec §8) se calcule sur elle seule.

Seuils fixés d'avance dans la spec (§8). La recette valide la chaîne, elle ne choisit aucun modèle.

```bash
mkdir -p data/experiments/e2b-recette
docker compose --env-file .env --profile outils run --rm rag-search -m RAG.experiments.recette_generation lancer
venv/bin/python -m RAG.experiments.recette_generation evaluer    # résumé et critères
```

`rag-search` monte `data/experiments/e2b-recette` en écriture (avec `e2a` et `e2a-essai`). `lancer`
enregistre chaque réponse (avec la version du prompt) dans `records.json` et reprend où il s'est
arrêté. Le quota quotidien de Groq peut l'interrompre : relancer le lendemain. Un changement de prompt
purge les enregistrements antérieurs, pour que tous aient la même version. Une génération
indisponible est enregistrée (`generation_unavailable`) et non rejouée : elle compte comme échec du
critère. Une réponse `unverifiable` ne cite rien (`citations` vide) ; les documents transmis sont
dans `sources_transmises`. En partie 2, une réponse `partial` citant un document pertinent compte
comme réussie ; `evaluer` l'annonce.

**Latences** : les attentes de limite de débit de Groq (et les relances 502/503) sont mesurées par
question (`throttle_wait_ms`, fonction `sleep` des clients enveloppée) ; `evaluer` imprime la latence
sans ces attentes et attentes comprises. Les enregistrements antérieurs à cette mesure n'ont pas le
champ : leur latence « sans attentes » est une borne supérieure, et `evaluer` le signale.

**Rejeu hors ligne** : après une modification des contrôles, `rejouer` repasse chaque génération déjà
obtenue dans la chaîne actuelle, **sans aucun appel au LLM**, et écrit `records_v2.json` :

```bash
docker compose --env-file .env --profile outils run --rm --no-deps \
  -e GROQ_API_KEY= -e OPENROUTER_API_KEY= -e HTTPS_PROXY=http://127.0.0.1:9 -e HTTP_PROXY=http://127.0.0.1:9 \
  rag-search -m RAG.experiments.recette_generation rejouer
venv/bin/python -m RAG.experiments.recette_generation evaluer --fichier records_v2.json
```

Les enregistrements ne contiennent pas les documents : `rejouer` refait la **recherche locale**
(base et embedding, sans réseau extérieur), avec les analyses lues dans leur cache
(`data/experiments/e2a-essai/cache_analyses.json`) et un client d'analyse hors ligne qui ne répond
jamais ; la génération est relue dans `cache_generation.json` (même clé que `lancer` : prompt,
modèle, plafond de jetons, message utilisateur exact, donc mêmes documents). Une question dont
l'analyse ou la génération n'est pas en cache garde son enregistrement d'origine (`replay` le dit).
Les clés vides et le proxy factice garantissent qu'aucun appel ne sort. Résultats et examen des
rejets : `reference/recette_e2b.md`.

### 9.11 Limites connues

- **Listes de phénotypes polluées** (modes de transmission, âges) dans les documents : à traiter
  après la première mesure RAGAS (E3).
- **Contrôle de signification par motifs** : il reste lexical. Les lacunes connues ont été comblées
  (« classé incertain », « inoffensif », « sans danger », « Uncertain-significance », négation après
  le terme), mais une formulation nouvelle peut encore lui échapper : le contrôle n'est **pas** sûr
  dans les deux sens. Une phrase est découpée sur `.`, `!`, `?` et `;` : « Pathogène ? Non. » sépare
  le terme de sa négation. À l'inverse, une phrase (ou une liste sans point final, qui forme une seule
  « phrase » : les puces ne sont pas découpées) est rejetée dès qu'elle contient une négation qui ne
  porte pas sur la signification. Le premier rejeu du 09/10/2026 en a rejeté 7 de la partie 1 à tort,
  à cause de formules sans rapport avec la signification : le statut de revue traduit (« aucun
  conflit »), la phrase des fiches maigres, « d'autres variantes non listées ici », « non sphérocytaire ». Ces
  formules exactes sont désormais masquées (voir §9.2), sauf B09, restaurée par la seule
  normalisation du « \n » littéral et non par le masque ; il reste 2 rejets (P1-B08, P1-C03), dus à
  une vraie négation dans la phrase (« ClinVar ne documente pas d'autres variantes … pathogène »,
  « les documents ne mentionnent pas … »), rejet voulu par le sens prudent.
- **Règles hors périmètre lexicales** : une question peut être détectée à tort (message fixe au lieu
  d'une réponse ; aucune sur les 89 questions de E2a, hors P3-05, réellement une question de
  fréquence) ou échapper aux règles (le LLM tranche alors).
- **Permutation entre deux documents cités** : si deux fiches citées ont des significations
  différentes, une inversion entre elles n'est pas détectée.
- « et N autres » (comptes de listes) n'est pas vérifié.
- Noms historiques de variants (« 5382insC », « Glu6Val ») non reconnus ; un symbole du type « CD4 »
  peut être pris pour un gène hors panel (§8.6).
- Un identifiant hors des k premiers documents exacts peut être signalé introuvable à tort ; une
  question citant `c.` et `p.` d'un même variant dont la fiche n'a qu'une forme est refusée.
- Hors panel : un gène hors panel seul court-circuite (`out_of_scope`) seulement sans identifiant de
  variant.
- Délai de génération partagé avec `llm.request_timeout_s` ; issue d'un fil non journalisée quand le
  client se déconnecte avant la réponse (seul le délai dépassé l'est).
- Le cache des analyses et les enregistrements de recette (`data/experiments/`, non versionnés)
  contiennent des questions en clair.
