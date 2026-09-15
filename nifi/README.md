# NiFi — orchestration de l'étape 1 (collecte)

> ⚠️ **Alternative écartée.** Ce dossier n'est plus le chemin d'orchestration du projet.
> Il est conservé pour documenter un choix évalué puis écarté avec mesures — voir
> `CLAUDE.md`. L'orchestration active vit dans `dags/`.

Ce dossier fait tourner l'étape 1 (collecte RAW) via un flow Apache NiFi plutôt que via
un lancement manuel/cron de `scripts/run_collection.py`. **Périmètre volontairement
limité à la collecte** : NiFi n'orchestre pas les étapes Bronze/Silver/Gold ni la RAG —
voir la section "Pourquoi NiFi ne fait que ça" du `CLAUDE.md` racine pour la justification
de cette frontière.

## Ce que ça change (et ce que ça ne change pas)

NiFi **ne réimplémente aucune logique de collecte**. Le flow appelle
`scripts/run_collection.py` tel quel via un processor `ExecuteStreamCommand` — tout le
code testé par `pytest` dans `src/ingestion/` (rate limiting NCBI, retries, filtrage
polars, parsing XML MedGen, enrichissement HPO…) reste inchangé et continue d'être
couvert par la suite de tests existante. NiFi n'apporte que :

- **le déclenchement planifié** (cron, tous les jours à 2h par défaut),
- **le routage succès/échec** selon le code de sortie du script,
- **la journalisation** du résultat (niveau info en cas de succès, error sinon).

## Démarrer

```bash
cd nifi/
cp .env.example .env      # puis choisir un mot de passe réel (12 caractères min.)
docker compose up -d --build
```

L'interface est sur `https://localhost:8443/nifi` (utilisateur/mot de passe définis
dans `.env`). Le certificat est auto-signé — l'accepter dans le navigateur.

**Un vrai `.env` doit exister à la racine du repo** (celui utilisé par
`scripts/run_collection.py`, avec `NCBI_EMAIL` renseigné — voir le README racine) : le
conteneur monte tout le repo dans `/opt/projet`, donc ce `.env` doit être créé côté host
avant de lancer une collecte réelle. Sans lui, le flow échoue proprement côté NiFi (voir
plus bas).

## Importer le flow

Le process group "Collecte génomique (étape 1)" est exporté dans
`flows/collecte-genomique.json`. Sur une instance NiFi vierge : glisser un process group
vide sur le canvas, puis utiliser "Import from Registry/File" (icône d'import du process
group) en pointant sur ce fichier.

## Composition du flow

1. **Déclencheur quotidien (02h00)** — `GenerateFlowFile`, planification CRON
   (`0 0 2 * * ?`).
2. **Exécuter run_collection.py** — `ExecuteStreamCommand`, lance
   `/opt/collecte-venv/bin/python3 scripts/run_collection.py` avec pour répertoire de
   travail `/opt/projet` (racine du repo montée dans le conteneur).
3. **Router selon le code de sortie** — `RouteOnAttribute`, teste l'attribut
   `execution.status` posé par `ExecuteStreamCommand` (`0` = succès).
4. **Log collecte réussie** / **Log collecte en échec** — `LogAttribute`, niveau
   `info`/`error` respectivement.

## Ce qui a été vérifié, et ce qui ne l'a pas été

- ✅ L'image se construit (Python 3.11 + venv dédié avec `requirements.txt` installé
  par-dessus l'image `apache/nifi:2.6.0`).
- ✅ Le venv de collecte fonctionne dans le conteneur (`from ingestion.config import
  ALL_GENES` → 18).
- ✅ **Chemin d'échec testé de bout en bout** : sans `.env`, `run_collection.py` sort en
  code 1 (`NCBI_EMAIL manquant`) ; `ExecuteStreamCommand` capture ce code non nul,
  route vers "nonzero status", `RouteOnAttribute` route vers `echec`, et
  `LogAttribute` journalise l'erreur avec l'attribut `execution.error` contenant le
  message exact. Vérifié via l'API REST de NiFi (statut des connexions, bulletin board)
  et les logs du conteneur — pas seulement supposé.
- ⚠️ **Chemin de succès non testé ici**, volontairement : il nécessite un `NCBI_EMAIL`
  réel et déclenche ~1200 appels NCBI + un téléchargement ClinVar de 440 Mo. Exactement
  la même réserve que pour `run_collection.py` lui-même, déjà documentée dans le README
  racine ("fait de vrais appels réseau et n'est pas testé automatiquement"). À valider
  manuellement une fois un `.env` réel en place, en surveillant `data/raw/` et les logs
  NiFi.

## Dockerfile

Base `apache/nifi:2.6.0` (Debian 12), + `python3-venv`/`python3-pip` installés via apt,
+ un venv dédié `/opt/collecte-venv` avec `requirements.txt` (dépendances runtime
seulement, pas `pytest`/`responses`). Ce venv est séparé de l'interpréteur système que
NiFi utilise pour ses propres fonctionnalités Python natives (`nifi.python.command`).
