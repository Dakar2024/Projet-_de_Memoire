# Sous-projet C — `bronze → silver` en Polars et Delta — Design

**Date :** 2026-09-16
**Statut :** validé par l'utilisateur, en attente de relecture de ce document
**Périmètre :** sous-projet C de `docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md` (§7)

---

## 1. Objet

Ce document conçoit l'implémentation de `bronze_to_silver()` (stub documenté,
`src/transformations/bronze_to_silver.py`) et de `quality_check_silver()` (aujourd'hui une
tâche du DAG qui lève directement, sans fonction importable dans `src/` — cette absence est
elle-même corrigée par ce sous-projet, pour respecter la règle non négociable « la logique
vit dans `src/`, Airflow n'appelle que des fonctions »). Il ne revient sur aucune décision
déjà prise par la spec du 15/09 — neuf tables, partition `panel`, historique SCD2 sur ClinVar,
règles de domaine du §5 — il les met en œuvre.

**Rappel du contrat (spec du 15/09, §3 et §5), non renégocié ici :**
- Typage, filtre panel, filtre GRCh38, dédoublonnage `#AlleleID`, éclatement des lignes
  multi-gènes, parsing du XML MedGen, normalisation HGVS via RefSeq, historique des
  reclassifications. Ne calcule jamais d'agrégat (rôle du Gold).
- Les variants bénins ne sont **jamais** filtrés : la signification clinique est un attribut.
- Les identifiants (HGVS, accessions, symboles de gènes) ne sont **jamais** normalisés en
  casse.
- `RS# (dbSNP)` est un entier ; `-1` quand absent.

**Signature déjà figée par le sous-projet A**, consommée par `dag_genomic_pipeline.py` :

```python
def bronze_to_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None
```

Un seul appel par run de panel — contrairement à `raw_to_bronze`, qui reçoit une liste de
sources, `bronze_to_silver` lit en interne tout ce dont il a besoin : les bronze **partagés**
(`clinvar`, `hpo`, sans suffixe panel) filtrés au panel courant, et les bronze **du panel**
(`ncbi_gene`, `refseq`, `medgen`, `hpo_terms`).

---

## 2. Emplacement physique et partitionnement

Rupture avec le modèle raw/bronze : `silver/<entité>/` est une **table Delta unique**,
partagée entre les deux panels, partitionnée en interne par la colonne `panel` — pas un arbre
de répertoires `dt=/panel=` par run. Un run sur `panel="brca"` ne touche jamais les lignes où
`panel="sickle"`.

- Écriture des 8 tables sans historique : `write_deltalake(uri, df, mode="overwrite",
  partition_by=["panel"], predicate="panel = '<panel>'")` (ou équivalent scindant l'overwrite
  à la seule partition du panel courant) — jamais un overwrite de la table entière.
- Écriture de `clinvar_variant` : `MERGE`, décrit au §4.

**Nouvelle dépendance** : `deltalake` (delta-rs), non ajoutée par le sous-projet A (aucune
tâche n'écrivait encore de table Delta). À épingler dans `requirements.txt` à la version
validée au moment du plan d'implémentation — l'API exacte de `merge()`/`write_deltalake()`
sera vérifiée à la main à ce moment-là, comme les appels Polars l'ont été pour le sous-projet
B, plutôt que supposée ici.

---

## 3. Les neuf tables

| Table | Source(s) bronze | Traitement | Clé |
|---|---|---|---|
| `clinvar_variant` | `clinvar` (partagé, filtré au panel via `clinvar_variant_gene`) | Filtre `assembly == "GRCh38"`, dédoublonnage sur `alleleid`, `rs_dbsnp` → `Int64` (`-1` si absent), parsing `name` → `refseq_accession`/`refseq_version`/`hgvs_c`/`hgvs_p`, jointure `refseq_transcript` → `refseq_accession_known`, historique SCD2 | `alleleid` |
| `clinvar_variant_gene` | `clinvar` (même filtre) | Éclatement de `genesymbol` sur `;` → une ligne par (variant, gène). C'est cette table qui détermine quelles lignes `clinvar_variant` appartiennent au panel (jointure sur `alleleid`) | (`alleleid`, `gene_symbol`) |
| `ncbi_gene` | `ncbi_gene` (panel) | Parse `esummary_json` → `name`, `description`, `maplocation`, `summary`, `chromosome`... | `gene_symbol` |
| `refseq_transcript` | `refseq` (panel) | Parse `transcripts_json`, éclate la liste (une ligne par transcrit), `accessionversion` (`"NM_007294.4"`) → `accession` + `version` | (`gene_symbol`, `accession`, `version`) |
| `medgen_concept` | `medgen` (panel) | `ingestion.medgen.parse_medgen_conceptmeta()` **réutilisée telle quelle** (déjà testée) → champs singuliers + XML brut conservé (`conceptmeta_xml`), source de vérité | `cui` |
| `medgen_mim` | `medgen` (panel) | Même parsing, éclate `mim_numbers` | (`cui`, `mim_number`) |
| `medgen_inheritance` | `medgen` (panel) | Même parsing, éclate `modes_inheritance` | (`cui`, `mode_inheritance`) |
| `hpo_gene_phenotype` | `hpo` (partagé, filtré au panel) | Filtre `gene_symbol` ∈ gènes du panel, typage | (`gene_symbol`, `hpo_id`) |
| `hpo_term` | `hpo_terms` (panel) | Parse `details_json` → `definition`, `synonyms`, `xrefs` | `hpo_id` |

**Cas particulier — CUI MedGen non résolu.** Un enregistrement bronze `{"cui": "...",
"esummary_json": "{}"}` garde sa ligne dans `medgen_concept` (champs vides plutôt
qu'absents) et n'explose aucune ligne dans `medgen_mim`/`medgen_inheritance` (listes vides).
Jamais supprimé, jamais une erreur — cohérent avec le traitement déjà réservé à ce cas en
raw/bronze.

**`Name` ClinVar au format HGVS irrégulier.** La ligne est conservée, `name` brut toujours
préservé ; les colonnes structurées (`refseq_accession`, `hgvs_c`, `hgvs_p`) restent nulles
plutôt que de faire échouer la conversion pour une forme atypique.

---

## 4. Historique des reclassifications (`clinvar_variant`)

Schéma SCD2 : `valid_from`, `valid_to` (nullable), `is_current` (bool), en plus des colonnes
métier.

```
alleleid | clinical_significance          | valid_from | valid_to   | is_current
45948    | Pathogenic                     | 2026-08-01 | 2026-09-01 | false
45948    | Pathogenic/Likely pathogenic   | 2026-09-01 | null       | true
```

- État actuel : `WHERE is_current`.
- État à une date passée : `WHERE valid_from <= X AND (valid_to > X OR valid_to IS NULL)`.

**Condition du `MERGE`**, sur la ligne `is_current = true` existante du même `alleleid`
(et du même `panel`) :
- Si les champs surveillés — exactement `clinical_significance`, `review_status` et
  `last_evaluated` (les trois seuls champs que le §2.2 de la spec du 15/09 documente comme
  ayant varié d'un mois à l'autre sur l'échantillon mesuré) — sont **identiques** à
  l'entrant → ne rien faire.
- S'ils **diffèrent** → clôturer l'ancienne ligne (`valid_to = logical_date`,
  `is_current = false`) et insérer la nouvelle (`valid_from = logical_date`,
  `is_current = true`).
- Un `alleleid` jamais vu → insertion simple, `is_current = true`.

**Pourquoi comparer les valeurs et pas seulement `alleleid`.** Sans ce garde-fou, rejouer le
même mois deux fois (replay, ou un run qui échoue après le `MERGE` et qu'on relance)
créerait une nouvelle ligne d'historique à chaque exécution au lieu de ne rien faire — le
rejeu doit être idempotent.

---

## 5. `quality_check_silver`

Nouvelle fonction importable — aujourd'hui la tâche du DAG lève directement, sans passer par
`src/`, ce que ce sous-projet corrige en même temps qu'il l'implémente.

```python
def quality_check_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None
```

Fichier séparé, `src/transformations/quality_check_silver.py` — `bronze_to_silver.py` est déjà
volumineux (9 bâtisseurs + orchestration + `MERGE`), et le DAG les distingue déjà en deux
tâches.

Contrôles, dans l'ordre, toutes les erreurs rapportées ensemble (comme
`assert_partitions_complete` le fait déjà pour raw/bronze — pas d'arrêt au premier
problème) :

1. **Complétude par table** : chacune des 9 tables a au moins une ligne pour `panel` —
   exception documentée pour `hpo_gene_phenotype`, vide légitime pour `HBS1L`/`MYB` (loci
   GWAS absents des annotations HPO, déjà le cas en raw/bronze).
2. **Cohérence référentielle** : tout `clinvar_variant_gene.gene_symbol` appartient au panel
   (`PANELS[panel]`).
3. **Unicité de l'état courant** : `clinvar_variant.groupby(alleleid, panel).is_current.sum() == 1`
   partout — l'historique SCD2 ne doit jamais laisser deux lignes courantes pour le même
   variant.

Lève `SilverQualityError` (nouvelle exception, même famille que `IncompletePartitionError`)
nommant la table et le problème.

---

## 6. Gestion des erreurs

| Cas | Comportement |
|---|---|
| Partition bronze absente ou incomplète | Pas de re-vérification — `check_bronze` l'a garantie en amont. Erreur de lecture remontée telle quelle. |
| Accession RefSeq introuvable pour un variant | Pas une erreur — `refseq_accession_known = False`, ligne conservée. |
| `Name` ClinVar au format HGVS irrégulier | Ligne conservée, colonnes structurées nulles (§3). |
| CUI MedGen non résolu | Ligne conservée dans `medgen_concept`, aucune ligne dans `medgen_mim`/`medgen_inheritance` (§3). |
| Rejeu du même mois (replay) | Le `MERGE` SCD2 ne doit produire aucun changement si les champs surveillés sont identiques (§4). Les 8 tables sans historique sont de toute façon un overwrite complet du panel — un rejeu y est déjà naturellement idempotent. |

---

## 7. Tests

`tests/transformations/test_bronze_to_silver.py` et `test_quality_check_silver.py`, lac
local (`file://`), sans réseau ni conteneur.

- Un test par bâtisseur (9), fixtures bronze minimales, colonnes et valeurs attendues.
- `medgen_concept`/`medgen_mim`/`medgen_inheritance` : vérifier l'appel réel à
  `parse_medgen_conceptmeta` (pas une réimplémentation parallèle).
- `clinvar_variant_gene` : éclatement multi-gènes sur `;`.
- `clinvar_variant` : filtre GRCh38, dédoublonnage, parsing HGVS (cas régulier et
  irrégulier), jointure RefSeq.
- **SCD2** : deux runs successifs avec `clinical_significance` différente → l'ancienne ligne
  passe `is_current = false` avec `valid_to` renseigné, la nouvelle `is_current = true`. Puis
  un **rejeu du même mois** (mêmes valeurs) → aucune ligne d'historique supplémentaire.
- `quality_check_silver` : les trois contrôles, chacun testé en échec et en succès,
  message d'erreur nommant la table concernée.
- Isolation par panel : un run sur `brca` ne modifie aucune ligne `panel = "sickle"`
  préexistante dans les tables partagées.

---

## 8. Hors périmètre

- **`silver_to_gold_rag`, `silver_to_gold_analytique`** : sous-projet D, non touché ici.
- **Le taux de reclassification réel sur le fichier ClinVar complet** (spec du 15/09, §8,
  point ouvert) : ce sous-projet implémente le mécanisme SCD2, il ne mesure pas le volume réel
  de reclassifications par mois sur les ~48 000 variants du panel.
- **L'API exacte de `deltalake`** (`merge()`, `write_deltalake()`) : décrite ici au niveau
  conceptuel (§4), vérifiée à la main au moment d'écrire le plan d'implémentation — même
  méthode que pour les appels Polars du sous-projet B.
