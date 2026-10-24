# Rapport E3b — Évaluation du pipeline de données

Spec : `docs/superpowers/specs/2026-10-23-sous-projet-e3b-evaluation-pipeline-design.md` (locale).
Critères fixés **avant** les mesures. Pile isolée `genomique-e3b` (spec § 3), jamais la principale.

| Niveau | État |
|---|---|
| 6 — Restauration | ✅ conforme ; un défaut du pipeline trouvé (D-E3b-1), **corrigé et revérifié** |
| 5 — Comportement en panne | ✅ six scénarios joués ; deux défauts trouvés (D-E3b-2 corrigé, D-E3b-3 à corriger), une réserve (O-E3b-2) |
| 7a — Onze fiches (utilisateur) | à faire |
| 7b — 400 variants contre l'API ClinVar | à faire |

---

## Niveau 5 — Comportement en panne (23 et 24/10/2026)

Pile isolée, restaurée au niveau 6. **Scénarios reformulés sur le mois en cours** : le 24/10/2026,
l'utilisateur a fixé la règle « le pipeline ne traite que le mois en cours, jamais un mois passé »
(commit f597ec0). P3 ne vise donc plus 2019 mais octobre avec `force`, P6 ne vise plus un
`bronze_to_silver` hors ordre mais le refus en amont. Mails reçus : ceux de la pile isolée, même
`ALERT_EMAIL`.

| # | Scénario | Provocation | Observé | Verdict |
|---|---|---|---|---|
| P1 | Conteneur tué en plein run | `docker kill` du scheduler isolé à 12:01:27 pendant `bronze_to_silver` (brca), redémarré à 12:02:40 | Les deux tâches en cours (`bronze_to_silver` brca, `ingest_refseq` sickle) marquées en échec à 12:02:15, réussies au 2ᵉ essai ; les deux runs vont au bout. Chaque table instantanée prend exactement 2 versions (une par panel, comme un run normal) : l'essai tué n'a rien commité. `clinvar_variant` reste v1, `gold/rag/documents` inchangé (R4). Deux mails de succès, aucun mail d'échec | ✅ |
| P2 | Disque saturé | Scheduler isolé avec un tmpfs de 1 Gio sur `data/external`, acquisition d'octobre `force` | « espace disque insuffisant dans /opt/projet/data/external : 1,0 Gio libres pour 2,0 Gio requis », **avant tout téléchargement** ; mais **4 essais en 15 min** au lieu d'un échec immédiat ; aucun événement d'Asset | ⚠️ D-E3b-3 |
| P3 | Source indisponible | Scheduler isolé derrière un proxy fermé (`HTTPS_PROXY=http://127.0.0.1:9`), archive retirée du cache, acquisition d'octobre `force` | ClinVar : `ProxyError` explicite, 4 essais en 15 min, mail d'échec « après 4 essais » ; aucun événement d'Asset ; aucun run de panel. HPO réussit sans réseau : un rejeu relit la release épinglée dans le manifest du mois (`v2026-09-01`) et le fichier en cache, voulu | ✅ |
| P4 | Archive tronquée | Bronze ClinVar d'octobre réécrit avec une ligne sur deux (9 223 698 → 4 611 849), panel brca sur octobre | `quality_check_silver` : « 42722 variant(s) courant(s) sur 93615 absent(s) de l'instantané du mois, soit 46 % — au-delà du seuil de 5 % » ; Gold non construit (versions inchangées), rien d'indexé, pas de mail de succès. Mais 4 essais du contrôle (D-E3b-3) et Silver instantané réécrit avec les données tronquées (O-E3b-2) | ✅ réserve |
| P5 | Double déclenchement | Trigger manuel sans date, octobre déjà publié | Mois résolu `2026-10-01` depuis l'heure de départ ; 6 tâches sautées par `skip_if_already_published` ; aucun événement d'Asset, aucun run de panel (7 s) | ✅ |
| P6 | Mois passé | `--logical-date 2026-09-10` sur l'acquisition ; `sources_date 2026-09-01` sur brca | Les deux refusés au 1er essai, 4 s : « … hors du mois en cours (2026-10) : le pipeline ne traite que le mois en cours » ; aucune ingestion. Avant la règle (23/10) : `bronze_to_silver` des deux panels refusait septembre (« contient déjà le mois »), 24 versions Delta inchangées — la garde reste en filet | ✅ |

### Défaut D-E3b-2 — panel lancé sur un mois sans sources partagées (corrigé)

**Observé le 23/10** : un run de panel sur un mois sans acquisition échouait dans `bronze_to_silver`
sur un `NoSuchKey` brut, après les ingestions NCBI et trois relances. **Corrigé** (f597ec0) :
`resolve_sources_date` vérifie d'abord que le bronze ClinVar et HPO du mois est complet, et échoue
sans relance (« lancer d'abord dag_acquisition_sources pour ce mois »).

### Défaut D-E3b-3 — erreurs permanentes relancées

**Observé** (P2, P4, et le 24/10 à 01:24 quand le disque C: était plein) : `ensure_free_space`
lève une `ConfigurationError` documentée « non relancée », et `quality_check_silver` une
`SilverQualityError` ; aucune des tâches qui les appellent (`download_clinvar_bulk`,
`download_hpo_files`, `quality_check_silver`, et de même `quality_check_gold`) ne les convertit en
`AirflowFailException`. Chaque relance refait le même constat : 15 min perdues, et le mail d'échec
dit « après 4 essais, erreur peut-être passagère » au lieu de « corriger la cause ».

### Observation O-E3b-1 — run manuel avant `start_date`

Le 23/10, `--logical-date 2019-01-10` donnait un run « réussi » sans aucune tâche : Airflow ne crée
pas de tâche avant le `start_date` du DAG (2026-01-01). Sans effet sur les données (rien n'est
ingéré, conforme à la règle du mois en cours), mais sans message.

### Observation O-E3b-2 — le Silver n'est pas protégé par son propre contrôle

Le contrôle Silver bloque le Gold, pas le Silver : `bronze_to_silver` a déjà remplacé les tables
instantanées du panel par les données tronquées (v7 → v8). L'application et le RAG lisent le Gold,
resté sain ; le Silver reste faux jusqu'au prochain run correct (`procedure_reprise.md` § 5.1 :
réacquérir le mois avec `force`).

---

## Niveau 6 — Restauration (23/10/2026)

### Déroulé

| Étape | Heure (UTC) | Détail |
|---|---|---|
| Copie | 15:01 | `~/sauvegardes-genomique/2026-10-23-1501` ; la pile principale n'a rien exécuté depuis (dernier run terminé à 13:38), une copie plus fraîche aurait été identique |
| Restauration | — | `scripts/restaurer.sh --pile genomique-e3b`, 2 min 16, sur une pile isolée démarrée vide |
| Fidélité | — | `scripts/comparer_piles.sh` : conforme, 1 min |
| Pile principale arrêtée | 19:06:00 | D7 : mesures sans contention |
| Rejeu forcé d'octobre | 19:06:29 | `--logical-date 2026-10-20 --conf '{"force": true}'` |
| Fin des deux panels | 19:16:54 | sickle en dernier |
| Pile principale redémarrée | après les relevés | 12 services sains |

### Critères

| # | Critère | Mesuré | Verdict |
|---|---|---|---|
| R1 | Restauration fidèle | Base Airflow (10 runs, 83 tâches, empreintes), base RAG (97 210 documents, vecteurs, index, droits, 10 plus proches voisins), 236 objets octet pour octet, 24 tables Delta relues | ✅ |
| R2 | Le pipeline tourne sur la pile restaurée | Acquisition 2 min 15, brca 5 min 50, sickle 8 min 09 ; toutes les tâches au premier essai ; aucun e-mail d'échec | ✅ |
| R3 | Le rejeu est vu comme un rejeu | Un seul événement d'Asset nouveau (n° 3, 19:08:44) ; `skip_if_already_published` laisse passer grâce à `force` ; `notify_catch_up` sauté (run manuel) | ✅ |
| R4 | Sources versionnées identiques | Bronze `clinvar` (9,2 M lignes) et `hpo` identiques hors colonnes techniques ; `silver/clinvar_variant` **v1 → v1**, aucune nouvelle version | ✅ |
| R5 | Écarts des sources non versionnées, expliqués | Seul MedGen bouge (bronze brca 45 lignes, sickle 17 ; Silver `medgen_concept` 62 = 45 + 17, colonne `conceptmeta_xml` seule : la notice servie par NCBI le jour de l'appel). NCBI Gene et RefSeq identiques. **Mais** `gold/analytique/dim_disease` change de 13 lignes **sans lien avec MedGen** : défaut D-E3b-1 | ✅ après correction de D-E3b-1 |
| R6 | Gold et index suivent | `gold/rag/documents` **v1 → v1** (aucune écriture) ; indexation : 0 à vectoriser, 0 à supprimer, 93 627 + 3 583 inchangés, canari 1,000000 | ✅ |
| R7 | Volumes (< 5 % de la référence d'octobre) | `clinvar_variant` 97 192 (93 615 brca, 3 577 sickle) : 0 % ; `clinvar_variant_disease` 171 141 ; `gold/rag/documents` 97 210 | ✅ |
| R8 | Ressources | Pic mémoire du scheduler **1 022 Mio** (114 relevés à 5 s, pic à 19:08:35, pendant `raw_to_bronze_shared`), seuil 2,5 Gio ; durées dans les références du protocole (§ 9) | ✅ |

Durées comparées au § 9 du protocole (secondes) :

| Tâche | Référence | brca | sickle |
|---|---|---|---|
| `bronze_to_silver` | 10 (brca), 5 (sickle) | 8 | 6 |
| `silver_to_gold_rag` | 15 (brca) | 6 | 2 |
| `silver_to_gold_analytique` | 3 (brca) | 3 | 3 |
| `quality_check_gold` | 1 | 2 | 2 |
| Panel complet | 8 à 12 min | 5 min 50 | 8 min 09 |

`ingest_medgen` domine (260 s brca, 130 s sickle) : appels NCBI à débit limité, pool à un créneau.

**Réserve sur R8** : un relevé toutes les 5 s peut manquer un pic bref. Le protocole citait 2 Go mesurés
sur la conversion ClinVar ; la valeur relevée ici est deux fois plus basse. Elle reste une borne
inférieure du vrai pic.

### Défaut D-E3b-1 — `dim_disease` non déterministe, avec perte d'identifiants

**Observé** : sur le rejeu, 13 CUI de `gold/analytique/dim_disease` changent d'identifiants OMIM
(9), Orphanet (5) ou MONDO (11). Exemple : `C0024623` « Gastric cancer » avait OMIM 613659 et
MONDO:0001056, il n'en a plus aucun après le rejeu.

**Cause** (code, puis données) : ces identifiants viennent de `phenotypeids` de ClinVar, source
versionnée dont le bronze est identique. Dans `clinvar_variant_disease`, 17 des 19 couples
(CUI, panel) concernés ont **plusieurs jeux d'identifiants sous le même nom de maladie** : pour
`C0024623`, une ligne porte OMIM et MONDO, une autre aucun. `silver_to_gold_analytique` trie par
`disease_name` puis garde la première ligne par CUI : entre lignes de même nom, le choix dépend de
l'ordre des lignes, que `_build_clinvar_variant_disease` ne garantit pas (`unique(keep="first")`
sans `maintain_order`). Le commentaire du code (« stable d'un run à l'autre ») est faux dans ce cas.

**Conséquences** : un rejeu peut remplacer des identifiants réels par des valeurs nulles, sans
erreur ni contrôle qui le signale ; deux runs sur les mêmes données ne donnent pas le même Gold
analytique. Le Gold RAG n'est pas touché (`documents` identique).

**Correction** (23/10/2026, avec l'accord de l'utilisateur) : `dim_disease` agrège par (CUI, panel)
au lieu de garder une ligne. Le nom retenu est le premier non nul par ordre alphabétique (un nom nul
passait devant au tri) ; les identifiants sont réunis **entre les seules lignes de ce nom**, plus
petite valeur non nulle : jamais l'identifiant d'une maladie sous le nom d'une autre.

Tests d'abord, rouges sur l'ancien code : le cas « Gastric cancer » dans les deux ordres ; vingt
permutations des lignes d'entrée donnent la même dimension ; pas de mélange de noms ; nom réel
préféré à un nom nul ; CUI aux noms tous nuls conservé.

**Revérifié sur les données réelles** (Silver rejoué de la pile isolée, `silver_to_gold_analytique`
lancé deux fois sur les deux panels) :

| Contrôle | Résultat |
|---|---|
| Deux passes successives | `dim_disease` identique |
| Contre la copie d'avant le rejeu (ancien code, run du 21/10) | 442 CUI, aucun disparu, aucun nom changé |
| Identifiants perdus ou modifiés | 0 |
| Identifiants **récupérés** (déjà perdus par le run du 21/10) | OMIM 8, Orphanet 7, MONDO 18 |
| `C0024623` « Gastric cancer » | OMIM 613659, MONDO:0001056, dans les deux panels |

Le Gold analytique de la pile principale garde l'ancienne dimension jusqu'au prochain run de panel.

Sorties : `data/experiments/e3b/ecarts_rejeu.txt`, `data/experiments/e3b/memoire.csv`.
