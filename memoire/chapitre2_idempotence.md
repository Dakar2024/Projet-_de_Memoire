## Idempotence de la chaîne de traitement

### 1. Définition et enjeu

**Une opération est idempotente quand l'exécuter plusieurs fois produit le même état qu'une
seule exécution.** Appliquée à un pipeline de données, la propriété signifie qu'une étape peut
être relancée sur les mêmes entrées sans créer de doublons, sans perdre de données et sans
modifier ce qui n'a pas changé (Kleppmann, 2017 ; Helland, 2012).

**Dans ce projet, l'idempotence n'est pas un raffinement : c'est une condition de
fonctionnement.** Le pipeline tourne une fois par mois sans surveillance, sur des sources
publiques sujettes aux coupures réseau et aux limitations de débit. L'orchestrateur Apache
Airflow relance donc automatiquement une tâche en échec, jusqu'à trois fois à cinq minutes
d'intervalle, et la documentation d'Airflow pose en principe que toute tâche doit pouvoir être
rejouée sans effet de bord. Deux autres situations exigent la même garantie :
- **le rejeu manuel d'un mois passé**, après la correction d'une anomalie ;
- **la reprise après une panne**, lorsqu'un conteneur s'arrête au milieu d'une écriture.

Sans idempotence, chacune de ces situations risquerait de dupliquer des variants, de fausser
l'historique des reclassifications ou de faire recalculer inutilement les vecteurs du RAG, au
prix de plusieurs heures de calcul.

**La difficulté tient au stockage choisi.** Le lac de données repose sur MinIO, un stockage
objet compatible S3. Contrairement à un système de fichiers, un stockage objet n'offre pas de
renommage atomique : on ne peut pas écrire un résultat à côté puis le substituer d'un coup à
l'ancien. Une écriture interrompue peut donc laisser une partition à moitié remplie, qu'une étape
suivante lirait comme complète. L'idempotence doit alors être construite explicitement, couche
par couche.

### 2. Principe général : une partition déterminée par la date logique

**Chaque exécution travaille sur une date logique, et non sur la date du jour.** Cette date est
toujours ramenée au premier jour du mois. Le run planifié du 10 octobre et un rejeu manuel lancé
le 25 travaillent donc tous deux sur `dt=2026-10-01`.

**Les données sont rangées dans des partitions dont le chemin ne dépend que de cette date**, de
la source et, le cas échéant, du panel de gènes :

```
raw/clinvar/dt=2026-10-01/
bronze/ncbi_gene/dt=2026-10-01/panel=brca/
```

Rejouer le mois d'octobre réécrit ainsi les partitions d'octobre, et elles seules. Aucune
exécution ne peut déborder sur un autre mois ou sur un autre panel.

### 3. Couches raw et bronze : un protocole d'écriture en quatre temps

**Pour compenser l'absence de renommage atomique, chaque partition est écrite selon un protocole
fixe** :
1. le marqueur de complétude `_SUCCESS` éventuellement laissé par une exécution précédente est
   d'abord supprimé ;
2. les données sont écrites ;
3. un manifeste décrit la partition : source, version de la source, fichiers, nombre
   d'enregistrements ;
4. le marqueur `_SUCCESS` est écrit **en dernier**.

**L'ordre de ces opérations porte toute la garantie.** Si l'exécution s'interrompt avant la
quatrième étape, la partition n'a pas de marqueur : elle est considérée comme incomplète. La
tâche de contrôle qui sépare chaque couche de la suivante vérifie à la fois la présence du
marqueur et un nombre d'enregistrements strictement positif, et bloque la propagation sinon. Si
le rejeu aboutit, la partition est simplement réécrite par-dessus l'ancienne.

**Les téléchargements suivent la même logique.** Les fichiers volumineux (440 Mo pour le fichier
ClinVar) sont écrits dans un fichier temporaire `.part`, renommé seulement une fois le transfert
complet et sa taille vérifiée. Un téléchargement coupé ne peut donc jamais être réutilisé par
erreur comme un fichier complet.

**Rejouer un mois n'a de sens que si l'on relit les mêmes données.** Le fichier « latest » de
ClinVar est remplacé plusieurs fois par mois : un rejeu qui le relirait mélangerait deux
versions. Le pipeline télécharge donc **l'archive mensuelle immuable** du mois traité
(`variant_summary_2026-10.txt.gz`). Pour l'ontologie HPO, le tag de version publié
(`v2026-09-01`) est résolu une fois puis **inscrit dans le manifeste**. Lors d'un rejeu, ce tag
est relu dans le manifeste au lieu de prendre la dernière version publiée.

Ce point a été corrigé pendant le développement. Une première version utilisait les adresses
« latest ». Un audit interne a montré qu'un rejeu du mois d'août aurait alors silencieusement
téléchargé les données de septembre : le pipeline pouvait être relancé, mais sans reproduire
l'exécution d'origine.

### 4. Couche Silver : remplacer ou fusionner selon la nature de la table

La couche Silver compte dix tables au format Delta Lake (Armbrust et al., 2020). Elles relèvent
de deux stratégies distinctes.

**Les neuf tables sans historique** (gènes, maladies, phénotypes, transcrits…) sont **remplacées
intégralement pour le panel traité** à chaque exécution. L'écriture Delta est restreinte au
panel par un prédicat (`panel = 'brca'`). Le résultat d'un rejeu est donc identique à celui de la
première exécution, et l'autre panel n'est jamais touché.

**La table des variants conserve leur historique de classification** selon le modèle des
dimensions à évolution lente de type 2, ou SCD2 (Kimball et Ross, 2013) : chaque changement de
signification clinique crée une nouvelle version, l'ancienne étant clôturée par une date de fin.
C'est le cas le plus délicat. Une insertion naïve ajouterait une version à chaque rejeu et
inventerait des reclassifications qui n'ont jamais eu lieu. L'écriture passe donc par une
opération `MERGE` qui :
- compare chaque variant à sa version courante sur **trois champs surveillés seulement** :
  signification clinique, statut de revue, date de dernière évaluation ;
- n'écrit rien pour un variant dont ces champs sont inchangés ;
- pour un variant modifié, clôture l'ancienne version et insère la nouvelle.

Deux précautions rendent la comparaison exacte :
- une **comparaison tolérante aux valeurs nulles** (`ne_missing`), sans laquelle une valeur
  absente des deux côtés serait vue comme un changement ;
- un **indicateur explicite de correspondance**, qui distingue « variant absent de l'historique »
  de « variant dont un champ surveillé est nul ».

Sans elles, chaque rejeu recréerait des versions pour les variants concernés.

### 5. Couche Gold et index du RAG : n'écrire que ce qui a changé

**Les documents destinés au RAG sont fusionnés sur leur identifiant**, là encore par un `MERGE`.
Chaque document porte une empreinte SHA-256 de son texte, le `chunk_id`. Un document n'est
réécrit que si cette empreinte a changé ; un document disparu de la couche Silver est supprimé.

Cette règle impose une contrainte forte : **le texte d'un document doit être strictement
déterministe**. Si deux exécutions sur les mêmes données produisaient deux textes différents,
leurs empreintes divergeraient et le document serait réécrit à chaque rejeu. Le texte peut
varier pour deux raisons :
- l'ordre d'affichage des maladies associées, que Polars ne garantit pas sans demande explicite ;
- l'endroit où un résumé trop long est tronqué.

Les tris sont donc rendus stables (`maintain_order=True`) et la troncature coupe toujours au
même mot.

**L'indexation vectorielle prolonge le même principe.** Avant tout calcul, elle compare
l'état de la couche Gold à celui de la base vectorielle et ne vectorise que trois cas : les
documents nouveaux, les documents dont l'empreinte a changé, et ceux qui avaient été vectorisés
par un autre modèle. Les lots sont validés un à un : une indexation interrompue ne perd que le
lot en cours, et sa relance ne traite que le reste. Un verrou PostgreSQL interdit deux
indexations simultanées du même panel. Un garde-fou refuse de supprimer une part anormale de
l'index : il évite qu'une couche Gold lue incomplètement ne vide la base.

### 6. Vérification

L'idempotence a été vérifiée par la suite de tests automatisés et sur les données réelles.

| Couche | Rejeu d'un mois déjà traité | Résultat observé |
|---|---|---|
| Silver — table des variants (SCD2) | rejeu du 23/09/2026 | aucune nouvelle version Delta |
| Gold — documents du RAG (97 211 documents) | rejeu d'octobre 2026, le 15/10/2026 | version Delta inchangée (3), empreinte SHA-256 de la table identique, 19 s |
| Index vectoriel (96 910 documents) | rejeu du même mois, sur CPU | 0 document recalculé, 0 écriture, 3 s |

Le dernier résultat illustre l'intérêt pratique de la propriété. Une réindexation complète sur
processeur dure environ quatre heures, alors que le rejeu d'un mois inchangé s'achève en trois
secondes. Relancer le pipeline est donc sans risque, et presque sans coût.

**Les services d'amorçage de l'infrastructure sont eux aussi idempotents**, puisqu'ils
s'exécutent à chaque démarrage de la plateforme :
- la création des buckets ignore ceux qui existent déjà ;
- la migration de la base d'Airflow et la déclaration des pools peuvent être rejouées ;
- le schéma de la base vectorielle n'utilise que des créations conditionnelles
  (`IF NOT EXISTS`), et une double exécution a été vérifiée.

### 7. Limites

**L'idempotence est garantie sur la structure des données ; elle ne l'est sur leur contenu que
pour les sources versionnées.** ClinVar et HPO publient des versions datées : un rejeu relit
exactement les mêmes fichiers. En revanche, les API de NCBI Gene, RefSeq et MedGen n'offrent pas
de version figée. Rejouer un mois ancien renvoie leur réponse actuelle, et non celle de
l'exécution d'origine. Le rejeu reste sans doublon ni corruption, mais ces trois sources ne sont
pas reproductibles à l'identique. Le manifeste enregistre honnêtement la date d'interrogation
comme version de la source.

**La reproductibilité du passé dépend aussi de la disponibilité des archives.** Les archives
mensuelles de ClinVar antérieures à 2023 ne sont plus téléchargeables à l'adresse épinglée. Un
historique de reclassifications perdu ne pourrait donc pas être reconstruit par un simple rejeu.
C'est pourquoi le lac de données et la base vectorielle font l'objet d'une sauvegarde
hebdomadaire, dont la restauration a elle-même été vérifiée.

---

<!--
Notes pour l'auteur (à supprimer avant export) :

1. Numérotation : section prévue pour le chapitre II (pré-traitement à travers les couches du
   pipeline) ; renuméroter (II.x) selon le plan définitif.

2. Références à vérifier et à ajouter à la bibliographie :
   - Kleppmann M. (2017). Designing Data-Intensive Applications. O'Reilly.
   - Helland P. (2012). « Idempotence Is Not a Medical Condition ». ACM Queue, 10(4).
   - Kimball R., Ross M. (2013). The Data Warehouse Toolkit, 3e éd. Wiley (dimensions à évolution lente, type 2).
   - Armbrust M. et al. (2020). « Delta Lake: High-Performance ACID Table Storage over Cloud
     Object Stores ». Proceedings of the VLDB Endowment, 13(12).
   - Documentation Apache Airflow, « Best Practices » (tâches idempotentes) : citer la version 3.

3. Sources des mesures du §6 :
   - Silver : reference/etat_implementation.md (historique Delta, rejeu du 23/09).
   - Gold : rejeu du 15/10/2026 (silver_to_gold_rag, 2026-10-01, brca puis sickle) : version
     Delta 3 → 3, 97 211 documents, empreinte de la table (panel, doc_id, chunk_id, texte,
     signification, collected_at) e8a1ab31… avant et après ; 17,0 s + 1,9 s.
     Pour comparaison, la mise à jour réelle septembre → octobre (versions 2 et 3) a inséré
     301 documents, en a réécrit 1 394 et recopié les 95 516 autres sans réécriture.
   - Index : RAG/README.md §6 (mesures du 04/10/2026).

4. Le scénario de panne « conteneur tué en plein run » (reference/evaluation.md §6, P1) n'a pas
   encore été exécuté. Le réaliser permettrait d'ajouter une ligne « reprise après panne » au
   tableau du §6.

5. Une figure du protocole en quatre temps (§3) serait utile : frise begin → données →
   manifeste → _SUCCESS, avec le point d'interruption et le contrôle qui bloque la suite.
-->
