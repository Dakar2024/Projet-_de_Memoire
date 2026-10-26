# Évaluation du pipeline — protocole complet

**Date de rédaction :** 29 septembre 2026 ; **mise à jour :** 26 octobre 2026, à la fin d'E3b
**Référence des données :** archive ClinVar de septembre 2026, partition `dt=2026-09-01` ;
niveaux 5 à 7 et volumes du § 3 recalés sur l'archive d'**octobre 2026** (`dt=2026-10-01`)
**Résultats des niveaux 5 à 7 :** `reference/rapport_e3b.md` ; grille manuelle :
`reference/grille_justesse_e3b.md`
**Objet :** établir, preuve à l'appui, que le pipeline produit des données justes, complètes et
reproductibles — et dire précisément ce qui n'est pas prouvé.

---

## 1. Principe : « 100 % fonctionnel » ne se démontre pas

Aucun test ne prouve qu'un système fonctionne totalement. Ce qu'on peut faire, et ce que ce
document organise, c'est **empiler des preuves de nature différente** jusqu'à ce que le doute
résiduel soit explicite et assumé.

Sept niveaux, du plus faible au plus fort. Un niveau élevé ne remplace pas les précédents : des
tests unitaires verts ne disent rien de la justesse biologique, et une vérification manuelle
réussie ne dit rien du comportement en panne.

| # | Niveau de preuve | Ce qu'il établit | État au 26/10/2026 |
|---|---|---|---|
| 1 | Tests automatisés | La logique est juste, isolément | ✅ 1 757 + 77 tests verts (`pytest`, `tests_airflow`) |
| 2 | Exécution de bout en bout | Les composants s'assemblent | ✅ 18 gènes, 97 210 documents (octobre) |
| 3 | Contrôles qualité intégrés | Chaque exécution se vérifie elle-même | ✅ 5 contrôles actifs |
| 4 | Idempotence du rejeu | Relancer ne corrompt rien | ✅ vérifié sur le lac réel |
| 5 | Comportement en panne | Le système échoue proprement | ✅ six scénarios joués, deux défauts corrigés (D-E3b-2, D-E3b-3), une réserve (O-E3b-2) |
| 6 | Restauration | Les données sont récupérables | ✅ restauration complète sur pile vide, rejeu ; un défaut corrigé (D-E3b-1) |
| 7 | **Justesse métier** | Les données correspondent à la réalité | 7b ✅ 400/400 contre l'API ClinVar ; 7a ⏳ **grille prête, à cocher par l'utilisateur — §8** |

**Le niveau 7 est celui qui compte pour un jury de génomique**, et c'est le seul qu'aucun
programme ne peut produire à votre place.

---

## 2. Niveau 1 — Tests automatisés

```bash
cd ~/Documents/Projet-_de_Memoire
source venv/bin/activate
pytest -q                  # logique métier
pytest tests_airflow -q    # structure des DAGs
```

**Attendu :** `284 passed, 1 deselected` et `24 passed`. Toute régression invalide les niveaux
supérieurs : ne pas poursuivre l'évaluation tant que cette passe n'est pas verte.

**Ce que ces tests couvrent :** parsing des quatre sources, conversion des couches, historique
SCD2, contrôles qualité, rendu des documents RAG, écriture Delta par panel, maintenance. **Ce
qu'ils ne couvrent pas :** tout appel réseau réel, et donc toute dérive des sources.

---

## 3. Niveau 2 — Exécution de bout en bout

### Procédure

```bash
docker compose --env-file .env up -d
docker compose ps                        # attendre « healthy » partout

# 1. Sources partagées (ClinVar 440 Mo + HPO), ~10 min
docker compose exec airflow-scheduler \
  airflow dags trigger dag_acquisition_sources --logical-date 2026-09-01

# 2. Les deux panels démarrent seuls à la fin de l'acquisition.
#    Suivre dans l'interface, ou :
docker compose exec airflow-scheduler airflow dags list-runs dag_genomic_pipeline_brca
```

### Critères de réussite, avec les valeurs de référence mesurées

| Contrôle | Valeur attendue |
|---|---|
| Toutes les tâches vertes sauf | aucune — `quality_check_gold` est la dernière |
| Durée totale d'un panel | 8 à 12 min (dominée par les appels NCBI) |
| `silver/clinvar_variant` | 97 192 lignes — 93 615 brca, 3 577 sickle (octobre ; septembre : 96 892) |
| `silver/clinvar_variant_disease` | 171 141 lignes (septembre : 170 475) |
| `gold/rag/documents` | 97 210 — 97 192 variants + 18 gènes (septembre : 96 910) |
| Pic mémoire du scheduler | < 2,5 Go (mesuré : 2 Go sur la conversion ClinVar) |

Un écart de plus de 5 % sur les volumes doit être expliqué avant de poursuivre : soit
l'archive ClinVar du mois a changé, soit quelque chose ne va pas.

### Relevé des volumes

```bash
docker exec genomique-airflow-scheduler python -c "
import polars as pl
from ingestion.storage import storage_options
for t in ['clinvar_variant','clinvar_variant_gene','clinvar_variant_disease','ncbi_gene',
          'refseq_transcript','medgen_concept','hpo_gene_phenotype','hpo_term']:
    u=f's3://silver/{t}'; d=pl.read_delta(u,storage_options=storage_options(u))
    print(f'{t:26} {d.height:7} {dict(d.group_by(\"panel\").len().iter_rows())}')"
```

---

## 4. Niveau 3 — Les contrôles qualité intégrés

Ce sont eux qui transforment « ça marchait le jour de la démonstration » en « chaque exécution
se vérifie ». Ils bloquent la propagation vers la couche suivante.

| Contrôle | Ce qu'il vérifie | Ce qu'il attraperait |
|---|---|---|
| `check_raw` | Partition complète, `_SUCCESS` présent, `record_count` > 0 | Un téléchargement tronqué |
| `check_bronze` | Idem après conversion | Une conversion partielle |
| `quality_check_silver` | Les 10 tables non vides, gènes du panel, unicité de l'état courant, références croisées, **plausibilité du volume (seuil 5 %)** | Une archive ClinVar tronquée |
| `quality_check_gold` | Conservation des variants, un document par variant et par gène, unicité des `doc_id`, taille des textes, clés non pendantes | Une perte entre Silver et Gold |

### Prouver qu'un garde-fou se déclenche vraiment

Un contrôle qui n'a jamais échoué n'a jamais été prouvé. Les tests d'injection de faute
existent déjà dans la suite :

```bash
pytest tests/transformations/test_quality_check_silver.py -v -k "rejects or truncated"
pytest tests/transformations/test_quality_check_gold.py -v
```

**Attendu :** chaque test nommé `rejects_*` échoue *volontairement* le contrôle et vérifie que
l'erreur nomme la table fautive. C'est la démonstration que le filet a bien des mailles.

---

## 5. Niveau 4 — Idempotence

Relancer le même mois ne doit rien changer.

```bash
docker exec genomique-airflow-scheduler python -c "
from deltalake import DeltaTable
from ingestion.storage import storage_options
from transformations.silver_to_gold_rag import documents_uri, silver_to_gold_rag
u = documents_uri(); o = storage_options(u)
avant = DeltaTable(u, storage_options=o).version()
silver_to_gold_rag('2026-09-01', 'brca')
print('version Delta', avant, '->', DeltaTable(u, storage_options=o).version())"
```

**Attendu :** la version Delta **ne change pas**. Un document inchangé n'est pas réécrit, donc
l'étape RAG n'aura rien à ré-embedder. C'est la propriété qui rend le pipeline rejouable sans
coût.

---

## 6. Niveau 5 — Comportement en panne *(réalisé le 23 et 24/10/2026)*

> **Résultats** : `reference/rapport_e3b.md`, niveau 5. Joués sur la pile isolée `genomique-e3b`,
> jamais sur la principale, avec deux scénarios ajoutés (P5 double déclenchement, P6 mois passé).
> Depuis la règle « mois en cours uniquement » (24/10/2026), P3 ne vise plus 2019 : l'acquisition
> d'octobre est relancée derrière un proxy fermé. Le tableau ci-dessous est le protocole d'origine.

Quatre scénarios, à exécuter une fois et à consigner. Chacun vérifie que le système **échoue
proprement** plutôt que de produire des données fausses.

| # | Scénario | Commande | Comportement attendu |
|---|---|---|---|
| P1 | Conteneur tué en plein run | `docker kill genomique-airflow-scheduler` pendant `bronze_to_silver`, puis `docker compose up -d` | La tâche repart (3 tentatives) ; aucune partition marquée complète à tort ; le rejeu produit le même résultat |
| P2 | Disque saturé | Remplir `data/external` jusqu'à moins de 2 Go libres, relancer `ingest_clinvar` | Échec **immédiat** avec « espace disque insuffisant », sans consommer les tentatives, avant tout téléchargement |
| P3 | Source indisponible | Déclencher l'acquisition sur un mois inexistant : `--logical-date 2019-01-01` | Erreur HTTP explicite, 3 tentatives, puis échec ; l'Asset n'est **pas** publié ; les panels ne démarrent pas |
| P4 | Archive tronquée | Semer un `clinvar_variant_gene` amputé de moitié, relancer `quality_check_silver` | `SilverQualityError` nommant la proportion de variants absents et bloquant le Gold |

Pour P4, sans toucher au lac réel :

```bash
pytest tests/transformations/test_quality_check_silver.py -v -k truncated
```

---

## 7. Niveau 6 — Restauration *(réalisé le 23/10/2026)*

> **Résultats** : `reference/rapport_e3b.md`, niveau 6. Restauration complète sur une pile vide
> (`scripts/restaurer.sh`), puis rejeu ; le « vrai test » décrit à la fin de cette section est fait.

Une sauvegarde non restaurée n'est pas une sauvegarde.

```bash
./scripts/sauvegarde.sh                       # produit ~931 Mo dans ~/sauvegardes-genomique/
B=~/sauvegardes-genomique/<horodatage>

# 1. Le dump PostgreSQL est-il un fichier d'archive valide ?
docker cp $B/airflow.dump genomique-postgres:/tmp/t.dump
docker exec genomique-postgres pg_restore --list /tmp/t.dump | head -5   # attendu : PGDMP, ~479 entrées

# 2. Une table Delta sauvegardée se relit-elle hors du lac ?
PYTHONPATH=src:. venv/bin/python -c "
import polars as pl; print(pl.read_delta('$B/silver/clinvar_variant').height, 'lignes')"
```

**Reste à faire, et c'est le vrai test :** restaurer sur une stack vide (`docker compose down -v`
sur une copie, `pg_restore` de la base, `mc mirror` inverse des buckets), puis relancer un run
et vérifier que les volumes du §3 sont retrouvés à l'identique.

---

## 8. Niveau 7 — Justesse métier : la vérification manuelle

**C'est la section la plus importante de ce document.** Elle établit que les données du Gold
correspondent à ce que disent réellement les bases sources.

### 8.1 Trois pièges méthodologiques, à connaître avant de commencer

**Piège 1 — le décalage temporel.** Le pipeline a figé une **archive mensuelle** (septembre
2026 à la rédaction, octobre 2026 pour E3b). Le site de ClinVar affiche l'état **courant**, qui a pu changer depuis. Une divergence
n'est donc pas automatiquement une erreur.

> **Règle de décision :** comparer d'abord la date « Last evaluated » affichée sur le site avec
> la nôtre. Si celle du site est **postérieure**, la divergence est une mise à jour légitime :
> la noter comme telle, et non comme un défaut. Si les deux dates sont **identiques** mais que
> la signification diffère, c'est un vrai défaut.

**Piège 2 — les variants multi-gènes.** ClinVar rattache parfois un variant à plusieurs gènes
séparés par `;` (par exemple `TP53;WRAP53`). Le pipeline conserve la chaîne brute dans
`genesymbol` et éclate la relation dans `clinvar_variant_gene`. Ce n'est pas une incohérence.

**Piège 3 — les valeurs absentes.** ClinVar écrit `-1` quand il n'y a pas d'identifiant dbSNP,
et `-` pour un champ non renseigné. Le Silver conserve ces sentinelles telles quelles ; le
document RAG, lui, **omet la ligne** correspondante. Un document sans ligne « dbSNP » est donc
correct, pas amputé.

### 8.2 L'échantillon de vérification

> **E3b (octobre 2026)** : les onze variants sont toujours dans le Gold. La grille
> `reference/grille_justesse_e3b.md` (`scripts/verifier_justesse.py --grille`) reprend chacun avec
> **nos valeurs d'octobre**, qui priment sur celles du tableau ci-dessous (septembre), et le texte
> de son document RAG. **Maladies** : `PhenotypeList` liste celles de **tous** les RCV, pas
> seulement de la classification germinale (correction P-E3b-1 du rapport).
>
> **7b**, complément automatique : 400 variants tirés au hasard (graine 20261023), comparés aux
> E-utilities sur les mêmes six éléments : 400 conformes, Wilson 95 % [99,05 ; 100].

Onze variants réellement présents dans le Gold, choisis pour couvrir toutes les catégories de
signification clinique, les deux panels et les trois cas particuliers.

| # | Variant | Gène | Signification dans notre Gold | Statut de revue | Évalué le | Fiche ClinVar à ouvrir |
|---|---|---|---|---|---|---|
| 1 | `NM_007294.4(BRCA1):c.116G>A (p.Cys39Tyr)` | BRCA1 | Pathogenic/Likely pathogenic | criteria provided, multiple submitters, no conflicts | Jul 14, 2026 | https://www.ncbi.nlm.nih.gov/clinvar/variation/37392/ |
| 2 | `NM_000059.4(BRCA2):c.1490_1493del (p.Ser497fs)` | BRCA2 | Pathogenic | criteria provided, single submitter | Sep 01, 2020 | https://www.ncbi.nlm.nih.gov/clinvar/variation/1012631/ |
| 3 | `NM_000051.4(ATM):c.8300T>C (p.Leu2767Pro)` | ATM | Likely pathogenic | **reviewed by expert panel** | Jun 11, 2025 | https://www.ncbi.nlm.nih.gov/clinvar/variation/1023669/ |
| 4 | `NM_000059.4(BRCA2):c.1166C>A (p.Pro389Gln)` | BRCA2 | Benign | **reviewed by expert panel** | Jun 18, 2019 | https://www.ncbi.nlm.nih.gov/clinvar/variation/96762/ |
| 5 | `NM_000465.4(BARD1):c.855A>G (p.Gln285=)` | BARD1 | Likely benign | criteria provided, single submitter | Feb 17, 2024 | https://www.ncbi.nlm.nih.gov/clinvar/variation/1017479/ |
| 6 | `NM_000314.8(PTEN):c.-27T>C` | PTEN | Uncertain significance | criteria provided, single submitter | Sep 01, 2020 | https://www.ncbi.nlm.nih.gov/clinvar/variation/1013569/ |
| 7 | `NM_000059.4(BRCA2):c.8602A>G (p.Lys2868Glu)` | BRCA2 | Conflicting classifications of pathogenicity | criteria provided, conflicting classifications | May 15, 2025 | https://www.ncbi.nlm.nih.gov/clinvar/variation/1764023/ |
| 8 | `NM_000314.8(PTEN):c.141_142inv` | PTEN | Pathogenic | criteria provided, single submitter | Jul 22, 2024 | https://www.ncbi.nlm.nih.gov/clinvar/variation/1018969/ |
| 9 | `NM_001143992.2(WRAP53):c.1A>G (p.Met1Val)` | **TP53;WRAP53** | Uncertain significance | criteria provided, multiple submitters, no conflicts | Sep 01, 2022 | https://www.ncbi.nlm.nih.gov/clinvar/variation/1336926/ |
| 10 | `NM_001360016.2(G6PD):c.973G>A (p.Asp325Asn)` | G6PD | Conflicting classifications of pathogenicity | criteria provided, conflicting classifications | Aug 12, 2022 | https://www.ncbi.nlm.nih.gov/clinvar/variation/1014228/ |
| 11 | `NC_000011.10:g.5224303_5227790del` | HBB | Pathogenic | no assertion criteria provided | Mar 01, 2021 | https://www.ncbi.nlm.nih.gov/clinvar/variation/1048666/ |

Cas particuliers représentés : **n° 8 et 11** n'ont pas d'identifiant dbSNP (`rs_dbsnp = -1`) ;
**n° 9** est multi-gènes ; **n° 10 et 11** appartiennent au panel drépanocytose ; **n° 3 et 4**
portent le plus haut niveau de revue (panel d'experts), **n° 11** le plus bas.

### 8.3 Ce qu'il faut comparer, champ par champ

Pour chaque ligne du tableau, ouvrir la fiche et confronter **six éléments** :

| Élément | Où le trouver sur la fiche ClinVar | Tolérance |
|---|---|---|
| Nom HGVS complet | Titre de la page | **Aucune** — doit être identique au caractère près |
| Signification clinique | Encadré « Germline classification » | Aucune, sauf si « Last evaluated » du site est postérieure (piège 1) |
| Statut de revue | Étoiles + libellé sous la classification | Idem |
| Date de dernière évaluation | « Last evaluated » | Le site peut être postérieur ; jamais antérieur |
| Identifiant dbSNP | Section « Allele ID / dbSNP » | Aucune ; absent chez nous = absent sur la fiche |
| Maladies associées | Onglet « Conditions » | Notre liste est un **sous-ensemble** possible : nous écartons les libellés vides (« not provided ») |

**Consigner le résultat de chaque ligne dans la grille du §11.**

### 8.4 Vérifier le document RAG, et pas seulement la table

La table peut être juste et le document mal rédigé. Extraire le texte réellement produit :

```bash
docker exec genomique-airflow-scheduler python -c "
import polars as pl
from ingestion.storage import storage_options
from transformations.silver_to_gold_rag import documents_uri
u = documents_uri()
d = pl.read_delta(u, storage_options=storage_options(u))
print(d.filter(pl.col('doc_id') == 'clinvar:45948').row(0, named=True)['text'])"
```

**Trois vérifications sur le texte obtenu :**

1. Chaque fait énoncé se retrouve sur la fiche ClinVar (c'est la condition de la fidélité, la
   métrique *Faithfulness* de RAGAS annoncée dans la problématique).
2. Le lien de citation `clinvar_url` pointe vers la bonne fiche.
3. Aucune sentinelle résiduelle : le texte ne doit contenir ni `rs-1`, ni `None`, ni
   `Last evaluated: -.`

```bash
docker exec genomique-airflow-scheduler python -c "
import polars as pl
from ingestion.storage import storage_options
from transformations.silver_to_gold_rag import documents_uri
u = documents_uri(); d = pl.read_delta(u, storage_options=storage_options(u))
for motif in ['rs-1', 'None', 'Last evaluated: -.', 'Review status: -']:
    print(motif, ':', d.filter(pl.col('text').str.contains(motif, literal=True)).height)"
```

**Attendu : 0 partout.**

### 8.5 Vérifier les trois autres sources

Le pipeline ne repose pas que sur ClinVar. Un échantillon par source suffit.

| Source | À vérifier | URL de contrôle |
|---|---|---|
| **NCBI Gene** | `description` de BRCA1 = « BRCA1 DNA repair associated », `maplocation` = 17q21.31 | https://www.ncbi.nlm.nih.gov/gene/672 |
| **RefSeq** | `NM_007294` version 4 existe et concerne BRCA1 | https://www.ncbi.nlm.nih.gov/nuccore/NM_007294.4 |
| **MedGen** | Le concept `C1292231` correspond au libellé stocké, et son numéro MIM est 111150 | https://www.ncbi.nlm.nih.gov/medgen/C1292231 |
| **HPO** | `HP:0002027` = « Abdominal pain », définition identique | https://ontology.jax.org/api/hp/terms/HP%3A0002027 |
| **dbSNP** | `rs80357498` renvoie bien au variant n° 1 | https://www.ncbi.nlm.nih.gov/snp/rs80357498 |

> **Note sur OMIM :** `https://www.omim.org/entry/111150` renvoie une erreur 403 aux requêtes
> automatisées. Ouvrir le lien dans un navigateur, ou passer par la fiche MedGen ci-dessus, qui
> référence le même numéro MIM.
>
> **Note sur HPO :** l'adresse de contrôle donnée est celle de l'**API** — c'est exactement la
> source que le pipeline interroge, donc la comparaison est directe. Le navigateur de
> `hpo.jax.org` a changé d'adresse et ses liens profonds ne répondent plus de façon fiable.

---

## 9. Performance — valeurs mesurées de référence

Relevées sur la machine de développement, contre le lac réel. Elles servent de point de
comparaison : une dérive importante signale un problème.

| Étape | Durée | Pic mémoire |
|---|---|---|
| `bronze_to_silver` (brca) | 10 s | 1,37 Go |
| `bronze_to_silver` (sickle) | 5 s | — |
| `silver_to_gold_rag` (brca, 93 381 variants) | 15 s | 716 Mo |
| `silver_to_gold_analytique` (brca) | 3 s | — |
| `quality_check_gold` | 1 s | — |
| Conversion du bulk ClinVar (6 M lignes) | — | ~2 Go |
| Sauvegarde complète | — | 931 Mo produits |

La limite mémoire du conteneur qui exécute les tâches est de **3 Go** : la marge est réelle
mais pas infinie, et c'est ce que surveillera le tableau de bord Infrastructure.

---

## 10. Ce que cette évaluation ne prouve pas

À écrire noir sur blanc dans le mémoire — c'est ce qui distingue une évaluation d'un argumentaire.

1. **La justesse de l'ensemble des 97 192 variants.** Onze sont vérifiés à la main, et 400 tirés
   au hasard sont comparés automatiquement à l'API ClinVar (7b : 400/400, taux d'erreur inférieur
   à 1 % avec 95 % de confiance). Le reste est une inférence statistique, pas une preuve. Et 7b
   vérifie nos transformations, pas ClinVar lui-même : la source est la même.
2. **La stabilité dans le temps.** Un seul mois a été traité. Le mécanisme d'historique SCD2 est
   testé unitairement, mais aucune reclassification réelle n'a encore été observée entre deux
   archives.
3. **Le comportement sur plusieurs années.** Les archives ClinVar antérieures à 2023 ne sont plus
   accessibles par l'URL épinglée : rejouer un historique profond est impossible.
4. **La qualité du RAG.** Les métriques RAGAS annoncées dans la problématique (Faithfulness,
   Answer Relevancy, Context Recall) ne peuvent être mesurées qu'une fois l'étape RAG
   implémentée.
5. **La tenue en charge.** Le pipeline traite 18 gènes. Rien ne prouve son comportement sur 500.

---

## 11. Grille de résultats à remplir

### Niveaux 1 à 4 — automatisés

| Niveau | Commande | Résultat | Date | Conclusion |
|---|---|---|---|---|
| 1 | `pytest -q` | ______ | ______ | ☐ conforme |
| 1 | `pytest tests_airflow -q` | ______ | ______ | ☐ conforme |
| 2 | Run complet des deux panels | ______ | ______ | ☐ conforme |
| 3 | Tests d'injection de faute | ______ | ______ | ☐ conforme |
| 4 | Rejeu sans changement de version Delta | ______ | ______ | ☐ conforme |

### Niveaux 5 et 6 — manuels

| Scénario | Comportement observé | Date | Conclusion |
|---|---|---|---|
| P1 conteneur tué | Tâches reprises au 2ᵉ essai, rien de commité par l'essai tué | 24/10/2026 | ☑ conforme |
| P2 disque saturé | Refus avant tout téléchargement ; échec au 1er essai après correction D-E3b-3 | 24/10/2026 | ☑ conforme (après correction) |
| P3 source indisponible | `ProxyError`, 4 essais, mail d'échec, aucun Asset ni run de panel | 24/10/2026 | ☑ conforme |
| P4 archive tronquée | `quality_check_silver` bloque à 46 % de variants absents, Gold intact | 24/10/2026 | ☑ conforme, réserve O-E3b-2 |
| P5 double déclenchement | Sauté par `skip_if_already_published`, aucun Asset | 24/10/2026 | ☑ conforme |
| P6 mois passé | Refusé au 1er essai (« hors du mois en cours ») | 24/10/2026 | ☑ conforme |
| Restauration complète | Pile vide restaurée, rejeu ; D-E3b-1 trouvé et corrigé | 23/10/2026 | ☑ conforme (après correction) |

### Niveau 7 — justesse métier

> À remplir depuis `reference/grille_justesse_e3b.md` (7a). Le résultat de 7b est dans
> `reference/rapport_e3b.md`.

| # | Nom HGVS | Signification | Statut de revue | Date | dbSNP | Maladies | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 2 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 3 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 4 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 5 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 6 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 7 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 8 | ☐ | ☐ | ☐ | ☐ | — | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 9 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 10 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |
| 11 | ☐ | ☐ | ☐ | ☐ | — | ☐ | ☐ conforme ☐ mise à jour postérieure ☐ **écart** |

**Taux de concordance = (conformes + mises à jour postérieures) / 11.** C'est ce chiffre qui a
sa place dans le mémoire, accompagné du détail de tout écart constaté.

### Sources annexes

| Source | Élément vérifié | Verdict |
|---|---|---|
| NCBI Gene | BRCA1 : description et localisation | ☐ conforme ☐ écart |
| RefSeq | NM_007294.4 | ☐ conforme ☐ écart |
| MedGen | C1292231 et MIM 111150 | ☐ conforme ☐ écart |
| HPO | HP:0002027 et sa définition | ☐ conforme ☐ écart |
| dbSNP | rs80357498 | ☐ conforme ☐ écart |

---

## 12. Ordre recommandé

1. Niveaux 1 à 4 — une demi-heure, tout est automatisé.
2. Niveau 7 — deux heures pour les onze variants et les cinq sources annexes. **À faire en
   premier si le temps manque** : c'est la preuve qui porte devant un jury.
3. Niveaux 5 et 6 — une demi-journée, et à refaire après toute modification de l'infrastructure.
