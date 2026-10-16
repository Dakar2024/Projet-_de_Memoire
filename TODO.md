# À faire

Ce qui n'est pas encore fait. Les audits complets sont dans `reference/audit_securite.md` et
`reference/audit_production.md` ; ce qui est livré se lit dans `CLAUDE.md` et les rapports de `reference/`.

**Dernière vérification :** 16 octobre 2026, chaque ligne confrontée à l'état réel du dépôt.

---

## 1. RAG — terminer les mesures (bloqué par les crédits OpenRouter)

- [ ] **Acheter les crédits OpenRouter** (prévu vers le 19/10) et renseigner `OPENROUTER_API_KEY`.
- [ ] **Mesure officielle E2a** : séries `full` des 3 profils, `evaluer`, ablation sur le profil
      retenu, rapport `reference/mesure_recherche_e2a.md`. Fixe `llm.analysis_profile`, encore
      provisoire (`essai-groq-gpt-oss-120b`).
- [ ] **Lancer E3a** (`RAG/README.md` §10.2, environ 14 $, plafond 25 $) depuis le dossier principal
      sur `rag/e3a-evaluation`, verite-terrain refaite. Fixe `llm.generation_profile`, encore provisoire.
- [ ] **Annoter les 40 réponses** (environ 1 h 30, `annoter`) sans ouvrir `echantillon.json`.
- [ ] **Refaire la recette E2b avec le modèle retenu**, avec une **nouvelle série de contrôle P4**
      (l'actuelle est compromise). Dernière recette : échec P2 19/20 et P3 9/10.
- [ ] **Commiter `reference/recette_e2b.md`** (§5, §5.1 et §8 rédigés, non commités).
- [ ] **Décider du nettoyage des listes de phénotypes** (« Autosomal dominant inheritance »,
      « Middle age onset » occupent des places sur dix) d'après la première mesure E3a.

## 2. RAG — sous-projets restants

- [ ] **E3b — évaluation du pipeline de données** (niveaux 5 à 7 de `reference/evaluation.md`) :
      spec, plan, implémentation. Inclut la restauration complète (voir §4).
- [ ] **E3c — audit général et politique de garantie** : spec, plan, implémentation.
- [ ] **Fusion des branches** RAG → `pipeline/ingest` → `main`, à la toute fin du RAG, avec accord.

## 3. Application web (`apps/`)

- [ ] **Backend et frontend** : `apps/backend` et `apps/Frontend` sont vides. Suivre
      `apps/CONTEXT.template.md` (Litestar + Piccolo + asyncpg, TanStack Start), lecture du RAG et de
      `gold/analytique` via DuckDB.

## 4. Exploitation

- [ ] **Tester une restauration complète** sur une stack vide : la base Airflow et les buckets MinIO,
      puis relancer un run dessus. (La base vectorielle est déjà vérifiée.)
- [ ] **Brancher les alertes e-mail** (le câblage existe, les clés sont vides) : Resend au moment du
      backend (`smtp.resend.com`, 587 STARTTLS, utilisateur `resend`, domaine vérifié obligatoire),
      renseigner `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_FROM`, `ALERT_EMAIL`,
      puis faire échouer une tâche pour vérifier que le mail arrive.
- [ ] **Monitoring** : relire en entier la spec
      `docs/superpowers/specs/2026-09-29-monitoring-prometheus-grafana-design.md`, puis décider.

## 5. Robustesse du pipeline de données

Références : `reference/audit_production.md`.

- [ ] **Rattraper ou signaler un mois manqué** (P4) : `catchup=False`, une machine éteinte le 10 saute
      le mois sans bruit.
- [ ] **Rétention Delta (`VACUUM`) et cycle de vie MinIO** (P11, P9) : aucun des deux n'existe.
- [ ] **Procédure de reprise** (P17) : écrire le rattrapage d'un mois manquant et la restauration
      après perte du lac.
- [ ] **Vérifier le schéma des sources à l'entrée** (P13) : une colonne ClinVar renommée doit donner
      un message explicite, pas une erreur Polars.

## 6. Sécurité

Références : `reference/audit_securite.md`. « Production » = critique seulement hors de la machine
de développement.

- [ ] **TLS sur MinIO**, endpoint en `https://` (T1) — *production*.
- [ ] **Reverse proxy TLS avec authentification devant Airflow** (D2) — *production*.
- [ ] **Versioning des buckets** (M3) : la protection la moins chère contre une suppression accidentelle.
- [ ] **Secrets par fichiers montés** plutôt que par variables d'environnement (D5).
- [ ] **Intégration continue** : tests, scan des dépendances et des images (G1). Pas de `.github`.

## 7. RAG — durcissements différés

- [ ] **Verrou de l'image d'export hors x86_64**, si l'export doit tourner ailleurs.
- [ ] **Sortir les tests d'intégration de la base de production** (panel `test_integration` dans
      `rag-postgres`). La recherche filtre déjà sur les panels réels.
- [ ] **Automatiser l'aller-retour indexation + rejeu** (spec E1 §7.3), prouvé à la main le 04/10.
- [ ] **Journaliser la déconnexion du client** avant la réponse (seuls `late_error` et `late_result`
      le sont).

