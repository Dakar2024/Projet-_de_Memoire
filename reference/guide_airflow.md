# Guide de prise en main d'Airflow pour ce projet

Ce guide couvre les gestes courants : démarrer la stack, lancer un traitement, comprendre un
échec, relancer, ajouter une tâche. Il s'adresse à quelqu'un qui connaît Airflow 2 et retrouve
ici la version 3.3.1 — les différences sont signalées au fil du texte et récapitulées à la fin.

---

## 1. Démarrer et s'y connecter

```bash
cd ~/Documents/Projet-_de_Memoire
docker compose --env-file .env up -d
docker compose ps                  # attendre que les services soient « healthy »
```

Trois interfaces, **accessibles uniquement depuis cette machine** (elles sont liées à
`127.0.0.1`, voir `audit_securite.md`) :

| Interface | Adresse | Identifiants |
|---|---|---|
| Airflow | http://localhost:8080 | `admin` + le mot de passe de `AIRFLOW_ADMIN_PASSWORD` dans ton `.env` |
| Console MinIO | http://localhost:9011 | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` du `.env` |
| API S3 MinIO | http://localhost:9010 | idem |

Le mot de passe est celui que tu as mis dans `.env` sous `AIRFLOW_ADMIN_PASSWORD` : le service
d'initialisation le réapplique à chaque démarrage. Pour le relire tel que la stack l'utilise :

```bash
docker exec genomique-airflow-apiserver \
  cat /opt/airflow/logs/simple_auth_manager_passwords.json.generated
```

> **Différence avec Airflow 2 :** il n'y a plus de commande `airflow users create`. La 3.x
> utilise un gestionnaire d'authentification simple, qui lit ses comptes dans un fichier — ici
> alimenté depuis le `.env` pour que le mot de passe soit stable d'un démarrage à l'autre.

Pour tout arrêter sans rien perdre : `docker compose down`. Les volumes — donc le lac et
l'historique Airflow — survivent. N'ajoute **jamais** `-v` : cela effacerait les deux.

---

## 2. Les trois DAGs

```
dag_acquisition_sources       mensuel, le 10 à 06:00 UTC
        │  télécharge ClinVar + HPO, les convertit, publie un signal de fin
        ▼
dag_genomic_pipeline_brca     déclenchés automatiquement par ce signal
dag_genomic_pipeline_sickle
        │  collecte NCBI du panel → bronze → silver → gold → contrôle qualité
```

Le DAG d'acquisition traite ce qui est **commun aux deux panels** (le fichier ClinVar de 440 Mo
n'est téléchargé et converti qu'une fois). Les deux DAGs de panel font le reste, chacun pour
ses gènes.

> **Différence avec Airflow 2 :** ce que tu connais sous le nom de *Dataset* s'appelle *Asset*
> en 3.x. Le principe est identique — une tâche déclare produire un signal, les DAGs qui
> l'attendent démarrent — seul le vocabulaire change.

---

## 3. Lancer un traitement à la main

### Le DAG d'acquisition

Le pipeline ne traite que **le mois en cours** : la tâche `resolve_acquisition_month` le lit dans
l'heure de démarrage réelle du run (`dag_run.start_date`, UTC), jamais dans la date logique.
Pourquoi : une pile activée le 4 décembre exécute l'échéance du **10 novembre** ; lire la date
logique ingérerait novembre, un mois passé.

```bash
docker compose exec airflow-scheduler airflow dags trigger dag_acquisition_sources
```

Une `--logical-date` reste acceptée si elle tombe dans le mois en cours ; une autre est refusée
sans relance (`hors du mois en cours`).

### Un DAG de panel

Il attend normalement le signal de l'acquisition. Pour le lancer seul, il faut lui dire sur
quelles sources travailler, dans le mois en cours :

```bash
docker compose exec airflow-scheduler \
  airflow dags trigger dag_genomic_pipeline_brca --conf '{"sources_date": "2026-10-01"}'
```

`resolve_sources_date` vérifie d'abord que le bronze ClinVar et HPO de ce mois est complet ;
sinon, échec sans relance (`lancer d'abord dag_acquisition_sources`).

### Depuis l'interface

Bouton ▶ sur la ligne du DAG. Pense à l'activer d'abord (l'interrupteur à gauche du nom) : un
DAG en pause ne se déclenche jamais, même par signal.

> **Piège vécu (21/10) :** activer `dag_acquisition_sources` déclenche aussi, immédiatement, le run
> planifié du mois en cours s'il est déjà passé. Un ▶ Trigger juste après acquérait le même mois une
> seconde fois et faisait tourner chaque panel deux fois. Depuis le 23/10, la tâche
> `skip_if_already_published` saute un mois déjà publié lors d'un Trigger manuel ; pour le
> réacquérir quand même, ajouter `--conf '{"force": true}'`. Un run **planifié** passe toujours :
> le 10, il relit le mois pour prendre ce qui a changé (NCBI Gene, RefSeq et MedGen sont
> interrogés en direct).
>
> Le même mécanisme rattrape une machine éteinte le 10 : au redémarrage, Airflow lance la dernière
> échéance passée et `notify_catch_up` l'annonce par e-mail, avec le mois traité. Seule la
> **dernière** échéance est rattrapée, et elle traite le mois du redémarrage : un mois
> entièrement manqué est perdu, volontairement (jamais de mois passé).

---

## 4. Comprendre un échec

### Où regarder

Dans l'interface : le DAG → l'onglet **Graph** → la tâche en rouge → **Logs**. Le message utile
est presque toujours dans les vingt dernières lignes.

En ligne de commande, pour retrouver l'état de toutes les tâches d'un run :

```bash
docker compose exec airflow-scheduler airflow dags list-runs dag_genomic_pipeline_brca
docker compose exec airflow-scheduler \
  airflow tasks states-for-dag-run dag_genomic_pipeline_brca "<run_id>"
```

Les journaux sont conservés dans un volume dédié : ils survivent à un `docker compose down` et
même à une reconstruction des images.

### Les échecs normaux, qui ne sont pas des bugs

| Message | Ce que ça veut dire |
|---|---|
| `hors du mois en cours` | Un Trigger manuel sur un autre mois que le mois en cours : refusé exprès. |
| `pas encore publiée` | Run lancé avant le premier jeudi du mois : l'archive ClinVar n'existe pas encore. Le run du 10 la prendra. |
| `date des sources absente` | Un run manuel de panel sans `--conf '{"sources_date": ...}'`. |
| `lancer d'abord dag_acquisition_sources` | Run de panel sur un mois sans bronze partagé complet. |
| `SilverQualityError` / `GoldQualityError` | Un contrôle qualité a bloqué la propagation. Le message nomme la table et le problème : c'est le garde-fou qui fonctionne. |
| `espace disque insuffisant` | Moins de 2 Go libres avant un téléchargement de 440 Mo. Libérer de la place, puis relancer. |
| `NotImplementedError ... sous-projet D` | Ne devrait plus apparaître : tout est livré. Si tu le vois, c'est qu'une ancienne image traîne. |

### Relancer une tâche

Depuis l'interface : clic sur la tâche → **Clear**. Les tâches en aval sont relancées avec elle.

> **Piège vécu, à connaître :** la commande `airflow tasks clear` ne trouve pas les tâches d'un
> run déclenché par signal, parce qu'elle filtre par date logique et que ces runs n'en ont pas.
> Passe par l'interface, ou par l'API :
>
> ```bash
> docker exec genomique-airflow-apiserver python - <<'EOF'
> import os, requests
> mdp = os.environ['AIRFLOW_ADMIN_PASSWORD']
> base = 'http://localhost:8080'
> jeton = requests.post(base + '/auth/token',
>                       json={'username': 'admin', 'password': mdp}).json()['access_token']
> r = requests.post(base + '/api/v2/dags/dag_genomic_pipeline_brca/clearTaskInstances',
>                   headers={'Authorization': 'Bearer ' + jeton},
>                   json={'dry_run': False, 'dag_run_id': '<run_id>',
>                         'task_ids': ['bronze_to_silver'],
>                         'include_downstream': True, 'only_failed': False,
>                         'reset_dag_runs': True})
> print(r.status_code)
> EOF
> ```

---

## 5. Ajouter ou modifier une tâche

La règle du projet : **aucune logique métier dans un DAG**. Une tâche appelle une fonction de
`src/`, rien de plus. C'est ce qui permet de tout tester sans Airflow ni conteneur.

```python
# dans dags/dag_genomic_pipeline.py
@task(task_id="ma_nouvelle_etape", pool=HEAVY_CONVERSION_POOL)   # pool si la tâche est lourde ou écrit une table partagée
def task_ma_nouvelle_etape(sources_date: str) -> None:
    ma_fonction(sources_date, panel)      # la logique vit dans src/transformations/
```

puis la brancher dans le graphe, en bas de la fonction :

```python
quality >> task_ma_nouvelle_etape(sources_date)
```

Enfin, écrire le test de structure correspondant dans `tests_airflow/`.

> **Différence avec Airflow 2 :** l'import est `from airflow.sdk import DAG, task` au lieu de
> `from airflow.decorators import task`. L'écriture d'une tâche, elle, est identique.

**Les pools** sérialisent les tâches qui se marcheraient dessus :

| Pool | Un seul créneau, parce que… |
|---|---|
| `ncbi` | NCBI limite le débit global : deux tâches en parallèle dépasseraient le quota |
| `conversion_lourde` | Conversions lourdes (ClinVar ≈ 2 Go, Silver 1,37 Go, plafond 3 Go) et écritures Delta partagées entre les deux panels (`raw_to_bronze`, `bronze_to_silver`, `silver_to_gold_*`) |
| `rag_index` | Une indexation à la fois : le service d'embedding sature déjà le processeur |

Les deux DAGs n'acceptent qu'**un run actif à la fois** (`max_active_runs=1`) : deux runs
écriraient la même partition `raw`. Les anciens pools `silver_write` et `gold_write`, remplacés
par `conversion_lourde`, peuvent rester dans une base existante sans effet (plus aucune tâche ne
les utilise) ; `airflow pools delete silver_write gold_write` les retire.

Après toute modification : `pytest -q` puis `pytest tests_airflow -q`. Les DAGs sont relus
automatiquement, inutile de redémarrer la stack — sauf si tu changes `docker-compose.yml` ou le
`Dockerfile`, auquel cas `docker compose up -d --build`.

---

## 6. Les commandes à retenir

```bash
docker compose --env-file .env up -d          # démarrer
docker compose ps                             # état des services
docker compose logs -f airflow-scheduler      # suivre un service
docker compose down                           # arrêter (données conservées)

docker compose exec airflow-scheduler airflow dags list
docker compose exec airflow-scheduler airflow dags list-runs <dag_id>
docker compose exec airflow-scheduler airflow pools list

./scripts/sauvegarde.sh                       # sauvegarder le lac et la base
pytest -q && pytest tests_airflow -q          # les deux passes de tests
```

---

## 7. Récapitulatif : Airflow 2 → 3 pour ce projet

Ce que tu connais reste vrai à 90 %. Les cinq différences que tu rencontreras :

| Point | Airflow 2 | Ici, en 3.3.1 |
|---|---|---|
| Écrire une tâche | `@task` | `@task` — identique |
| Import | `from airflow.decorators import task` | `from airflow.sdk import DAG, task` |
| Déclenchement par événement | *Dataset* | *Asset* — même principe |
| Date d'un run déclenché par événement | il en a une | il n'en a pas : le projet transmet la date dans le signal, ou par `--conf` |
| Utilisateur de l'interface | `airflow users create` | compte `admin`, mot de passe pris dans le `.env` |
| Service web | `webserver` | `api-server` |

Tout le reste — l'interface, les logs, les pools, les tentatives, le graphe, les commandes
`dags trigger` et `dags list` — fonctionne comme tu en as l'habitude.

---

## 8. Où trouver le reste

| Question | Document |
|---|---|
| Qu'est-ce que fait ce projet, comment l'installer | `README.md` |
| Pourquoi Airflow plutôt que NiFi | `reference/choix_contexte.md` |
| Risques d'accès, secrets, exposition réseau | `reference/audit_securite.md` |
| Ce qui peut casser en exploitation | `reference/audit_production.md` |
| Ce qui reste à faire | `TODO.md` |
