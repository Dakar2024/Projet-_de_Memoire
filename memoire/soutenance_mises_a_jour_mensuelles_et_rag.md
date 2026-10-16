# Mises à jour mensuelles des données génomiques et impact sur le RAG

*Fiche de préparation à la soutenance. Les chiffres viennent du premier cycle réel de mise à jour
(septembre → octobre 2026), relevés le 12/10/2026.*

---

## 1. L'essentiel en 30 secondes

> ClinVar publie chaque début de mois une **copie complète** de sa base, pas une liste des
> changements. Le 10 de chaque mois, Airflow télécharge cette archive entière et la garde intacte
> dans la couche `raw`, un dossier par mois. La **détection des changements** se fait dans la
> couche Silver : un variant nouveau est ajouté, un variant reclassé garde son ancienne version
> datée et en reçoit une nouvelle (historique SCD2), un variant inchangé n'est pas touché.
> Chaque document du RAG porte une **empreinte SHA-256 de son texte**. À l'indexation, seuls
> les documents dont l'empreinte a changé sont revectorisés.
>
> **On télécharge tout, mais on n'écrit que ce qui a changé.** Sur le cycle réel d'octobre 2026,
> **1 695 documents sur 97 211 (1,7 %)** ont été revectorisés. Le reste n'a pas été touché.

Les ingénieurs de données appellent ce schéma *full extract, incremental load* : extraction
complète, chargement incrémental.

---

## 2. Le déroulement, étape par étape

### Le déclenchement

- `dag_acquisition_sources` est planifié **le 10 du mois à 06 h UTC** (`dags/dag_acquisition_sources.py`).
- **Pourquoi le 10 et pas le 1er ?** L'archive mensuelle de ClinVar paraît entre le 2 et le 6 du
  mois (dates observées : 04/06, 02/07, 06/08, 03/09). Un run le 1er ne la trouverait pas.
- La date de travail est **ramenée au 1er du mois** : le run du 10/10 produit des partitions
  `2026-10-01`.
- Quand le bronze des sources partagées est complet, le DAG publie l'Asset `SOURCES_READY`. Cet
  événement lance automatiquement les deux DAGs de panel : `brca` (cancer du sein, 12 gènes) et
  `sickle` (drépanocytose, 6 gènes).
- `catchup=False` : si la machine était éteinte à l'heure prévue, Airflow exécute le run manqué
  **au redémarrage**, mais ne rejoue pas tous les mois passés. C'est ce qui s'est produit en
  octobre : run prévu le 10/10, exécuté le 11/10 à 11 h 33.

### Couche par couche

| Couche | Comportement | Fichier |
|---|---|---|
| **raw** | Copie complète du mois. ClinVar (~440 Mo) et HPO sont téléchargés en entier. NCBI Gene, RefSeq, MedGen et les termes HPO sont réinterrogés pour les 18 gènes. Chaque mois a sa propre partition, et les anciennes ne sont pas écrasées. | `scripts/ingest_*.py`, `src/ingestion/storage.py` |
| **bronze** | Conversion complète en Parquet, une partition par mois. | `src/transformations/raw_to_bronze.py` |
| **silver – `clinvar_variant`** | **Incrémental avec historique (SCD2).** Comparaison avec la version actuelle sur 3 champs : signification clinique, statut de revue, date d'évaluation. | `src/transformations/bronze_to_silver.py` (`_write_clinvar_variant`) |
| **silver – les 9 autres tables** | **Remplacement complet**, limité au panel, sans historique. | même fichier (`_write_silver_snapshot`) |
| **gold/rag/documents** | **MERGE sur `doc_id`** : un document dont l'empreinte a changé est réécrit, un nouveau est inséré, un document disparu du Silver est supprimé. Un document inchangé n'est pas réécrit. | `src/transformations/silver_to_gold_rag.py` (`write_documents`) |
| **pgvector (index RAG)** | Seuls les documents nouveaux ou modifiés sont revectorisés. Les disparus sont supprimés. | `RAG/src/ingestion/indexer.py`, `RAG/src/utils/diff.py` |

### Les garde-fous

- **Protocole de partition** : `begin` → données → manifeste → `_SUCCESS`. Une partition sans
  `_SUCCESS` est considérée comme incomplète, et l'étape suivante refuse de démarrer.
- **Contrôles qualité** à la sortie du Silver et du Gold. L'indexation ne se lance qu'après le
  contrôle du Gold : un Gold défaillant n'est jamais indexé.
- **Garde-fou de suppression** : l'indexation refuse de supprimer plus de **5 %** de l'index
  (`max_delete_ratio` dans `RAG/config.yaml`), sauf confirmation explicite (`force_deletions`).
- **Canari** : avant d'écrire, l'indexeur vérifie que le modèle d'embedding produit exactement
  le même vecteur qu'à la référence (cosinus 1,000000 en octobre).
- **Verrou par panel** : deux indexations du même panel ne peuvent pas tourner en même temps.
- **Idempotence** : rejouer le même mois ne produit aucune écriture (0 revectorisation mesurée).

---

## 3. Pourquoi ce choix plutôt qu'un autre

### Pourquoi ne pas « ajouter seulement le nouveau » ?

- En génomique clinique, l'information critique est souvent **ce qui change** : un variant de
  signification incertaine qui devient pathogène, ou une classification qui devient
  conflictuelle.
- En ajoutant seulement, on garderait des **classifications périmées**. Le RAG donnerait alors
  une réponse cliniquement fausse tout en citant correctement sa source, ce qui est le pire cas
  possible.
- On ne verrait pas non plus les disparitions.

### Pourquoi ne pas « tout recharger » ?

- Une réindexation complète prend **environ 4 h sur CPU** (environ 9 min sur GPU), contre
  quelques minutes en incrémental.
- Elle ne garderait **pas d'historique** : on perdrait l'information « ce variant était bénin
  jusqu'en septembre ».
- Elle ferait varier l'index sans raison, ce qui gêne la reproductibilité des évaluations.

### Pourquoi télécharger quand même tout ?

- **ClinVar ne fournit pas de liste fiable des changements** pour `variant_summary`. La seule
  manière de savoir ce qui a changé est de comparer avec ce qu'on a déjà.
- Garder chaque copie mensuelle en `raw` rend tout **reproductible et auditable** : on peut
  reconstruire n'importe quel mois, ou rejouer le pipeline après la correction d'un bug.

### Pourquoi l'historique seulement sur ClinVar ?

L'historique n'a de valeur que là où il a un **sens clinique**, c'est-à-dire pour les
reclassifications. Pour une description de gène ou un terme HPO, il n'apporte rien : un
remplacement complet suffit, et les versions anciennes restent de toute façon en `raw` et en
bronze.

### Pourquoi une empreinte SHA-256 du texte ?

- Le texte est **la seule chose que le modèle d'embedding voit**. Si le texte n'a pas changé,
  le vecteur ne changera pas : le recalculer serait du gaspillage.
- Le texte est produit de façon **déterministe** (tris stables), pour que la même donnée donne
  toujours la même empreinte.
- L'empreinte du **modèle** fait aussi partie de la comparaison : si l'on change de modèle,
  tout l'index est revectorisé automatiquement, puisqu'on ne peut pas mélanger des vecteurs de
  deux modèles.

---

## 4. Le cycle réel septembre → octobre 2026

| Étape | Résultat |
|---|---|
| Acquisition (ClinVar et HPO d'octobre) | réussie, 2 min 23 s |
| DAG `brca` | réussi, 16 min 30 s (de l'ingestion NCBI à l'indexation) |
| DAG `sickle` | réussi, 17 min 40 s |

**Silver, historique ClinVar**

| | Nombre |
|---|---|
| Variants nouveaux | **301** |
| Anciennes versions fermées | **990** |
| … dont la signification clinique a changé | **214** |
| … dont le statut de revue a changé | 423 |
| … dont seule la date d'évaluation a changé | 479 |

Les trois dernières lignes se recoupent : une même version peut avoir changé à la fois de
signification et de statut de revue. La table `fact_reclassification` du Gold analytique compte
990 lignes (elle était vide avant).

**Reclassifications les plus fréquentes**

| Avant | Après | Nombre |
|---|---|---|
| Pathogenic | Pathogenic/Likely pathogenic | 76 |
| Uncertain significance | Conflicting classifications | 29 |
| Benign | Benign/Likely benign | 26 |
| Likely benign | Conflicting classifications | 18 |
| Likely pathogenic | Conflicting classifications | 8 |

**Index RAG**

| Panel | Revectorisés | Inchangés | Supprimés |
|---|---|---|---|
| brca | 1 508 | 92 120 | 0 |
| sickle | 187 | 3 396 | 0 |
| **Total** | **1 695 (1,7 %)** | 95 516 | 0 |

**D'où viennent les 1 695 revectorisations** (vérifié par comparaison des textes entre les deux
versions Delta du Gold) :

| Origine | Documents |
|---|---|
| Variants nouveaux (insertions) | 301 |
| Variants dont une version a été fermée (SCD2) | 990 |
| Liste des **maladies associées** modifiée par ClinVar, sans changement de classification | 401 |
| Documents de gène | 3 |
| **Total** | **1 695** |

Les 401 cas du milieu montrent que le mécanisme par empreinte rattrape **aussi** des changements
que le SCD2 ne surveille pas volontairement, par exemple un soumissionnaire qui ajoute une
maladie. Le document du RAG reste donc à jour, même quand ce changement n'est pas une
« reclassification ».

---

## 5. L'impact sur le RAG

| Question | Réponse |
|---|---|
| Les anciens vecteurs restent-ils dans l'index ? | Non. Un document modifié est **remplacé** (`ON CONFLICT … DO UPDATE`), un document disparu est supprimé. Il n'y a pas de doublon. |
| Le RAG est-il mis à jour sans intervention ? | Oui. L'indexation est la dernière tâche de chaque DAG de panel. |
| Que voit l'utilisateur pour un variant reclassé ? | Le document contient « Classification history: previously X until date ». **Le code**, et non le LLM, ajoute à la réponse une phrase « Historique ClinVar … ». Le LLM n'a pas le droit de raconter l'historique lui-même : les mots « auparavant » ou « reclassé » dans sa réponse la font rejeter. 214 documents portent cette ligne depuis octobre. |
| Sait-on de quel mois vient une information ? | Oui. Chaque document porte `source_version`, et la réponse cite l'archive. |
| Faut-il redémarrer l'API ? | Non. L'API lit la base vectorielle à chaque question, sans cache de documents. |
| Que se passe-t-il pendant la mise à jour ? | L'index est validé **lot par lot**. Pendant quelques minutes, une question peut voir certains documents déjà mis à jour et d'autres pas encore. Pour un pipeline mensuel, c'est acceptable. |

---

## 6. Les limites, à annoncer soi-même

1. **Un variant retiré par ClinVar n'est jamais fermé dans le Silver.** Son document reste dans
   le RAG. C'est une limite documentée, compensée par une alerte de `quality_check_silver`
   au-delà de 5 %. C'est aussi pourquoi l'index n'a compté **0 suppression** en octobre.
2. **`source_version` est le mois de la dernière modification**, pas celui de la dernière
   vérification. Un document inchangé depuis septembre affiche « 2026-09 » alors qu'il a été
   revérifié en octobre. Après octobre, l'index contient 95 516 documents « 2026-09 » et
   1 695 documents « 2026-10 ».
3. **La mise à jour de l'index n'est pas une seule transaction** (voir § 5).
4. **Les tables Silver autres que ClinVar n'ont pas d'historique** : seules les copies `raw` et
   bronze gardent les anciennes versions.
5. **Les évaluations sont liées à un mois donné.** Les jeux de questions E2a et la recette E2b
   ont été construits sur septembre 2026. La recette E2b a d'ailleurs été commencée sur
   l'index de septembre (43/99) et se poursuit sur celui d'octobre. Les comparaisons de
   mesures refusent de démarrer si les documents ont changé
   (`RAG/tests/test_comparaison.py`).
6. **Aucune sauvegarde automatique** (`reference/audit_production.md`, P2). Les archives
   ClinVar antérieures à 2023 ne sont plus accessibles par l'URL épinglée : si les volumes
   étaient perdus, l'historique des reclassifications serait **définitivement** perdu.
7. **Stockage** : environ 440 Mo de plus par mois en `raw`, sans durée de conservation définie.

---

## 7. Questions probables du jury et réponses

**« Comment vos données sont-elles mises à jour ? »**
→ Par un DAG Airflow mensuel, le 10 du mois. Il télécharge l'archive complète de ClinVar et
réinterroge les API NCBI et HPO. Les changements sont détectés dans le Silver, puis propagés
jusqu'à l'index vectoriel par empreinte de texte.

**« Vous rechargez tout ou seulement le nouveau ? »**
→ Ni l'un ni l'autre. On télécharge tout, parce que ClinVar ne publie pas de liste des
changements. On n'écrit que ce qui a changé, y compris les modifications et les disparitions,
pas seulement les ajouts. En octobre, 1,7 % de l'index a été recalculé.

**« Pourquoi pas seulement les ajouts ? »**
→ Parce qu'une reclassification n'est pas un ajout. 214 variants ont changé de signification
clinique en un seul mois. En ajoutant seulement, le RAG répondrait avec l'ancienne
classification.

**« Comment savez-vous qu'un document a changé ? »**
→ Par une empreinte SHA-256 de son texte, calculée dans le Gold. Si le texte n'a pas changé,
le vecteur ne changera pas, donc on ne le recalcule pas. L'empreinte du modèle d'embedding est
aussi comparée.

**« Que se passe-t-il si un variant change de classification ? »**
→ Dans le Silver, l'ancienne ligne est fermée (`valid_to`, `is_current = false`) et une
nouvelle est créée. Le document Gold est réécrit avec une ligne d'historique, puis revectorisé.
La réponse du RAG donne la classification actuelle, suivie d'une phrase d'historique ajoutée
par le code.

**« Et si le téléchargement échoue à moitié ? »**
→ La partition n'a pas de marqueur `_SUCCESS`, donc l'étape suivante refuse de démarrer.
Airflow relance la tâche 3 fois, à 5 min d'intervalle. Le rejeu est idempotent.

**« Et si une mise à jour vide la base par erreur ? »**
→ Le garde-fou refuse de supprimer plus de 5 % de l'index sans confirmation explicite.

**« Et si vous changez de modèle d'embedding ? »**
→ L'empreinte du modèle ne correspond plus, donc tout l'index est revectorisé. Au démarrage,
l'API vérifie aussi que le modèle servi est bien celui qui a construit l'index.

**« Avez-vous testé ce mécanisme ? »**
→ Oui, à deux niveaux. Des tests unitaires couvrent l'historique SCD2, le MERGE du Gold et la
revectorisation sélective. Il y a aussi un cycle réel : septembre → octobre 2026, avec 990
versions fermées, 301 nouveaux variants et 1 695 documents revectorisés, sans erreur.

**« Pourquoi Airflow le 10 et pas le 1er ? »**
→ L'archive mensuelle de ClinVar paraît entre le 2 et le 6. Le 10 laisse une marge.

**« Que se passe-t-il si le serveur est éteint le 10 ? »**
→ Airflow exécute le run manqué au redémarrage. C'est arrivé en octobre : prévu le 10/10,
exécuté le 11/10, sans intervention.

**« Quelles sont les limites ? »**
→ Annoncer les points 1, 2 et 6 du § 6 : variants retirés non fermés, sens de `source_version`,
absence de sauvegarde.

**« Comment l'améliorer ? »**
→ Fermer dans le Silver les variants absents de l'archive du mois. Ajouter un champ « dernière
vérification » distinct de `source_version`. Mettre en place une sauvegarde automatique des
volumes. À plus long terme, envoyer une notification à chaque reclassification d'un variant
pathogène.

---

## 8. Où le montrer dans le code

| Pour montrer… | Ouvrir |
|---|---|
| La planification mensuelle | `dags/dag_acquisition_sources.py` (`schedule="0 6 10 * *"`) |
| L'enchaînement complet jusqu'à l'index | `dags/dag_genomic_pipeline.py` |
| L'historique SCD2 | `src/transformations/bronze_to_silver.py`, `_write_clinvar_variant` |
| L'empreinte du texte | `src/transformations/silver_to_gold_rag.py`, `chunk_id` |
| Le MERGE du Gold | `src/transformations/silver_to_gold_rag.py`, `write_documents` |
| La phrase d'historique | `src/transformations/silver_to_gold_rag.py`, `_previous_significance` |
| La revectorisation sélective | `RAG/src/utils/diff.py`, `plan_sync` ; `RAG/src/ingestion/indexer.py` |
| Le garde-fou de suppression | `RAG/src/utils/diff.py`, `check_deletion_guard` ; `RAG/config.yaml` |
| Les runs réels | interface Airflow : runs du 11/10/2026 des trois DAGs |
