# À faire

Suivi des éléments identifiés mais non implémentés. Les deux audits complets sont dans
`reference/audit_securite.md` et `reference/audit_production.md` ; ce fichier n'en garde que ce
qui reste à faire.

**Dernière vérification :** 25 septembre 2026, chaque ligne confrontée à l'état réel du dépôt.

---

## 1. Alertes — brancher un serveur d'envoi

Le câblage est **fait** : les deux DAGs envoient un e-mail à chaque échec de tâche dès qu'un
serveur SMTP est renseigné, et le destinataire vient du `.env`. Il ne manque que le fournisseur,
volontairement laissé de côté pour être choisi au moment du backend.

- [ ] **Brancher Resend au moment du backend**, pour que les envois du pipeline et ceux de
      l'application partent du même compte et soient visibles au même endroit.
      Relais : `smtp.resend.com`, port 587 en STARTTLS, utilisateur `resend`, mot de passe =
      clé API. Leur documentation exige un **domaine vérifié** : l'adresse de test
      `onboarding@resend.dev` ne passe pas par SMTP.
- [ ] **Renseigner dans `.env`** : `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
      `ALERT_FROM`, `ALERT_EMAIL`. Vérifié le 25/09 : toutes vides.
- [ ] **Tester pour de vrai** : faire échouer une tâche volontairement et vérifier que le mail
      arrive. Une alerte non testée ne compte pas.

Tant que ces clés sont vides, rien ne casse : les tâches échouent normalement, seul le mail ne
part pas.

---

## 2. Exploitation — à installer

- [ ] **Planifier la sauvegarde hebdomadaire.** `scripts/sauvegarde.sh` est écrit et exécuté
      avec succès (931 Mo, dump PostgreSQL vérifié relisible, table Delta sauvegardée relue),
      mais **aucune tâche cron ne le lance** — vérifié le 25/09, `crontab` ne le mentionne pas.
      Ligne à ajouter avec `crontab -e` :
      `0 3 * * 0 cd /home/azuka/Documents/Projet-_de_Memoire && ./scripts/sauvegarde.sh >> ~/sauvegarde.log 2>&1`
- [ ] **Tester une restauration complète** sur une stack vide. Ce qui est vérifié à ce jour :
      le dump est un fichier d'archive valide et une table Delta sauvegardée se relit. Ce qui ne
      l'est pas : restaurer réellement la base et les buckets, puis relancer un run dessus.

---

## 3. Robustesse en production — reste de l'audit

Par ordre d'intérêt. Références : `reference/audit_production.md`.

- [ ] **Limiter à une exécution simultanée par DAG de panel** (P5). Une ligne,
      `max_active_runs=1` — vérifié le 25/09 : absent des deux DAGs. Évite que deux runs
      écrivent la même partition `raw`.
- [ ] **Rattraper ou signaler un mois manqué** (P4). `catchup=False` dans les deux DAGs : une
      machine éteinte le 10 saute le mois, définitivement et sans bruit.
- [ ] **Sérialiser les conversions lourdes par un pool dédié** (P7). Vérifié : `raw_to_bronze`
      n'a aucun pool. Le conteneur est plafonné à 3 Go et autorise 4 tâches, alors que la
      conversion ClinVar a mesuré un pic à 2 Go — seul l'ordre du graphe évite le chevauchement.
- [ ] **Définir une rétention Delta (`VACUUM`) et une règle de cycle de vie MinIO** (P11, P9).
      Aucune des deux n'existe.
- [ ] **Compléter la procédure de reprise** (P17). *Partiellement fait* :
      `reference/guide_airflow.md` couvre la lecture d'un échec et la relance d'une tâche, et le
      README décrit la marche à suivre après un changement de schéma Gold. Restent à écrire :
      le rattrapage d'un mois manquant et la restauration après perte du lac.
- [ ] **Vérifier le schéma des sources à l'entrée** (P13), pour qu'une colonne ClinVar renommée
      produise un message explicite plutôt qu'une erreur Polars.

---

## 4. Sécurité — reste de l'audit

Références : `reference/audit_securite.md`. Les points marqués « production » ne deviennent
critiques que le jour d'un déploiement hors de la machine de développement.

- [ ] **Activer TLS sur MinIO** et basculer l'endpoint en `https://` (T1) — *production*.
      Vérifié : l'endpoint est toujours en `http://`.
- [ ] **Reverse proxy TLS avec authentification devant Airflow** (D2) — *production*.
- [ ] **Activer le versioning des buckets** (M3). Protection la moins coûteuse contre une
      suppression accidentelle, qui est le scénario le plus probable. Absent du script
      d'amorçage.
- [ ] **Vérifier la somme de contrôle MD5 publiée par ClinVar** après téléchargement (C2).
- [ ] **Valider les composants de chemin** (`source`, `panel`, date) avant de construire les
      clés d'objet (I1).
- [x] **Durcissement d'exécution des conteneurs** (D4) — *fait, partiellement.*
      `no-new-privileges` est appliqué à tous les services. `cap_drop: [ALL]` a été essayé puis
      retiré : les points d'entrée d'Airflow, PostgreSQL et `mc` ont besoin de `CHOWN`/`FOWNER`
      pour préparer leurs fichiers. La raison est consignée dans `docker-compose.yml`.
- [ ] **Passer les secrets par fichiers montés** plutôt que par variables d'environnement (D5).
- [ ] **Ajouter une intégration continue** : tests, scan de vulnérabilités des dépendances, scan
      des images (G1). Aucun dossier `.github` à ce jour.

### Corrigé depuis la rédaction de l'audit

- [x] **Mot de passe admin d'Airflow stable et pris dans le `.env`** (D9). Il était régénéré à
      chaque démarrage et illisible depuis l'hôte ; il vient désormais de
      `AIRFLOW_ADMIN_PASSWORD`, et le fichier de comptes a migré dans le volume des logs.
- [x] **`MINIO_ROOT_USER` rendu obligatoire** au démarrage plutôt que silencieusement vide.

---

## 5. Suite du projet

- [x] **Sous-projet RAG — E1, indexation** : `gold/rag/documents` → pgvector, incrémental et
      reprenable, tâche `index_rag_documents` en fin de DAG de panel. Modèle choisi par mesure :
      NeuML PubMedBERT (`reference/choix_embedding.md`). Exploitation : `RAG/README.md`.
- [x] **Sous-projet RAG — E2, question-réponse** : *implémenté* — E2a (recherche hybride, branche
      `rag/e2a-recherche`, mesure officielle en attente de crédits) et E2b (génération vérifiée, API
      Litestar, passerelle, proxy, durcissement ; branche `rag/e2b-generation`, recette en cours).
      Objectif d'origine : recherche hybride (filtres gène et
      signification, correspondance exacte `rs`/HGVS, similarité), prompts, appel au LLM, API Litestar. La mesure de E1 confirme que la similarité seule ne distingue pas
      un variant pathogène d'un bénin (précision 0,305 sur la famille C).
- [ ] **Sous-projet RAG — E3, évaluation et audit** : RAGAS, puis audit du RAG et application de
      la même politique au pipeline. Décision à trancher **après** une première mesure RAGAS :
      les listes de phénotypes contiennent des termes HPO qui n'en sont pas vraiment
      (« Autosomal dominant inheritance », « Middle age onset ») et occupent des places dans une
      liste plafonnée à dix.
- [ ] **Sauvegarde de `rag-postgres-data`** dans `scripts/sauvegarde.sh`. La base se reconstruit
      depuis le Gold, mais en ~4 h sur CPU (9 min sur GPU).
- [ ] **Application web** : interface et API, lisant le RAG et `gold/analytique` via DuckDB.

---

## 6. RAG E1 — durcissements différés (revue finale du 04/10/2026)

Écarts relevés par la revue finale de la branche `rag/e1-indexation` et volontairement laissés
pour plus tard : aucun ne fausse l'index produit aujourd'hui, sur une machine de
développement où seul Airflow joint la base vectorielle.

### Sécurité — avant que `rag_reader` serve l'API (E2)

- [x] **Retirer le droit de tables temporaires** : `REVOKE TEMPORARY ON DATABASE rag FROM PUBLIC`.
      Reporté : aucun client autre qu'Airflow ne se connecte avant E2. Fait en E2b
      (`REVOKE TEMPORARY, CREATE ON DATABASE rag FROM PUBLIC`, vérifié par
      `RAG/tests/test_hardening_integration.py`).
- [x] **Faire converger les attributs des rôles** à chaque amorçage :
      `ALTER ROLE … NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`, et
      `REVOKE ALL … FROM rag_indexer, rag_reader` avant les `GRANT`. Reporté : les rôles sont
      créés par le script et personne d'autre ne les modifie ; à faire avant d'ouvrir
      `rag_reader` à l'API. Fait en E2b (`NOREPLICATION LOGIN` en plus).
- [x] **Passer les mots de passe à psql par `\getenv`** plutôt que par `-v` : ils apparaissent
      brièvement dans la liste des processus et, si un `CREATE`/`ALTER ROLE` échoue, dans le
      journal du serveur. Reporté : conteneur éphémère sur une machine mono-utilisateur ; à
      faire avec la convergence des rôles ci-dessus. Fait en E2b : `psql -q -f`, variable
      absente → erreur SQL et code de sortie 3.
- [x] **Réserver les secrets `RAG_*` et `rag-network` au scheduler**, seul à exécuter la tâche
      d'indexation ; ils sont aujourd'hui sur tous les services Airflow, apiserver compris.
      Reporté : demande de sortir ces clés de l'ancre `x-airflow-common` ; à faire avant
      d'exposer l'apiserver hors de la machine. Fait en E2b (ancre `x-rag-indexer-env`).
- [x] **Isoler `rag-model-export`** sur un réseau d'export dédié, avec un plafond mémoire : il
      est aujourd'hui sur `genomique-network`, qui atteint `postgres` et `minio`. Reporté :
      outil lancé à la main, rarement ; à faire avant E2. Fait en E2b (réseau `rag-export`,
      4 Gio).
- [x] **Monter `./data/models` en lecture seule dans les services Airflow** : ils y ont
      aujourd'hui l'écriture (via `./data`), donc une tâche compromise pourrait empoisonner le
      modèle servi. Reporté : demande de redécouper le montage de `./data` ; à faire avant E2.
      Fait en E2b (montage `:ro` superposé à `./data`).

- [x] **Proxy sortant filtrant (squid/tinyproxy, `openrouter.ai:443` seulement) sur
      `rag-egress`**, `rag-search` sur réseau interne + `HTTPS_PROXY` — avant E2b.
      Fait en E2b (rag-proxy, docker/rag-api/requirements.lock) : Squid, seul service sur
      `rag-egress`, n'autorise que `CONNECT` vers `openrouter.ai:443` et `api.groq.com:443` ;
      `rag-api` / `rag-search` sont sur le réseau interne `rag-proxy-net`.
- [x] **Verrouiller par empreinte les dépendances de l'image `rag-search`**, comme l'image
      d'export : versions épinglées aujourd'hui, sans empreintes. À faire avant que le service
      devienne l'API (E2b). Fait en E2b (rag-proxy, docker/rag-api/requirements.lock) : image
      commune `docker/rag-api/Dockerfile`, `pip install --require-hashes`.

### Robustesse — avant la mise en service régulière

- [ ] **`connect_timeout` et `statement_timeout`** sur la connexion PostgreSQL. Reporté : seul
      le délai de 6 h de la tâche borne aujourd'hui une base qui ne répond plus.
- [ ] **Fermer la connexion si `register_vector` échoue** dans `__enter__`. Reporté : fuite
      d'une connexion par échec, sans effet sur l'index.
- [ ] **Ne pas masquer l'erreur d'origine dans `finally: unlock`** quand la connexion tombe.
      Reporté : le diagnostic est plus difficile, l'issue (échec puis relance) reste juste.
- [ ] **Importer le RAG dans le corps de la tâche Airflow** plutôt qu'au niveau du module : une
      dépendance RAG manquante casse aujourd'hui l'analyse de tous les DAGs. Reporté : les
      dépendances sont dans l'image ; à faire au prochain changement du DAG de panel.

### Exploitation

- [ ] **Supprimer la fenêtre sans modèle de `export_model.py --force`** (`rmtree` puis
      `rename`). Reporté : réexport rare ; d'ici là, arrêter `rag-embeddings` avant un `--force`.
- [ ] **Verrou de l'image d'export pour une autre architecture que x86_64.** Reporté : la
      machine de développement est x86_64 ; à faire si l'export doit tourner ailleurs.
- [ ] **Séparer les tests d'intégration de la base de production** : ils écrivent dans
      `rag-postgres` sous le panel `test_integration`. Reporté : panel isolé et nettoyé par les
      tests ; **E2 doit filtrer `panel IN ('brca','sickle')`**.
- [ ] **Automatiser l'aller-retour complet indexation + rejeu** prévu par la spec §7.3.
      Reporté : prouvé en conditions réelles le 04/10/2026 (RAG/README.md §6), non
      automatisé ; à faire avec E3.
- [ ] **Corriger l'avertissement de dépréciation Polars `is_in`** dans
      `RAG/experiments/comparaison_embeddings.py`. Reporté : script de mesure déjà exécuté,
      sans effet sur l'indexation ; à faire avant de le relancer.

---

## 7. E2b — reste à faire (revues de la branche `rag/e2b-generation`)

Écarts de sécurité relevés en revue et volontairement différés (aucun n'est exploitable depuis
l'extérieur de la machine de développement) :

- [ ] **`SET log_min_error_statement = panic`** en tête de `RAG/sql/001_schema.sql` : si un
      `ALTER ROLE … PASSWORD` échoue, l'instruction (donc le mot de passe) peut apparaître dans le
      journal du serveur.
- [ ] **`BEGIN` / `COMMIT` autour des `REVOKE ALL` / `GRANT`** : un arrêt entre les deux laisse
      brièvement les rôles sans aucun droit (ou, dans l'ordre inverse, avec trop).
- [ ] **`REVOKE CONNECT, TEMPORARY ON DATABASE postgres, template1 FROM PUBLIC`** : les bases
      système restent ouvertes à tout rôle.
- [ ] **Garder synchronisé le sous-réseau du proxy** (`172.31.250.0/24`) entre
      `docker/rag-proxy/squid.conf` et le réseau `rag-proxy-net` de `docker-compose.yml` ; un test qui
      compare les deux éviterait la dérive.
- [ ] Droits d'écriture de l'indexeur non exercés après le changement de rôles, et « seul le scheduler
      voit les secrets » vérifié à la main : à automatiser.
- [ ] Relance bornée 429/5xx côté clients HTTP, fermeture des sessions HTTP, `text/plain` refusé sur
      `/v1/questions`, journalisation de l'erreur d'un fil après déconnexion du client.
