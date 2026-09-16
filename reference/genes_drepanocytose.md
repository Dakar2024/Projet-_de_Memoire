# Gènes de référence — Drépanocytose

> Périmètre : gènes pertinents pour l'interprétation de variants ADN (données germinales, ClinVar).
> Objectif : couverture complète et justifiée pour le système RAG.

---

## Point clé à retenir

La drépanocytose est une maladie **monogénique** : elle est causée par **un seul gène (HBB)**.
Les autres gènes ne *causent* pas la maladie — ils en **modifient la sévérité** (taux d'hémoglobine
fœtale HbF) ou représentent une **co-morbidité** fréquente. Il faut donc les présenter dans cette
hiérarchie, et non comme des « gènes de la drépanocytose » au même titre que HBB.

> **Différence majeure avec le cancer du sein :** la drépanocytose est **purement germinale**. Il
> n'existe **pas** de catégorie « somatique » à exclure ici — tous les gènes concernés relèvent du
> génome constitutionnel, donc de ClinVar/ACMG. Le périmètre est intrinsèquement cohérent.

---

## Critères de sélection des gènes (règle de décision)

Contrairement au cancer du sein (maladie multigénique), la drépanocytose est monogénique. La règle
d'inclusion suit donc une **hiérarchie de rôles**. Un gène est inclus s'il remplit **l'un** de ces
rôles ET dispose de variants exploitables dans ClinVar.

| Rôle | Critère d'inclusion | Justification par rapport au projet |
|------|---------------------|-------------------------------------|
| **Causal** | Gène qui **provoque** la maladie | Cœur de l'interprétation : c'est le variant que le biologiste cherche à classer. |
| **Modificateur** | Module la **sévérité** (via l'HbF), validé par la littérature (GWAS) + pertinence thérapeutique | Enrichit l'interprétation clinique (pronostic, éligibilité aux thérapies HbF/CRISPR). |
| **Co-morbidité** | Maladie **distincte** mais très prévalente dans la population cible (Afrique de l'Ouest) | Pertinence contextuelle : co-hérédité fréquente influençant la prise en charge. |
| *(transversal)* | Présent dans **ClinVar** avec un volume de variants suffisant | Sans variants à indexer, aucun apport pour le RAG. |

---

## 1. Gène causal (obligatoire — cœur de la maladie)

| Gène | Localisation | Rôle | Variants ClinVar (ordre de grandeur) | Statut |
|------|--------------|------|--------------------------------------|--------|
| **HBB** | 11p15.4 | Sous-unité bêta de l'hémoglobine. Porte la mutation HbS (rs334, `NM_000518.5:c.20A>T`, p.Glu6Val), HbC (c.19G>A), et les mutations de bêta-thalassémie. **Seul gène causal.** | ~800 | ✅ Déjà choisi |

---

## 2. Gènes modificateurs — hémoglobine fœtale (HbF)

Ils ne causent pas la maladie mais en atténuent la sévérité en augmentant le taux d'HbF.
Ce sont les **trois loci modificateurs majeurs** de la littérature (études GWAS).

| Gène | Localisation | Rôle | Variants ClinVar | Statut |
|------|--------------|------|------------------|--------|
| **BCL11A** | 2p16.1 | Répresseur principal de l'HbF. **Cible de la thérapie génique CRISPR Casgevy (exa-cel, 2023).** | ~150 | ✅ Déjà choisi |
| **HBS1L-MYB** | 6q23 | Région intergénique, QTL majeur du taux d'HbF (GWAS). | ~80 | ✅ Déjà choisi |
| **KLF1** | 19p13.13 | Facteur de transcription érythroïde ; régule BCL11A et l'HbF. | ~60 | ✅ Déjà choisi |

---

## 3. Gènes modificateurs — extension possible (facultatif)

Biologiquement légitimes, non retenus dans ton périmètre actuel. À ajouter si tu veux
maximiser l'exhaustivité (l'architecture du pipeline le permet sans modification).

| Gène | Localisation | Rôle | Pourquoi c'est pertinent | Statut |
|------|--------------|------|--------------------------|--------|
| **HBG1 / HBG2** | 11p15.4 | Gènes gamma-globine (hémoglobine fœtale). Variants HPFH (persistance héréditaire de l'HbF) et polymorphisme Xmn1-HBG2 (rs7482144). | Modifient directement la sévérité via l'HbF. | ⬜ À considérer |
| **HBA1 / HBA2** | 16p13.3 | Gènes alpha-globine. | La co-hérédité d'une alpha-thalassémie **modifie réellement** la sévérité de la drépanocytose. Meilleur candidat d'ajout « solide ». | ⬜ À considérer |

---

## 4. Co-morbidité (maladie distincte)

| Gène | Localisation | Rôle | Statut |
|------|--------------|------|--------|
| **G6PD** | Xq28 | Déficit en G6PD — **autre maladie**, pas la drépanocytose. Retenu uniquement car très fréquent en Afrique subsaharienne (10-25 %) et souvent co-hérité. | ✅ Déjà choisi (à présenter comme co-morbidité) |

---

## Synthèse : ton périmètre est-il complet pour la drépanocytose ?

- **Gène causal : COMPLET.** HBB est l'unique gène causal, tu l'as. Rien à ajouter.
- **Modificateurs : quasi complet.** Tu as les 3 loci majeurs. Ajouts possibles : HBG1/HBG2, HBA1/HBA2.
- **Co-morbidité : G6PD** (à qualifier correctement dans le mémoire).

**Recommandation :** ton périmètre actuel est **scientifiquement solide et défendable en soutenance**.
L'ajout de HBA1/HBA2 est le seul qui apporterait une vraie valeur biologique si tu veux renforcer
l'exhaustivité.

---

## Gènes EXCLUS et justification (à défendre en soutenance)

### Catégorie A — Gènes causals « manquants » → IL N'Y EN A AUCUN

**C'est un point fort à mettre en avant.** La drépanocytose n'ayant qu'**un seul gène causal (HBB)**,
il est **impossible** d'en oublier. La couverture causale est **complète par nature**, contrairement
au cancer du sein.

> **Formulation soutenance :** « La drépanocytose est monogénique : HBB est l'unique gène causal.
> Ma couverture de la cause de la maladie est donc totale, sans sélection ni compromis possible. »

### Catégorie B — Gènes modificateurs non retenus → EXCLUS pour le périmètre

Ces gènes sont biologiquement pertinents mais écartés du prototype pour une raison de **périmètre**,
pas de biologie. Ils sont documentés en section 3 comme extension possible.

| Gène(s) exclus | Rôle | Motif d'exclusion défendable |
|----------------|------|------------------------------|
| **HBA1 / HBA2** | Alpha-globine (co-hérédité alpha-thalassémie) | Modificateur réel mais indirect ; priorité donnée aux 3 loci modificateurs **principaux** de l'HbF validés par GWAS. Ajout possible en extension. |
| **HBG1 / HBG2** | Gamma-globine (HbF) | Effet redondant avec les régulateurs déjà retenus (BCL11A, KLF1) ; n'apporte pas de gène causal supplémentaire. |

### Catégorie C — Gènes somatiques → NON APPLICABLE

La drépanocytose n'implique **aucun** gène somatique. Cette catégorie, centrale pour le cancer du
sein, **n'existe pas** ici. À souligner comme preuve de la cohérence du périmètre.

---

## Tableau de synthèse pour la soutenance

| Décision | Gènes | Justification en une phrase |
|----------|-------|-----------------------------|
| ✅ **Inclus — causal** | HBB | Unique gène causal de la drépanocytose ; couverture totale de la cause. |
| ✅ **Inclus — modificateurs** | BCL11A, HBS1L-MYB, KLF1 | Trois loci modificateurs majeurs de l'HbF (GWAS), pertinents pour le pronostic et les thérapies. |
| ✅ **Inclus — co-morbidité** | G6PD | Déficit très prévalent en Afrique de l'Ouest, souvent co-hérité ; pertinence contextuelle. |
| ⬜ **Exclus — extension** | HBA1/HBA2, HBG1/HBG2 | Modificateurs secondaires ; périmètre concentré sur les loci HbF principaux. Extension future. |
| ❌ **Exclus — somatiques** | *(aucun)* | Maladie purement germinale, pas de génome tumoral concerné. |

---

## Liste finale recommandée (à indexer)

```
HBB          # causal
BCL11A       # modificateur HbF
HBS1L-MYB    # modificateur HbF
KLF1         # modificateur HbF
G6PD         # co-morbidité
# --- extension optionnelle ---
HBA1         # modificateur (alpha-thalassémie co-héritée)
HBA2         # modificateur (alpha-thalassémie co-héritée)
HBG1         # modificateur HbF
HBG2         # modificateur HbF
```
