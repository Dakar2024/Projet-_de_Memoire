# Recette fonctionnelle de E2b — génération de réponses et API

> **État : rédigé (2026-10-14).** Passage final terminé (109/109, prompt `generation-v6`, corpus
> ClinVar 2026-10, code 751fae3). **Verdict : deux critères sur trois échouent (parties 2 et 3)**,
> à cause de deux fautes du modèle d'essai, toutes deux bloquées par les contrôles (§5, §5.1).
> Cinq correctifs post-recette (§8, branche `rag/e2b-correctifs`) ont été validés hors ligne sur les
> mêmes réponses : partie 3 → 10/10, partie 4 → 10/10, rejets 15 → 7 ; la partie 2 reste à 19/20
> (P2-05 est une vraie erreur du modèle). Ces chiffres ne remplacent pas le verdict officiel du §5.

## 1. Objet et portée

La recette vérifie que la **chaîne complète** — analyse de la question, recherche hybride, génération,
contrôles déterministes, messages fixes — se comporte comme la spec l'exige
(`docs/superpowers/specs/2026-10-08-sous-projet-e2b-generation-api-design.md`, §8.3).

Elle **ne choisit aucun modèle**. Le modèle de génération sera choisi en E3, par une mesure RAGAS. La
recette tourne avec le profil d'essai gratuit (`essai-groq-gpt-oss-120b`, Groq) pour l'analyse et la
génération. Ses latences sont donc celles de Groq, pas celles du profil de production OpenRouter.

## 2. Jeu de questions

| Partie | Contenu | Nombre | Origine |
|---|---|---|---|
| 1 | Questions ouvertes (familles A, B, C), traduites de E1 | 59 | E2a |
| 2 | Questions à identifiants (rs, HGVS) | 20 | E2a |
| 3 | Pièges : identifiant introuvable, gène hors panel, noms historiques… | 10 | E2a |
| 4 dev | Hors périmètre : comptage, ACMG, fréquence, conseil clinique, autre | 10 | validées le 2026-10-08 |
| 4 contrôle | Hors périmètre, formulations différentes | 10 | validées le 2026-10-09 |

**Série de contrôle tenue à l'écart.** La série de développement a servi à écrire les règles hors
périmètre (`RAG/src/generation/scope.py`). La série de contrôle, en revanche, a été écrite **avant**
ces règles. Ceux qui les ont écrites ne l'ont jamais vue. Le seuil de la partie 4 se calcule sur
elle seule, sinon on mesurerait une règle sur les exemples qui l'ont inspirée. Le score de la série
de développement est rapporté à part, à titre indicatif.

## 3. Critères fixés avant la recette (spec §8.3)

| Critère | Seuil |
|---|---|
| Partie 2 : statut `answered` (ou `partial`) citant un document pertinent | 20/20 |
| Partie 3 : identifiant introuvable ou gène hors panel → message fixe, aucune citation ; autres pièges → jamais `unverifiable` | 100 % |
| Partie 4 (série de contrôle) : `out_of_scope` avec la bonne raison | ≥ 9/10 |
| Réponses rejetées par les contrôles | comptées, examinées une à une |
| Temps de réponse de bout en bout | médiane et p95 rapportés |

Une génération indisponible (`generation_unavailable`, erreur de l'API Groq) compte comme un échec du
critère. La partie 1 est comptée, sans seuil : sa qualité sera mesurée par RAGAS en E3.

## 4. Protocole

- **Outil** : `RAG/experiments/recette_generation.py`. `lancer` pose les questions au pipeline réel.
  `evaluer` calcule les critères et refuse de conclure s'il manque des questions. `rejouer` et
  `diagnostiquer` travaillent hors ligne, sans aucun appel au LLM.
- **Reproductibilité** :
  - chaque enregistrement porte la version du prompt ; un changement de prompt purge les
    enregistrements antérieurs ;
  - les générations sont mises en cache sous une clé qui contient l'empreinte du prompt, le modèle,
    le fournisseur, le plafond de jetons et le message exact (donc les documents transmis) ;
  - les analyses viennent du cache de l'essai E2a ;
  - les écritures sont atomiques : un arrêt ne corrompt aucun fichier.
- **Corpus unique** : `rejouer` vérifie que l'index contient exactement les documents de la vérité
  terrain de E2a (empreinte du Gold). Il refuse de mélanger deux versions du corpus (voir §6.2).
- **Quota** : le quota quotidien gratuit de Groq interrompt `lancer`, qui reprend le lendemain là où
  il s'est arrêté.
- **Latence** : elle est mesurée de bout en bout, en reconstituant la latence d'origine de l'analyse.
  Les attentes dues à la limite de débit de Groq sont mesurées à part (`throttle_wait_ms`). La latence
  est rapportée avec et sans ces attentes.

## 5. Résultats du passage final (prompt `generation-v6`, ClinVar 2026-10)

**Provenance des chiffres.** Les 109 questions ont été posées en trois jours (12–14/10). Les 33
premières l'ont été avant les vagues de correctifs 2 et 3 des contrôles (code 751fae3). Les chiffres
officiels viennent donc du **rejeu hors ligne** (`rejouer`, sur 751fae3, sans aucun appel au LLM) :
chaque génération, relue du cache, repasse dans la chaîne de contrôles finale. Résultat : **aucun
statut ne change** (109 rejouées, 109 identiques), ce qui confirme que tous les enregistrements sont
cohérents avec le code final.

| Critère | Résultat | Seuil | Verdict |
|---|---|---|---|
| Partie 2 (identifiants) | 19/20 | 20/20 | **échec** (P2-05) |
| Partie 3 (pièges) | 9/10 | 100 % | **échec** (P3-07) |
| Partie 4, série de contrôle | 9/10 | ≥ 9/10 | **réussi** (P4-20 manqué) |
| Partie 4, série de développement (indicatif) | 9/10 | — | — (P4-10 manqué) |

Les seuils, fixés avant la recette, ne sont pas assouplis après coup.

**Répartition des statuts** (109 questions) :

| Partie | answered | partial | not_in_sources | out_of_scope | unverifiable | generation_unavailable |
|---|---|---|---|---|---|---|
| 1 (59) | 39 | 1 | 5 | — | 13 | 1 |
| 2 (20) | 19 | — | — | — | 1 | — |
| 3 (10) | — | — | 5 | 4 | 1 | — |
| 4 (20) | — | — | 2 | 18 | — | — |
| **Total** | **58** | **1** | **12** | **22** | **15** | **1** |

Le LLM de génération a été appelé 85 fois : 84 réponses, dont 15 rejetées par les contrôles (18 %),
et une génération indisponible (P1-C11, sortie inexploitable).

**Latence de bout en bout** (enregistrements d'origine, profil d'essai Groq) :

| Réponses | n | Médiane | p95 |
|---|---|---|---|
| Générées par le LLM, sans les attentes de débit Groq | 84 | 4,7 s | 9,3 s |
| Générées par le LLM, attentes comprises | 84 | 21,5 s | 40,1 s |
| Messages fixes (sans LLM de génération) | 24 | 1,6 s | 4,6 s |

Le rejeu ne mesure aucune latence (générations relues du cache) : ces chiffres viennent de
`records.json`. Ce sont les latences de gpt-oss-120b chez Groq, avec le quota gratuit, et non celles
du profil de production.

**Les deux échecs** :

- **P2-05** (« Que sait-on du variant rs334 sur HBB ? »). Le modèle a écrit « c.20A>C (p.Glu7Ala) :
  signification clinique probablement pathogène? Non, le document indique "Likely benign" ». Il a
  donc d'abord écrit une signification fausse, puis s'est corrigé dans la même phrase. Le contrôle de
  signification a rejeté la réponse : le rejet est juste, mais la question à identifiant reste sans
  réponse.
- **P3-07** (« Quels sont les variants pathogènes de BRCA 2 ? »). Le modèle a écrit les étiquettes
  internes « [D1] … [D10] » dans le texte, malgré la règle 8 du prompt. La réponse a été rejetée
  (`document_label_in_text`), alors que son contenu était exact.

**Partie 4** : P4-10 (« Quelle est la capitale du Sénégal ? ») et P4-20 (« Écris-moi un poème sur la
génétique. ») reçoivent `not_in_sources` au lieu de `out_of_scope`. La raison « other » n'a pas de
règle déterministe (seuls comptage, ACMG, fréquence et conseil clinique en ont) : le LLM tranche, et
il a choisi le mauvais statut. Le message livré (« Aucune fiche ClinVar du panel ne correspond ») est
sans danger, mais la raison est fausse.

### 5.1 Examen une à une des réponses rejetées

Chaque rejet a été examiné contre le texte complet du LLM et les fiches transmises (relus hors ligne
du cache, `data/experiments/e2b-recette/examen_rejets.json`). Cinq verdicts possibles :

- **erreur réelle** : le modèle a écrit quelque chose de faux, et le rejet l'a bloqué ;
- **faute de format** : le contenu est juste, mais le modèle a enfreint une règle du prompt, et le
  rejet est voulu par la règle ;
- **abstention à tort** : le modèle dit « pas dans les sources » alors que les fiches répondent ;
- **rejet à tort** : la réponse était juste, et c'est le contrôle lexical qui s'est trompé ;
- **rejet sévère** : la réponse est imprécise sur un point mineur.

| Question | Contrôle | Élément en cause | Verdict |
|---|---|---|---|
| P1-C12 | signification | Deux variants « probablement bénins » (c.5457C>G, c.4725C>T) présentés comme **« probablement pathogènes »** | **erreur réelle grave** (inversion de sens) |
| P1-B20 | signification | c.-43G>A dit « bénin », fiche « probablement bénin » | **erreur réelle** (imprécision) |
| P2-05 | signification | « probablement pathogène? Non… » pour un variant probablement bénin | **erreur réelle** (autocorrigée) |
| P1-C03 | texte retenu (« délétère ») | `not_in_sources`, alors que les 10 fiches STK11 transmises sont pathogènes (Peutz-Jeghers) | **abstention à tort** |
| P1-C13 | texte retenu (négation) | « aucun variant bénin », alors que les 10 fiches ATM transmises sont bénignes | **abstention à tort** |
| P1-B05 | étiquette | « (voir D2) », « (voir D3) » | faute de format |
| P1-B10 | étiquette | « [D1] » … « [D8] » en fin de ligne | faute de format |
| P1-C07 | identifiant | « (voir par ex. D1, D2…) », D1 lu comme un symbole de gène | faute de format |
| P1-C10 | étiquette | « [D1] » … « [D10] » | faute de format |
| P1-C15 | étiquette | « [D1] » … « [D10] » | faute de format |
| P3-07 | étiquette | « [D1] » … « [D10] » | faute de format |
| P1-B09 | signification | « bénignes » dans « excroissances bénignes », la paraphrase de la question reprise par le modèle | **rejet à tort** |
| P1-C20 | signification | même formule « excroissances bénignes » | **rejet à tort** |
| P1-B19 | appariement | « G6PD ZURICH (Pathogenic/Likely pathogenic) » : le variant, désigné par son nom historique sans HGVS, hérite au-delà du « ; » du variant précédent (c.1478G>A, Pathogenic). La réponse est exacte. | **rejet à tort** |
| P1-B21 | négation | « (sans mention de syndrome) » dans la phrase d'un variant probablement pathogène | **rejet à tort** (négation sans rapport) |
| P1-B03 | signification | « (Et d'autres variantes pathogènes ou probablement pathogènes listées dans ClinVar) » : renvoi général, vrai, mais non sourcé par les fiches citées | **rejet à tort** (sévère) |
| P1-C14 | appariement | phrase finale « modifications bénignes » pour une liste qui contient des « probablement bénins » | rejet sévère (imprécision mineure) |

**Bilan des 17 rejets** :

| Verdict | Nombre | Lecture |
|---|---|---|
| Erreur réelle bloquée | 3 | Dont **une inversion pathogène / bénin (C12)** : sans les contrôles, elle aurait été livrée. C'est la justification directe des contrôles déterministes. |
| Abstention à tort | 2 | Le message fixe « aucune fiche » est livré : la réponse est fausse par omission, mais sans danger. Les contrôles ne détectent pas ce cas ; c'est l'abstention à tort de E3a qui le mesure. |
| Faute de format (étiquettes D) | 6 | Le défaut le plus fréquent du modèle d'essai : la règle 8 du prompt n'est pas respectée de façon fiable. |
| Rejet à tort | 5 | C'est le coût du contrôle lexical. Il vient de deux causes : un mot de la question repris dans la réponse (« bénignes ») et la portée de l'appariement au-delà du « ; » ou d'une négation. |
| Rejet sévère | 1 | Imprécision réelle, mais mineure. |

**Ce que la recette établit.** Les contrôles ont bloqué toutes les erreurs de signification
écrites par le modèle, dont une inversion grave. En contrepartie, environ un rejet sur trois est un
rejet à tort, et le service perd près d'une réponse générée sur cinq (16 sur 85, indisponible comprise). La première cause de rejet est un modèle d'essai
qui suit mal les consignes de format. Les deux échecs de critère viennent de ce modèle, et non de la
chaîne. La recette est donc à **refaire avec le modèle de génération retenu en E3a**, avec les mêmes
questions et les mêmes seuils, avant toute mise en service. Les rejets à tort sont documentés comme
limite du contrôle lexical (README §9.11) ; les corriger demanderait de modifier le code gelé, ce qui
relève d'une décision distincte.

## 6. Historique des passages : ce que la recette a appris

La recette a été lancée trois fois. Chaque relance avait une cause identifiée et approuvée. Les
résultats intermédiaires sont archivés (`data/experiments/e2b-recette-septembre/`,
`data/experiments/e2b-recette-octobre-v5/`, non versionnés).

### 6.1 Premier passage — prompt v5, corpus ClinVar 2026-09 (08–09/10/2026)

- **Arrêt** à 95/99 questions, sur le quota Groq (la série de contrôle n'existait pas encore).
- **Statuts** : 66 `answered`, 14 `unverifiable`, 10 `not_in_sources`, 5 `out_of_scope`.
- **Défaut révélé** : P4-01 (« Combien de variants pathogènes compte BRCA2 ? ») a reçu la réponse
  « Le gène BRCA2 compte 1 variant pathogène dans ClinVar. ». Ce chiffre est faux, et il était présenté
  comme une réponse. → Des **règles hors périmètre** s'appliquent désormais avant le LLM, et la
  **série de contrôle** a été créée pour les mesurer honnêtement.
- **Défaut révélé lors de la relecture** : des inversions de sens passaient les contrôles
  (« inoffensif », « en aucun cas pathogène »). → Toute négation dans la phrase du terme de
  signification provoque désormais un rejet, et les qualificatifs hors table ClinVar sont rejetés.
- **Rejeu hors ligne** après ces correctifs : 61 `answered`, 16 `unverifiable`, 10 `out_of_scope`,
  8 `not_in_sources`. Le rejeu a aussi montré 7 rejets à tort, dus à des formules sans rapport avec la
  signification (« aucun conflit », « non sphérocytaire »…). Ces formules exactes sont désormais
  masquées.

### 6.2 Changement de corpus (11/10/2026)

Le 11/10, le pipeline a collecté **de lui-même** l'archive ClinVar d'octobre 2026, puis a réindexé
1 695 documents. Il n'y a eu aucune intervention : la mise à jour mensuelle automatique a fonctionné de
bout en bout. Le garde-fou de la recette a alors refusé de mélanger deux corpus.

**Décision** : recalculer la vérité terrain de E2a sur le Gold d'octobre et refaire toute la recette
sur un seul corpus. La vérité terrain change pour 23 questions de la partie 1, et pour aucune de la
partie 2.

### 6.3 Deuxième passage — prompt v5, corpus 2026-10 (12/10/2026) : diagnostic des rejets

- **Arrêt** à 66/109 questions, sur le quota.
- **Statuts** : 39 `answered`, 17 `unverifiable`, 5 `generation_unavailable`, 4 `not_in_sources`,
  1 `partial`.
- **Le diagnostic hors ligne** (`diagnostiquer`) a expliqué chacun des 18 rejets :

| Cause | Nombre | Lecture |
|---|---|---|
| « ClinVar *n* » dans le texte, absent des fiches | 10 | **Défaut de conception**. Les 59 numéros en cause étaient exactement les identifiants internes (AlleleID) que le code donnait aux documents transmis. Le modèle les recopiait. Ce n'est pas le Variation ID affiché par ClinVar : un lecteur serait tombé sur un autre variant. Le rejet a donc évité une erreur réelle. |
| « pas de conflit » (statut de revue) | 2 | Rejet à tort : formule non masquée. |
| Traduction libre d'un nom de maladie (« excroissances bénignes ») | 1 | Rejet **voulu** : le terme n'est pas vérifiable contre les fiches. |
| Négation réelle dans la phrase du terme de signification | 5 | Rejet **voulu** (règle prudente). |

- **Correctifs** :
  - les documents transmis portent des étiquettes neutres (D1…D10), et le code les fait correspondre
    aux vraies fiches ;
  - une étiquette écrite comme référence dans le texte est rejetée ;
  - « pas de conflit » est masqué ;
  - un terme de signification placé à l'intérieur du nom exact d'une maladie présente dans une fiche
    citée est neutralisé ;
  - la phrase d'historique, écrite par le code, désigne le variant par son nom HGVS et son Variation
    ID, et non plus par l'identifiant interne ;
  - ces changements donnent le prompt `generation-v6`.

Ces trois passages illustrent le rôle des contrôles déterministes. Ils ne se contentent pas de bloquer
une réponse : ils produisent un **motif de rejet explicable**. Ce motif a permis de trouver un défaut
de conception que l'examen d'un échantillon de réponses n'aurait pas montré.

## 7. Limites de la recette

- **Ce que les contrôles ne voient pas** : une abstention à tort (C03, C13) passe sans rejet, puisque
  le message fixe est livré. Une réponse acceptée n'est pas prouvée juste : seule la mesure de fidélité
  de E3a peut l'établir.

- **Jeu réduit** : 109 questions, écrites par une seule personne. La série de contrôle ne compte que
  10 questions : un échec de plus fait passer le score de 90 % à 80 %.
- **Modèle d'essai** : les réponses et les latences sont celles de gpt-oss-120b chez Groq. Le modèle
  de production sera choisi en E3.
- **La partie 1 n'est pas notée sur le fond** ici : seuls les rejets sont examinés. La fidélité et la
  pertinence relèvent de RAGAS (E3).
- **Les contrôles sont lexicaux** : un rejet prouve qu'un élément n'est pas vérifiable, mais une
  réponse acceptée n'est pas prouvée juste. Les limites connues sont décrites dans `RAG/README.md`
  §9.11.
- **Itérations sur les mêmes questions** : les correctifs des parties 1 à 3 ont été décidés après
  avoir vu des réponses de ces parties. Pour la partie 4, la série de contrôle corrige ce biais. Pour
  les parties 1 à 3, il est atténué par le fait que les correctifs visent des **causes** (identifiant
  interne, formules masquées exactes) et non des questions précises. La mesure RAGAS de E3 utilisera
  un jeu distinct.

## 8. Correctifs post-recette (14/10/2026) et rejeu de contrôle

À la demande de l'utilisateur, les causes des rejets à tort et des échecs identifiés au §5.1 ont été
corrigées sur une branche dédiée (`rag/e2b-correctifs`, depuis 751fae3, 6 commits). Chaque correctif
vise une **cause générale**, jamais une question précise, et il est couvert par des tests unitaires
(1434 tests verts). Il a ensuite été validé par **rejeu hors ligne** des 109 réponses de la recette,
avec les contrôles corrigés, sans aucun appel au LLM. Le prompt n'a pas changé, donc toutes les
générations sont relues du cache.

| # | Cause (§5.1) | Correctif | Réponses touchées |
|---|---|---|---|
| 1 | Étiquettes D1…Dn recopiées dans le texte | Une référence entre parenthèses ou crochets dont toutes les étiquettes sont déjà citées est **retirée** du texte livré, au lieu de faire rejeter la réponse. Une étiquette non citée, ou écrite dans la phrase (« Selon D2, … »), reste rejetée. | B05, B10, C10, P3-07 récupérées ; C07 et C15 ne sont plus rejetées pour leurs étiquettes, mais le sont pour une autre raison (voir ci-dessous) |
| 2 | « excroissances bénignes », expression reprise de la question | Un terme de signification qui fait partie d'une expression reprise mot pour mot de la question n'est pas compté, sauf s'il qualifie un variant (« variants bénins », « est bénin ») | B09, C20 |
| 3 | « (sans mention de syndrome) » | Formule ajoutée à la liste fermée des formules neutres | B21 |
| 4 | Variant désigné par son nom historique (« G6PD ZURICH ») | Le nom d'une fiche citée sans HGVS devient un identifiant de l'appariement. La règle est **plus stricte** qu'avant : une signification attribuée au mauvais nom est maintenant rejetée, alors qu'elle passait inaperçue. | B19 |
| 5 | Hors-sujet (« capitale », « poème ») laissé au LLM | Deux listes fermées pour la raison `other` : demande de création et sujets de culture générale | P4-10, P4-20 |

**Rejeu de contrôle sur les mêmes réponses** :

| Critère | 751fae3 (officiel) | Après correctifs |
|---|---|---|
| Partie 2 | 19/20 | 19/20 (P2-05, vraie erreur du modèle) |
| Partie 3 | 9/10 | **10/10** |
| Partie 4, série de contrôle | 9/10 | **10/10** |
| Partie 4, série de développement | 9/10 | 10/10 |
| Réponses `unverifiable` | 15 | **7** |

Statuts après correctifs : answered 66, out_of_scope 24, not_in_sources 10, unverifiable 7, partial 1,
generation_unavailable 1. **Aucune régression** : aucune réponse acceptée ou classée hors périmètre à
751fae3 ne change de statut. Les 10 changements vont tous dans le sens attendu (8 `unverifiable` →
`answered`, 2 `not_in_sources` → `out_of_scope`), et les 8 réponses récupérées ont été relues : leur
contenu est exact et elles ne contiennent plus d'étiquette.

**Les 9 rejets restants sont tous voulus** :

| Verdict | Questions |
|---|---|
| Erreur réelle du modèle | C12 (inversion), B20 (imprécision), P2-05 (erreur autocorrigée) |
| Abstention à tort (texte retenu, message fixe livré) | C03, C13 |
| Rejet strict défendable | B03 (renvoi général non sourcé) ; C07 (« ou probablement pathogène » absent des fiches citées) ; C14 (« modifications bénignes » pour des « probablement bénins ») ; C15 (« sans effet clinique », formule hors table reprise de la question) |

**Limites de cette validation, à dire honnêtement** :

- **Ce n'est pas une nouvelle recette.** Les correctifs ont été écrits en connaissant les réponses de
  la recette, et le rejeu ne fait que vérifier qu'ils produisent l'effet voulu, sans régression, sur ces
  mêmes réponses. Le verdict officiel reste celui du §5.
- **La série de contrôle de la partie 4 n'est plus indépendante.** La règle « demande de création » a
  été écrite après avoir vu P4-20. Pour la prochaine recette, une **nouvelle série de contrôle**,
  rédigée par l'utilisateur et jamais montrée au développement, est nécessaire.
- **La mesure indépendante viendra de E3a**, sur 70 questions jamais vues. La branche E3a a été rebasée
  sur ces correctifs : la mesure se fera avec les contrôles corrigés.
- La prochaine recette officielle se fera avec le modèle retenu en E3a, avec les mêmes questions des
  parties 1 à 3 et la nouvelle série de contrôle.

Fichiers (non versionnés) : rejeu officiel archivé dans `records_v2_751fae3.json` et
`diagnostic_rejets_751fae3.json` ; rejeu après correctifs dans `records_v2.json` et
`diagnostic_rejets.json` (`data/experiments/e2b-recette/`).
