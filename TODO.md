# À faire

Suivi des éléments identifiés mais non implémentés. Les deux audits complets sont dans
`reference/audit_securite.md` et `reference/audit_production.md` ; ce fichier n'en garde que
ce qui reste à faire.

---

## 1. Resend — à finir quand le backend sera en place

La configuration côté pipeline est **déjà faite** : Airflow envoie un e-mail à chaque échec de
tâche via le relais SMTP de Resend (`smtp.resend.com:587`, utilisateur `resend`, mot de passe =
clé API). Il ne manque que le compte.

- [ ] **Vérifier un domaine dans Resend.** Leur documentation l'exige pour l'envoi SMTP :
      l'adresse de test `onboarding@resend.dev` ne fonctionne pas par ce canal.
- [ ] **Créer une clé API** et la mettre dans `.env` sous `RESEND_API_KEY`.
- [ ] **Renseigner `ALERT_FROM`** (une adresse du domaine vérifié) et **`ALERT_EMAIL`**
      (le ou les destinataires, séparés par des virgules).
- [ ] **Tester pour de vrai** : faire échouer une tâche volontairement et vérifier que le mail
      arrive. Une alerte non testée ne compte pas.
- [ ] **Réutiliser le même compte Resend dans le backend**, pour que les envois du pipeline et
      ceux de l'application soient visibles au même endroit.

Tant que ces clés sont vides, rien ne casse : les tâches échouent normalement, seul le mail ne
part pas.

---

## 2. Exploitation — à installer

- [ ] **Planifier la sauvegarde hebdomadaire.** Le script `scripts/sauvegarde.sh` est écrit et
      testé (931 Mo, dump PostgreSQL vérifié relisible), mais rien ne le lance encore.
      Ligne à ajouter avec `crontab -e` :
      `0 3 * * 0 cd /home/azuka/Documents/Projet-_de_Memoire && ./scripts/sauvegarde.sh >> ~/sauvegarde.log 2>&1`
- [ ] **Tester une restauration complète** au moins une fois, depuis une sauvegarde, sur une
      stack vide. C'est le seul moyen de savoir qu'elle fonctionne.

---

## 3. Robustesse en production — reste de l'audit

Par ordre d'intérêt. Références entre parenthèses : `reference/audit_production.md`.

- [ ] **Limiter à une exécution simultanée par DAG de panel** (P5). Une ligne :
      `max_active_runs=1`. Évite que deux runs écrivent la même partition `raw`.
- [ ] **Rattraper ou signaler un mois manqué** (P4). `catchup=False` fait qu'une machine éteinte
      le 10 saute le mois, définitivement et sans bruit.
- [ ] **Sérialiser les conversions lourdes par un pool dédié** (P7). Le conteneur est plafonné à
      3 Go et autorise 4 tâches ; la conversion ClinVar a mesuré un pic à 2 Go. Aujourd'hui seul
      l'ordre du graphe évite le chevauchement.
- [ ] **Définir une rétention Delta (`VACUUM`) et une règle de cycle de vie MinIO** (P11, P9).
- [ ] **Écrire la procédure de reprise** (P17) : mois manquant, table corrompue, lac perdu.
- [ ] **Vérifier le schéma des sources à l'entrée** (P13), pour qu'une colonne ClinVar renommée
      produise un message explicite plutôt qu'une erreur Polars.

---

## 4. Sécurité — reste de l'audit

Références : `reference/audit_securite.md`. Les points marqués « production » ne deviennent
critiques que le jour d'un déploiement hors de la machine de développement.

- [ ] **Activer TLS sur MinIO** et basculer l'endpoint en `https://` (T1) — *production*.
- [ ] **Reverse proxy TLS avec authentification devant Airflow** (D2) — *production*.
- [ ] **Activer le versioning des buckets** (M3). Protection la moins coûteuse contre une
      suppression accidentelle, qui est le scénario le plus probable.
- [ ] **Vérifier la somme de contrôle MD5 publiée par ClinVar** après téléchargement (C2).
- [ ] **Valider les composants de chemin** (`source`, `panel`, date) avant de construire les
      clés d'objet (I1).
- [ ] **Durcir l'exécution des conteneurs** : `no-new-privileges`, retrait des capacités Linux
      inutiles (D4).
- [ ] **Passer les secrets par fichiers montés** plutôt que par variables d'environnement (D5).
- [ ] **Ajouter une intégration continue** : tests, scan de vulnérabilités des dépendances,
      scan des images (G1).

---

## 5. Suite du projet

- [ ] **Sous-projet RAG** : découpage, embeddings BioBERT, base vectorielle, récupération,
      prompts, appel au LLM, API. Il lira `gold/rag/documents` (96 910 documents produits).
      Structure de dossiers fixée par `architecture RAG.jpeg`. Une décision à trancher au
      passage : les listes de phénotypes contiennent des termes HPO qui n'en sont pas vraiment
      (« Autosomal dominant inheritance », « Middle age onset ») et occupent des places dans une
      liste plafonnée à dix.
- [ ] **Application web** : interface et API, lisant le RAG et `gold/analytique` via DuckDB.
