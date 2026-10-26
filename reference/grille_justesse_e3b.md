# Grille de justesse E3b — niveau 7a

Générée par `scripts/verifier_justesse.py --grille` sur le Gold du mois 2026-10.
Pour chaque fiche : ouvrir le lien, confronter les six éléments (`reference/evaluation.md`
§ 8.3), cocher, puis reporter le verdict dans la grille ci-dessous. Appliquer les trois pièges
du § 8.1 : une date du site **postérieure** à la nôtre fait d'un écart de signification ou de
statut une mise à jour légitime ; une date **antérieure** est un écart en soi.

**Maladies** : les nôtres viennent de **tous** les RCV de la fiche (correction P-E3b-1 du
rapport), pas seulement de l'encadré germinal. Chercher une maladie absente de l'encadré dans
la liste complète des conditions et des soumissions avant de la compter comme écart.

## Fiches

### 1 — BRCA1 pathogène/probablement pathogène

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/37392/ — gène(s) `BRCA1`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NM_007294.4(BRCA1):c.116G>A (p.Cys39Tyr)` | ☐ |
| Signification (Germline classification) | Pathogenic/Likely pathogenic | ☐ |
| Statut de revue | criteria provided, multiple submitters, no conflicts | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | Jul 14, 2026 | ☐ |
| dbSNP | rs80357498 | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | Breast neoplasm<br>Breast-ovarian cancer, familial, susceptibility to, 1<br>Hereditary breast ovarian cancer syndrome<br>Hereditary cancer-predisposing syndrome<br>Malignant tumor of urinary bladder | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NM_007294.4(BRCA1):c.116G>A (p.Cys39Tyr), gene BRCA1, chromosome 17q21.31.
dbSNP rs80357498. ClinVar Variation ID 37392. Type: single nucleotide variant.
Clinical significance: Pathogenic/Likely pathogenic.
Review status: criteria provided, multiple submitters, no conflicts (21 submitters).
Last evaluated: Jul 14, 2026.
Associated conditions: Breast neoplasm; Breast-ovarian cancer, familial, susceptibility to, 1 (OMIM 604370); Hereditary breast ovarian cancer syndrome (inheritance: Autosomal dominant inheritance); Hereditary cancer-predisposing syndrome; Malignant tumor of urinary bladder (OMIM 109800).
Related phenotypes (HPO): Abnormal fallopian tube morphology; Autosomal dominant inheritance; Breast carcinoma; Melanoma; Middle age onset; Neoplasm of the pancreas; Non-Mendelian inheritance; Ovarian neoplasm; Primary peritoneal carcinoma; Prostate cancer.
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/37392/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

### 2 — BRCA2 pathogène, un soumetteur

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/1012631/ — gène(s) `BRCA2`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NM_000059.4(BRCA2):c.1490_1493del (p.Ser497fs)` | ☐ |
| Signification (Germline classification) | Pathogenic | ☐ |
| Statut de revue | criteria provided, single submitter | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | Sep 01, 2020 | ☐ |
| dbSNP | rs2072414606 | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | aucune | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NM_000059.4(BRCA2):c.1490_1493del (p.Ser497fs), gene BRCA2, chromosome 13q13.1.
dbSNP rs2072414606. ClinVar Variation ID 1012631. Type: Deletion.
Clinical significance: Pathogenic.
Review status: criteria provided, single submitter (1 submitters).
Last evaluated: Sep 01, 2020.
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/1012631/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

### 3 — ATM probablement pathogène, panel d'experts

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/1023669/ — gène(s) `ATM`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NM_000051.4(ATM):c.8300T>C (p.Leu2767Pro)` | ☐ |
| Signification (Germline classification) | Likely pathogenic | ☐ |
| Statut de revue | reviewed by expert panel | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | Jun 11, 2025 | ☐ |
| dbSNP | rs1591247825 | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | ATM-related cancer predisposition<br>Ataxia-telangiectasia syndrome | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NM_000051.4(ATM):c.8300T>C (p.Leu2767Pro), gene ATM, chromosome 11q22.3.
dbSNP rs1591247825. ClinVar Variation ID 1023669. Type: single nucleotide variant.
Clinical significance: Likely pathogenic.
Review status: reviewed by expert panel (2 submitters).
Last evaluated: Jun 11, 2025.
Associated conditions: ATM-related cancer predisposition; Ataxia-telangiectasia syndrome (OMIM 208900, inheritance: Autosomal recessive inheritance).
Related phenotypes (HPO): Abnormal hair morphology; Abnormal speech pattern; Abnormal spermatogenesis; Abnormal testis morphology; Abnormal total B cell count; Abnormality of chromosome stability; Abnormality of eye movement; Abnormality of movement; Abnormality of the immune system; Acute lymphoblastic leukemia; and 65 more.
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/1023669/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

### 4 — BRCA2 bénin, panel d'experts

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/96762/ — gène(s) `BRCA2`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NM_000059.4(BRCA2):c.1166C>A (p.Pro389Gln)` | ☐ |
| Signification (Germline classification) | Benign | ☐ |
| Statut de revue | reviewed by expert panel | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | Jun 18, 2019 | ☐ |
| dbSNP | rs397507263 | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | Breast neoplasm<br>Breast-ovarian cancer, familial, susceptibility to, 2<br>Familial cancer of breast<br>Fanconi anemia complementation group D1<br>Hereditary breast ovarian cancer syndrome<br>Hereditary cancer-predisposing syndrome<br>Malignant tumor of breast | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NM_000059.4(BRCA2):c.1166C>A (p.Pro389Gln), gene BRCA2, chromosome 13q13.1.
dbSNP rs397507263. ClinVar Variation ID 96762. Type: single nucleotide variant.
Clinical significance: Benign.
Review status: reviewed by expert panel (20 submitters).
Last evaluated: Jun 18, 2019.
Associated conditions: Breast neoplasm; Breast-ovarian cancer, familial, susceptibility to, 2 (OMIM 612555); Familial cancer of breast (OMIM 114480, inheritance: Non-Mendelian inheritance); Fanconi anemia complementation group D1 (OMIM 605724); Hereditary breast ovarian cancer syndrome (inheritance: Autosomal dominant inheritance); and 2 more.
Related phenotypes (HPO): Abnormal fallopian tube morphology; Acute myeloid leukemia; Anal atresia; Autosomal dominant inheritance; Autosomal recessive inheritance; Bone marrow hypocellularity; Breast carcinoma; Cafe-au-lait spot; Chromosomal breakage induced by crosslinking agents; Failure to thrive; and 12 more.
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/96762/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

### 5 — BARD1 probablement bénin

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/1017479/ — gène(s) `BARD1`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NM_000465.4(BARD1):c.855A>G (p.Gln285=)` | ☐ |
| Signification (Germline classification) | Likely benign | ☐ |
| Statut de revue | criteria provided, single submitter | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | Feb 17, 2024 | ☐ |
| dbSNP | rs1694987168 | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | Familial cancer of breast | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NM_000465.4(BARD1):c.855A>G (p.Gln285=), gene BARD1, chromosome 2q35.
dbSNP rs1694987168. ClinVar Variation ID 1017479. Type: single nucleotide variant.
Clinical significance: Likely benign.
Review status: criteria provided, single submitter (1 submitters).
Last evaluated: Feb 17, 2024.
Associated conditions: Familial cancer of breast (OMIM 114480, inheritance: Non-Mendelian inheritance).
Related phenotypes (HPO): Autosomal dominant inheritance; Breast carcinoma; Typified by somatic mosaicism.
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/1017479/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

### 6 — PTEN de signification incertaine

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/1013569/ — gène(s) `PTEN`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NM_000314.8(PTEN):c.-27T>C` | ☐ |
| Signification (Germline classification) | Uncertain significance | ☐ |
| Statut de revue | criteria provided, single submitter | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | Sep 01, 2020 | ☐ |
| dbSNP | rs1858391629 | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | aucune | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NM_000314.8(PTEN):c.-27T>C, gene PTEN, chromosome 10q23.31.
dbSNP rs1858391629. ClinVar Variation ID 1013569. Type: single nucleotide variant.
Clinical significance: Uncertain significance.
Review status: criteria provided, single submitter (1 submitters).
Last evaluated: Sep 01, 2020.
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/1013569/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

### 7 — BRCA2 conflictuel

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/1764023/ — gène(s) `BRCA2`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NM_000059.4(BRCA2):c.8602A>G (p.Lys2868Glu)` | ☐ |
| Signification (Germline classification) | Conflicting classifications of pathogenicity | ☐ |
| Statut de revue | criteria provided, conflicting classifications | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | May 15, 2025 | ☐ |
| dbSNP | rs1469574477 | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | BRCA2-related cancer predisposition<br>Hereditary cancer-predisposing syndrome | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NM_000059.4(BRCA2):c.8602A>G (p.Lys2868Glu), gene BRCA2, chromosome 13q13.1.
dbSNP rs1469574477. ClinVar Variation ID 1764023. Type: single nucleotide variant.
Clinical significance: Conflicting classifications of pathogenicity.
Review status: criteria provided, conflicting classifications (3 submitters).
Last evaluated: May 15, 2025.
Associated conditions: BRCA2-related cancer predisposition; Hereditary cancer-predisposing syndrome.
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/1764023/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

### 8 — PTEN pathogène sans dbSNP

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/1018969/ — gène(s) `PTEN`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NM_000314.8(PTEN):c.141_142inv (p.Arg47_Asn48delinsSerHis)` | ☐ |
| Signification (Germline classification) | Pathogenic | ☐ |
| Statut de revue | criteria provided, single submitter | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | Jul 22, 2024 | ☐ |
| dbSNP | aucun (`-1`) | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | PTEN hamartoma tumor syndrome | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NM_000314.8(PTEN):c.141_142inv (p.Arg47_Asn48delinsSerHis), gene PTEN, chromosome 10q23.31.
ClinVar Variation ID 1018969. Type: Inversion.
Clinical significance: Pathogenic.
Review status: criteria provided, single submitter (1 submitters).
Last evaluated: Jul 22, 2024.
Associated conditions: PTEN hamartoma tumor syndrome (inheritance: Autosomal dominant inheritance).
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/1018969/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

### 9 — multi-gènes TP53;WRAP53

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/1336926/ — gène(s) `TP53;WRAP53`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NM_001143992.2(WRAP53):c.1A>G (p.Met1Val)` | ☐ |
| Signification (Germline classification) | Uncertain significance | ☐ |
| Statut de revue | criteria provided, multiple submitters, no conflicts | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | Sep 01, 2022 | ☐ |
| dbSNP | rs867179605 | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | aucune | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NM_001143992.2(WRAP53):c.1A>G (p.Met1Val), gene TP53, chromosome 17p13.1.
dbSNP rs867179605. ClinVar Variation ID 1336926. Type: single nucleotide variant.
Clinical significance: Uncertain significance.
Review status: criteria provided, multiple submitters, no conflicts (2 submitters).
Last evaluated: Sep 01, 2022.
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/1336926/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

### 10 — G6PD conflictuel (drépanocytose)

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/1014228/ — gène(s) `G6PD`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NM_001360016.2(G6PD):c.973G>A (p.Asp325Asn)` | ☐ |
| Signification (Germline classification) | Conflicting classifications of pathogenicity | ☐ |
| Statut de revue | criteria provided, conflicting classifications | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | Aug 12, 2022 | ☐ |
| dbSNP | rs781906610 | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | Anemia, nonspherocytic hemolytic, due to G6PD deficiency | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NM_001360016.2(G6PD):c.973G>A (p.Asp325Asn), gene G6PD, chromosome Xq28.
dbSNP rs781906610. ClinVar Variation ID 1014228. Type: single nucleotide variant.
Clinical significance: Conflicting classifications of pathogenicity.
Review status: criteria provided, conflicting classifications (2 submitters).
Last evaluated: Aug 12, 2022.
Associated conditions: Anemia, nonspherocytic hemolytic, due to G6PD deficiency (OMIM 300908, inheritance: X-linked recessive inheritance).
Related phenotypes (HPO): Abdominal pain; Anisocytosis; Childhood onset; Congenital onset; Decreased circulating glucose-6-phosphate dehydrogenase activity; Fava bean-induced hemolytic anemia; Fever; Heinz bodies; Hemoglobinuria; Increased total leukocyte count; and 13 more.
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/1014228/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

### 11 — HBB pathogène sans dbSNP ni critères (drépanocytose)

Fiche : https://www.ncbi.nlm.nih.gov/clinvar/variation/1048666/ — gène(s) `HBB`. Variant du protocole (§ 8.2), présent dans le Gold.

| Élément | Notre valeur (Silver) | Conforme à la fiche |
|---|---|---|
| Nom HGVS (titre, au caractère près) | `NC_000011.10:g.5224303_5227790del` | ☐ |
| Signification (Germline classification) | Pathogenic | ☐ |
| Statut de revue | no assertion criteria provided | ☐ |
| Last evaluated (le site peut être postérieur, jamais antérieur) | Mar 01, 2021 | ☐ |
| dbSNP | aucun (`-1`) | ☐ |
| Maladies (les nôtres ⊆ onglet Conditions) | beta Thalassemia | ☐ |

Document RAG produit (`gold/rag/documents`) :

```text
Variant NC_000011.10:g.5224303_5227790del, gene HBB, chromosome 11p15.4.
ClinVar Variation ID 1048666. Type: Deletion.
Clinical significance: Pathogenic.
Review status: no assertion criteria provided (1 submitters).
Last evaluated: Mar 01, 2021.
Associated conditions: beta Thalassemia (inheritance: Autosomal dominant inheritance).
```

- ☐ chaque fait du document se retrouve sur la fiche
- ☐ le lien de citation est bien https://www.ncbi.nlm.nih.gov/clinvar/variation/1048666/
- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte

## Grille

| # | Variation | Nom HGVS | Signification | Statut de revue | Date | dbSNP | Maladies | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | 37392 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 2 | 1012631 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 3 | 1023669 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 4 | 96762 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 5 | 1017479 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 6 | 1013569 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 7 | 1764023 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 8 | 1018969 | ☐ | ☐ | ☐ | ☐ | — | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 9 | 1336926 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 10 | 1014228 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 11 | 1048666 | ☐ | ☐ | ☐ | ☐ | — | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |

**Taux de concordance = (conformes + mises à jour postérieures) / 11** : ______

## Sentinelles dans tous les documents RAG (automatique, § 8.4)

| Motif | Documents qui le contiennent (attendu : 0) |
|---|---|
| `rs-1` | 0 |
| `None` | 0 |
| `Last evaluated: -.` | 0 |
| `Review status: -` | 0 |

## Sources annexes (§ 8.5)

| Source | Élément | Notre valeur | Fiche de contrôle | Verdict |
|---|---|---|---|---|
| NCBI Gene | BRCA1 : description et localisation | BRCA1 DNA repair associated ; 17q21.31 | https://www.ncbi.nlm.nih.gov/gene/672 | ☐ conforme ☐ écart |
| RefSeq | NM_007294 : version et gène | version 4 ; BRCA1 | https://www.ncbi.nlm.nih.gov/nuccore/NM_007294.4 | ☐ conforme ☐ écart |
| MedGen | C1292231 : libellé et MIM | BLOOD GROUP--LUTHERAN INHIBITOR (OMIM) ; MIM 111150 | https://www.ncbi.nlm.nih.gov/medgen/C1292231 | ☐ conforme ☐ écart |
| HPO | HP:0002027 : nom et définition | Abdominal pain — An unpleasant sensation characterized by physical discomfort (such as pricking, throbbing, or aching) and perceived to originate in the abdomen. | https://ontology.jax.org/api/hp/terms/HP%3A0002027 | ☐ conforme ☐ écart |
| dbSNP | rs80357498 : variant n° 1 | variation(s) ClinVar 37392, 37393, 867499 | https://www.ncbi.nlm.nih.gov/snp/rs80357498 | ☐ conforme ☐ écart |
