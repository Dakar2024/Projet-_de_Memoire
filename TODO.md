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
- [ ] **Sous-projet RAG — E2, question-réponse** : recherche hybride (filtres gène et
      signification, correspondance exacte `rs`/HGVS, similarité), prompts, appel au LLM
      Anthropic, API Litestar. La mesure de E1 confirme que la similarité seule ne distingue pas
      un variant pathogène d'un bénin (précision 0,305 sur la famille C).
- [ ] **Sous-projet RAG — E3, évaluation et audit** : RAGAS, puis audit du RAG et application de
      la même politique au pipeline. Décision à trancher **après** une première mesure RAGAS :
      les listes de phénotypes contiennent des termes HPO qui n'en sont pas vraiment
      (« Autosomal dominant inheritance », « Middle age onset ») et occupent des places dans une
      liste plafonnée à dix.
- [ ] **Sauvegarde de `rag-postgres-data`** dans `scripts/sauvegarde.sh`. La base se reconstruit
      depuis le Gold, mais en ~4 h sur CPU (9 min sur GPU).
- [ ] **Application web** : interface et API, lisant le RAG et `gold/analytique` via DuckDB.
