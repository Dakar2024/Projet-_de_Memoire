# Proposition d'interface — application web du RAG génomique

> Statut : **proposition**, à valider avant toute implémentation.
> Date : 2026-10-20. Base : lecture du code de la branche `qualite/clean-code`, du gabarit
> `apps/CONTEXT.template.md` et des deux starters (`api-starter-Litestar`, `react-app-starter-with-tanstack`).
> Dans ce document, **[vérifié]** signale ce qui a été lu dans le code et **[proposé]** ce qui reste un choix à valider.

---

## 1. En une phrase

L'application donne à un professionnel de la génétique **deux portes d'entrée sur les mêmes données ClinVar / MedGen / HPO** :

1. un **assistant** qui répond en français à une question sur un variant, avec ses sources ;
2. un **explorateur** (tableau de bord) qui montre les données sous forme de chiffres et de graphiques.

Le tout est précédé d'une page de présentation publique et d'un espace de connexion.

---

## 2. Ce que l'application peut consommer aujourd'hui [vérifié]

### 2.1 L'API RAG (Litestar, `RAG/src/api/app.py`)

| Route | Garde | Rôle |
|---|---|---|
| `GET /health` | aucune | le processus répond |
| `GET /ready` | clé d'API | la base vectorielle et le service d'embedding répondent |
| `POST /v1/questions` | clé d'API + JSON | répond à une question |

**Corps de la requête** (`QuestionIn`) : `{"question": "<1 à 1 000 caractères>", "trace": false}`. Tout champ inconnu est refusé.

**Réponse** (`PipelineResult.as_dict`) :

```json
{
  "status": "answered | not_in_sources | out_of_scope",
  "answer": "texte en français",
  "history": ["phrase d'historique de classification, une par source qui en a un"],
  "sources": [{
    "doc_id": "...", "gene": "BRCA1", "variant": "NM_007294.4:c.68_69del", "protein": "p.Glu23fs",
    "significance": "Pathogenic", "significance_fr": "Pathogène",
    "review_status": "reviewed by expert panel", "clinvar_variation_id": "...",
    "clinvar_url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/...", "archive": "2026-10",
    "previous_significance": "...", "previous_significance_fr": "...", "previous_until": "..."
  }],
  "disclaimer": "avertissement",
  "scope_reason": null,
  "timings_ms": {"analysis": 0, "search": 0, "generation": 0, "total": 0},
  "request_id": "..."
}
```

**Erreurs** : le corps est toujours `{"error", "message", "request_id"}`. Les codes possibles :

- `unauthorized` (401) ;
- `invalid_question` (422) ;
- `busy` (429) : la concurrence est bornée ;
- `timeout` (503) ;
- `unavailable` (503), parfois avec `Retry-After` ;
- `internal` (500).

**Conséquences pour l'interface :**

- **Trois états de réponse à dessiner, pas un seul.**
  - `answered` affiche une réponse avec ses sources.
  - `not_in_sources` signifie que ClinVar ne documente pas le point demandé. C'est une réponse honnête, pas une erreur : il faut l'afficher comme telle.
  - `out_of_scope` signifie que la question sort du périmètre (autre gène, question non génomique). L'écran doit proposer de reformuler.
- **Pas de flux progressif (streaming) ni de mémoire de conversation.** Chaque question est indépendante et la réponse arrive d'un bloc après plusieurs secondes. L'attente doit être soignée, mais **sans fausse barre de progression** : on n'a pas les étapes en temps réel. On peut en revanche afficher `timings_ms` une fois la réponse arrivée.
- **L'API est protégée par une clé et n'écoute qu'en local** : `rag-gateway` est sur `127.0.0.1:8090`. Le navigateur ne l'appelle **jamais** directement : c'est le backend `apps/` qui l'appelle et garde la clé. Cela respecte la règle du gabarit (« l'API n'est jamais exposée »).
- **La trace (`trace: true`)** contient le modèle, le fournisseur et le coût en dollars. Elle est réservée à un rôle administrateur.

### 2.2 La couche `gold/analytique` (`src/transformations/silver_to_gold_analytique.py`)

C'est un modèle en étoile au format Delta, partitionné par `panel`, stocké dans MinIO. La spec d'architecture prévoit qu'il soit **lu par DuckDB** (`delta_scan`).

| Table | Contenu utile pour l'interface |
|---|---|
| `fact_variant` | une ligne par (variant courant, gène) : signification, statut de revue, chromosome, type, mois |
| `fact_variant_disease` | pont variant × maladie (compter par maladie sans double compte) |
| `fact_reclassification` | transitions de classification : de → vers, date du changement |
| `dim_gene` | nom, description, locus, résumé NCBI |
| `dim_disease` | maladie (MedGen CUI, OMIM, Orphanet, MONDO), modes de transmission, résumé clinique |
| `dim_phenotype`, `bridge_gene_phenotype` | termes HPO (définition, synonymes) et fréquence par gène |
| `dim_clinical_significance`, `dim_review_status` | libellés et **étoiles ClinVar** (0 à 4) |
| `dim_month` | calendrier |
| `agg_variants_by_gene_significance` | **agrégat prêt** : nombre de variants par gène et par signification |
| `agg_review_status` | **agrégat prêt** : répartition des statuts de revue |
| `agg_reclassifications_by_month` | **agrégat prêt** : reclassifications par mois |

**Aucune API ne sert ces tables aujourd'hui.** C'est le backend `apps/` qui doit les exposer en lecture seule.

### 2.3 Les panels sont configurables

`PANEL_GENES = {"brca": [12 gènes], "sickle": [6 gènes]}` (`src/ingestion/config.py`). Ajouter une maladie revient à ajouter une entrée.

L'interface ne doit donc **jamais coder en dur** « cancer du sein » et « drépanocytose » : elle lit la liste des panels depuis le backend. C'est aussi l'argument d'extensibilité à mettre en avant sur la page de présentation.

---

## 3. Architecture proposée [proposé]

```
Navigateur
   │  https://<domaine>            (seul point public)
   ▼
Traefik ──► web  (TanStack Start, SSR)
   │
   └─ /api/* ──► api (Litestar apps/backend, réseau interne)
                   ├─ PostgreSQL apps   : utilisateurs, conversations, quotas, retours
                   ├─ rag-gateway        : POST /v1/questions  (clé RAG_API_KEY côté serveur)
                   └─ DuckDB en processus : delta_scan sur MinIO gold/analytique (compte lecture seule)
```

Les principes :

- **Deux bases distinctes.** La base de l'application (comptes, conversations) ne partage rien avec `rag-postgres` ni avec la base d'Airflow : c'est le moindre privilège, et une sauvegarde séparée.
- **Un compte MinIO en lecture seule**, limité au préfixe `gold/analytique`, pour DuckDB.
- **Un cache des agrégats** (TTL d'une heure, ou invalidation au mois). Les données ne changent qu'une fois par mois, au passage du DAG : inutile de relire Delta à chaque clic.
- **À vérifier dans `docker-compose.yml`** : `rag-gateway` est publié sur l'hôte, en `127.0.0.1`. Il faudra relier le conteneur `api` au réseau de la passerelle, ou ajouter un réseau dédié `apps → rag-gateway`, plutôt que de passer par l'hôte.

### 3.1 Features backend (pattern `tables / schemas / service / controller`)

| Feature | Rôle | Routes principales |
|---|---|---|
| `auth` (starter) | inscription, connexion, moi, déconnexion, mot de passe oublié | `/api/auth/*` |
| `assistant` | relaie la question au RAG, enregistre la conversation, applique le quota | `POST /api/assistant/questions`, `GET /api/assistant/conversations`, `GET /api/assistant/conversations/{id}` |
| `analytics` | lit `gold/analytique` via DuckDB | `GET /api/analytics/overview`, `/genes`, `/genes/{symbol}`, `/significance`, `/review-status`, `/reclassifications`, `/diseases` (filtres `panel`, `gene`) |
| `panels` | catalogue des panels et gènes, date de la dernière archive ClinVar | `GET /api/panels` (public, pour la page d'accueil) |
| `feedback` | « réponse utile / pas utile », avec un commentaire | `POST /api/assistant/answers/{id}/feedback` |
| `admin` (phase 2) | utilisateurs, quotas, coûts agrégés, état `/ready` | `/api/admin/*` |

**Quota par utilisateur : obligatoire.** Chaque question appelle un LLM payant (OpenRouter). Sans quota, un seul compte peut vider les crédits. La proposition : N questions par jour et par utilisateur, configurable. Le backend renvoie le reste du quota pour que l'interface l'affiche.

---

## 4. Plan du site [proposé]

```
/{lang}                      Page de présentation (publique)
/{lang}/sign-in              Connexion        ┐ écran partagé en deux
/{lang}/sign-up              Création de compte┘
/{lang}/forgot-password      Mot de passe oublié
/{lang}/assistant            Assistant (questions-réponses)        ┐
/{lang}/assistant/{id}       Une conversation enregistrée          │ espace connecté
/{lang}/explorer             Tableau de bord analytique            │ (_panel, garde d'auth)
/{lang}/explorer/genes/{sym} Fiche gène                            │
/{lang}/account              Profil, quota, préférences            ┘
/{lang}/admin                (phase 2)
```

Le français est la langue par défaut et l'anglais est déjà prévu par Lingui dans le starter. Les **documents restent en anglais** (ClinVar). L'interface est bilingue ; les réponses de l'assistant sont en français.

---

## 5. Page de présentation [proposé]

**Ton** : un produit, pas un travail universitaire. Aucune mention de soutenance, de mémoire ni d'école.

Le **disclaimer médical**, en revanche, est indispensable : un outil d'aide à l'interprétation n'est pas un outil de diagnostic. C'est aussi ce qui rassure une structure de santé.

| # | Section | Contenu |
|---|---|---|
| 1 | **Barre de navigation** | logo texte provisoire `[Nom]` · Fonctionnalités · Données · Comment ça marche · bouton **Se connecter** (et **Créer un compte** en bouton plein) · sélecteur FR/EN · thème clair/sombre |
| 2 | **Hero** | Titre : *« Interrogez les bases génomiques en langage naturel. »* Sous-titre : *« Posez une question sur un variant de l'ADN : la réponse s'appuie uniquement sur ClinVar, MedGen et HPO, sources citées. »* Deux boutons : *Commencer* / *Voir un exemple*. Visuel : une **carte de réponse animée** (question → réponse → sources), plus parlante qu'une illustration d'ADN générique. |
| 3 | **Ce que vous pouvez demander** | 3 ou 4 exemples cliquables (qui mènent à la connexion) : « rs80357906 sur BRCA1 est-il pathogène ? », « Quelle est la classification de HBB c.20A>T ? », « Ce variant a-t-il été reclassé ? » |
| 4 | **Deux outils, une seule source de vérité** | deux grandes cartes, **Assistant** et **Explorateur**, chacune avec une capture stylisée |
| 5 | **Fiable par construction** | 4 tuiles : *Sources citées* (lien ClinVar sur chaque affirmation) · *Abstention plutôt qu'invention* (le système dit « non documenté ») · *Historique des reclassifications* · *Données mises à jour chaque mois* |
| 6 | **Comment ça marche** | une frise horizontale en 4 étapes, sans jargon : *Collecte (ClinVar, MedGen, HPO, NCBI)* → *Nettoyage et versionnage* → *Indexation sémantique* → *Réponse sourcée*. Le vocabulaire médaillon (raw/bronze/silver/gold) reste en info-bulle. |
| 7 | **Les données couvertes** | une carte par panel, **chargée depuis `GET /api/panels`** : « Cancer du sein héréditaire — 12 gènes », « Drépanocytose et modificateurs de l'HbF — 6 gènes », puis une carte en pointillés *« D'autres maladies arrivent »*. Chiffres en direct : nombre de variants, date de la dernière archive ClinVar. |
| 8 | **Confidentialité** | aucune donnée patient requise · questions non transmises en clair aux journaux · fournisseurs LLM sans rétention (ZDR) |
| 9 | **Appel final + pied de page** | bouton *Créer un compte* · liens Mentions / Confidentialité / Contact · avertissement : *« Outil d'aide à l'interprétation. Ne remplace pas l'avis d'un généticien ni un compte rendu de laboratoire. »* |

---

## 6. Connexion et création de compte [proposé]

L'écran est partagé en deux sur ordinateur. Sur mobile, le panneau gauche se réduit en bandeau.

```
┌──────────────────────────────────┬──────────────────────────────────┐
│  fond vert très clair + motif     │        [Nom]                      │
│  discret (hélice en filigrane)    │   Bon retour                      │
│                                   │   ┌──────────────────────────┐   │
│  « Les variants, expliqués        │   │ G  Continuer avec Google │   │
│    avec leurs sources. »          │   └──────────────────────────┘   │
│                                   │   ───────── ou ─────────          │
│  ┌──────────┐ ┌──────────┐        │   E-mail     [              ]    │
│  │ Assistant│ │Explorateur│       │   Mot de passe [            ] 👁  │
│  │ Questions│ │ Chiffres  │       │   Mot de passe oublié ?           │
│  │ sourcées │ │ par gène  │       │   [      Se connecter        ]    │
│  └──────────┘ └──────────┘        │                                   │
│  ┌──────────┐ ┌──────────┐        │   Pas de compte ? Créer un compte │
│  │Historique│ │ 18 gènes, │       │                                   │
│  │reclassif.│ │ 2 maladies│       │                                   │
│  └──────────┘ └──────────┘        │                                   │
│  (chiffres lus depuis /api/panels)│   Conditions · Confidentialité    │
└──────────────────────────────────┴──────────────────────────────────┘
```

- Les quatre tuiles de gauche sont les « petits dossiers » demandés. Leurs chiffres viennent de l'API, pas du code.
- Le formulaire de création de compte contient : nom, e-mail, mot de passe avec indicateur de robustesse, **profil** (généticien, biologiste, chercheur, étudiant, autre) et une case d'acceptation des conditions qui rappelle le disclaimer médical. Le profil sert aux statistiques d'usage et, plus tard, à adapter les réponses.
- Validation en direct, messages d'erreur sous chaque champ, champs accessibles au clavier.

### 6.1 Connexion Google : recommandation

**Oui, mais en phase 2, et pas comme seule méthode.**

| Pour | Contre |
|---|---|
| inscription en un clic : moins d'abandon | le starter n'a **pas** d'OAuth : c'est du travail en plus (flux *authorization code* + PKCE côté serveur, liaison de comptes, gestion de l'e-mail déjà inscrit) |
| e-mail déjà vérifié par Google | les établissements de santé utilisent souvent **Microsoft 365 / Entra ID** plutôt que Google |
| pas de mot de passe à stocker pour ces comptes | dépendance à un tiers, mentions RGPD à ajouter |

**Ordre conseillé :**

1. E-mail + mot de passe, avec **vérification de l'e-mail** (le starter a déjà l'envoi de courriels).
2. Google, puis Microsoft, via une bibliothèque OIDC éprouvée côté backend. La bibliothèque et sa version sont à vérifier sur PyPI au moment de l'implémenter, conformément à `rules.md`.

**Option à décider** : faut-il **valider manuellement les nouveaux comptes** (liste d'attente) ? Vu le coût par question, c'est probablement utile au début.

---

## 7. Espace connecté

La mise en page commune : une **barre latérale repliable** (Assistant · Explorateur · Historique · Compte), un en-tête avec le sélecteur de panel global (*Tous* / *Cancer du sein* / *Drépanocytose*…) et l'avatar.

### 7.1 Assistant

```
┌ Historique ─────────┬──────────────────────────────────────────────┐
│ + Nouvelle question  │  Question : rs80357906 sur BRCA1 est-il ...   │
│ Aujourd'hui          │  ┌──────────────────────────────────────────┐ │
│  · rs80357906 BRCA1  │  │ ✓ Réponse                                 │ │
│  · HBB c.20A>T       │  │ Ce variant est classé pathogène [1] ...   │ │
│ Hier                 │  │ ⟲ Reclassé : « VUS » jusqu'au 2019-03 [1] │ │
│  · ...               │  │ ⚠ Avertissement                           │ │
│                      │  └──────────────────────────────────────────┘ │
│                      │  Sources                                      │
│                      │  ┌[1] BRCA1 · c.5266dup · Pathogène ★★★ ↗┐  │
│                      │  └──────────────────────────────────────────┘ │
│                      │  👍 👎   Copier   ⏱ 6,2 s                     │
│                      │ ┌────────────────────────────────────────────┐│
│                      │ │ Posez une question sur un variant…   0/1000 ││
│                      │ └────────────────────────────────────────────┘│
│                      │  Questions restantes aujourd'hui : 18/20      │
└──────────────────────┴──────────────────────────────────────────────┘
```

- **Carte de source** : gène, HGVS (police à chasse fixe), signification en français, **badge couleur** (pathogène, probablement pathogène, VUS, bénin…) et **étoiles de revue**. Un clic ouvre ClinVar dans un nouvel onglet. Le numéro `[n]` dans le texte renvoie à la carte, qui se met en surbrillance au survol.
- **Trois rendus selon `status`** :
  - `answered` : rendu normal, en vert ;
  - `not_in_sources` : encadré neutre « ClinVar ne documente pas ce point », avec les sources consultées ;
  - `out_of_scope` : encadré informatif qui rappelle le périmètre (liste des panels) et propose des exemples.
- **Attente** : une animation sobre (squelette de carte et texte « Recherche dans ClinVar… ») et un bouton *Annuler* côté interface. L'annulation n'arrête pas le calcul serveur : le dire dans l'info-bulle.
- **Erreurs** : `busy` et `unavailable` déclenchent un toast avec *Réessayer* (et le délai `Retry-After` s'il est fourni) ; `timeout` affiche un message dédié ; le quota atteint affiche un message et l'heure de remise à zéro.
- **Limite d'avertissement** : le champ de saisie rappelle *« Ne saisissez aucune donnée permettant d'identifier un patient. »* Le backend `apps/` va stocker les conversations : c'est potentiellement de la **donnée de santé** au sens du RGPD. À décider : durée de conservation, droit à l'effacement, et éventuel mode « sans historique ».
- **Mode trace** (admin seulement) : panneau dépliable avec le modèle, le fournisseur, le coût et les durées par étape.

### 7.2 Explorateur (BI sur `gold/analytique`)

| Bloc | Source | Visualisation |
|---|---|---|
| Chiffres clés : variants, gènes, maladies, reclassifications sur 12 mois, dernière archive | `fact_variant`, `dim_*`, `fact_reclassification` | 4 ou 5 tuiles |
| Variants par gène et par signification | `agg_variants_by_gene_significance` | barres horizontales empilées, une couleur par signification (même code couleur que les badges de l'assistant) |
| Qualité des preuves | `agg_review_status` × `dim_review_status.stars` | barres par nombre d'étoiles (0 à 4) |
| Reclassifications dans le temps | `agg_reclassifications_by_month` | courbe ou aire mensuelle, filtrable par gène |
| Flux de reclassification (ex. VUS → bénin) | `fact_reclassification` | tableau des transitions les plus fréquentes, avec diagramme de Sankey en option (phase 2) |
| Maladies associées | `fact_variant_disease` × `dim_disease` | tableau triable (CUI, OMIM, Orphanet, modes de transmission) |
| Phénotypes HPO par gène | `bridge_gene_phenotype` × `dim_phenotype` | liste avec fréquence et définition au survol |

- **Fiche gène** (`/explorer/genes/{symbol}`) : résumé NCBI, locus, graphiques filtrés et un bouton **« Poser une question sur ce gène »**, qui pré-remplit l'assistant. C'est le pont entre les deux outils.
- **Filtres** : le panel global, puis gène, signification et période. L'état est conservé dans l'URL (search params de TanStack Router), pour qu'une vue soit partageable.
- **Export CSV** de chaque tableau (phase 2).

---

## 8. Identité visuelle [proposé]

### 8.1 Couleurs (« vert léger »)

Le vert sert d'**accent**, pas de fond partout. Le bleu est réservé aux liens et aux informations, pour rappeler l'hésitation bleu/vert.

| Jeton | Clair | Sombre | Usage |
|---|---|---|---|
| `--primary` | `#2E9E6B` | `#4CC38A` | boutons, accents |
| `--primary-strong` | `#1E7550` | `#7AD9A8` | texte sur fond clair (contraste AA) |
| `--primary-soft` | `#E8F6EE` | `#12261C` | fonds de section, panneau gauche de la connexion |
| `--accent-info` | `#2B7A9B` | `#5FB3D6` | liens, infos |
| `--background` | `#FAFCFB` | `#0B1210` | fond de page |
| `--foreground` | `#0F1F18` | `#E6EFEA` | texte |

**Couleurs sémantiques des significations**, cohérentes partout (badges et graphiques) : pathogène en rouge, probablement pathogène en orange, VUS en ambre ou gris, probablement bénin en vert clair, bénin en vert.

**À valider avec un outil de contraste** (≥ 4,5:1 pour le texte) avant de figer. Le vert `#2E9E6B` sur blanc **ne suffit pas pour du petit texte** : c'est pour cela qu'il existe un `--primary-strong`.

### 8.2 Typographie et composants

- Texte : **Inter** ou **Geist**. HGVS et identifiants : une police à chasse fixe (**JetBrains Mono** ou **Geist Mono**).
- Composants : **shadcn/ui** (déjà dans le starter, Tailwind v4) :
  - Sidebar, Card, Badge, Tabs, Command (palette de recherche ⌘K), Sheet, Skeleton, Tooltip, Data Table ;
  - pour l'affichage des données : **shadcn Charts** (sur Recharts), même thème que le reste ;
  - **TanStack Table** pour les tableaux et **TanStack Form** (ou react-hook-form + zod) pour les formulaires ;
  - **Motion** pour les animations de la page d'accueil, **lucide** pour les icônes ;
  - **sonner** pour les toasts et **next-themes** pour le thème clair/sombre (déjà dans le starter).
- **Toutes les versions sont à vérifier** sur npm et la documentation officielle au moment de les épingler (`rules.md`). TanStack Start était encore en *release candidate* d'après les sources trouvées (mi-2026). Ton starter l'utilise déjà, mais il faudra noter ce risque dans `reference/`.

---

## 9. Sites à visiter pour s'inspirer

Je ne les ai **pas tous parcourus dans cette session**. Pour chacun, voici ce que je te conseille d'y regarder.

**Même domaine (génomique, IA médicale, réponses sourcées)**

- **Franklin by Genoox** — franklin.genoox.com : recherche de variant, fiche variant, classification ACMG. C'est le plus proche de ton produit, organisé en *Search / Knowledge Base / My Cases*.
- **Mastermind (Genomenon)** — genomenon.com/mastermind : moteur de recherche de variants qui intègre ClinVar.
- **OpenEvidence** — openevidence.com : IA médicale qui répond avec des citations. Très bon modèle pour l'assistant.
- **Consensus** — consensus.app et **Elicit** — elicit.com : réponses scientifiques sourcées, cartes de sources.
- **Perplexity** — perplexity.ai : la référence de l'affichage « réponse + sources numérotées ».
- **ClinVar** et **gnomAD browser** (gnomad.broadinstitute.org) : moins beaux, mais ce sont les références que tes utilisateurs connaissent.

**Qualité visuelle SaaS (pages d'accueil, connexion, tableaux de bord)**

- **Linear** (linear.app) : page d'accueil soignée, animations sobres.
- **Vercel** (vercel.com) et **Supabase** (supabase.com) : sections « comment ça marche », mode sombre.
- **Clerk** (clerk.com) : écrans de connexion modernes, bouton Google.
- **Benchling** (benchling.com) : SaaS biotech, ton professionnel.
- **Tremor** (tremor.so) et les blocs **shadcn/ui** (ui.shadcn.com/blocks) : tableaux de bord et écrans de connexion en deux colonnes prêts à adapter.

**Galeries**

- Lapa Ninja, collection verte : https://www.lapa.ninja/color/green
- SaaS UI : https://www.saasui.design/best-saas-landing-page-inspiration
- Sites biotech 2026 : https://www.3mediaweb.com/blog/best-biotech-website-designs/
- Modèle « Nura Health », santé, vert mousse sur fond sombre : https://superdesign.dev/library/nura-health-landing-page

---

## 10. Découpage proposé

| Phase | Contenu |
|---|---|
| **1 — Socle** | renommage des dossiers `apps/Frontend ` et `apps/backend ` (espace final dans le nom) ; compose `apps` (api, web, base apps) ; auth e-mail/mot de passe ; mise en page de l'espace connecté |
| **2 — Assistant** | feature `assistant` (relais vers `rag-gateway`, quota, conversations) ; page Assistant avec les trois états et les cartes de sources |
| **3 — Explorateur** | feature `analytics` (DuckDB + cache) ; tableau de bord et fiche gène |
| **4 — Vitrine** | page de présentation et `GET /api/panels` public ; connexion en deux colonnes finalisée |
| **5 — Compléments** | Google/Microsoft, retours 👍/👎, admin et coûts, export CSV, Sankey |

La phase 4 peut passer avant la phase 2 si tu veux d'abord montrer la vitrine.

---

## 11. Risques et points à trancher

1. **Écart avec la spec** : la spec d'architecture (§ « Outil analytique ») annonce **Streamlit**, alors que l'application part sur TanStack Start + Litestar. Il faut amender la spec et justifier le choix dans `reference/` : authentification, séparation front/back, rendu produit, réutilisation de ton gabarit standard.
2. **Coût LLM** : un quota par utilisateur, et peut-être une validation des comptes.
3. **Données de santé** : conservation des conversations, RGPD, mention « aucune donnée patient ».
4. **Latence de plusieurs secondes** sans flux progressif. Ajouter du streaming à l'API RAG serait une évolution du RAG (E2b gelé, contrôles déterministes faits *avant* livraison) : non recommandé pour l'instant.
5. **Le modèle de génération n'est pas encore figé** (mesure E3a en attente). L'interface ne doit pas afficher de nom de modèle en dur.
6. **Maturité de TanStack Start** (*release candidate*) : risque de changements cassants.
7. **Réseau** : le raccordement `api` → `rag-gateway` est à concevoir dans le compose (voir § 3).

### Questions ouvertes pour toi

- Nom du produit (même provisoire) pour le logo texte ?
- Inscription libre, ou validation par un administrateur ?
- Conserver l'historique des conversations (et combien de temps) ?
- Le lien de l'application qui t'inspire, pour ajuster la proposition.
