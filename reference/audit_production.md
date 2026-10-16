# Audit de robustesse en production

**Date :** 25 septembre 2026
**Objet :** identifier les pannes susceptibles de se produire en exploitation réelle, par
opposition à l'audit de sécurité (`audit_securite.md`) qui traite des accès et des secrets.
**Périmètre :** ordonnancement Airflow, reprise sur incident, consommation de ressources,
durabilité du stockage, dérive des sources externes, observabilité.
**Méthode :** lecture du code et de la configuration, mesures sur la machine et sur le lac
réel (environ 97 000 variants, deux panels de gènes).

---

## 1. Ce qui doit tenir en production

Le pipeline s'exécute **une fois par mois**, sans surveillance humaine continue. Cette cadence
gouverne tous les risques qui suivent : une panne passée inaperçue ne se manifeste pas le
lendemain, mais au mois suivant — ou, plus vraisemblablement, le jour où l'on consulte les
données et qu'on les trouve incomplètes.

Trois propriétés comptent, dans cet ordre :

1. **On doit savoir qu'une panne a eu lieu.** Un pipeline mensuel qui échoue en silence produit
   un trou de données que rien ne signale.
2. **On doit pouvoir revenir en arrière.** Les archives mensuelles ClinVar antérieures à 2023 ne
   sont plus accessibles par l'URL épinglée : l'historique des reclassifications, qui est la
   contribution propre de ce pipeline, ne se reconstruit pas.
3. **On doit pouvoir comprendre après coup.** Diagnostiquer un échec suppose que ses traces
   existent encore.

Le système est aujourd'hui déficient sur les trois.

---

## 2. Synthèse

Dix-neuf constats, dont cinq retenus comme prioritaires.

| Domaine | Constats | Dont bloquants |
|---|---|---|
| Observabilité et alerte | 3 | 2 |
| Durabilité et sauvegarde | 4 | 1 |
| Ordonnancement et reprise | 3 | 1 |
| Ressources (mémoire, disque) | 3 | 1 |
| Dérive des sources externes | 4 | 0 |
| Cohérence des données dans le temps | 2 | 1 |

---

## 3. Constats

### 3.1 Observabilité et alerte

| Réf. | Constat | Probabilité | Impact |
|---|---|---|---|
| **P1** | **Aucune alerte n'existe** : ni e-mail, ni rappel de fin de tâche, ni serveur d'envoi configuré. Scénario complet : le 10 du mois, l'archive ClinVar n'est pas encore publiée (elle paraît habituellement entre le 2 et le 6, mais rien ne le garantit) ; le téléchargement échoue en 404 ; trois tentatives espacées de cinq minutes échouent aussi ; l'Asset de fin d'acquisition n'est donc jamais émis ; **les deux DAGs de panel ne se déclenchent pas du tout**. Le mois est absent, et rien ne le signale. | Élevée | **Bloquant** |
| **P3** | **Les logs d'Airflow ne survivent pas à une reconstruction.** Aucun volume n'est monté sur `/opt/airflow/logs` : les journaux résident dans le système de fichiers des conteneurs. Un `docker compose up -d --build`, une montée de version ou un simple `down` efface l'intégralité des logs de tâches. Le post-mortem d'un incident de la semaine précédente est alors impossible. | Certaine | **Bloquant** |
| P17 | **Aucune procédure de reprise écrite.** Que faire si un mois manque, si une table Gold est corrompue, si le stockage est perdu ? La réponse n'existe que dans la mémoire de l'auteur. | — | Élevé |

### 3.2 Durabilité et sauvegarde

| Réf. | Constat | Probabilité | Impact |
|---|---|---|---|
| **P2** | **Aucune sauvegarde**, ni du stockage objet, ni de la base de métadonnées d'Airflow. Une suppression de volumes, une panne de disque ou une fausse manœuvre efface les quatre couches. Les mois récents seraient rejouables ; les anciens non (voir P16). L'historique SCD2 des reclassifications serait **définitivement perdu**. | Moyenne | **Bloquant** |
| P10 | MinIO fonctionne en nœud unique sur un disque unique, sans réplication ni code d'effacement. Une défaillance matérielle perd l'ensemble du lac. | Faible | Critique |
| P11 | Aucune politique de rétention Delta (`VACUUM`) : les versions obsolètes et le journal de transactions croissent sans borne. **✅ 16/10/2026** : tâche `vacuum_delta_tables` en fin de DAG de panel, rétention 30 jours (une erreur vue au run mensuel suivant reste rattrapable) ; le journal suit `logRetentionDuration`, 30 jours par défaut. | Certaine | Faible |
| P12 | **Tout changement de schéma interrompt le pipeline.** Constaté pendant l'audit : renommer une colonne d'une table Gold provoque une `SchemaMismatchError` sur la table existante, et impose de supprimer la table puis de relancer. La procédure est documentée dans le README, mais reste une intervention manuelle à chaud. | Moyenne | Moyen |

### 3.3 Ordonnancement et reprise

| Réf. | Constat | Probabilité | Impact |
|---|---|---|---|
| P4 | `catchup=False` : si la machine est éteinte le 10 à 6 h UTC, le run mensuel **n'est jamais rattrapé automatiquement**. Le rattrapage manuel est documenté, encore faut-il savoir qu'il est nécessaire — ce que P1 empêche. | Élevée sur poste de travail | Élevé |
| P5 | Aucun `max_active_runs` sur les DAGs de panel : deux événements d'Asset (un rattrapage manuel pendant un run planifié) déclenchent deux exécutions simultanées du même panel. Les pools à un créneau protègent les écritures Silver et Gold, **mais pas les ingestions vers `raw`** : deux écrivains sur la même partition. Le marqueur de complétude limite les dégâts sans les exclure. | Faible | Moyen |
| P6 | Les pools à un créneau sérialisent correctement les écritures partagées, mais constituent un point de contention : une tâche lente occupe le seul créneau et retarde l'autre panel, jusqu'à la limite de trois heures fixée par `execution_timeout`. | Moyenne | Faible |

### 3.4 Ressources

| Réf. | Constat | Probabilité | Impact |
|---|---|---|---|
| P7 | **La limite mémoire tient par l'ordre du graphe, pas par construction.** Le conteneur qui exécute les tâches est plafonné à 3 Go et autorise quatre tâches simultanées. Mesures sur les données réelles : conversion du bulk ClinVar ≈ 2 Go, `bronze_to_silver` 1,37 Go, `silver_to_gold_rag` 716 Mo. Deux conversions lourdes concurrentes dépassent la limite. Le graphe les sépare aujourd'hui, mais un rejeu manuel lancé pendant un run planifié ne s'en soucie pas. Ce pipeline a déjà subi un arrêt pour dépassement mémoire pendant son développement. | Moyenne | Élevé |
| **P8** | **Croissance disque non gérée.** `data/external` grossit de 442 Mo par mois sur l'hôte et n'est jamais purgé ; le lac ajoute environ 885 Mo par mois en `raw` et `bronze`. Soit à peu près 16 Go par an sur l'hôte et 11 Go dans MinIO, sans aucune surveillance ni seuil d'alerte. Le disque actuel est occupé à 39 %, ce qui laisse plusieurs années — mais un disque plein pendant un téléchargement de 440 Mo produit un échec tardif et opaque. | Certaine | Moyen |
| P9 | Aucune règle de cycle de vie MinIO : les envois multipart interrompus restent stockés indéfiniment sans apparaître dans les listings ordinaires. **✅ 16/10/2026** : constat inexact pour les envois interrompus, MinIO les supprime déjà (`stale_uploads_expiry=24h`, vérifié par `mc admin config get … api`). Règle de cycle de vie ajoutée pour les versions anciennes (30 jours, sauf `raw`), nécessaire depuis le versioning (M3). | Faible | Faible |

### 3.5 Dérive des sources externes

Sur la durée de vie d'un projet, ces événements ne sont pas hypothétiques.

| Réf. | Constat | Probabilité à 3 ans | Impact |
|---|---|---|---|
| P13 | ClinVar renomme ou supprime une colonne : `bronze_to_silver` la sélectionne par son nom et échoue. L'échec est franc et immédiat — c'est le bon comportement — mais le pipeline reste arrêté jusqu'à correction. | Élevée | Moyen |
| P14 | NCBI restreint l'accès pour usage jugé excessif : environ 1 200 appels par exécution, à trois requêtes par seconde sans clé API. Les tentatives puis l'échec sont corrects, mais un blocage prolongé arrête tous les panels. | Moyenne | Moyen |
| P15 | L'URL du fichier HPO est une redirection `purl.obolibrary.org` : un changement de cible casse le téléchargement. | Moyenne | Moyen |
| **P16** | **Les archives ClinVar antérieures à 2023 ne sont pas accessibles** par l'URL épinglée (elles sont rangées dans des sous-dossiers par année). Rejouer un mois ancien est donc impossible. C'est ce constat qui rend P2 irréversible. | Certaine, déjà vrai | Élevé |

### 3.6 Cohérence des données dans le temps

| Réf. | Constat | Probabilité | Impact |
|---|---|---|---|
| **P18** | **Aucun contrôle de plausibilité d'un mois sur l'autre.** Les contrôles qualité existants vérifient la *cohérence entre couches* — que le Gold reflète fidèlement le Silver — et non la *vraisemblance* du volume. Si ClinVar publiait une archive tronquée, le Gold refléterait fidèlement un Silver appauvri et tous les contrôles resteraient verts. | Faible | **Bloquant** |
| P19 | **Un variant retiré de ClinVar reste marqué comme courant indéfiniment.** Vérifié dans le code : le `MERGE` SCD2 clôture une ligne lorsque la signification clinique, le statut de revue ou la date d'évaluation changent, mais ne clôture jamais un `alleleid` absent du nouveau lot. Conséquence d'une archive tronquée : `clinvar_variant` ne rétrécit pas (il conserve des variants périmés) alors que `clinvar_variant_gene` et `clinvar_variant_disease`, qui sont des instantanés, rétrécissent. Le Silver diverge silencieusement de sa source, sans qu'aucun contrôle actuel ne puisse le voir. | Faible | Élevé |

---

## 4. Ce qui protège déjà

L'audit ne relève aucune faiblesse dans les mécanismes de correction mis en place pendant le
développement. Ils méritent d'être cités, car ils portent l'essentiel de la fiabilité actuelle :

- **Les contrôles qualité entre couches échouent bruyamment** et comparent chaque couche à une
  source indépendante plutôt qu'à elle-même. Deux défauts réels ont été détectés ainsi pendant
  le développement du Gold.
- **L'idempotence des rejeux est vérifiée**, par des tests et en conditions réelles : rejouer un
  mois ne crée aucune version Delta supplémentaire sur la table des documents.
- **Le protocole d'écriture des partitions** (fichier temporaire, renommage atomique, manifeste,
  puis marqueur de complétude) empêche qu'une partition interrompue soit lue comme complète.
- **Toute tâche est bornée dans le temps** (deux à trois heures selon le DAG), et les erreurs de
  configuration ne consomment pas les tentatives.
- **Les conteneurs redémarrent seuls**, avec des sondes de santé sur chaque service et des
  limites mémoire justifiées par des mesures.

---

## 5. Les cinq corrections prioritaires

Choisies parce qu'elles suppriment un risque irréversible ou une cécité, et non un simple
inconfort.

| Rang | Correction | Constats couverts | Justification |
|---|---|---|---|
| 1 | **Alerter par e-mail à chaque échec de tâche**, via le relais SMTP du fournisseur déjà retenu pour le backend de l'application. | P1, et indirectement P4 | Sans cela, tous les autres défauts deviennent invisibles. C'est la correction qui conditionne l'utilité des autres. |
| 2 | **Sauvegarder le stockage objet et la base de métadonnées**, avec rotation, hors du disque du projet. | P2, P10 | Seule parade à une perte irréversible, puisque les archives anciennes ne sont plus téléchargeables. |
| 3 | **Persister les logs d'Airflow** dans un volume dédié. | P3 | Une ligne de configuration ; sans elle, aucun diagnostic a posteriori n'est possible. |
| 4 | **Contrôler la plausibilité du volume** : bloquer si la proportion de variants encore courants mais absents de l'instantané du mois dépasse un seuil. | P18, P19 | Transforme une divergence silencieuse en échec explicite, donc en alerte. |
| 5 | **Purger les téléchargements anciens et vérifier l'espace libre** avant de télécharger. | P8 | Évite l'échec tardif et opaque d'un disque saturé, et borne une croissance aujourd'hui infinie. |

---

## 6. Recommandations restantes

Par ordre d'intérêt décroissant, si le pipeline devait tourner durablement sans surveillance.

1. **Limiter à une exécution simultanée par DAG de panel** (P5) : une ligne de configuration.
2. **Rattraper automatiquement un mois manqué**, ou à tout le moins alerter sur son absence (P4).
3. **Découpler les conversions lourdes** de la limite mémoire du conteneur, en les sérialisant
   par un pool dédié plutôt qu'en comptant sur l'ordre du graphe (P7).
4. **Définir une rétention Delta** et une règle de cycle de vie MinIO (P11, P9).
5. **Écrire la procédure de reprise** : mois manquant, table corrompue, stockage perdu (P17).
6. **Épingler explicitement le schéma attendu des sources** et le vérifier à l'entrée, pour que
   la dérive d'une colonne produise un message explicite plutôt qu'une erreur de Polars (P13).

---

## 7. Conclusion

Les faiblesses relevées ne portent pas sur la justesse des transformations — celle-ci est
défendue par des contrôles qualité entre couches, par des rejeux idempotents et par une suite
de tests exécutée sans infrastructure. Elles portent sur ce qui entoure le traitement :
savoir qu'il a échoué, pouvoir revenir en arrière, pouvoir comprendre ce qui s'est passé.

C'est la conséquence attendue d'un pipeline conçu et validé en développement, où l'auteur
observe chaque exécution. Le passage en exploitation supprime cet observateur, et c'est
précisément ce que les cinq corrections prioritaires viennent remplacer.

Un constat mérite d'être retenu au-delà de ce projet : sur les dix-neuf points relevés, un seul
— la persistance des variants retirés (P19) — relève d'une erreur de conception, et il n'a été
visible qu'en lisant le code du `MERGE` ligne à ligne. Tous les autres relèvent de ce qui n'a
pas été mis en place, non de ce qui a été mal fait. C'est le propre des audits de production :
ils cherchent moins des fautes que des absences.
