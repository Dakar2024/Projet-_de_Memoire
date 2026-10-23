# Rapport E3b — Évaluation du pipeline de données

Spec : `docs/superpowers/specs/2026-10-23-sous-projet-e3b-evaluation-pipeline-design.md` (locale).
Critères fixés **avant** les mesures. Pile isolée `genomique-e3b` (spec § 3), jamais la principale.

| Niveau | État |
|---|---|
| 6 — Restauration | ✅ conforme, **un défaut du pipeline trouvé** (D-E3b-1) |
| 5 — Comportement en panne | à faire |
| 7a — Onze fiches (utilisateur) | à faire |
| 7b — 400 variants contre l'API ClinVar | à faire |

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
| R5 | Écarts des sources non versionnées, expliqués | Seul MedGen bouge (bronze brca 45 lignes, sickle 17 ; Silver `medgen_concept` 62 = 45 + 17, colonne `conceptmeta_xml` seule : la notice servie par NCBI le jour de l'appel). NCBI Gene et RefSeq identiques. **Mais** `gold/analytique/dim_disease` change de 13 lignes **sans lien avec MedGen** : défaut D-E3b-1 | ⚠️ |
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

**Correction proposée** (non appliquée : la spec interdit de modifier le pipeline pendant E3b sans
accord) : agréger par (CUI, panel) au lieu de choisir une ligne, avec pour chaque identifiant la
plus petite valeur non nulle, et pour le nom la plus petite par ordre alphabétique. Résultat
déterministe, et aucune perte quand une seule ligne porte l'identifiant. Test d'abord : deux lignes
de même nom, l'une avec identifiants, l'autre sans, dans les deux ordres → même dimension.
Scénario rejoué après correction (R5 sur `dim_disease`).

Sorties : `data/experiments/e3b/ecarts_rejeu.txt`, `data/experiments/e3b/memoire.csv`.
