# Piste d'amélioration : réponses rédigées par gabarits, puis reformulées par le LLM

*Fiche pour la discussion du mémoire (chapitre « Limites et perspectives ») et pour la soutenance.
Rédigée le 14/10/2026 à partir d'une suggestion d'un collègue et des résultats de la recette E2b.
Cette piste **n'est pas implémentée** : l'architecture actuelle est conservée, et cette idée est
présentée comme une perspective argumentée.*

---

## 1. L'essentiel en 30 secondes

> Aujourd'hui, le code retrouve les fiches ClinVar pertinentes, puis le LLM rédige la réponse à
> partir de ces fiches, et des contrôles déterministes vérifient ce qu'il a écrit. La piste
> consiste à faire rédiger les **faits** par le code, avec des gabarits remplis à partir des champs
> structurés des fiches (signification, statut de revue, maladies, HGVS). Le LLM servirait
> seulement à rendre le texte plus fluide. Les faits seraient alors exacts par construction, le
> nombre de jetons envoyés baisserait fortement, et les fautes de recopie observées pendant la
> recette disparaîtraient. En contrepartie, la reformulation peut elle-même déformer un fait, et les
> gabarits ne savent pas répondre aux questions ouvertes. La bonne réponse serait une
> **architecture hybride**, à valider par la même mesure que E3a.

## 2. La proposition

Un collègue a suggéré de ne pas laisser le LLM construire seul la réponse à partir des documents.
À la place :

1. on retrouve les documents dans la base vectorielle (pgvector), éventuellement avec une recherche
   lexicale de type BM25 en plus des embeddings ;
2. on en extrait l'information de façon déterministe, ce qui donne une réponse juste mais
   « robotisée » ;
3. on confie au LLM (le modèle Groq actuel, par exemple) le seul soin d'embellir les phrases pour
   les rendre plus lisibles.

Arguments avancés : des réponses plus cohérentes et une économie de jetons.

## 3. Deux précisions techniques

- **Dans notre RAG, le LLM n'interroge pas la base vectorielle.** La recherche est faite par le
  code, en trois étages : correspondance exacte des identifiants (rs, HGVS), filtres par gène et par
  signification, puis similarité PubMedBERT dans pgvector. Le LLM n'intervient que pour reformuler la
  question en anglais avant la recherche, et pour rédiger la réponse après.
- **On ne « décode » pas un embedding.** Un vecteur sert à retrouver un document, pas à
  reconstituer un texte. BM25 n'est pas un embedding, mais une recherche par mots-clés. Ce que l'on
  peut faire, c'est lire les **champs structurés** des fiches retrouvées et en tirer des phrases par
  le code. C'est la forme exacte de la piste : une génération de texte à partir de données
  (*data-to-text*) par gabarits, suivie d'une reformulation.

## 4. Pourquoi l'idée est pertinente pour ce projet

- **Les données s'y prêtent.** Une fiche ClinVar du Gold est très structurée. Pour « Que sait-on
  du variant rs334 ? », une phrase construite à partir des champs `clinical_significance`,
  `review_status` et des conditions est exacte par construction.
- **Le projet applique déjà ce principe.** La phrase d'historique de classification (« Ce variant
  était classé … jusqu'en … ») est écrite par le code et non par le LLM. Les métadonnées des sources
  (Variation ID, lien ClinVar, version de l'archive) viennent aussi de la base, jamais du modèle.
- **La recette E2b confirme le besoin** (`reference/recette_e2b.md`, §5.1) :
  - les trois erreurs réelles bloquées sont des **fautes de recopie de signification**. P1-C12
    présentait deux variants « probablement bénins » comme « probablement pathogènes », P1-B20
    écrivait « bénin » au lieu de « probablement bénin », et P2-05 se trompait puis se corrigeait
    dans la même phrase ;
  - six rejets sur dix-sept sont des **fautes de format** du modèle : les étiquettes internes D1…D10
    écrites dans le texte ;
  - un gabarit ne commet aucune de ces erreurs.
- **On économise des jetons.** Le LLM ne recevrait plus les dix fiches (environ 6 000 jetons
  d'entrée par question), mais un texte court déjà rédigé (quelques centaines de jetons).

## 5. Limites de la piste

- **La reformulation déplace le risque, elle ne le supprime pas.** Un LLM qui « embellit » peut
  remplacer « probablement bénin » par « bénin », ou ajouter une connaissance qui n'est pas dans la
  fiche : c'est l'erreur de P1-B20. Il faudrait garder les contrôles déterministes sur le texte
  reformulé, et y ajouter une comparaison terme à terme avec le texte du gabarit.
- **Les gabarits ne couvrent pas tout.** Ils conviennent aux questions sur un variant précis et aux
  listes de variants pour un gène, une maladie ou une signification. Ils ne savent pas répondre à
  « Quel est le rôle de BRCA1 ? » ou « Comment BCL11A régule-t-il l'hémoglobine fœtale ? » : il faut
  alors résumer un texte libre, ce qui reste le travail d'un LLM.
- **Le côté « robotisé » ne justifie pas forcément un LLM.** Des gabarits français bien écrits, avec
  des formulations variées, peuvent suffire. La reformulation serait alors facultative.
- **BM25 répond à une autre question**, celle de la recherche et non de la rédaction. Il pourrait
  aider les questions formulées par nom de maladie, point faible mesuré en E2a (précision d'environ
  0,5 en famille C), en combinant son classement avec celui de PubMedBERT (fusion de rangs, RRF).
  Pour les identifiants, la correspondance exacte actuelle fait déjà mieux. C'est une hypothèse à
  mesurer, pas un gain acquis.

## 6. Architecture cible envisagée

| Type de question | Rédaction de la réponse |
|---|---|
| Variant précis (rs, HGVS) | Gabarit rempli par le code ; reformulation LLM facultative et contrôlée |
| Liste de variants pour un gène, une maladie, une signification | Gabarit (liste structurée) ; reformulation facultative |
| Question ouverte (rôle d'un gène, mécanisme) | LLM sur les fiches, comme aujourd'hui, avec les contrôles |

## 7. Comment on la validerait

La validation suivrait la même méthode que le reste du projet : une mesure, avec une règle fixée
d'avance.

1. Ajouter à l'évaluation E3a une configuration candidate « gabarits + reformulation contrôlée ».
2. La juger sur les mêmes 70 questions, avec le même juge et la même annotation humaine.
3. La comparer à la génération libre sur la fidélité, la pertinence, le taux de rejet, l'abstention
   à tort et le coût.
4. Mesurer BM25 à part, sur la recherche seule, sous forme d'ablation contre la recherche actuelle.

## 8. Pourquoi elle n'est pas implémentée maintenant

- L'architecture actuelle est complète, testée et documentée. Le code de génération (E2b) est figé
  pour la recette, et E3a est prêt à mesurer.
- Ajouter cette voie maintenant obligerait à modifier la spec de E3a et à écrire un nouveau module,
  pour un gain qui n'a pas encore été démontré.
- C'est un choix assumé : présenter la piste comme une **perspective argumentée**, appuyée sur des
  observations réelles de la recette, plutôt que comme une promesse non mesurée.

## 9. Phrase pour la soutenance

> « Une amélioration naturelle serait de faire rédiger les faits par le code à partir des champs
> ClinVar, ce qui les rendrait exacts par construction, et de ne confier au modèle que la mise en
> forme ou les questions ouvertes. La recette montre que les erreurs réelles du modèle sont
> justement des fautes de recopie de signification. Cette piste n'est pas implémentée : elle se
> validerait par la même mesure que le choix du modèle, et la reformulation resterait soumise aux
> contrôles, car embellir un texte peut aussi le déformer. »
