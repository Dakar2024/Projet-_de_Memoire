# Le rôle du RAG dans le projet

*Note à l'attention du Dr Nourou SYLLA, directeur de mémoire. État du projet au 1er novembre 2026.*

---

## 1. L'essentiel

> Le pipeline de données construit une base de connaissances fiable à partir de ClinVar, MedGen,
> HPO, NCBI Gene et RefSeq. **Le RAG est la partie qui permet d'interroger cette base en français
> et d'obtenir une réponse sourcée.** Il ne crée aucune connaissance : il retrouve les bonnes
> fiches, fait rédiger une réponse à partir de ces seules fiches, puis vérifie cette réponse.

RAG signifie *Retrieval-Augmented Generation*, c'est-à-dire génération augmentée par la recherche
(Lewis et al., 2020). Ce n'est ni un modèle d'IA entraîné sur nos données, ni un simple chatbot :
c'est une **chaîne de traitement** dans laquelle le modèle de langage (LLM) n'est qu'un maillon.

## 2. Le problème qu'il résout

Un biologiste qui veut interpréter un variant a deux options, et chacune a un défaut :

| Option | Défaut |
|---|---|
| Consulter les bases directement | Interfaces techniques, en anglais, informations dispersées entre plusieurs bases |
| Interroger un LLM seul (type ChatGPT) | Réponse de mémoire, invérifiable, parfois fausse : variant inventé, signification inversée |

Le RAG réunit les avantages des deux : la facilité d'une question en français et la fiabilité
d'une réponse appuyée sur des fiches identifiées, datées et consultables.

## 3. Sa place dans le projet

```
Sources publiques (ClinVar, MedGen, HPO, NCBI Gene, RefSeq)
        │
        ▼
PIPELINE DE DONNÉES (Airflow) : raw → bronze → silver → gold
        │  environ 97 000 fiches textuelles, une par variant et par gène (18 gènes)
        ▼
─────────────────────────── RAG ───────────────────────────
  1. Indexation   chaque fiche est convertie en vecteur et stockée
  2. Recherche    retrouve les 10 fiches utiles pour la question
  3. Génération   le LLM rédige la réponse à partir de ces fiches
  4. Contrôles    le code vérifie la réponse avant de l'afficher
───────────────────────────────────────────────────────────
        │
        ▼
Le professionnel de santé : réponse en français + sources + avertissement
```

**Le pipeline et le RAG sont donc complémentaires.** Le pipeline garantit la qualité des données ;
le RAG les rend utilisables. C'est le sens de la problématique du mémoire : sans le pipeline, le
RAG citerait des données périmées ou incomplètes ; sans le RAG, le pipeline produirait une base
que seul un profil technique saurait interroger.

## 4. Un exemple

**La question :** « Que sait-on du variant rs80357498 ? »

**La fiche que le pipeline a produite pour ce variant** (extrait réel, en anglais comme la source) :

```text
Variant NM_007294.4(BRCA1):c.116G>A (p.Cys39Tyr), gene BRCA1, chromosome 17q21.31.
dbSNP rs80357498. ClinVar Variation ID 37392. Type: single nucleotide variant.
Clinical significance: Pathogenic/Likely pathogenic.
Review status: criteria provided, multiple submitters, no conflicts (21 submitters).
Last evaluated: Jul 14, 2026.
```

**Ce que fait le RAG :**

1. **Il comprend la question.** Le code repère l'identifiant `rs80357498`. Le LLM reformule la
   question en anglais, la langue des fiches.
2. **Il retrouve la fiche.** Le code, et non le LLM, interroge la base (détail au § 5).
3. **Il fait rédiger la réponse.** Le LLM reçoit la question et les fiches retrouvées, avec la
   consigne de répondre en français, à partir de ces fiches uniquement.
4. **Il vérifie.** Le code contrôle les identifiants, les citations et la signification clinique.
5. **Il répond.** Par exemple *(réponse illustrative)* :

> Le variant c.116G>A (p.Cys39Tyr) du gène BRCA1 est classé pathogène/probablement pathogène dans
> ClinVar (21 soumissionnaires, sans conflit, dernière évaluation le 14 juillet 2026).
> *Source : ClinVar, Variation ID 37392.*
> *Aide à la consultation de ClinVar ; ne remplace pas l'interprétation clinique d'un biologiste.*

## 5. Les trois apports concrets du RAG

### Trouver la bonne fiche

Une recherche par similarité seule ne suffit pas : elle ne sait pas retrouver un identifiant exact.
La recherche combine donc trois étages :

1. **Correspondance exacte** sur les identifiants de variant (rs, HGVS).
2. **Filtres** sur le gène et la signification clinique.
3. **Similarité sémantique**, avec le modèle PubMedBERT, choisi par la mesure face à BioBERT (écart
   moyen de +0,361, IC 95 % [+0,257 ; +0,469]).

Mesure d'essai du 5 octobre 2026 (89 questions, score de 0 à 1) :

| Type de question | Similarité seule | Recherche complète |
|---|---|---|
| Rôle d'un gène | 0,838 | 0,907 |
| Maladie dans un gène | 0,729 | 0,829 |
| Signification et maladie, tout le panel | 0,330 | 0,495 |
| Question avec un identifiant de variant | **0** | **1,000** |
| Questions pièges | 0,70 | 1,000 |

Les questions du type « signification et maladie » restent le point faible.

### Répondre en restant fidèle aux fiches

Le LLM peut se tromper même lorsqu'il a la bonne fiche sous les yeux. Le code vérifie donc que :

- chaque source citée fait bien partie des fiches transmises ;
- chaque identifiant écrit existe dans ces fiches ;
- chaque signification clinique est bien celle de la fiche du variant concerné.

**Une réponse qui échoue à un contrôle n'est pas affichée.** Lors de la recette (109 questions),
15 des 84 réponses générées ont ainsi été bloquées. Certaines étaient de vraies erreurs : deux
variants « probablement bénins » présentés comme « probablement pathogènes ». D'autres étaient
justes, mais mal formatées. Ce sont des refus à tort, à réduire.

### Rester à jour

ClinVar publie une nouvelle version chaque mois, et un variant peut y être reclassé. Le RAG suit
automatiquement : seules les fiches modifiées sont recalculées. Sur le cycle réel
septembre → octobre 2026, 214 variants ont changé de signification clinique et **1 695 fiches sur
97 211 (1,7 %)** ont été mises à jour. Chaque réponse indique l'archive dont elle provient.

## 6. Ce que le RAG ne fait pas

- **Il ne classe pas les variants** et ne produit pas de classification ACMG. Il restitue ce que
  dit ClinVar.
- **Il ne traite pas de données de patients ni de fichiers de séquençage** (VCF).
- **Il ne donne pas de conseil clinique.** Une question sur un traitement ou un dépistage reçoit un
  message fixe de refus, sans appel au LLM de génération.
- **Il ne remplace pas le biologiste**, qui reste seul responsable de la conclusion.
- **Il ne répond pas aux questions de comptage ni de fréquence** (« combien de variants… »). Elles
  sont refusées, car dix fiches ne permettent pas d'y répondre correctement.

Quand l'information n'est pas dans les fiches, il le dit au lieu de combler le manque.

## 7. Ce qui reste à démontrer

- **Le gain par rapport à un LLM seul (hypothèse H3) n'est pas encore mesuré.** L'outil d'évaluation
  de la fidélité (E3a, inspiré de RAGAS) est prêt, mais la campagne n'a pas encore été lancée. Le
  modèle de génération actuel reste donc provisoire.
- **La recette n'a pas atteint tous ses seuils**, fixés à l'avance : 19/20 sur les questions à
  identifiant et 9/10 sur les pièges, pour des seuils de 100 %. Les deux échecs sont des réponses
  bloquées par les contrôles, et non des erreurs livrées à l'utilisateur.
- **Les contrôles ne couvrent pas tout.** Ils reposent sur des motifs de texte : une erreur formulée
  autrement peut leur échapper. Les maladies et les phénotypes cités ne sont pas vérifiés par le code.
- **Certains noms d'usage ne sont pas reconnus**, comme « Glu6Val » pour la drépanocytose.
- **La question transite par un service LLM externe**, ce qui limite pour l'instant un usage avec
  des informations sensibles.

## 8. En une phrase

> Le pipeline construit une base de connaissances fiable ; le RAG permet à un professionnel de santé
> de l'interroger en français et d'obtenir une réponse sourcée et contrôlée, sans se substituer à
> son jugement.
