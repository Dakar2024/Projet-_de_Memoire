# Procédure de reprise du pipeline

Que faire quand un run mensuel manque, échoue, publie des données fausses, ou quand une partie du
stockage est perdue. Chaque situation part d'un **symptôme observable** et se termine par une
**vérification**. Rédigée le 23/10/2026 (constat P17 de `reference/audit_production.md`).

Toutes les commandes se lancent depuis la racine du dépôt monté par la pile. En cas de doute,
`docker inspect genomique-airflow-scheduler` (rubrique Mounts) indique lequel.

| Statut d'une commande | Signification |
|---|---|
| **Vérifiée** | exécutée sur la pile le jour indiqué |
| **Vérifiée en conteneurs jetables** | même commande, jouée sur une copie isolée : elle détruirait des données sur la vraie pile |

---

## 0. Trois règles avant toute reprise

1. **Sauvegarder d'abord** : `./scripts/sauvegarde.sh`. Une reprise ratée doit pouvoir s'annuler.
2. **Le pipeline ne traite que le mois en cours, jamais un mois passé** (règle du 24/10/2026).
   Le mois traité est celui du **démarrage réel** du run, pas de son échéance : une pile activée le
   4 décembre ingère décembre. Un Trigger manuel sur un autre mois est refusé, sans relance
   (`hors du mois en cours`). Un mois manqué est donc perdu, et c'est voulu : rejouer novembre
   après décembre fausserait l'historique SCD2 de `clinvar_variant` (prouvé le 23/10/2026 sur une
   table de test ; `bronze_to_silver` le refuse aussi, § 4).
3. **Relancer un échec dans le mois même.** Un run du mois en échec, relancé (Clear) après le
   début du mois suivant, retraiterait un mois passé : laisser plutôt le run du 10 prendre le
   nouveau mois.

---

## 1. La machine était éteinte le 10

**Symptôme** : un e-mail « Rattrapage : run du JJ/MM/AAAA lancé en retard ».

**Action** : aucune. Au redémarrage, Airflow lance de lui-même la dernière échéance passée, même
avec `catchup=False`, et `notify_catch_up` l'annonce. Vérifié le 23/10/2026 : scheduler arrêté
3 min 30 sur un DAG planifié chaque minute, la dernière échéance manquée est partie 10 s après le
redémarrage. Le run traite le **mois du redémarrage** (« Mois traité » dans l'e-mail) : rallumée
le 3 décembre après un 10 novembre manqué, la pile ingère décembre, et novembre n'est pas
rattrapé (règle 2).

Avant le premier jeudi du mois, l'archive ClinVar du mois n'existe pas encore : le run échoue
sans relance (`pas encore publiée`). Rien à faire, le run planifié du 10 la prendra.

**Vérification** : un e-mail d'échec arriverait sinon. En l'absence d'e-mail, voir § 6.

## 2. La machine était éteinte plus d'un mois

**Symptôme** : un seul e-mail de rattrapage. Airflow ne relance que la **dernière** échéance
passée : les échéances intermédiaires ne tournent jamais (vérifié le 23/10/2026), et le run traite
le mois du redémarrage.

**Action : aucune, le trou est accepté** (règle 2). L'état courant du mois traité est exact. Seule
la date d'une reclassification survenue pendant le trou est décalée : un variant reclassé en
novembre apparaîtra reclassé en décembre.

## 3. Un e-mail d'échec

**Symptôme** : « [genomique] Échec dag_id.task_id ». L'e-mail dit si l'échec est **définitif**
(sans relance : corriger la cause d'abord) ou survenu **après les relances** (souvent passager),
donne le message d'erreur et un bouton vers le journal.

1. Lire l'exception dans l'e-mail, puis le journal (lien de l'e-mail). Causes connues :

   | Message | Cause | Correction |
   |---|---|---|
   | `archive ClinVar … pas encore publiée` | run lancé avant le premier jeudi du mois (parution observée du 1er au 7, FTP NCBI 2025-07 à 2026-10) | rien : le run planifié du 10 la prendra |
   | `colonnes manquantes` / `SourceSchemaError` | la source a changé de format | adapter le code de conversion, puis relancer |
   | `hors du mois en cours` | Trigger manuel sur un autre mois | relancer sans date, ou avec une date du mois en cours (règle 2) |
   | `date des sources absente` | run de panel manuel sans `--conf` | relancer avec `--conf '{"sources_date": …}'` du mois en cours (README) |
   | `lancer d'abord dag_acquisition_sources` | run de panel sur un mois dont le bronze partagé manque | lancer l'acquisition du mois : elle déclenche les panels |
   | `contient déjà le mois` | mois antérieur à l'historique Silver | § 4 |

2. Relancer **la tâche en échec et la suite**, sans refaire ce qui a réussi. Dans l'interface :
   le DAG, onglet Grid, la tâche rouge, **Clear** avec « Downstream ». En ligne de commande,
   **sans `-y`** pour lire d'abord la liste :

   ```bash
   docker compose exec airflow-scheduler airflow tasks clear dag_genomic_pipeline_brca -f -d
   ```

   `-f` retient toutes les tâches en échec de ce DAG, **tous runs confondus**. Répondre `n` si la
   liste contient un run qu'on ne veut pas relancer, et passer par l'interface. Les options de date
   `-s`/`-e` ne s'appliquent pas aux runs de panel, qui n'ont pas de date logique en Airflow 3.
   Vérifiée le 23/10/2026 (aperçu de la liste, puis réponse `n`).

**Vérification** : le run passe au vert ; pour une acquisition, les deux runs de panel démarrent
ensuite d'eux-mêmes.

## 4. Erreur « contient déjà le mois » (garde de chronologie)

**Symptôme** : `bronze_to_silver` échoue sans relance, avec
`clinvar_variant (brca) contient déjà le mois 2026-12-01 : y ajouter 2026-11-01 après lui fausserait l'historique SCD2`.

**Cause** : un run de panel a reçu un mois plus ancien que le dernier mois de son historique.
Les DAGs refusant tout mois autre que le mois en cours, le cas restant est un run d'un mois passé
relancé par Clear après le run du mois suivant (règle 3). La garde a refusé **avant toute
écriture** : le Silver et le Gold sont intacts.

**Action** : ne rien forcer, marquer le run en échec comme vu. Le mois passé n'est pas intégré
(règle 2).

## 5. Perte ou corruption du stockage

### 5.1 Données fausses publiées pour le dernier mois

Un bug corrigé après le run du mois : rejouer **ce mois-là** (le plus récent, donc sans risque
pour l'historique). L'acquisition d'un mois déjà publié est sautée, il faut la forcer :

```bash
docker compose exec airflow-scheduler \
  airflow dags trigger dag_acquisition_sources --logical-date 2026-10-15 --conf '{"force": true}'
```

Le jour est ramené au 1er du mois. Choisir un jour qu'aucun run n'utilise déjà : Airflow refuse
deux runs de même date logique. Si seule la partie panel est en cause, relancer le panel seul :
`airflow dags trigger dag_genomic_pipeline_brca --conf '{"sources_date": "2026-10-01"}'`.
Vérifiée le 23/10/2026 (sans `force` : run sauté, aucun événement d'Asset, aucun run de panel).

### 5.2 Une table Delta corrompue

**Gold, ou un instantané Silver** (toutes les tables sauf `clinvar_variant`) : relancer le panel
sur le dernier mois (commande ci-dessus). Ces tables sont recalculées depuis le Silver pour le
panel : réécrites (instantanés, Gold analytique) ou réconciliées par fusion (Gold RAG).

**`clinvar_variant`** (historique SCD2, impossible à reconstruire) : revenir à la version Delta
d'avant l'incident. Lister les versions :

```bash
docker exec -w /opt/projet genomique-airflow-scheduler env PYTHONPATH=src:. python -c "
from deltalake import DeltaTable
from ingestion.storage import storage_options
from transformations.silver_io import silver_table_uri
uri = silver_table_uri('clinvar_variant')
t = DeltaTable(uri, storage_options=storage_options(uri))
for h in t.history(10): print(h['version'], h['timestamp'], h['operation'])
"
```

Les horodatages sont en millisecondes depuis 1970. Choisir la dernière version saine `N`, puis
remplacer la dernière ligne du script par `print(t.restore(N))`. La lecture de l'historique a été
vérifiée sur la pile le 23/10/2026, `restore` sur une table de test avec `deltalake` 1.6.3, la
version de la pile. Relancer ensuite le panel sur le dernier mois, pour que le Gold et l'index
RAG suivent.

**Limite** : `vacuum_delta_tables` supprime les fichiers des versions de plus de 30 jours. Au-delà,
restaurer la sauvegarde (§ 5.3).

### 5.3 Perte du lac ou de la base Airflow

Volume MinIO ou PostgreSQL perdu, disque remplacé, `docker compose down -v`. Un seul script
restaure les trois bases depuis la **même** copie, pour qu'elles restent alignées : base Airflow,
lac, base vectorielle.

```bash
./scripts/restaurer.sh --pile genomique --pile-principale ~/sauvegardes-genomique/<date>
```

La plus récente copie. Sans `--pile-principale`, le script refuse : il écrase les
trois bases de la pile visée. Il refuse aussi une copie incomplète, avant toute modification.

**Vérifié le 23/10/2026** sur la pile isolée de l'évaluation E3b (`--pile genomique-e3b`, copie
`2026-10-23-1501`, 2 min 16) : runs, événements d'Asset, documents RAG et objets des quatre
buckets identiques à la pile principale. Jamais lancé sur la pile principale elle-même.

Ce que fait le script, dans l'ordre :
1. arrêt de ce qui écrit (services Airflow, API RAG) ;
2. base Airflow : `pg_restore --clean` ;
3. lac : `minio-init` (buckets, versionnage, cycle de vie), puis `mc mirror --overwrite --remove`
   de chaque bucket. `--remove` est indispensable si le lac n'est pas vide : sans lui, les
   journaux Delta postérieurs à la copie resteraient en place, et chaque table lirait des versions
   dont les fichiers n'existent plus. Les objets retirés restent récupérables grâce au versionnage
   des buckets : 30 jours, sans limite dans `raw` ;
4. base RAG : `rag-postgres-init` (schéma et comptes ; les mots de passe ne sont pas dans le dump),
   puis `pg_restore --clean` ;
5. redémarrage de la pile.

**Vérification** : `docker compose exec airflow-scheduler airflow dags list-runs dag_acquisition_sources`
redonne l'historique d'avant la copie ; l'interface MinIO montre les quatre buckets.

### 5.4 Après la restauration : reprendre au mois en cours

Les mois écoulés entre la copie et la restauration ne sont **pas** rejoués (règle 2). Le run
planifié du 10 reprendra au mois en cours ; pour l'ingérer tout de suite :

```bash
docker compose exec airflow-scheduler airflow dags trigger dag_acquisition_sources
```

Sans date, le Trigger prend le mois en cours. Si la copie contenait déjà ce mois, il est sauté
(`skip_if_already_published`) : ajouter `--conf '{"force": true}'` pour le relire quand même.

### 5.5 Perte de la base vectorielle seule

README, « Restaurer la base vectorielle en production » (l'équivalent de la seule étape 4 du § 5.3). Vérifiée en conteneur jetable le
23/10/2026 (97 210 documents, empreintes identiques). À défaut de copie, la prochaine indexation
d'un run de panel la reconstruit depuis le Gold, en environ 4 h sur CPU.

## 6. Aucun e-mail du tout

Ni rappel J-2, ni rappel jour J, ni e-mail d'échec ou de rattrapage autour du 10 : l'envoi lui-même
est en panne. `dag_test_alerte` échoue volontairement et doit produire un e-mail ; il est en pause
dès sa création :

```bash
docker compose exec airflow-scheduler airflow dags unpause dag_test_alerte
docker compose exec airflow-scheduler airflow dags trigger dag_test_alerte
```

Le remettre en pause ensuite (`dags pause`). Configuration : README, « Recevoir les alertes ».

---

## Sauvegardes : rappel

- `scripts/sauvegarde_si_necessaire.sh` tourne chaque heure (crontab) et copie si la dernière copie
  a plus de 7 jours ou précède un run de panel réussi. Journal : `~/sauvegarde.log`.
- Après une réinstallation de WSL, vérifier `crontab -l` et `ls ~/sauvegardes-genomique` : le
  23/10/2026, crontab et copies avaient disparu sans alerte.
- Dernière vérification de restauration : 23/10/2026, copie `2026-10-23-1501`, conforme (base
  Airflow, 236 objets du lac, 24 tables Delta, base vectorielle).
