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
2. **Ne jamais rejouer un mois antérieur au dernier mois traité.** La fusion SCD2 de
   `clinvar_variant` compare toujours le mois traité aux lignes courantes : novembre rejoué après
   décembre ferme les versions de décembre au 1er novembre et rend l'état de novembre « courant ».
   Prouvé le 23/10/2026 sur une table de test, et désormais refusé par `bronze_to_silver` (§ 4).
3. **Un mois à la fois, dans l'ordre**, en attendant la fin des deux runs de panel avant le suivant.

---

## 1. La machine était éteinte le 10

**Symptôme** : un e-mail « Rattrapage : run du JJ/MM/AAAA lancé en retard ».

**Action** : aucune. Au redémarrage, Airflow lance de lui-même la dernière échéance passée, même
avec `catchup=False`, et `notify_catch_up` l'annonce. Vérifié le 23/10/2026 : scheduler arrêté
3 min 30 sur un DAG planifié chaque minute, la dernière échéance manquée est partie 10 s après le
redémarrage.

**Vérification** : un e-mail d'échec arriverait sinon. En l'absence d'e-mail, voir § 6.

## 2. La machine était éteinte plus d'un mois

**Symptôme** : rattrapage annoncé pour le dernier mois seulement. Airflow ne relance que la
**dernière** échéance passée : les mois intermédiaires ne tournent jamais. Vérifié le 23/10/2026,
les échéances intermédiaires ont été sautées.

**Action recommandée : accepter le trou.** L'état courant du dernier mois est exact. Seule la date
d'une reclassification survenue pendant le trou est décalée : un variant reclassé en novembre
apparaîtra reclassé en décembre. Ne pas rejouer novembre (règle 2).

**Si la date exacte compte** (analyse de l'historique pour le mémoire) : restaurer la dernière
sauvegarde **antérieure** au premier mois manquant (§ 5), puis rejouer chaque mois dans l'ordre
(§ 5.4). La rotation ne garde que quatre copies : à faire vite, avant que la copie utile soit
supprimée.

## 3. Un e-mail d'échec

**Symptôme** : « [genomique] Échec dag_id.task_id (run_id) », avec l'exception et le lien du journal.

1. Lire l'exception dans l'e-mail, puis le journal (lien de l'e-mail). Causes connues :

   | Message | Cause | Correction |
   |---|---|---|
   | 404 sur l'archive ClinVar | archive du mois pas encore publiée (habituellement entre le 2 et le 6) | attendre sa publication |
   | `colonnes manquantes` / `SourceSchemaError` | la source a changé de format | adapter le code de conversion, puis relancer |
   | `contient déjà le mois` | mois antérieur à l'historique Silver | § 4 |
   | `date logique absente` / `date des sources absente` | run manuel sans date | relancer avec `--logical-date` ou `--conf` (README) |

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

**Cause** : un run de panel a reçu un mois plus ancien que le dernier mois de son historique
(Trigger manuel sur un vieux mois, ou acquisition `force` d'un mois passé). La garde a refusé
**avant toute écriture** : le Silver et le Gold sont intacts.

**Action** : ne rien forcer. Si ce mois devait vraiment être intégré, suivre l'option « date
exacte » du § 2. Sinon, marquer le run en échec comme vu, rien à corriger.

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

Volume MinIO ou PostgreSQL perdu, disque remplacé, `docker compose down -v`. Toutes ces commandes
sont **vérifiées en conteneurs jetables** par `./scripts/verifier_restauration_lac_airflow.sh`
(mêmes `pg_restore` et `mc mirror`, cible différente), jamais sur la vraie pile.

```bash
COPIE=~/sauvegardes-genomique/<date>        # la plus récente, sauf § 2

# 1. Plus aucune écriture dans le lac ni dans la base Airflow
docker compose --env-file .env stop airflow-scheduler airflow-dag-processor airflow-triggerer airflow-apiserver

# 2. Base Airflow (historique des runs et des événements d'Asset)
docker compose --env-file .env up -d postgres
docker exec -i genomique-postgres pg_restore -U airflow -d airflow \
  --clean --if-exists --exit-on-error < "${COPIE}/airflow.dump"

# 3. Lac : MinIO et ses buckets (versionnage et cycle de vie posés par minio-init)
docker compose --env-file .env up -d minio minio-init
set -a; . <(tr -d '\r' < .env); set +a
docker run --rm --network genomique_genomique-network --user "$(id -u):$(id -g)" \
  --security-opt no-new-privileges:true --entrypoint sh \
  -e MC_HOST_lac="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000" \
  -v "${COPIE}:/sauvegarde:ro" genomique/minio-mc:RELEASE.2025-08-13T08-35-41Z \
  -c 'for b in raw bronze silver gold; do mc --config-dir /tmp/mc mirror --quiet --overwrite --remove "/sauvegarde/$b" "lac/$b" > /dev/null || exit 1; done'

# 4. Toute la pile
docker compose --env-file .env up -d
```

- `--remove` est indispensable si le lac n'est pas vide : sans lui, les journaux Delta postérieurs
  à la copie resteraient en place, et chaque table lirait des versions dont les fichiers n'existent
  plus. Les objets supprimés restent récupérables grâce au versionnage des buckets : 30 jours,
  sans limite dans `raw`.
- La base vectorielle se restaure depuis la **même** copie : README, « Restaurer la base
  vectorielle ». Elle reste ainsi alignée sur le Gold restauré.

**Vérification** : `docker compose exec airflow-scheduler airflow dags list-runs dag_acquisition_sources`
redonne l'historique d'avant la copie ; l'interface MinIO montre les quatre buckets.

### 5.4 Rejouer les mois postérieurs à la copie

Pour chaque mois absent de la copie, **du plus ancien au plus récent** :

```bash
docker compose exec airflow-scheduler \
  airflow dags trigger dag_acquisition_sources --logical-date 2026-11-10
```

Attendre que l'acquisition **et les deux runs de panel** soient verts avant le mois suivant
(règle 3). La garde de chronologie (§ 4) refuse un mois sauté dans le mauvais ordre. Les archives
ClinVar mensuelles depuis 2023 restent téléchargeables ; les plus anciennes non (constat P16).

### 5.5 Perte de la base vectorielle seule

README, « Restaurer la base vectorielle en production ». Vérifiée en conteneur jetable le
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
