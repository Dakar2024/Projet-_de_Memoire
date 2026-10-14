# Rapport E3a — Évaluation de la génération et choix du modèle

> Rédigé le 2026-10-14 à la demande de l'utilisateur, qui a délégué la conception détaillée et
> l'implémentation de E3a sans validation intermédiaire, à charge de tout documenter ici. Chaque
> décision est donnée avec sa justification et sa source, pour pouvoir être relue, contestée et
> modifiée.

## 1. Où en est E3a

| Étape | État |
|---|---|
| Cadrage (questions 1 à 9, approche, sections 1 à 3) | **validé par l'utilisateur** les 13 et 14/10 |
| Spec | écrite : `docs/superpowers/specs/2026-10-14-sous-projet-e3a-evaluation-generation-design.md` (§15 : amendements) |
| Plan | écrit : `docs/superpowers/plans/2026-10-14-sous-projet-e3a-evaluation-generation.md` |
| Code, tests, jeu de questions, documentation | **faits**, branche `rag/e3a-evaluation` (14 commits, non poussée) |
| Mesure réelle | **pas encore lancée** : elle attend les crédits OpenRouter, la mesure officielle de E2a et la fin de la recette E2b |

Rien n'a été envoyé à OpenRouter : aucun appel payant n'a été fait. Le code de E2b, gelé à 751fae3
pour la recette, n'a pas été touché. Le travail est fait dans une copie de travail séparée
(`../Projet-_de_Memoire-e3a`, `git worktree`), si bien que la recette quotidienne continue sur le
dossier principal sans être affectée.

## 2. Ce que E3a mesure, en une page

**La question** : quel modèle de génération mettre en service, parmi Claude Opus 5.5 (Google Vertex
Europe), Mistral Medium 3.5 (Mistral) et gpt-oss-120b (DeepInfra), et les réponses sont-elles fidèles
aux fiches et pertinentes ?

**Le principe** :

1. Les trois modèles répondent aux **mêmes 70 questions, avec exactement les mêmes documents**. La
   recherche est faite une fois et figée, puis refaite et comparée avant chaque génération. Un écart
   entre modèles ne peut donc venir que du modèle.
2. On juge la **réponse brute du modèle**, avant les contrôles déterministes de E2b. On mesure ainsi
   le modèle, et non le filtre.
3. Un **juge** (Gemini 3.8 Flash, d'une famille différente des trois candidats) découpe chaque
   réponse en affirmations et dit si chacune est soutenue par les documents : c'est la **fidélité**,
   au sens de RAGAS. Il note aussi la **pertinence** sur une grille 0/1/2.
4. **Le juge est lui-même contrôlé.** Vous annotez à l'aveugle 40 réponses avec les mêmes définitions
   que lui. Si l'accord (kappa de Cohen) est inférieur à 0,6, ses scores ne sont qu'indicatifs, et la
   décision repose sur votre annotation.
5. Une **règle écrite avant la mesure** choisit le modèle :
   - éliminer tout candidat dont la fidélité est inférieure à 0,90, le taux de rejet supérieur à
     25 % ou l'abstention à tort supérieure à 10 % ;
   - parmi les candidats restants, garder le plus fidèle. Un écart ne compte que s'il est établi
     statistiquement (intervalle bootstrap) **et** supérieur au bruit mesuré entre deux passages ;
   - en cas d'égalité, départager par la pertinence, puis le coût, puis la latence.

## 3. Décisions et justifications

### 3.1 Décisions de cadrage (validées par l'utilisateur)

| # | Décision | Pourquoi |
|---|---|---|
| Q1 | Nouveau jeu de questions, pertinence par règles, sans réponses de référence | Les 109 questions de la recette ont servi à corriger la chaîne : les réutiliser reviendrait à mesurer sur des exemples d'entraînement. |
| Q2 | Les trois candidats de E2a | Points d'accès déjà vérifiés : zéro rétention et sorties structurées. Une seule politique fournisseur à défendre. |
| Q3 | Un juge unique, Google Gemini | Aucune famille candidate, donc pas de biais d'un modèle envers ses propres réponses. |
| Q4 | Annotation humaine en aveugle, kappa ≥ 0,6 | Un juge LLM n'est pas une vérité : son accord avec un humain se mesure. 0,6 correspond à un accord « substantiel » (Landis et Koch, 1977). |
| Q5 | Pertinence notée par grille | La métrique RAGAS d'origine passe par des embeddings, et PubMedBERT est anglais seulement. |
| Q6 | Fidélité codée nous-mêmes, d'après la définition de RAGAS | RAGAS 0.4.3 n'est plus maintenu depuis 9 mois, porte une faille sans correctif (CVE-2026-6587, SSRF) et beaucoup de dépendances. |
| Q7 | Seuils éliminatoires, puis classement | La fiabilité passe d'abord, sans poids arbitraire. C'est la méthode déjà défendue en E1 et E2a. |
| Q8 | Tirage aléatoire avec graine | Évite de choisir, sans le vouloir, des cas faciles ; le tirage est reproductible. |
| Q9 | Un passage complet, deux reprises sur 20 questions, plafond de dépense | La variabilité est mesurée, pas supposée ; le coût est borné. |

### 3.2 Décisions prises seul pendant la conception détaillée

| Décision | Justification | Où |
|---|---|---|
| **Juge : `google/gemini-3.8-flash`** sur `google-vertex/global` | Version stable depuis le 02/09/2026, sans date d'arrêt annoncée ; recommandée par Google pour les nouveaux projets ; point d'accès zéro rétention avec sorties structurées. 0,75 $ / 3,75 $ par million de jetons. | spec §3 |
| Écartés : `gemini-4-argon` (publié le 13/10, trop récent), `gemini-3.1-pro-preview` (préversion), `gemini-3.5-flash` (remplacé), `gemini-2.5-pro` (ancienne génération) | Règle du projet : versions stables et éprouvées. | spec §3 |
| **Aucune température envoyée au juge** (amendement de « température 0 ») | Google recommande « fortement » la valeur par défaut, 1,0, pour Gemini 3, car une valeur plus basse peut provoquer des boucles. De plus, le point d'accès zéro rétention n'accepte pas ce paramètre. La reproductibilité vient du cache des verdicts, et la stabilité du juge est mesurée par un rejugement. | spec §2.1 |
| Profil du juge dans `evaluation_e3a.yaml`, pas dans `RAG/config.yaml` | L'ajouter à `llm.profiles` changerait l'empreinte des séries officielles de E2a et en ferait un candidat d'analyse. | spec §3 |
| Prompts du juge **en français** | Ils reprennent mot pour mot les définitions données à l'annotateur : le juge et l'humain appliquent le même critère, et c'est ce que mesure le kappa. | `judge.py` |
| Découpage et verdict en **deux appels distincts** ; le découpage ne voit pas les documents | C'est la procédure de l'article RAGAS : le découpage ne doit pas être orienté par ce que contiennent les documents. | `judge.py` |
| Justification **avant** le verdict, dans le schéma de sortie | Le modèle raisonne avant de trancher (bonne pratique des juges LLM). | `judge.py` |
| La table de traduction des significations est donnée au juge | Les réponses traduisent « Pathogenic » en « pathogène » : sans la table, le juge pourrait déclarer une traduction exacte « non soutenue ». | `judge.py` |
| **Abstention à tort** comptée (`not_in_sources` ou `out_of_scope` alors qu'un document pertinent est transmis) | Sans elle, un modèle qui s'abstient souvent aurait une fidélité parfaite à bon compte. | spec §6.3 |
| Bruit entre passages : ε = 1,96 × √((v_a + v_b)/n) | Borne à 95 % du bruit d'un passage à l'autre sur l'écart de deux moyennes de n questions, v étant la variance mesurée sur les reprises. | `decision.py` |
| Kappa **pondéré linéairement** pour la pertinence | L'échelle 0/1/2 est ordonnée : un désaccord 0/2 est plus grave qu'un désaccord 0/1 (Cohen, 1968). | `agreement.py` |
| IC du kappa par **bootstrap par grappes** | Les affirmations d'une même réponse ne sont pas indépendantes : on rééchantillonne des réponses entières. | `agreement.py` |
| Bootstrap recopié dans `decision.py` (même algorithme que E1), avec un test qui vérifie que les deux donnent des résultats identiques | Le code de `RAG/src` ne doit pas dépendre d'un script d'expérience. | `decision.py` |
| Strates du jeu : I 25, S 25, M 10, G 10 | Couvrir les trois usages réels : un variant précis, gène + signification + maladie, rôle d'un gène. | spec §4.1 |
| Gène tiré **uniformément**, puis élément dans ce gène | Sans cela, BRCA2, ATM et BRCA1 (60 % des variants) domineraient : les 18 gènes doivent être représentés. | `tirer` |
| Noms de maladie vides exclus (« not provided », « N conditions »…) | Ils ne font pas une question. | `tirer` |

### 3.3 Défauts trouvés et corrigés pendant l'implémentation

| Défaut | Comment il a été trouvé | Correction |
|---|---|---|
| Une sortie incohérente du juge était mise en cache : elle aurait été relue à chaque reprise, et le jugement ne se serait jamais fait | Par le test de `juger` | La sortie refusée quitte le cache ; les appels valides précédents y restent. |
| Deux commandes payantes lancées en même temps auraient pu dépasser le plafond | Revue de sécurité | Verrou exclusif (`flock`) sur le budget. |
| Une fiche ou une réponse contenant une séquence d'échappement ANSI pouvait agir sur le terminal de l'annotateur | Revue de sécurité | Caractères de contrôle retirés avant affichage. |
| Une panne réseau ou une erreur 5xx comptait contre le candidat dans son taux de rejet | Revue finale | Seules les fautes du modèle (sortie hors schéma, réponse coupée) sont comptées ; une panne est retentée. |
| Le filtre des noms de maladie, insensible à la casse, n'était pas compris par Polars | À l'écriture | Drapeau `(?i)`, commun à Python et à Rust. |

## 4. Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `RAG/experiments/evaluation_e3a.yaml` | Conditions fixées d'avance : juge, candidats, graines, effectifs, seuils, budget. |
| `RAG/src/evaluation/settings.py` | Lecture et contrôle de ces réglages. Refuse notamment un candidat inconnu ou un juge de la même famille qu'un candidat. |
| `RAG/src/evaluation/judge.py` | Prompts du juge (`juge-v1`, empreinte `JUDGE_PROMPT_SHA`), schémas stricts, contrôle des sorties, fidélité d'une réponse. |
| `RAG/src/evaluation/agreement.py` | Kappa de Cohen simple et pondéré ; bootstrap par grappes. |
| `RAG/src/evaluation/decision.py` | Règle de choix ; chaque comparaison est tracée. |
| `RAG/experiments/evaluation_generation.py` | Les 8 sous-commandes : tirage, vérité terrain, recherches, générations, jugement, échantillon, annotation, évaluation. Budget, caches, manifestes. |
| `RAG/experiments/questions_evaluation_e3a.yaml` | Le jeu de 70 questions. |
| `docker-compose.yml` | Un seul ajout : le dossier `data/experiments/e3a`, accessible en écriture au service `rag-search`. |
| `RAG/README.md` §10 | Exploitation : commandes dans l'ordre, garde-fous, limites. |
| `RAG/tests/test_evaluation_*.py` | 137 tests nouveaux, sans réseau ni base. |

**Vérifications faites** :

- **Tests** : 1520 tests de logique verts (1383 avant E3a), dont un bout en bout complet d'`evaluer` sur
  des données synthétiques. Il vérifie que la règle désigne le bon candidat, qu'elle n'est pas
  appliquée avec un juge invalide, et qu'`evaluer` refuse de conclure si une annotation ou une
  génération manque.
- **Image réelle** : l'outil a été chargé dans l'image `rag-search`, sans réseau.
- **Jeu de questions** : tirage et vérité terrain exécutés sur le vrai Gold (ClinVar 2026-10,
  97 211 documents). Chacune des 70 questions a au moins un document pertinent : médiane 1, maximum
  4 029 (pour « Quels variants de CDH1 sont associés à l'adénocarcinome gastrique ? »).
- **Contrôles du jeu** : aucune question n'est classée hors périmètre, aucun faux gène hors panel
  n'est détecté, et le texte de chaque question de la strate I cite bien le variant tiré.

**Sécurité** :

- **Réseau et accès** : les commandes réseau tournent dans `rag-search`, avec un compte en lecture
  seule ; la seule sortie passe par le proxy filtrant. Le juge est appelé en zéro rétention.
- **Données** : elles sont échappées et balisées, et les sorties du juge sont contrôlées par le code.
- **Budget** : le plafond est vérifié avant chaque appel, avec un verrou contre les commandes
  simultanées.
- **Dépendances** : aucune nouvelle.
- **Secrets** : jamais écrits dans les journaux ni dans les messages d'erreur.

## 5. Ce qu'il vous reste à faire, et quand

1. **Relire le jeu de questions** (`RAG/experiments/questions_evaluation_e3a.yaml`), avant toute
   génération. Les questions ont été rédigées à partir d'un tirage au hasard ; certaines maladies
   tirées sont inattendues, par exemple « polykystose rénale » pour RAD51D ou « diabète de type 2 »
   pour G6PD. C'est voulu : ClinVar rattache certains variants à de nombreuses affections, et le
   tirage n'a rien choisi. Vous pouvez reformuler une question, sans changer `tirage` ni `relevant`,
   ou l'écarter avec un motif (`ecartee: "…"`). Toute modification après la première génération
   invalide les séries.
2. **Ordre de lancement** :
   - fin de la recette E2b (109/109), puis son rapport ;
   - achat des crédits OpenRouter (vers le 19/10) ;
   - mesure officielle de E2a, qui fixe le modèle d'analyse ;
   - E3a, avec les commandes du README §10.2.
3. **Votre annotation** : 40 réponses, environ 1 h 30 dans le terminal (`annoter`), avec reprise
   possible. N'ouvrez pas `echantillon.json` avant la fin : il contient la correspondance entre
   chaque réponse et son modèle.
4. **Coût estimé** : environ 14 $ au total. Le plafond de 25 $ arrête tout de lui-même.
5. **Pour lancer E3a depuis le dossier principal**, il faudra y faire `git checkout
   rag/e3a-evaluation` une fois la recette terminée. Rien n'est poussé ni fusionné sans votre accord.

## 6. Points que vous pourriez vouloir changer

| Point | Valeur actuelle | Alternative |
|---|---|---|
| Plancher de fidélité | 0,90 | 0,85 si l'on accepte plus de risque, 0,95 si l'on veut plus d'exigence. C'est un choix de risque, pas une norme. |
| Taux de rejet maximal | 25 % | Plus strict si un refus de répondre vous paraît plus grave. |
| Juge | Gemini 3.8 Flash | `gemini-4-argon` quand il aura quelques semaines de recul (plus fort, plus cher). |
| Taille de l'annotation | 40 réponses | 60 pour un kappa plus précis (environ 45 min de plus). |
| Strate G | 10 questions sur les mêmes documents de gène que E2a | La réduire, au profit des strates I et S. |

Chaque valeur se trouve dans `RAG/experiments/evaluation_e3a.yaml`. La modifier avant la mesure est
légitime ; la modifier après avoir vu les résultats ne l'est pas, et les manifestes le
détecteraient.

## 7. Limites

- Le juge est validé sur 40 réponses (environ 13 par candidat), pas sur tout le jeu.
- L'aveugle de l'annotation est **procédural** : le fichier qui relie chaque réponse à son modèle
  existe, et vous vous engagez à ne pas l'ouvrir.
- La fidélité dépend du découpage en affirmations fait par le juge. Les découpages fautifs que vous
  signalez sont comptés, pas corrigés.
- La pertinence par grille n'est pas la métrique RAGAS d'origine ; c'est un écart assumé, décidé en
  Q5.
- Un appel refusé par le client après avoir été facturé (fournisseur inattendu) n'a pas de coût
  lisible : la réserve de 0,25 $ par appel le couvre.
- Les questions et leurs réponses sont conservées en clair dans `data/experiments/e3a` (non
  versionné). Ce sont des questions de test, sans données de patient.
