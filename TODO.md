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

- [ ] **E3b — reste la 7a** : cocher `reference/grille_justesse_e3b.md` (onze fiches ClinVar et
      cinq sources annexes, ~2 h 30), puis reporter le taux dans `reference/evaluation.md` § 11 et
      `reference/rapport_e3b.md`. Niveaux 5, 6 et 7b faits le 23–26/10 (`reference/rapport_e3b.md`).
- [ ] **Appliquer D-E3b-4 au Gold RAG** : relancer les deux panels sur octobre (22 149 documents
      re-vectorisés) ou attendre le run de novembre. Décision de l'utilisateur.
- [ ] **E3c — audit général et politique de garantie** : spec, plan, implémentation.
- [ ] **Fusion des branches** RAG → `pipeline/ingest` → `main`, à la toute fin du RAG, avec accord.

## 3. Application web (`apps/`)

- [ ] **Backend et frontend** : `apps/backend` et `apps/Frontend` sont vides. Suivre
      `apps/CONTEXT.template.md` (Litestar + Piccolo + asyncpg, TanStack Start), lecture du RAG et de
      `gold/analytique` via DuckDB.

## 4. Exploitation

- [x] **Relancer un run complet sur une pile restaurée** (E3b, 23/10/2026) : critère R2 du niveau 6,
      toutes les tâches au premier essai (`reference/rapport_e3b.md`).
- [ ] **Design des e-mails** (alerte d'échec, rappels J-2 et jour J) une fois le design de l'application
      validé : tout est dans `dags/common/emails.py`.
- [ ] **Monitoring** : relire en entier la spec
      `docs/superpowers/specs/2026-09-29-monitoring-prometheus-grafana-design.md`, puis décider.

## 5. Robustesse du pipeline de données

Références : `reference/audit_production.md` ; reprise : `reference/procedure_reprise.md` (23/10).

- [ ] **Seconde copie hors du disque** (`DESTINATION_SAUVEGARDE` : disque externe ou dossier cloud
      privé) : une copie sur le même SSD ne protège pas d'une panne de ce disque.

## 6. Sécurité

Références : `reference/audit_securite.md`. « Production » = critique seulement hors de la machine
de développement.

- [ ] **TLS sur MinIO**, endpoint en `https://` (T1) — *production*.
- [ ] **Reverse proxy TLS avec authentification devant Airflow** (D2) — *production*.
- [ ] **Secrets par fichiers montés** plutôt que par variables d'environnement (D5).
- [ ] **`transformers` 4.57.6 de l'image d'export** (`docker/embeddings/requirements-export.txt`) : 6 avis
      (PYSEC-2025-217, PYSEC-2026-2288 à 2290, 3929, 4174), acceptés dans la CI car aucun chemin n'est utilisé
      (modèles épinglés par SHA, pas de `Trainer`, torch 2.14.1). Passer en ≥ 5.10 change sans doute l'export
      ONNX, donc l'empreinte du modèle et tout l'index : à décider par mesure (canari), pas en passant.
- [ ] **Scan des images Docker** dans la CI (G1, reste) ; et rendre `pyright` bloquant une fois l'existant
      nettoyé (193 erreurs au 16/10/2026). `ruff` est bloquant depuis le 26/10/2026 (120 erreurs → 0).

## 7. RAG — durcissements différés

- [ ] **Verrou de l'image d'export hors x86_64**, si l'export doit tourner ailleurs.
- [ ] **Sortir les tests d'intégration de la base de production** (panel `test_integration` dans
      `rag-postgres`). La recherche filtre déjà sur les panels réels.
- [ ] **Automatiser l'aller-retour indexation + rejeu** (spec E1 §7.3), prouvé à la main le 04/10.
- [ ] **Journaliser la déconnexion du client** avant la réponse (seuls `late_error` et `late_result`
      le sont).

