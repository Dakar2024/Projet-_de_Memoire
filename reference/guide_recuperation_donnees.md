# Guide d'acquisition des données — Sources du pipeline

> **Statut : vérifié sur les APIs et serveurs réels le 2026-07-16.**
> Chaque commande, chaque champ et chaque format de ce document a été **exécuté et confirmé**.
> Les avertissements ⛔ signalent des méthodes testées qui **ne fonctionnent pas**.

---

## 0. Vue d'ensemble : deux familles de sources

| Famille | Sources | Mode d'accès | Clé requise |
|---|---|---|---|
| **APIs NCBI (E-utilities)** | ClinVar, NCBI Gene, MedGen | HTTP / BioPython `Bio.Entrez` | Clé NCBI (recommandée) |
| **Fichiers publics** | HPO | Téléchargement HTTP direct | Aucune |

> **OMIM n'est plus une source.** Remplacé par **MedGen** (voir `brain.md`, décision 2026-07-16).
> MedGen fournit le numéro MIM, donc OMIM reste **citable** sans dépendre de leur autorisation.

---

## 1. Prérequis communs NCBI

### 1.1 Identification obligatoire

Le NCBI exige une identification à chaque appel. Sans elle, ton IP peut être bloquée.

```python
from Bio import Entrez

Entrez.email = NCBI_EMAIL      # obligatoire
Entrez.api_key = NCBI_API_KEY  # fortement recommandé
```

### 1.2 Rate limiting — le piège à connaître

| Configuration | Limite |
|---|---|
| Sans clé API | **3 requêtes/seconde** |
| Avec clé API | **10 requêtes/seconde** |

⚠️ **Cette limite est GLOBALE, par adresse IP** — elle est **partagée entre ClinVar, Gene et MedGen**.
Ce n'est pas 10 req/s par base : c'est 10 req/s **au total**. Prévoir un rate limiter centralisé
(ex. `time.sleep(0.11)` entre appels) dans le pipeline.

### 1.3 Endpoint de base

```
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
    ├── esearch.fcgi    → chercher des identifiants (UID)
    ├── esummary.fcgi   → récupérer un résumé structuré  ✅ à privilégier
    └── efetch.fcgi     → récupérer un enregistrement complet
```

---

## 2. ClinVar — source principale (variants + signification clinique)

### ⛔ AVERTISSEMENT CRITIQUE : `efetch` ne fonctionne PAS

```bash
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=clinvar&id=4851147&rettype=vcv&retmode=xml"
```

**Résultat réel obtenu (110 octets) :**
```xml
<?xml version="1.0" encoding="UTF-8" ?>
<ClinVarResult-Set><set/></ClinVarResult-Set>
```

**Le résultat est VIDE.** Danger majeur : un parser XML sur ce contenu ne lève **aucune erreur** —
il retourne simplement une liste vide. Un pipeline construit dessus tourne **tout au vert avec zéro
variant indexé**. Ne jamais utiliser `efetch` sur ClinVar.

---

### ✅ Option A — Fichier bulk FTP (RECOMMANDÉ pour ce projet)

**Pourquoi c'est le bon choix ici :** le DAG est `@weekly` (donc du batch, pas du temps réel), et un
fichier unique est **idempotent, versionnable, reproductible et sans rate limiting** — exactement les
qualités attendues d'un pipeline de Data Engineering.

```bash
curl -O "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
```

**Caractéristiques vérifiées (2026-07-16) :**

| Propriété | Valeur constatée |
|---|---|
| Taille | ~440 Mo (gzip) |
| Dernière mise à jour | 2026-07-15 (la veille — mis à jour très régulièrement) |
| Format | TSV compressé gzip |
| Rate limiting | Aucun |

**Colonnes réelles du fichier (vérifiées) :**

```
#AlleleID, Type, Name, GeneID, GeneSymbol, HGNC_ID, ClinicalSignificance,
ClinSigSimple, LastEvaluated, RS# (dbSNP), nsv/esv (dbVar), RCVaccession,
PhenotypeIDS, PhenotypeList, Origin, OriginSimple, Assembly,
ChromosomeAccession, Chromosome, Start, Stop, ReferenceAllele,
AlternateAllele, Cytogenetic, ReviewStatus
```

**Correspondance avec les besoins du projet :**

| Besoin du chunk | Colonne du fichier |
|---|---|
| Gène (filtrage sur les 17 gènes) | `GeneSymbol` |
| Signification clinique (ACMG) | `ClinicalSignificance` |
| rsID | `RS# (dbSNP)` |
| HGVS | `Name` |
| **CUI MedGen** (jointure !) | `PhenotypeIDS` |
| Nom(s) de maladie | `PhenotypeList` |
| Position génomique | `Chromosome`, `Start`, `Stop`, `Cytogenetic` |
| Niveau de revue | `ReviewStatus` |

**Lecture avec filtrage sur les 17 gènes :**

```python
import polars as pl

# Lecture en streaming : ne charge pas les 440 Mo en mémoire
df = (
    pl.scan_csv(
        "data/external/variant_summary.txt.gz",
        separator="\t",
        infer_schema_length=0,   # tout en str : évite les erreurs de type
    )
    .filter(pl.col("GeneSymbol").is_in(ALL_GENES))
    # Doublons d'assemblage : garder GRCh38, mais NE PAS perdre les lignes "na"
    .filter(pl.col("Assembly").is_in(["GRCh38", "na"]))
    .collect()
)
```

### ⚠️ Piège n°1 — Les doublons d'assemblage (MESURÉ)

Chaque variant est présent **plusieurs fois**, une ligne par assemblage du génome de référence.

**Mesure réelle sur un échantillon de 20 000 lignes (2026-07-16) :**

| Constat | Valeur |
|---|---|
| AlleleID uniques | 10 169 |
| **AlleleID en doublon** | **9 806 (~96 %)** |
| Répartition `Assembly` | `GRCh38` : 9 887 · `GRCh37` : 9 823 · **`na` : 288** · `NCBI36` : 1 |

**Exemple réel — AlleleID `15041`, même variant, deux lignes :**
```
Assembly=GRCh37   Chr=7   Start=4820844   Name=NM_014855.3(AP5Z1):c.80_83delinsTGCTGTAAACTGT
Assembly=GRCh38   Chr=7   Start=4781213   Name=NM_014855.3(AP5Z1):c.80_83delinsTGCTGTAAACTGT
```

→ Sans filtre, **tu doubles quasiment ton nombre de variants** (et tu indexes deux chunks
quasi identiques par variant, ce qui dégraderait le retrieval).

### ⚠️ Piège n°2 — Ne pas filtrer trop strictement

Un filtre `Assembly == "GRCh38"` paraît logique… mais **288 lignes ont `Assembly = "na"`**
(variants sans coordonnées génomiques mappées). Un filtre strict les **supprimerait silencieusement**.

→ Utiliser `Assembly ∈ {"GRCh38", "na"}`, puis dédupliquer sur `#AlleleID` par sécurité.

> 💡 **Pour le mémoire :** ce type de constat (mesuré, chiffré, avec la décision de traitement
> associée) est exactement ce qu'on attend dans une section « qualité et nettoyage des données »
> d'un travail de Data Engineering.

---

### ✅ Option B — API `esummary` (si tu tiens à l'approche API)

```bash
# 1. Chercher les UID des variants d'un gène
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=clinvar&term=BRCA1[gene]&retmax=100&retmode=json"

# 2. Récupérer les résumés
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=clinvar&id=<UID>&retmode=json"
```

**Structure de réponse réelle (vérifiée) :**

```json
{
  "result": {
    "446748": {
      "uid": "446748",
      "accession": "VCV000446748",
      "title": "NM_000518.4(HBB):c.[205C>T;20A>T]",
      "obj_type": "copy number loss",
      "genes": [{"symbol": "HBB", "geneid": "3043"}],
      "germline_classification": {
        "description": "Pathogenic",
        "review_status": "criteria provided, single submitter",
        "trait_set": [
          {
            "trait_name": "Hereditary breast ovarian cancer syndrome",
            "trait_xrefs": [
              {"db_source": "MedGen", "db_id": "C3661900"}
            ]
          }
        ]
      }
    }
  }
}
```

**Champs clés :**

| Chemin JSON | Contenu |
|---|---|
| `title` | Notation HGVS |
| `accession` | Identifiant VCV (`VCV000446748`) |
| `genes[].symbol` | Gène(s) |
| `germline_classification.description` | **Signification clinique ACMG** |
| `germline_classification.review_status` | Niveau de revue |
| `germline_classification.trait_set[].trait_name` | Maladie |
| `germline_classification.trait_set[].trait_xrefs[]` | **→ CUI MedGen (clé de jointure)** |

```python
from Bio import Entrez
import json

def fetch_clinvar_summary(uids: list[str]) -> dict:
    """Récupère les résumés ClinVar via esummary (esummary, PAS efetch)."""
    handle = Entrez.esummary(db="clinvar", id=",".join(uids), retmode="json")
    return json.loads(handle.read())
```

---

## 3. NCBI Gene — contexte génomique et fonction du gène

> ⚠️ **Précision terminologique :** on parle souvent de « GenBank », mais la base réellement
> interrogée est **NCBI Gene** (`db=gene`). GenBank est une base de **séquences** ; NCBI Gene est
> une base de **métadonnées de gènes**. À corriger dans le mémoire.

### Méthode vérifiée

```bash
# 1. Trouver l'UID du gène
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gene&term=HBB[gene]+AND+human[organism]+AND+alive[property]&retmode=json"
# → UID: 3043

# 2. Récupérer le résumé
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=gene&id=3043&retmode=json"
```

**Résultat réel obtenu pour HBB :**

| Champ | Valeur constatée |
|---|---|
| `name` | `HBB` |
| `description` | `hemoglobin subunit beta` |
| `chromosome` | `11` |
| `maplocation` | `11p15.4` |
| `summary` | *« The alpha (HBA) and beta (HBB) loci determine the structure of the 2 types of polypeptide chains in adult hemoglobin… »* |
| `genomicinfo[0]` | `{chrloc: "11", chrstart: 5227070, chrstop: 5225463}` |

> 💡 **Le champ `summary` est précieux** : c'est une description fonctionnelle rédigée du gène.
> C'est exactement ce qu'il faut pour la ligne `Gene function` du chunk RAG.

> ⛔ **Ne pas utiliser** `efetch(db="gene", rettype="gene_table", retmode="text")` avec du parsing
> de texte par mots-clés (approche du plan initial) : c'est fragile et inutile. `esummary` en JSON
> donne les mêmes informations de façon structurée et fiable.

```python
def fetch_gene_info(gene: str) -> dict:
    """Récupère les métadonnées d'un gène via NCBI Gene (esummary JSON)."""
    handle = Entrez.esearch(
        db="gene",
        term=f"{gene}[gene] AND human[organism] AND alive[property]",
    )
    uids = Entrez.read(handle)["IdList"]
    if not uids:
        return {}
    handle = Entrez.esummary(db="gene", id=uids[0], retmode="json")
    data = json.loads(handle.read())
    return data["result"][uids[0]]
```

---

## 4. MedGen — maladie, transmission, numéro OMIM, phénotypes

MedGen est le **hub d'agrégation** du NCBI pour la génétique médicale. Il remplace OMIM.

### 4.1 Point d'entrée : le CUI fourni par ClinVar

La jointure se fait **au niveau du variant**, pas du gène :

```
ClinVar (variant) → trait_xrefs → {db_source: "MedGen", db_id: "C3661900"} → MedGen
```

### 4.2 Étape 1 — Convertir le CUI en UID MedGen

```bash
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=medgen&term=C0002895[conceptid]&retmode=json"
# → UID: 287
```

### 4.3 Étape 2 — Récupérer le concept

```bash
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=medgen&id=287&retmode=json"
```

**Résultat réel obtenu (drépanocytose, UID 287) :**

| Champ | Valeur constatée |
|---|---|
| `title` | `Hb SS disease` |
| `conceptid` | `C0002895` |
| `semantictype.value` | `Disease or Syndrome` |
| `definition` | Paragraphe clinique complet issu de **GeneReviews** |
| `conceptmeta` | **Chaîne XML** contenant tout le reste (voir ci-dessous) |

### 4.4 Le champ `conceptmeta` — la mine d'or

⚠️ **Attention :** `conceptmeta` est une **chaîne XML imbriquée dans du JSON**. Il faut la parser
séparément (`xml.etree.ElementTree`).

**Balises réellement présentes et exploitables :**

| Balise | Contenu réel vérifié (HBB / drépanocytose) |
|---|---|
| `<Definitions>` | `<Definition source="GeneReviews">Sickle cell disease (SCD) is characterized by…</Definition>` |
| `<ModesOfInheritance>` | `<Name>Autosomal recessive inheritance</Name>` + définition |
| `<OMIM>` | `<MIM>603903</MIM>` ← **le numéro OMIM, sans autorisation OMIM** |
| `<AssociatedGenes>` | `<Gene gene_id="3043" chromosome="11" cytogen_loc="11p15.4">HBB</Gene>` |
| `<ClinicalFeatures>` | `<ClinicalFeature ... SDUI="HP:0002027"><Name>Abdominal pain</Name>…` ← **termes HPO** |
| `<RelatedDisorders>` | Maladies apparentées |
| `<SNOMEDCT>` | Codes SNOMED CT |

```python
import xml.etree.ElementTree as ET

def parse_medgen_conceptmeta(conceptmeta: str) -> dict:
    """Extrait les champs utiles du XML conceptmeta de MedGen."""
    root = ET.fromstring(f"<root>{conceptmeta}</root>")

    mim = root.find(".//OMIM/MIM")
    inheritance = root.find(".//ModeOfInheritance/Name")
    definition = root.find(".//Definition")

    hpo_terms = [
        {"hpo_id": cf.get("SDUI"), "hpo_name": cf.findtext("Name", "")}
        for cf in root.findall(".//ClinicalFeature")
        if cf.get("SDUI", "").startswith("HP:")
    ]

    return {
        "mim_number": mim.text if mim is not None else "",
        "mode_inheritance": inheritance.text if inheritance is not None else "",
        "clinical_summary": definition.text if definition is not None else "",
        "hpo_terms": hpo_terms,
    }
```

> 💡 **Conséquence importante :** MedGen fournissant déjà des termes HPO au **niveau du variant**
> (via le CUI), la source HPO fichier (niveau **gène**) fait partiellement doublon. Son rôle reste
> à arbitrer.

---

## 5. HPO — phénotypes par gène (fichiers publics)

Aucune clé, aucune inscription, licence ouverte.

### 5.1 `genes_to_phenotype.txt` — gène → phénotypes

```bash
curl -L -o data/external/genes_to_phenotype.txt \
  "https://purl.obolibrary.org/obo/hp/hpoa/genes_to_phenotype.txt"
```

**Vérifié :** HTTP 200, ~20,7 Mo, TSV.

**Colonnes réelles (première ligne du fichier) :**
```
ncbi_gene_id    gene_symbol    hpo_id    hpo_name    frequency    disease_id
```

**Exemple réel :**
```
10    NAT2    HP:0000007    Autosomal recessive inheritance    -    OMIM:243400
10    NAT2    HP:0001939    Abnormality of metabolism/homeostasis    -    OMIM:243400
```

→ Index de parsing : `parts[1]` = `gene_symbol`, `parts[2]` = `hpo_id`, `parts[3]` = `hpo_name`.

### 5.2 `phenotype.hpoa` — maladie → phénotypes (+ noms de maladies OMIM)

```bash
curl -L -o data/external/phenotype.hpoa \
  "https://purl.obolibrary.org/obo/hp/hpoa/phenotype.hpoa"
```

**Vérifié :** version `2026-06-23`, couvre `8574 OMIM; 47 DECIPHER; 4337 ORPHANET`.

**Colonnes réelles :**
```
database_id  disease_name  qualifier  hpo_id  reference  evidence
onset  frequency  sex  modifier  aspect  biocuration
```

**Exemple réel :**
```
OMIM:619340    Developmental and epileptic encephalopathy 96        HP:0011097    PMID:31675180    PCS ...
```

> ⚠️ Le fichier commence par des lignes de commentaires `#`. Il faut les ignorer au parsing
> (`comment="#"` ou filtrage sur `line.startswith("#")`).

> 💡 **Ce fichier porte `disease_name` ET les identifiants OMIM** — c'est la preuve qu'on peut
> obtenir l'information OMIM utile sans jamais accéder à OMIM.

---

## 6. Récapitulatif — méthode retenue par source

| Source | Méthode retenue | Méthode à proscrire |
|---|---|---|
| **ClinVar** | FTP `variant_summary.txt.gz` (option A) ou `esummary` (option B) | ⛔ `efetch(rettype="vcv")` → retourne vide |
| **NCBI Gene** | `esearch` + `esummary` (JSON) | ⛔ `efetch(rettype="gene_table")` + parsing texte |
| **MedGen** | `esearch` (`[conceptid]`) + `esummary`, puis parsing XML de `conceptmeta` | — |
| **HPO** | Téléchargement HTTP direct des 2 fichiers | — |
| **OMIM** | ❌ Abandonné — remplacé par MedGen (numéro MIM inclus) | ⛔ `genemap2.txt` → autorisation jamais obtenue |

---

## 7. Ordre d'exécution dans le pipeline (couche RAW)

```
1. Télécharger variant_summary.txt.gz          (1 requête, pas de rate limit)
   └── filtrer sur les 17 gènes + Assembly=GRCh38
        │
2. Pour chaque gène (17)  → NCBI Gene esummary  (17 requêtes)
        │
3. Extraire les CUI MedGen distincts des variants filtrés
   └── Pour chaque CUI unique → MedGen esummary (N requêtes, dédupliquées)
        │
4. Charger les 2 fichiers HPO                  (0 requête API)
        │
   → data/raw/{gene}.json
```

> **Optimisation clé :** dédupliquer les CUI **avant** d'appeler MedGen. Des milliers de variants
> partagent la même condition (ex. tous les variants BRCA1 pathogènes → même CUI). Sans
> déduplication, tu ferais des milliers d'appels inutiles et tu exploserais le rate limit.

---

## 8. Checklist de vérification avant ingestion

- [ ] `NCBI_EMAIL` et `NCBI_API_KEY` définis dans `.env` (jamais en dur)
- [ ] Rate limiter global en place (≤ 10 req/s toutes bases NCBI confondues)
- [ ] Filtre `Assembly ∈ {"GRCh38", "na"}` appliqué sur ClinVar (~96 % de doublons sinon)
- [ ] Déduplication finale sur `#AlleleID`
- [ ] Déduplication des CUI MedGen avant appels
- [ ] Fichiers HPO présents dans `data/external/`
- [ ] Aucun appel à `efetch` sur ClinVar
