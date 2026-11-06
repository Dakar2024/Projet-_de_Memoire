## Sources de données génomiques

### 1. Bases interrogées

**Le pipeline collecte cinq bases publiques.** Quatre sont produites par le National Center for
Biotechnology Information (NCBI) ; la cinquième, la Human Phenotype Ontology, est maintenue par
le Jackson Laboratory (JAX) au sein de la fondation OBO. Chacune apporte une facette distincte
de la connaissance nécessaire à l'interprétation d'un variant.

*Tableau — Bases génomiques collectées par le pipeline*

| Base | Producteur | Données exploitées | Mode d'accès |
|---|---|---|---|
| **ClinVar** | NCBI | Variants et leur signification clinique (archive mensuelle de `variant_summary.txt.gz`) | Téléchargement de fichier |
| **NCBI Gene** | NCBI | Métadonnées de chaque gène du panel | API E-utilities, base `gene` |
| **RefSeq** | NCBI | Catalogue des transcrits de chaque gène, utilisé pour normaliser les notations HGVS | API E-utilities, base `nuccore` |
| **MedGen** | NCBI | Concepts de maladies, retrouvés à partir des identifiants cités par ClinVar | API E-utilities, base `medgen` |
| **Human Phenotype Ontology (HPO)** | JAX / OBO | Associations gène → phénotype (`genes_to_phenotype.txt`), et définitions, synonymes et références croisées des termes | Téléchargement de fichier et API de l'ontologie |

### 2. Mécanismes de collecte

**Le pipeline utilise deux mécanismes : le téléchargement de fichiers et l'appel d'API.** Il ne lit
aucune page web et n'utilise pas de moissonnage (*web scraping*). Les liens vers les fiches ClinVar
présents dans les documents du RAG sont construits à partir du Variation ID, sans que ces pages
soient consultées.

*Tableau — Mécanisme de collecte de chaque source*

| Donnée collectée | Mécanisme | Point d'accès | Portée de la collecte | Format reçu |
|---|---|---|---|---|
| Variants ClinVar | Téléchargement HTTPS | `ftp.ncbi.nlm.nih.gov`, archive `variant_summary_AAAA-MM.txt.gz` | Fichier complet, commun aux deux panels | TSV compressé |
| Associations gène → phénotype HPO | Téléchargement HTTPS | Publication GitHub de HPO, version épinglée | Fichier complet, commun aux deux panels | TSV |
| Détails des termes HPO | API REST, sans clé | `ontology.jax.org/api/hp/terms` | Termes des gènes du panel, par lots de 20 | JSON |
| Fiches NCBI Gene | API E-utilities : `esearch`, puis `esummary` | Base `gene` | Gènes du panel | JSON |
| Transcrits RefSeq | API E-utilities : `esearch`, puis `esummary` | Base `nuccore` | ARNm humains RefSeq des gènes du panel | JSON |
| Concepts MedGen | API E-utilities : `esearch`, puis `esummary` | Base `medgen` | Maladies citées par ClinVar pour les gènes du panel | JSON contenant un fragment XML (`conceptmeta`) |

**Le serveur de ClinVar porte le nom `ftp`, mais le transfert s'effectue en HTTPS.** Le pipeline
n'utilise pas le protocole FTP. Il télécharge l'archive du mois, qui n'est plus modifiée après sa
publication, plutôt que le fichier courant : un rejeu relit ainsi exactement les mêmes données.

**La version du fichier HPO est épinglée.** Le pipeline identifie la dernière publication à partir
de la redirection de l'adresse GitHub `/releases/latest`, puis télécharge le fichier de cette version
et l'inscrit dans le manifeste de la partition. Un rejeu du mois réutilise cette même version.

**Deux collectes dépendent de fichiers déjà déposés dans la couche `raw`.** Les identifiants MedGen
sont extraits de la colonne `PhenotypeIDS` du fichier ClinVar, et les identifiants des termes HPO de
`genes_to_phenotype.txt`. Les fichiers communs sont donc collectés avant les données propres à chaque
panel.

**Les trois sources interrogées par E-utilities partagent un même client d'accès.** Il identifie le
projet auprès du NCBI (nom d'outil et adresse de contact), respecte la limite de débit (environ 3
requêtes par seconde, ou 10 avec une clé d'API) et relance automatiquement les erreurs transitoires.

### 3. Bases référencées par leurs seuls identifiants

**Quatre autres bases apparaissent dans les données sans être interrogées.** Leurs identifiants
sont repris tels que les sources collectées les fournissent :

- **OMIM** : numéros MIM lus dans les concepts MedGen, puis repris dans les documents du RAG ;
- **Orphanet** et **MONDO** : identifiants de maladies présents dans les références croisées de
  ClinVar ;
- **dbSNP** : identifiant « rs » de chaque variant, fourni par ClinVar.

**OMIM a d'abord été envisagé comme source, puis remplacé par MedGen.** L'accès à OMIM dépend
d'une autorisation de son éditeur, alors que MedGen fournit déjà le numéro MIM de chaque maladie.
OMIM reste ainsi citable sans que le pipeline dépende de cette autorisation, et les identifiants
conservés permettent au professionnel de santé de remonter à chacune de ces bases.

### 4. Sources non intégrées

**Le pipeline n'intègre ni fréquences populationnelles, comme celles de gnomAD, ni bases
d'annotation des gènes et des protéines, comme Ensembl ou UniProt.** Leur ajout est discuté en
perspective, en particulier pour les fréquences alléliques des populations africaines.
