# Audit de sécurité du pipeline de données

**Date :** 23 septembre 2026
**Périmètre :** collecte des sources publiques, ingestion en couche `raw`, transmission entre
les couches du médaillon, stockage MinIO, orchestration Docker et Airflow.
**Méthode :** revue manuelle du code (`src/`, `scripts/`, `dags/`), de la configuration
(`docker-compose.yml`, `docker/`, `.env.example`, `.gitignore`), de l'historique git et du
comportement de la stack en exécution.

---

## 1. Objet et modèle de menace

Le pipeline collecte des données **publiques** de génétique médicale (ClinVar, NCBI Gene,
MedGen, HPO, RefSeq) et les transforme en tables destinées à un assistant RAG et à une
application web. Aucune donnée personnelle de patient n'est traitée : la confidentialité des
données elles-mêmes n'est pas l'enjeu principal.

Les risques qui comptent ici sont donc, par ordre d'importance :

1. **L'intégrité des données.** Un variant dont la signification clinique serait altérée — par
   corruption de téléchargement, par écrasement accidentel ou par une transformation fautive —
   produirait une réponse médicale fausse. C'est le risque le plus grave du système.
2. **La disponibilité et la réversibilité.** Une suppression accidentelle du lac impose de
   relancer plusieurs heures de collecte, et les archives mensuelles de ClinVar les plus
   anciennes ne sont plus accessibles par la même URL.
3. **La protection des secrets.** Clé API NCBI, identifiants MinIO et PostgreSQL, secret de
   session Airflow. Leur fuite n'expose pas de données sensibles, mais permettrait d'usurper
   l'identité de l'appelant auprès de NCBI ou de détruire le lac.
4. **La surface d'exposition réseau.** La stack est conçue pour tourner en local ; toute
   exposition sur un réseau partagé ou un serveur public change la nature des risques.

---

## 2. Synthèse

L'audit a relevé **dix-huit points**, dont cinq traités immédiatement. Le tableau ci-dessous
récapitule l'état après correction.

| Domaine | Points forts constatés | Corrigé | Reste à traiter |
|---|---|---|---|
| Collecte | HTTPS partout, TLS jamais désactivé, délais d'attente et tentatives bornés | 1 | 2 |
| Ingestion | Protocole d'écriture atomique, aucune exécution dynamique | 0 | 2 |
| Transmission | Contrôles qualité bloquants entre chaque couche | 0 | 3 |
| Stockage MinIO | Un bucket par couche, création idempotente | 1 | 2 |
| Docker / Airflow | Base non exposée, limites mémoire, variables obligatoires | 3 | 3 |
| Transverse | Aucun secret dans l'historique, dépendances épinglées, dépôt privé | 0 | 2 |

---

## 3. Constats détaillés

La gravité est évaluée dans le contexte d'un déploiement local ; la colonne « en production »
indique comment elle évoluerait sur un serveur exposé.

### 3.1 Collecte des données

| Réf. | Constat | Gravité | En production | État |
|---|---|---|---|---|
| C1 | La clé API NCBI voyage en paramètre d'URL, comme l'exige NCBI. Le message d'une erreur HTTP reproduit l'URL complète, et Airflow journalise les exceptions de tâche : la clé finissait en clair dans des logs conservés et consultables depuis l'interface web. | Moyen | Moyen | **Corrigé** |
| C2 | Aucune vérification d'intégrité des fichiers téléchargés. Seule la taille annoncée est comparée. ClinVar publie pourtant une somme de contrôle MD5 à côté de son archive. | Moyen | Moyen | Ouvert |
| C3 | Le XML MedGen est analysé avec `xml.etree`, qui ne résout pas les entités externes (pas de risque d'exfiltration) mais reste vulnérable aux bombes d'entités. La source est de confiance ; le risque n'existe qu'en cas de compromission amont. | Faible | Faible | Ouvert |
| C4 | ✅ Toutes les sources sont en HTTPS, la vérification TLS n'est désactivée nulle part, et chaque appel porte un délai d'attente explicite. | — | — | — |
| C5 | ✅ Les tentatives sont bornées (trois au maximum, avec temporisation croissante et respect de l'en-tête `Retry-After`) et un limiteur de débit respecte la politique d'usage de NCBI. | — | — | — |

### 3.2 Ingestion vers la couche `raw`

| Réf. | Constat | Gravité | En production | État |
|---|---|---|---|---|
| I1 | Les chemins d'objets sont construits par concaténation, sans normalisation. Les valeurs proviennent aujourd'hui de constantes internes, donc rien n'est exploitable ; mais une date fournie par un déclenchement manuel Airflow atteindrait cette construction sans validation. | Moyen | Moyen | Ouvert |
| I2 | Les objets sont déposés sans chiffrement côté serveur ni somme de contrôle transmise. | Faible | Moyen | Ouvert |
| I3 | ✅ Le protocole d'écriture d'une partition — fichier temporaire, renommage atomique, manifeste, puis marqueur de complétude vérifié en aval — empêche qu'une partition partielle soit lue comme complète. C'est la réponse adaptée à un stockage objet dépourvu de renommage atomique. | — | — | — |
| I4 | ✅ Aucune exécution dynamique dans tout le code : ni `eval`, ni `exec`, ni désérialisation `pickle`, ni appel de sous-processus. La surface d'attaque applicative est minimale. | — | — | — |

### 3.3 Transmission entre les couches

| Réf. | Constat | Gravité | En production | État |
|---|---|---|---|---|
| T1 | Le trafic vers le stockage objet n'est pas chiffré (`http://minio:9000`). Il reste aujourd'hui confiné au réseau Docker de l'hôte. Dès que MinIO sera sur une autre machine, les identifiants et les données circuleront en clair. | Moyen | **Élevé** | Ouvert |
| T2 | Les prédicats Delta sont construits par interpolation de chaîne à partir du nom de panel. Les valeurs sont internes, donc non exploitables, mais c'est le motif d'injection classique. | Faible | Faible | Ouvert |
| T3 | Aucune politique de rétention Delta : toutes les versions antérieures sont conservées indéfiniment. Question de coût de stockage plutôt que de sécurité. | Faible | Faible | Ouvert |
| T4 | ✅ Des contrôles qualité bloquants séparent chaque couche, et chacun compare la sortie à une source **indépendante** plutôt qu'à elle-même. Deux défauts réels ont été détectés par ce mécanisme pendant le développement. | — | — | — |

### 3.4 Stockage MinIO

| Réf. | Constat | Gravité | En production | État |
|---|---|---|---|---|
| M1 | Les tâches Airflow utilisaient les identifiants **root** de MinIO. Une exécution de code arbitraire dans une tâche donnait le contrôle total du stockage, suppression des quatre buckets comprise. | **Élevé** | **Critique** | **Corrigé** |
| M2 | La console d'administration et l'API S3 étaient publiées sur toutes les interfaces réseau, protégées par ces mêmes identifiants root. | **Élevé** | **Critique** | **Corrigé** |
| M3 | Ni versioning, ni verrouillage d'objet, ni chiffrement au repos sur les buckets. Le versioning protégerait d'une suppression accidentelle, qui est le scénario le plus probable ici. | Moyen | Moyen | Ouvert |
| M4 | ✅ Une couche du médaillon correspond à un bucket : la séparation logique préexistait, ce qui a permis d'écrire une politique d'accès par bucket sans rien restructurer. | — | — | — |

### 3.5 Orchestration Docker et Airflow

| Réf. | Constat | Gravité | En production | État |
|---|---|---|---|---|
| D1 | Le dépôt entier était monté en écriture dans tous les conteneurs Airflow, `.env` compris : une tâche compromise lisait tous les secrets et pouvait modifier le code source de l'hôte de façon persistante. | **Élevé** | **Élevé** | **Corrigé** |
| D2 | L'interface Airflow était publiée sur toutes les interfaces réseau, avec un gestionnaire d'authentification prévu pour le développement, sans TLS ni double facteur. | **Élevé** | **Critique** | **Corrigé** |
| D3 | Deux images étaient déclarées sans aucun tag, donc implicitement `latest` : comportement non reproductible et vecteur de chaîne d'approvisionnement. | Moyen | Moyen | **Corrigé** |
| D4 | Aucun durcissement d'exécution : ni interdiction d'élévation de privilèges, ni retrait des capacités Linux, ni système de fichiers en lecture seule au niveau du conteneur. | Moyen | Moyen | Ouvert |
| D5 | Les secrets sont transmis par variables d'environnement, donc visibles via l'inspection du conteneur et dans `/proc`. | Moyen | Moyen | Ouvert |
| D6 | Le fichier `.env` était lisible par tous les utilisateurs de la machine (permissions 664). | Faible | Moyen | **Corrigé** |
| D7 | ✅ PostgreSQL n'expose aucun port ; chaque service a une sonde de santé ; les limites mémoire sont explicites et justifiées par des mesures ; les variables obligatoires font échouer le démarrage plutôt que de prendre une valeur par défaut silencieuse. | — | — | — |

### 3.6 Transverse

| Réf. | Constat | Gravité | État |
|---|---|---|---|
| G1 | Aucun scan de vulnérabilités des dépendances ni des images, pas de vérification d'empreinte des paquets, pas d'intégration continue exécutant les tests. | Moyen | Ouvert |
| G2 | Aucune procédure de rotation des identifiants. | Faible | Ouvert |
| G3 | ✅ Aucun secret dans l'historique git, vérifié sur l'ensemble des branches. `.env` ignoré depuis l'origine, `.env.example` porteur d'un avertissement explicite. | — | — |
| G4 | ✅ Toutes les dépendances sont épinglées à une version exacte, et Airflow est réinstallé dans la même commande que les dépendances pour empêcher une mise à jour involontaire. | — | — |
| G5 | ✅ Le dépôt est privé. | — | — |

---

## 4. Corrections apportées

### 4.1 Compte de service MinIO (M1)

Les tâches du pipeline n'utilisent plus les identifiants administrateur. Le script d'amorçage
crée une politique nommée `airflow-lake`, limitée aux quatre buckets du médaillon et aux seules
actions dont Delta Lake a besoin — lire, écrire, supprimer un objet, lister un bucket et
abandonner un envoi multipart interrompu. Un utilisateur dédié reçoit cette politique, et c'est
lui que les conteneurs Airflow utilisent.

Vérification effectuée sur la stack en exécution :

| Action tentée par le compte de service | Résultat attendu | Résultat observé |
|---|---|---|
| Écrire puis relire un objet dans `silver` | autorisé | autorisé |
| Supprimer cet objet | autorisé | autorisé |
| Lire une table Delta (96 892 lignes) | autorisé | autorisé |
| Créer un nouveau bucket | refusé | `AccessDenied` |
| Supprimer le bucket `silver` | refusé | `AccessDenied` |
| Énumérer les buckets | limité aux quatre autorisés | `raw`, `bronze`, `silver`, `gold` |

Le compte administrateur ne sert donc plus qu'à deux choses : amorcer la stack et ouvrir la
console.

### 4.2 Interfaces d'administration en écoute locale (M2, D2)

Les trois ports publiés — interface Airflow, console MinIO, API S3 — sont désormais liés à
`127.0.0.1` au lieu de toutes les interfaces. Une machine du même réseau ne peut plus les
atteindre. C'est la mesure adaptée tant que ces services n'ont ni TLS ni authentification forte :
les exposer supposerait d'abord de placer un reverse proxy chiffré devant eux.

### 4.3 Code monté en lecture seule (D1)

Le dépôt est monté en lecture seule dans les conteneurs, et seul le dossier `data/` — où se
déposent le fichier ClinVar et le fichier HPO — reste accessible en écriture. Une tâche
compromise ne peut plus modifier le code du projet ni lire `.env` en écriture. Python n'a pas
besoin d'écrire dans l'arborescence du code : il se contente de ne pas y produire de fichiers
de bytecode.

### 4.4 Clé API jamais journalisée (C1)

Tous les appels aux services NCBI passent désormais par une fonction unique qui intercepte les
erreurs du client HTTP et les relève avec la clé remplacée par `***`. Le chaînage d'exceptions
est supprimé, afin que le message d'origine n'apparaisse pas non plus dans la trace. La clé
continue bien sûr d'être transmise à NCBI : c'est sa journalisation qui est empêchée, pas son
usage. Deux tests couvrent le cas d'une erreur HTTP et celui d'un échec de connexion.

### 4.5 Images épinglées par empreinte (D3)

Les images PostgreSQL et MinIO sont épinglées par empreinte `sha256`, celles-là mêmes qui ont
été validées sur cette machine. Un tag peut être republié sur une image différente ; une
empreinte, non. L'image de base Airflow reste déclarée par sa version exacte
(`3.3.1-python3.12`).

---

## 5. Recommandations restantes

Par ordre de priorité, si le projet devait être déployé hors de la machine de développement.

1. **Activer TLS sur MinIO** et basculer le point d'accès en `https://` (T1). Indispensable dès
   que le stockage n'est plus sur la même machine que les tâches.
2. **Placer un reverse proxy TLS avec authentification** devant l'interface Airflow, et
   remplacer le gestionnaire d'authentification de développement (D2, complément).
3. **Activer le versioning des buckets** (M3) : c'est la protection la moins coûteuse contre la
   suppression accidentelle, scénario bien plus probable qu'une attaque.
4. **Vérifier la somme de contrôle publiée par ClinVar** après téléchargement (C2). Trois lignes
   de code pour une garantie d'intégrité qui ne dépend plus uniquement de TLS.
5. **Valider les composants de chemin** (`source`, `panel`, date) avant construction des clés
   d'objet (I1).
6. **Durcir l'exécution des conteneurs** : interdiction d'élévation de privilèges, retrait des
   capacités Linux inutiles (D4).
7. **Passer les secrets par fichiers montés** plutôt que par variables d'environnement (D5).
8. **Ajouter une intégration continue** exécutant les tests, un scan de vulnérabilités des
   dépendances et un scan des images (G1).

---

## 6. Conclusion

L'architecture du pipeline présente plusieurs propriétés favorables à la sécurité, qui ne sont
pas des ajouts tardifs mais des conséquences de sa conception : la logique métier est isolée de
l'orchestrateur et testée sans infrastructure, aucune exécution dynamique n'est possible, les
partitions ne deviennent lisibles qu'une fois complètes, et chaque couche est contrôlée par
rapport à la précédente avant de propager ses données.

Les faiblesses relevées relèvent presque toutes de la configuration d'exécution plutôt que du
code, et s'expliquent par un contexte de développement local. Les cinq corrections apportées —
principe du moindre privilège sur le stockage, réduction de la surface réseau, isolation du
code, protection du secret d'API et reproductibilité des images — suppriment les risques les
plus élevés sans modifier le comportement fonctionnel du pipeline. Les deux passes de tests
automatisés restent vertes (272 tests de logique, 23 tests de structure des DAGs), et la stack
redémarrée sous la nouvelle configuration lit et écrit normalement le lac, y compris une table
Delta de 96 892 lignes, tout en se voyant refuser les actions d'administration du stockage.
