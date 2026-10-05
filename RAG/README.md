# RAG génomique — E1 : indexation, E2a : recherche

E1 copie les documents de `gold/rag/documents` dans une base vectorielle (PostgreSQL +
pgvector), avec leurs vecteurs, de façon incrémentale, reprenable et vérifiée (§1 à §7).
E2a cherche dans cette base à partir d'une question en français (§8). Restent :

- **E2b** (à venir) : génération de la réponse, prompts, API Litestar ;
- **E3** (à venir) : évaluation RAGAS et audit.

Documents de référence :

- spec : `docs/superpowers/specs/2026-10-01-sous-projet-e1-indexation-rag-design.md` ;
- choix du modèle, mesuré : `reference/choix_embedding.md`.

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

Outil à la demande (profil `outils`), qui deviendra l'API en E2b. Utilisateur non root, racine en
lecture seule, `no-new-privileges`, `cap_drop: ALL`, compte PostgreSQL `rag_reader`. Réseaux :
`rag-network` (base, embedding) et `rag-egress`, sortie Internet **non filtrée** (Docker ne filtre
pas par domaine ; proxy filtrant prévu avant E2b, `TODO.md`). Seuls `data/experiments/e2a` et
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

```bash
set -a; . ./.env; set +a
docker compose --env-file .env --profile outils run --rm \
  -e RAG_READER_PASSWORD -e RAG_INDEXER_PASSWORD \
  --entrypoint sh rag-search -c '
    pip install --quiet --target /tmp/pytest-lib pytest==9.1.1 &&
    export PYTHONPATH=/tmp/pytest-lib:$PYTHONPATH &&
    export RAG_TEST_PG_READER_CONNINFO="host=rag-postgres dbname=rag user=rag_reader password=$RAG_READER_PASSWORD" &&
    export RAG_TEST_PG_CONNINFO="host=rag-postgres dbname=rag user=rag_indexer password=$RAG_INDEXER_PASSWORD" &&
    python -m pytest -p no:cacheprovider -m integration RAG/tests/test_search_store_integration.py -q'
```

Limites connues : les noms historiques de variants (« 5382insC », « Glu6Val ») ne sont pas traduits ;
un symbole en majuscules avec un chiffre (« CD4 ») peut être signalé à tort comme gène hors panel ;
le cache des analyses (`data/experiments/`, non versionné) contient la reformulation anglaise des
questions en clair.
