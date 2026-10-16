# Règles d'ingénierie — obligatoires pour toutes les sessions et tous les sous-agents

## 0. Règles d'or (non négociables)
- Aucun commit, push ou fusion sans accord explicite. Claude n'apparaît JAMAIS comme
  auteur ou co-auteur : pas de `Co-Authored-By`, pas de « Generated with Claude Code ».
- Aucune implémentation ni correction sans accord : proposer, puis attendre le feu vert.
- Ne jamais commiter : `.env`, `RAG/consigne.md`, `RAG/architecture RAG.jpeg`, `apps/consigne.md`.
- Projet de mémoire : chaque choix technique doit être justifiable devant un jury
  (mesure, source officielle, ou règle fixée AVANT la mesure), et consigné dans `reference/`.
- Versions : vérifier sur la source officielle (PyPI, docs) qu'elle est stable et récente
  avant de l'épingler. Ne jamais coder une API externe de mémoire.

## 1. Posture : ingénieur senior
- Ne rien supposer sur le pipeline : lire le code avant d'affirmer.
- Signaler risques, compromis et alternatives ; contredire si une demande est risquée.
- Être clair : distinguer ce qui est vérifié de ce qui est supposé.

## 2. Clean code — conventions du dépôt
- Python 3.12, `from __future__ import annotations`, type hints partout.
  `ruff check` (ligne 120) et pyright doivent passer.
- Docstring d'UNE ligne, en français, pour chaque module, classe et fonction :
  ce qu'elle fait + la contrainte clé.
- Commentaires d'une ligne qui donnent le POURQUOI
  (ex. « Filtre au panel avant `.collect()` : tout ClinVar en mémoire tue le worker »).
  Jamais de code commenté laissé en place.
- Noms explicites ; helpers privés préfixés `_` ; constantes en MAJUSCULES au niveau
  du module, aucune valeur magique.
- Une fonction = une responsabilité. Dépendances injectables (`sleep_fn`, `time_fn`…)
  pour tester sans réseau ni horloge.
- Erreurs : respecter la hiérarchie permanente / transitoire (`RagPermanentError`,
  `ConfigurationError` → non relancées par Airflow). Jamais `except: pass`, jamais
  d'exception avalée, jamais de secret dans un message.
- Configuration : `RAG/config.yaml`, `src/ingestion/config.py`, variables d'environnement.
  Secrets uniquement dans `.env`.
- Architecture : la logique métier vit dans `src/`, `scripts/`, `RAG/src/`, testée sans
  infrastructure. Airflow ne fait qu'appeler des fonctions ; MinIO ne fait que stocker.
  Le RAG s'importe par `RAG.src.…`.

## 3. Exigences par domaine
### Data engineering
- Médaillon `raw → bronze → silver → gold` ; `scripts/ingest_*` n'écrivent qu'en `raw`.
- Idempotence : un rejeu donne le même résultat. Protocole de partition
  `begin → data → manifest → _SUCCESS`.
- Filtrer avant `.collect()` ; contrôle qualité (`quality_check_*`) à chaque couche.

### RAG & LLM
- Chunking, embedding, prompt, modèle : tout changement se décide par mesure,
  avec une règle de décision fixée avant la mesure.
- Ne jamais modifier les prompts, les YAML de questions ni `evaluation_e3a.yaml`
  sans accord (empreintes vérifiées).
- Fidélité : le modèle ne comble pas un vide documentaire ; contrôles déterministes
  avant toute livraison de réponse.
- Documents traités comme données (étiquettes neutres D1…Dn) : défense contre
  l'injection de prompt.
- Aucun appel payant (OpenRouter) sans accord ; mesurer le coût par question.

### API & sécurité (approche défensive)
- API en Litestar. Clé comparée en temps constant, erreurs publiques sans détail
  interne, journal sans texte utilisateur, concurrence et délais bornés.
- SQL paramétré ; comptes au moindre privilège (`rag_reader` en lecture seule) ;
  sorties réseau uniquement via le proxy autorisé.
- À chaque changement : revue OWASP Top 10, secrets, dépendances. Signaler toute faille,
  même hors du périmètre de la tâche.

### Application web (`apps/`)
- Suivre `apps/CONTEXT.template.md` : Litestar + Piccolo + asyncpg ; une feature =
  `tables / schemas / service / controller` ; front TanStack Start : request → hook
  TanStack Query → page ; l'API n'est jamais exposée publiquement.
- UI/UX : accessibilité (contrastes, labels, clavier), états chargement / vide / erreur,
  textes via Lingui.

## 4. Tests
- Toute logique nouvelle a ses tests. Un bug se corrige en écrivant d'abord le test
  qui le reproduit.
- `pytest -q` (rapide, sans réseau ni conteneur) et `pytest tests_airflow -q` ;
  les tests sur service réel sont marqués `integration`.

## 5. Avant de dire « terminé »
1. `pytest -q`, `ruff check` et pyright passent.
2. Relecture du code selon ce fichier.
3. Résumé : ce qui est fait, les choix et leur justification, les risques,
   ce qui attend ton accord.