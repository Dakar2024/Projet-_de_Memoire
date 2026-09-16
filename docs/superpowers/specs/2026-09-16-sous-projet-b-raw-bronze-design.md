# Sous-projet B — `raw → bronze` en Polars — Design

**Date :** 2026-09-16
**Statut :** validé par l'utilisateur, en attente de relecture de ce document
**Périmètre :** sous-projet B de `docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md` (§7)

---

## 1. Objet

Ce document conçoit l'implémentation de `raw_to_bronze()`, laissée en stub documenté par le
sous-projet A (`src/transformations/raw_to_bronze.py`). Il ne revient sur aucune décision
d'architecture déjà prise par la spec du 2026-09-15 — format Parquet, chemins, contrat de la
couche (§2.3 et §3.2 de cette spec) — il les met en œuvre pour les six sources concrètes du
projet.

**Rappel du contrat (spec du 15/09, §3.2), non renégocié ici :**
- Colonnes lues en chaînes de caractères : le typage est une décision Silver.
- Noms de colonnes normalisés, colonnes techniques `_source_version`, `_logical_date`,
  `_ingested_at`.
- Aucun filtre, aucun typage métier, aucun dédoublonnage. Seule une ligne entièrement vide
  peut être retirée ; une ligne incomplète est conservée.
- Le bulk ClinVar se lit en mode lazy, jamais chargé entièrement en mémoire.
- Le Bronze ne filtre pas sur le panel (spec §4.2) : `raw_to_bronze` convertit ce qu'on lui
  donne dans `sources`, sans connaître la distinction sources partagées / sources par panel —
  c'est l'appelant (le DAG) qui la fait.

**Signature déjà figée par le sous-projet A**, consommée par les deux DAGs — non modifiable
sans casser `dag_acquisition_sources.py` et `dag_genomic_pipeline.py` :

```python
def raw_to_bronze(
    logical_date: str,
    sources: list[str],
    panel: str | None = None,
    lake_uri: str | None = None,
) -> list[str]:
```

---

## 2. Les six sources

| Source | Format raw | Fichier | Volume | Traitement |
|---|---|---|---|---|
| `clinvar` | TSV gzippé | `variant_summary.txt.gz` | ~442 Mo compressés, ~6M lignes | lazy obligatoire |
| `hpo` | TSV | `genes_to_phenotype.txt` | ~20 Mo | lazy (uniforme avec clinvar) |
| `ncbi_gene` | JSONL gzippé | `gene_summaries.jsonl.gz` | 1 enregistrement/gène du panel | schéma explicite |
| `refseq` | JSONL gzippé | `transcripts.jsonl.gz` | 1 enregistrement/gène du panel | schéma explicite |
| `medgen` | JSONL gzippé | `concepts.jsonl.gz` | 1 enregistrement/CUI | schéma explicite |
| `hpo_terms` | JSONL gzippé | `hpo_terms.jsonl.gz` | 1 enregistrement/(gène, terme HPO) | schéma explicite |

---

## 3. Décisions

### 3.1 Représentation des payloads imbriqués

`ncbi_gene.esummary`, `refseq.transcripts`, `medgen.esummary` (XML `conceptmeta` inclus) et
`hpo_terms.details` sont des structures imbriquées et de forme variable (champs optionnels
selon la réponse NCBI). Ils sont conservés **en chaîne JSON**, une colonne par champ imbriqué
(`esummary_json`, `transcripts_json`, `details_json`), plutôt qu'aplatis en colonnes
individuelles.

**Pourquoi.** Aplatir en Bronze (une colonne par champ connu d'`esummary`, une ligne par
transcrit pour `refseq`...) est déjà une décision de modélisation, pas un changement de
format — la règle « Bronze ne fait aucun typage/structuration métier » (spec §3, tableau des
contrats) l'interdit. C'est aussi cohérent avec la règle déjà écrite pour `conceptmeta` :
« reste une chaîne ». L'aplatissement réel revient à `bronze_to_silver` (sous-projet C).

### 3.2 Normalisation des noms de colonnes

Fonction mécanique, pas de table de correspondance à maintenir :

1. minuscule ;
2. tout caractère non alphanumérique devient `_` ;
3. underscores consécutifs fusionnés en un seul ;
4. `_` de bord retirés.

```
#AlleleID           -> alleleid
Name                -> name
GeneSymbol          -> genesymbol
RS# (dbSNP)         -> rs_dbsnp
nsv/esv (dbVar)     -> nsv_esv_dbvar
HGVS_p              -> hgvs_p
```

**Pas de coupure aux frontières minuscule→MAJUSCULE** (`AlleleID` reste `alleleid`, pas
`allele_id`) : une colonne sans séparateur d'origine (`GeneSymbol`, `#AlleleID`) n'a aucun
indice mécanique de découpage, et une règle de coupure camelCase serait incohérente avec un
sigle comme `dbSNP` dans `RS# (dbSNP)` — qui, lui, ne doit pas devenir `db_snp`. Le découpage
en mots reste une décision Silver, comme le reste du typage.

S'applique aux colonnes de `clinvar` et `hpo` (sources flat). Les sources JSONL n'ont pas ce
problème : leurs noms de champs (`gene_symbol`, `cui`, `hpo_id`...) sont déjà des identifiants
Python propres, choisis par les scripts d'ingestion du sous-projet A.

### 3.3 Lecture du bulk ClinVar

Le fichier raw est d'abord streamé sur disque local (`open_stream` de `storage.py`, déjà
utilisé pour ce fichier par `ingest_medgen.py`), puis lu en lazy (`pl.scan_csv`, tout en
`Utf8`), transformé (colonnes renommées, colonnes techniques ajoutées), écrit en flux
(`sink_parquet`) vers un fichier Parquet local, puis déposé en un seul appel (`put_file`).
Aucune étape ne charge le fichier complet en mémoire.

**Pourquoi pas un scan direct `s3://` par Polars.** Un second mode de lecture S3 (storage
Options Polars, credentials, retry) ajouterait une surface à valider en plus d'`open_stream`,
pour un fichier qui tient de toute façon sur le disque du conteneur. Un seul mode de lecture
S3 dans tout le projet.

### 3.4 Architecture interne

Un fichier, `src/transformations/raw_to_bronze.py` :

- `raw_to_bronze(logical_date, sources, panel, lake_uri)` — boucle sur `sources`, consulte la
  table de correspondance, dispatche vers le convertisseur adapté, écrit selon le protocole
  `begin_partition` → données → manifest → `_SUCCESS` (identique à la couche raw).
- `_convert_flat_source(raw_partition, bronze_partition, object_name, technical_cols)` —
  `clinvar`, `hpo`.
- `_convert_jsonl_source(raw_partition, bronze_partition, object_name, scalar_fields, nested_fields, technical_cols)`
  — `ncbi_gene`, `refseq`, `medgen`, `hpo_terms`.
- Table déclarative associant chaque source à son format et, pour les sources JSONL, à ses
  champs scalaires et imbriqués :

| Source | Champs scalaires | Champs imbriqués → `_json` |
|---|---|---|
| `ncbi_gene` | `gene_symbol` | `esummary` |
| `refseq` | `gene_symbol` | `transcripts` |
| `medgen` | `cui` | `esummary` |
| `hpo_terms` | `ncbi_gene_id`, `gene_symbol`, `hpo_id`, `hpo_name` | `details` |

Ajouter une septième source ne touche que cette table (et, si le format diffère des deux déjà
gérés, un nouveau convertisseur).

### 3.5 Colonnes techniques

- **`_source_version`** : lu depuis le manifest de la partition **raw**
  (`read_manifest(raw_partition)["source_version"]`) — la version déjà épinglée à
  l'ingestion (mois d'archive ClinVar, tag de release HPO...), jamais recalculée.
- **`_logical_date`** : le paramètre `logical_date` de `raw_to_bronze`.
- **`_ingested_at`** : propagé depuis `written_at` du manifest **raw** — horodatage de la
  collecte de la donnée source, pas de l'exécution de cette conversion.

### 3.6 Manifest bronze

Réutilise `build_manifest()` (déjà générique, `storage.py`) :

- `source_url` = **l'URI de la partition raw d'origine** (traçabilité raw → bronze ; l'URL
  externe d'origine reste accessible à un saut de distance, dans le manifest raw).
- `source_version` = même valeur que la colonne `_source_version`.
- `record_count` = nombre de lignes effectivement écrites (après retrait des lignes vides).
- Un seul fichier de sortie par partition, `data.parquet` — nom uniforme, le format est
  désormais le même pour toutes les sources.

---

## 4. Gestion des erreurs

| Cas | Comportement |
|---|---|
| Partition raw absente ou incomplète | Pas de re-vérification ici — `check_raw` l'a déjà garanti en amont dans le DAG. Une erreur de lecture remonte telle quelle. |
| Champ scalaire ou imbriqué manquant dans un enregistrement JSONL | Ligne conservée, valeur nulle/vide — cohérent avec un CUI MedGen ou un gène NCBI Gene non résolu (déjà légitime en raw). |
| Source absente de la table de correspondance | `ValueError` explicite. |
| Échec sur une source parmi plusieurs dans un même appel | Chaque source a son propre cycle `begin_partition` → `finalize_partition` : les sources déjà finalisées avant l'échec restent complètes ; `check_bronze` détectera la source manquante. Aucun rattrapage à coder. |

---

## 5. Tests

`tests/transformations/test_raw_to_bronze.py`, lac local (`tmp_path`, `file://`), aucun accès
réseau ni conteneur — cohérent avec la passe rapide du projet (`pytest -q`).

- Normalisation des noms de colonnes : fonction pure, testée isolément sur les exemples du
  §3.2.
- Sources flat : petit TSV de quelques lignes → colonnes normalisées, colonnes techniques
  correctes, ligne entièrement vide retirée, ligne incomplète conservée.
- Garde de streaming ClinVar : test espion (`patch(..., wraps=open_stream)`, comme
  `test_ingest_medgen.py`) vérifiant que la conversion passe par `scan_csv`/`sink_parquet` et
  jamais par un chargement complet en mémoire. Un fixture de quelques lignes ne prouve pas la
  tenue mémoire sur les 6M lignes réelles — seule l'inspection du chemin de code l'atteste.
- Sources JSONL : champs scalaires extraits en colonnes, champ imbriqué sérialisé en
  `<champ>_json` (re-parsable via `json.loads`), champ imbriqué vide (`{}`) conservé sans faire
  disparaître la ligne.
- Manifest bronze : `source_url` pointe vers la partition raw d'origine, `record_count`
  correspond aux lignes réelles, `_source_version`/`_ingested_at` propagés depuis le manifest
  raw.
- Source inconnue : lève `ValueError`.
- Échec partiel : une source en échec ne bloque pas la finalisation des sources précédentes
  du même appel.

---

## 6. Hors périmètre

- **Typage métier, filtre panel, filtre GRCh38, dédoublonnage, parsing du XML MedGen,
  normalisation HGVS** : sous-projet C (`bronze → silver`).
- **`quality_check_silver`, `silver_to_gold_rag`, `silver_to_gold_analytique`** : sous-projets
  C et D, non touchés ici.
- **Rejeu interrompu en bronze** (fenêtre d'incohérence sur stockage objet sans renommage
  atomique) : question reportée au sous-projet A (spec du 15/09, §8) et non résolue
  spécifiquement pour bronze — le protocole `begin`/`finalize` existant s'applique tel quel,
  sans amélioration nouvelle apportée par ce sous-projet.
- **Schéma explicite des JSONL** : les schémas listés au §3.4 (scalaires/imbriqués) sont
  déterminés à partir des scripts d'ingestion du sous-projet A ; ce document ne redéfinit pas
  ces scripts.
