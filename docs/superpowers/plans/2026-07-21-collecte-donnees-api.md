# Collecte de données via APIs (NCBI + HPO) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire la couche de collecte (RAW) du pipeline : télécharger et interroger ClinVar, NCBI Gene, MedGen et HPO pour les 17 gènes du projet, et produire un fichier JSON par gène dans `data/raw/`.

**Architecture:** Un client HTTP unique (`NcbiClient`) avec rate limiter centralisé gère tous les appels NCBI E-utilities (Gene, MedGen). ClinVar est récupéré via le fichier bulk FTP (pas d'API, pas de rate limit) puis filtré avec Polars. HPO est téléchargé en fichiers plats publics. Une couche d'orchestration pure (sans I/O réseau) assemble les 4 sources par gène et écrit `data/raw/{GENE}.json`. Un script CLI final compose le tout pour une exécution réelle.

**Déviation volontaire par rapport à `guide_recuperation_donnees.md`** : le guide illustre les appels NCBI avec `Bio.Entrez` (biopython). Ce plan utilise `requests` directement à la place — mêmes endpoints, mêmes paramètres (`email`, `api_key`, `retmode=json`), mais cela permet de mocker les appels HTTP de façon déterministe avec la librairie `responses` (stratégie de test choisie). Biopython n'est donc pas une dépendance de cette étape.

**Tech Stack:** Python 3, `requests`, `polars` (lecture/filtrage TSV), `python-dotenv`, `pytest` + `responses` (tests), pip/venv classique (`requirements.txt` / `requirements-dev.txt`).

## Global Constraints

Contraintes extraites de `guide_recuperation_donnees.md` (vérifié sur APIs réelles le 2026-07-16) — s'appliquent à toutes les tâches ci-dessous :

- Rate limit NCBI E-utilities : **3 req/s sans clé API, 10 req/s avec clé API** — limite **globale**, partagée entre ClinVar/Gene/MedGen (§1.2).
- ⛔ Ne **jamais** utiliser `efetch` sur ClinVar (`rettype=vcv`) : retourne un résultat XML vide (`<ClinVarResult-Set><set/></ClinVarResult-Set>`) sans lever d'erreur (§2).
- ⛔ Ne **jamais** utiliser `efetch(db="gene", rettype="gene_table")` avec parsing texte : utiliser `esummary` JSON (§3).
- ClinVar bulk : filtrer sur `Assembly ∈ {"GRCh38", "na"}` — un filtre strict sur `GRCh38` seul supprime silencieusement les lignes `na` (variants sans coordonnées mappées) (§2, piège n°2).
- ClinVar bulk : dédupliquer sur `#AlleleID` après filtrage assembly (~96 % de doublons GRCh37/GRCh38 sinon) (§2, piège n°1).
- Dédupliquer les CUI MedGen **avant** d'appeler l'API MedGen (des milliers de variants partagent la même condition) (§7).
- `NCBI_EMAIL` et `NCBI_API_KEY` chargés depuis `.env`, jamais en dur dans le code (§8 checklist).
- OMIM n'est plus une source directe : le numéro MIM est récupéré via MedGen (`conceptmeta/OMIM/MIM`) (§0, §6).
- Périmètre exact : **17 gènes** — 12 cancer du sein germinal (`genes_cancer_sein.md`) + 5 drépanocytose (`genes_drepanocytose.md`). Aucun gène somatique, aucune extension optionnelle (NF1, HBA1/2, HBG1/2 exclus).

---

## File Structure

```
.
├── .env.example
├── .gitignore
├── pytest.ini
├── requirements.txt
├── requirements-dev.txt
├── scripts/
│   └── run_collection.py       # CLI d'orchestration (Task 8)
├── src/
│   └── ingestion/
│       ├── __init__.py
│       ├── config.py            # constantes : gènes, URLs, chemins (Task 1)
│       ├── http_client.py       # RateLimiter + NcbiClient (Task 2)
│       ├── clinvar.py           # download + filter bulk ClinVar (Task 3)
│       ├── ncbi_gene.py         # fetch_gene_info (Task 4)
│       ├── medgen.py            # extract CUIs + fetch + parse conceptmeta (Task 5)
│       ├── hpo.py               # download + parse fichiers HPO (Task 6)
│       └── orchestrate.py       # assemble + écrit data/raw/{gene}.json (Task 7)
├── tests/
│   ├── fixtures/
│   │   ├── clinvar_sample.tsv
│   │   └── genes_to_phenotype_sample.txt
│   └── ingestion/
│       ├── __init__.py
│       ├── test_config.py
│       ├── test_http_client.py
│       ├── test_clinvar.py
│       ├── test_ncbi_gene.py
│       ├── test_medgen.py
│       ├── test_hpo.py
│       └── test_orchestrate.py
└── data/
    ├── external/.gitkeep        # fichiers bulk téléchargés (gitignored)
    └── raw/.gitkeep             # {GENE}.json finaux (gitignored)
```

---

### Task 1: Scaffolding du projet + configuration

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `pytest.ini`
- Create: `src/ingestion/__init__.py`
- Create: `src/ingestion/config.py`
- Create: `tests/ingestion/__init__.py`
- Create: `tests/ingestion/test_config.py`
- Create: `data/external/.gitkeep`
- Create: `data/raw/.gitkeep`

**Interfaces:**
- Produces: `ALL_GENES: list[str]` (17 éléments), `BREAST_CANCER_GENES`, `SICKLE_CELL_GENES`, `EUTILS_BASE_URL: str`, `DATA_EXTERNAL_DIR: Path`, `DATA_RAW_DIR: Path` — utilisés par toutes les tâches suivantes.

- [ ] **Step 1: Initialiser git et l'environnement virtuel**

```bash
cd "/home/azuka/Documents/Système RAG pour l'interrogation intelligente de bases de données génomiques — annotation et interprétation des variants ADN"
git init
python3 -m venv venv
source venv/bin/activate
```

- [ ] **Step 2: Créer `.gitignore`**

```
venv/
__pycache__/
*.pyc
.pytest_cache/
.env
data/external/*
data/raw/*
!data/external/.gitkeep
!data/raw/.gitkeep
```

- [ ] **Step 3: Créer `.env.example`**

```
NCBI_EMAIL=your.email@example.com
NCBI_API_KEY=
```

- [ ] **Step 4: Créer `data/external/.gitkeep` et `data/raw/.gitkeep`**

Fichiers vides — garantissent que git suit les dossiers malgré `.gitignore`.

- [ ] **Step 5: Créer `requirements.txt`**

```
requests
polars
python-dotenv
```

- [ ] **Step 6: Créer `requirements-dev.txt`**

```
-r requirements.txt
pytest
responses
```

- [ ] **Step 7: Créer `pytest.ini`**

```ini
[pytest]
pythonpath = src
testpaths = tests
```

- [ ] **Step 8: Installer les dépendances**

```bash
pip install -r requirements-dev.txt
```

- [ ] **Step 9: Créer `src/ingestion/__init__.py` (vide) et `tests/ingestion/__init__.py` (vide)**

- [ ] **Step 10: Écrire le test de configuration (failing)**

`tests/ingestion/test_config.py`:
```python
from ingestion.config import (
    ALL_GENES,
    BREAST_CANCER_GENES,
    SICKLE_CELL_GENES,
    EUTILS_BASE_URL,
)


def test_all_genes_combines_both_gene_lists():
    assert len(BREAST_CANCER_GENES) == 12
    assert len(SICKLE_CELL_GENES) == 5
    assert len(ALL_GENES) == 17
    assert set(ALL_GENES) == set(BREAST_CANCER_GENES) | set(SICKLE_CELL_GENES)


def test_all_genes_has_no_duplicates():
    assert len(ALL_GENES) == len(set(ALL_GENES))


def test_eutils_base_url_is_https():
    assert EUTILS_BASE_URL == "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
```

- [ ] **Step 11: Lancer le test pour vérifier l'échec**

Run: `pytest tests/ingestion/test_config.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestion.config'`

- [ ] **Step 12: Implémenter `src/ingestion/config.py`**

```python
from __future__ import annotations

from pathlib import Path

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

DATA_EXTERNAL_DIR = Path("data/external")
DATA_RAW_DIR = Path("data/raw")

# Panel germinal complet cancer du sein (haute + modérée pénétrance) — genes_cancer_sein.md
BREAST_CANCER_GENES = [
    "BRCA1", "BRCA2", "TP53", "PALB2", "PTEN", "CDH1", "STK11",
    "ATM", "CHEK2", "BARD1", "RAD51C", "RAD51D",
]

# Gène causal + modificateurs HbF majeurs + co-morbidité — genes_drepanocytose.md
SICKLE_CELL_GENES = ["HBB", "BCL11A", "HBS1L-MYB", "KLF1", "G6PD"]

ALL_GENES = BREAST_CANCER_GENES + SICKLE_CELL_GENES
```

- [ ] **Step 13: Lancer le test pour vérifier le succès**

Run: `pytest tests/ingestion/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 14: Commit**

```bash
git add .gitignore .env.example pytest.ini requirements.txt requirements-dev.txt \
  data/external/.gitkeep data/raw/.gitkeep src/ingestion/__init__.py \
  src/ingestion/config.py tests/ingestion/__init__.py tests/ingestion/test_config.py
git commit -m "feat: scaffold ingestion project and gene configuration"
```

---

### Task 2: Client HTTP NCBI avec rate limiter centralisé

**Files:**
- Create: `src/ingestion/http_client.py`
- Create: `tests/ingestion/test_http_client.py`

**Interfaces:**
- Consumes: `EUTILS_BASE_URL` (Task 1, `ingestion.config`).
- Produces: `RateLimiter(min_interval_seconds: float, sleep_fn=time.sleep, time_fn=time.monotonic)` avec méthode `.wait() -> None` ; `NcbiClient(email: str, api_key: str = "", rate_limiter: RateLimiter | None = None, session: requests.Session | None = None)` avec méthodes `.esearch(db: str, term: str) -> list[str]` et `.esummary(db: str, uid: str) -> dict`. Utilisés par `ncbi_gene.py` (Task 3) et `medgen.py` (Task 5).

- [ ] **Step 1: Écrire le test du RateLimiter (failing)**

`tests/ingestion/test_http_client.py`:
```python
import pytest

from ingestion.http_client import RateLimiter


def test_rate_limiter_does_not_sleep_on_first_call():
    slept = []
    limiter = RateLimiter(0.11, sleep_fn=slept.append, time_fn=lambda: 0.0)
    limiter.wait()
    assert slept == []


def test_rate_limiter_sleeps_remaining_interval_on_second_call():
    clock = {"t": 0.0}

    def fake_time():
        return clock["t"]

    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    limiter = RateLimiter(0.11, sleep_fn=fake_sleep, time_fn=fake_time)
    limiter.wait()
    clock["t"] += 0.02
    limiter.wait()

    assert slept == [pytest.approx(0.09)]


def test_rate_limiter_does_not_sleep_if_interval_already_elapsed():
    clock = {"t": 0.0}
    slept = []
    limiter = RateLimiter(
        0.11, sleep_fn=slept.append, time_fn=lambda: clock["t"]
    )
    limiter.wait()
    clock["t"] += 0.5
    limiter.wait()
    assert slept == []
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/ingestion/test_http_client.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestion.http_client'`

- [ ] **Step 3: Implémenter `RateLimiter` dans `src/ingestion/http_client.py`**

```python
from __future__ import annotations

import time

import requests

from ingestion.config import EUTILS_BASE_URL


class RateLimiter:
    """Espace les appels pour respecter la limite globale NCBI E-utilities."""

    def __init__(self, min_interval_seconds, sleep_fn=time.sleep, time_fn=time.monotonic):
        self._min_interval = min_interval_seconds
        self._sleep = sleep_fn
        self._now = time_fn
        self._last_call = None

    def wait(self) -> None:
        if self._last_call is not None:
            elapsed = self._now() - self._last_call
            remaining = self._min_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_call = self._now()
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run: `pytest tests/ingestion/test_http_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Écrire les tests de `NcbiClient` (failing)**

Ajouter à `tests/ingestion/test_http_client.py`:
```python
import responses

from ingestion.http_client import NcbiClient


def _no_wait_limiter():
    return RateLimiter(0.0, sleep_fn=lambda s: None)


@responses.activate
def test_esearch_returns_idlist():
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": ["3043"]}},
        status=200,
    )
    client = NcbiClient(email="test@example.com", rate_limiter=_no_wait_limiter())
    assert client.esearch(db="gene", term="HBB[gene]") == ["3043"]


@responses.activate
def test_esearch_sends_email_and_api_key_params():
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": []}},
        status=200,
    )
    client = NcbiClient(
        email="test@example.com", api_key="secret", rate_limiter=_no_wait_limiter()
    )
    client.esearch(db="gene", term="HBB[gene]")
    sent_params = responses.calls[0].request.params
    assert sent_params["email"] == "test@example.com"
    assert sent_params["api_key"] == "secret"


@responses.activate
def test_esummary_returns_result_for_uid():
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        json={"result": {"3043": {"name": "HBB"}}},
        status=200,
    )
    client = NcbiClient(email="test@example.com", rate_limiter=_no_wait_limiter())
    assert client.esummary(db="gene", uid="3043") == {"name": "HBB"}
```

- [ ] **Step 6: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/ingestion/test_http_client.py -v`
Expected: FAIL avec `ImportError: cannot import name 'NcbiClient'`

- [ ] **Step 7: Implémenter `NcbiClient`**

Ajouter à `src/ingestion/http_client.py`:
```python
class NcbiClient:
    """Client HTTP pour NCBI E-utilities (esearch/esummary), rate limité."""

    def __init__(self, email, api_key="", rate_limiter=None, session=None):
        self._email = email
        self._api_key = api_key
        self._rate_limiter = rate_limiter or RateLimiter(0.11 if api_key else 0.34)
        self._session = session or requests.Session()

    def _params(self, extra: dict) -> dict:
        params = {"email": self._email, "retmode": "json", **extra}
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    def esearch(self, db: str, term: str) -> list[str]:
        self._rate_limiter.wait()
        resp = self._session.get(
            f"{EUTILS_BASE_URL}/esearch.fcgi",
            params=self._params({"db": db, "term": term}),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["esearchresult"]["idlist"]

    def esummary(self, db: str, uid: str) -> dict:
        self._rate_limiter.wait()
        resp = self._session.get(
            f"{EUTILS_BASE_URL}/esummary.fcgi",
            params=self._params({"db": db, "id": uid}),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["result"][uid]
```

- [ ] **Step 8: Lancer tous les tests du fichier pour vérifier le succès**

Run: `pytest tests/ingestion/test_http_client.py -v`
Expected: PASS (6 tests)

- [ ] **Step 9: Commit**

```bash
git add src/ingestion/http_client.py tests/ingestion/test_http_client.py
git commit -m "feat: add NCBI HTTP client with centralized rate limiter"
```

---

### Task 3: ClinVar — téléchargement bulk + filtrage

**Files:**
- Create: `src/ingestion/clinvar.py`
- Create: `tests/ingestion/test_clinvar.py`
- Create: `tests/fixtures/clinvar_sample.tsv`

**Interfaces:**
- Produces: `CLINVAR_BULK_URL: str`, `download_variant_summary(destination: Path, url: str = CLINVAR_BULK_URL) -> Path`, `filter_clinvar(source_path: Path, genes: list[str]) -> pl.DataFrame`. `filter_clinvar` est consommé par `orchestrate.py` (Task 7).

> **Vérifié en direct sur le fichier réel le 2026-07-21** (téléchargement partiel par Range HTTP + décompression gzip streaming) : le header réel du fichier bulk ClinVar contient **43 colonnes**, pas 25 — `guide_recuperation_donnees.md` (rédigé le 2026-07-16) documente seulement les 25 premières. Les 18 colonnes supplémentaires (`NumberSubmitters` … `SCVsForAggregateOncogenicityClassification`) sont ajoutées **après** `ReviewStatus`, sans réordonner les 25 premières — donc sans impact sur `filter_clinvar` (qui référence les colonnes par nom : `GeneSymbol`, `Assembly`, `#AlleleID`). La fixture ci-dessous reproduit le header réel à 43 colonnes.
> Vérification complémentaire sur des lignes réelles HBB : le champ `PhenotypeIDS` a un format `|`-délimité par phénotype, avec des groupes mixtes (`MONDO:MONDO:0019402,MedGen:C0005283,Orphanet:848`) — confirmé compatible avec le regex `MedGen:(CN?\d+)` de `extract_medgen_cuis` (Task 5), qui ne matche que le préfixe littéral `MedGen:`.

- [ ] **Step 1: Créer la fixture `tests/fixtures/clinvar_sample.tsv`**

```
#AlleleID	Type	Name	GeneID	GeneSymbol	HGNC_ID	ClinicalSignificance	ClinSigSimple	LastEvaluated	RS# (dbSNP)	nsv/esv (dbVar)	RCVaccession	PhenotypeIDS	PhenotypeList	Origin	OriginSimple	Assembly	ChromosomeAccession	Chromosome	Start	Stop	ReferenceAllele	AlternateAllele	Cytogenetic	ReviewStatus	NumberSubmitters	Guidelines	TestedInGTR	OtherIDs	SubmitterCategories	VariationID	PositionVCF	ReferenceAlleleVCF	AlternateAlleleVCF	SomaticClinicalImpact	SomaticClinicalImpactLastEvaluated	ReviewStatusClinicalImpact	Oncogenicity	OncogenicityLastEvaluated	ReviewStatusOncogenicity	SCVsForAggregateGermlineClassification	SCVsForAggregateSomaticClinicalImpact	SCVsForAggregateOncogenicityClassification
15041	deletion	NM_014855.3(AP5Z1):c.80_83delinsTGCTGTAAACTGT	9907	AP5Z1	HGNC:22197	Uncertain significance	0	Jan 01, 2020	rs123	-	RCV000123	MedGen:C0001	Some disease	germline	germline	GRCh37	NC_000007.13	7	4820844	4820847	na	na	7p22.1	criteria provided	1	-	N	-	1	100001	4820844	na	na	-	-	-	-	-	-	SCV000100001	-	-
15041	deletion	NM_014855.3(AP5Z1):c.80_83delinsTGCTGTAAACTGT	9907	AP5Z1	HGNC:22197	Uncertain significance	0	Jan 01, 2020	rs123	-	RCV000123	MedGen:C0001	Some disease	germline	germline	GRCh38	NC_000007.14	7	4781213	4781216	na	na	7p22.1	criteria provided	1	-	N	-	1	100001	4781213	na	na	-	-	-	-	-	-	SCV000100001	-	-
20001	single nucleotide variant	NM_000518.5(HBB):c.20A>T	3043	HBB	HGNC:4827	Pathogenic	1	Jan 01, 2020	rs334	-	RCV000200	|MedGen:C3661900|MONDO:MONDO:0019402,MedGen:C0005283,Orphanet:848	Sickle cell disease|beta Thalassemia	germline	germline	GRCh38	NC_000011.10	11	5227002	5227002	A	T	11p15.4	criteria provided	2	-	Y	-	1	100002	5227002	A	T	-	-	-	-	-	-	SCV000100002|SCV000100003	-	-
20001	single nucleotide variant	NM_000518.5(HBB):c.20A>T	3043	HBB	HGNC:4827	Pathogenic	1	Jan 01, 2020	rs334	-	RCV000200	|MedGen:C3661900|MONDO:MONDO:0019402,MedGen:C0005283,Orphanet:848	Sickle cell disease|beta Thalassemia	germline	germline	GRCh37	NC_000011.09	11	5248232	5248232	A	T	11p15.4	criteria provided	2	-	Y	-	1	100002	5248232	A	T	-	-	-	-	-	-	SCV000100002|SCV000100003	-	-
20002	single nucleotide variant	NM_000518.5(HBB):c.19G>A	3043	HBB	HGNC:4827	Pathogenic	1	Jan 01, 2020	rs33930165	-	RCV000201	|MedGen:CN169374	Hemoglobin C disease	germline	germline	na	na	na	na	na	na	na	na	no assertion criteria provided	1	-	N	-	1	100003	na	na	na	-	-	-	-	-	-	SCV000100004	-	-
20003	single nucleotide variant	NM_000518.5(HBB):c.1A>T	3043	HBB	HGNC:4827	Likely pathogenic	0	Jan 01, 2020	rs999999	-	RCV000202	|MedGen:C3661900|MedGen:CN169374	Sickle cell disease	germline	germline	GRCh38	NC_000011.10	11	5227100	5227100	A	T	11p15.4	criteria provided	1	-	N	-	1	100004	5227100	A	T	-	-	-	-	-	-	SCV000100005	-	-
20003	single nucleotide variant	NM_000518.5(HBB):c.1A>T	3043	HBB	HGNC:4827	Likely pathogenic	0	Jan 01, 2020	rs999999	-	RCV000202	|MedGen:C3661900|MedGen:CN169374	Sickle cell disease	germline	germline	GRCh38	NC_000011.10	11	5227100	5227100	A	T	11p15.4	criteria provided	1	-	N	-	1	100004	5227100	A	T	-	-	-	-	-	-	SCV000100005	-	-
30001	single nucleotide variant	NM_006218.4(PIK3CA):c.3140A>G	5290	PIK3CA	HGNC:8975	drug response	0	Jan 01, 2020	rs104886003	-	RCV000300	MedGen:C0678222	Breast cancer somatic	somatic	somatic	GRCh38	NC_000003.12	3	179234297	179234297	A	G	3q26.32	criteria provided	1	-	N	-	1	100005	179234297	A	G	Uncertain	Jan 01, 2020	criteria provided	-	-	-	SCV000100006	-	-
```

- [ ] **Step 2: Écrire les tests de filtrage (failing)**

`tests/ingestion/test_clinvar.py`:
```python
from pathlib import Path

FIXTURE = Path(__file__).parent.parent / "fixtures" / "clinvar_sample.tsv"


def test_filter_clinvar_keeps_only_target_genes_and_valid_assemblies():
    from ingestion.clinvar import filter_clinvar

    result = filter_clinvar(FIXTURE, genes=["AP5Z1", "HBB"])
    assert set(result["GeneSymbol"].to_list()) == {"AP5Z1", "HBB"}
    assert result.height == 4


def test_filter_clinvar_drops_grch37_duplicate_assembly_rows():
    from ingestion.clinvar import filter_clinvar

    result = filter_clinvar(FIXTURE, genes=["AP5Z1"])
    assert result.height == 1
    assert result["Assembly"].to_list() == ["GRCh38"]


def test_filter_clinvar_deduplicates_exact_allele_id_duplicates():
    from ingestion.clinvar import filter_clinvar

    result = filter_clinvar(FIXTURE, genes=["HBB"])
    allele_ids = result["#AlleleID"].to_list()
    assert len(allele_ids) == len(set(allele_ids))
    assert set(allele_ids) == {"20001", "20002", "20003"}


def test_filter_clinvar_excludes_genes_not_in_scope():
    from ingestion.clinvar import filter_clinvar

    result = filter_clinvar(FIXTURE, genes=["HBB"])
    assert "PIK3CA" not in result["GeneSymbol"].to_list()
```

- [ ] **Step 3: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/ingestion/test_clinvar.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestion.clinvar'`

- [ ] **Step 4: Implémenter `filter_clinvar` dans `src/ingestion/clinvar.py`**

```python
from __future__ import annotations

from pathlib import Path

import polars as pl
import requests

CLINVAR_BULK_URL = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
)


def filter_clinvar(source_path: Path, genes: list[str]) -> pl.DataFrame:
    """Filtre le fichier bulk ClinVar sur les gènes cibles, gère les doublons d'assemblage."""
    return (
        pl.scan_csv(source_path, separator="\t", infer_schema_length=0)
        .filter(pl.col("GeneSymbol").is_in(genes))
        .filter(pl.col("Assembly").is_in(["GRCh38", "na"]))
        .unique(subset=["#AlleleID"], keep="first")
        .collect()
    )
```

- [ ] **Step 5: Lancer les tests pour vérifier le succès**

Run: `pytest tests/ingestion/test_clinvar.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Écrire le test de téléchargement (failing)**

Ajouter à `tests/ingestion/test_clinvar.py`:
```python
import gzip

import responses

from ingestion.clinvar import CLINVAR_BULK_URL


@responses.activate
def test_download_variant_summary_writes_streamed_content(tmp_path):
    from ingestion.clinvar import download_variant_summary

    body = gzip.compress(b"header\ncontent\n")
    responses.add(responses.GET, CLINVAR_BULK_URL, body=body, status=200)

    destination = tmp_path / "external" / "variant_summary.txt.gz"
    result_path = download_variant_summary(destination)

    assert result_path == destination
    assert destination.read_bytes() == body
```

- [ ] **Step 7: Lancer le test pour vérifier l'échec**

Run: `pytest tests/ingestion/test_clinvar.py::test_download_variant_summary_writes_streamed_content -v`
Expected: FAIL avec `ImportError: cannot import name 'download_variant_summary'`

- [ ] **Step 8: Implémenter `download_variant_summary`**

Ajouter à `src/ingestion/clinvar.py`:
```python
def download_variant_summary(destination: Path, url: str = CLINVAR_BULK_URL) -> Path:
    """Télécharge le fichier bulk ClinVar en streaming vers `destination`."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(destination, "wb") as fh:
            for chunk in response.iter_content(chunk_size=8192):
                fh.write(chunk)
    return destination
```

- [ ] **Step 9: Lancer tous les tests du fichier pour vérifier le succès**

Run: `pytest tests/ingestion/test_clinvar.py -v`
Expected: PASS (5 tests)

- [ ] **Step 10: Commit**

```bash
git add src/ingestion/clinvar.py tests/ingestion/test_clinvar.py tests/fixtures/clinvar_sample.tsv
git commit -m "feat: add ClinVar bulk download and gene/assembly filtering"
```

---

### Task 4: NCBI Gene — métadonnées par gène

**Files:**
- Create: `src/ingestion/ncbi_gene.py`
- Create: `tests/ingestion/test_ncbi_gene.py`

**Interfaces:**
- Consumes: `NcbiClient`, `RateLimiter` (Task 2, `ingestion.http_client`).
- Produces: `fetch_gene_info(client: NcbiClient, gene_symbol: str) -> dict`. Consommé par `orchestrate.py` (Task 7) et `scripts/run_collection.py` (Task 8).

- [ ] **Step 1: Écrire les tests (failing)**

`tests/ingestion/test_ncbi_gene.py`:
```python
import responses

from ingestion.http_client import NcbiClient, RateLimiter


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


@responses.activate
def test_fetch_gene_info_returns_esummary_for_found_gene():
    from ingestion.ncbi_gene import fetch_gene_info

    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": ["3043"]}},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        json={
            "result": {
                "3043": {"name": "HBB", "description": "hemoglobin subunit beta"}
            }
        },
        status=200,
    )
    result = fetch_gene_info(_client(), "HBB")
    assert result["name"] == "HBB"
    assert result["description"] == "hemoglobin subunit beta"


@responses.activate
def test_fetch_gene_info_returns_empty_dict_when_gene_not_found():
    from ingestion.ncbi_gene import fetch_gene_info

    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": []}},
        status=200,
    )
    result = fetch_gene_info(_client(), "HBS1L-MYB")
    assert result == {}


@responses.activate
def test_fetch_gene_info_uses_gene_search_term_format():
    from ingestion.ncbi_gene import fetch_gene_info

    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": []}},
        status=200,
    )
    fetch_gene_info(_client(), "BRCA1")
    sent_term = responses.calls[0].request.params["term"]
    assert sent_term == "BRCA1[gene] AND human[organism] AND alive[property]"
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/ingestion/test_ncbi_gene.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestion.ncbi_gene'`

- [ ] **Step 3: Implémenter `src/ingestion/ncbi_gene.py`**

```python
from __future__ import annotations

from ingestion.http_client import NcbiClient


def fetch_gene_info(client: NcbiClient, gene_symbol: str) -> dict:
    """Récupère les métadonnées NCBI Gene pour un symbole de gène (esearch puis esummary)."""
    uids = client.esearch(
        db="gene",
        term=f"{gene_symbol}[gene] AND human[organism] AND alive[property]",
    )
    if not uids:
        return {}
    return client.esummary(db="gene", uid=uids[0])
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run: `pytest tests/ingestion/test_ncbi_gene.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/ncbi_gene.py tests/ingestion/test_ncbi_gene.py
git commit -m "feat: add NCBI Gene metadata fetching"
```

---

### Task 5: MedGen — extraction CUI, récupération et parsing conceptmeta

**Files:**
- Create: `src/ingestion/medgen.py`
- Create: `tests/ingestion/test_medgen.py`

**Interfaces:**
- Consumes: `NcbiClient`, `RateLimiter` (Task 2).
- Produces: `extract_medgen_cuis(phenotype_ids_field: str) -> list[str]`, `fetch_medgen_concept(client: NcbiClient, cui: str) -> dict`, `parse_medgen_conceptmeta(conceptmeta: str) -> dict`. Consommés par `orchestrate.py` (Task 7).

- [ ] **Step 1: Écrire les tests d'extraction de CUI (failing)**

`tests/ingestion/test_medgen.py`:
```python
def test_extract_medgen_cuis_parses_multiple_xrefs():
    from ingestion.medgen import extract_medgen_cuis

    field = "MedGen:C3661900,OMIM:603903|MedGen:CN169374"
    assert extract_medgen_cuis(field) == ["C3661900", "CN169374"]


def test_extract_medgen_cuis_deduplicates():
    from ingestion.medgen import extract_medgen_cuis

    field = "MedGen:C3661900|MedGen:C3661900,OMIM:603903"
    assert extract_medgen_cuis(field) == ["C3661900"]


def test_extract_medgen_cuis_returns_empty_list_when_absent():
    from ingestion.medgen import extract_medgen_cuis

    assert extract_medgen_cuis("") == []
    assert extract_medgen_cuis("na") == []
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/ingestion/test_medgen.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestion.medgen'`

- [ ] **Step 3: Implémenter `extract_medgen_cuis`**

`src/ingestion/medgen.py`:
```python
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ingestion.http_client import NcbiClient

MEDGEN_CUI_PATTERN = re.compile(r"MedGen:(CN?\d+)")


def extract_medgen_cuis(phenotype_ids_field: str) -> list[str]:
    """Extrait les CUI MedGen uniques (dans l'ordre d'apparition) d'un champ PhenotypeIDS."""
    seen: list[str] = []
    for cui in MEDGEN_CUI_PATTERN.findall(phenotype_ids_field or ""):
        if cui not in seen:
            seen.append(cui)
    return seen
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run: `pytest tests/ingestion/test_medgen.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Écrire le test de récupération du concept (failing)**

Ajouter à `tests/ingestion/test_medgen.py`:
```python
import responses

from ingestion.http_client import NcbiClient, RateLimiter


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


@responses.activate
def test_fetch_medgen_concept_returns_esummary_for_found_cui():
    from ingestion.medgen import fetch_medgen_concept

    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": ["287"]}},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        json={"result": {"287": {"title": "Hb SS disease", "conceptid": "C0002895"}}},
        status=200,
    )
    result = fetch_medgen_concept(_client(), "C0002895")
    assert result["title"] == "Hb SS disease"


@responses.activate
def test_fetch_medgen_concept_returns_empty_dict_when_not_found():
    from ingestion.medgen import fetch_medgen_concept

    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": []}},
        status=200,
    )
    assert fetch_medgen_concept(_client(), "C9999999") == {}
```

- [ ] **Step 6: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/ingestion/test_medgen.py -v`
Expected: FAIL avec `ImportError: cannot import name 'fetch_medgen_concept'`

- [ ] **Step 7: Implémenter `fetch_medgen_concept`**

Ajouter à `src/ingestion/medgen.py`:
```python
def fetch_medgen_concept(client: NcbiClient, cui: str) -> dict:
    """Récupère un concept MedGen à partir d'un CUI (esearch [conceptid] puis esummary)."""
    uids = client.esearch(db="medgen", term=f"{cui}[conceptid]")
    if not uids:
        return {}
    return client.esummary(db="medgen", uid=uids[0])
```

- [ ] **Step 8: Lancer les tests pour vérifier le succès**

Run: `pytest tests/ingestion/test_medgen.py -v`
Expected: PASS (5 tests)

- [ ] **Step 9: Écrire le test de parsing conceptmeta (failing)**

Ajouter à `tests/ingestion/test_medgen.py`:
```python
CONCEPTMETA_SAMPLE = """
<Definitions>
<Definition source="GeneReviews">Sickle cell disease (SCD) is characterized by intermittent vaso-occlusive events and chronic hemolytic anemia.</Definition>
</Definitions>
<ModesOfInheritance>
<ModeOfInheritance><Name>Autosomal recessive inheritance</Name></ModeOfInheritance>
</ModesOfInheritance>
<OMIM><MIM>603903</MIM></OMIM>
<AssociatedGenes><Gene gene_id="3043" chromosome="11" cytogen_loc="11p15.4">HBB</Gene></AssociatedGenes>
<ClinicalFeatures>
<ClinicalFeature SDUI="HP:0002027"><Name>Abdominal pain</Name></ClinicalFeature>
</ClinicalFeatures>
"""


def test_parse_medgen_conceptmeta_extracts_expected_fields():
    from ingestion.medgen import parse_medgen_conceptmeta

    result = parse_medgen_conceptmeta(CONCEPTMETA_SAMPLE)
    assert result["mim_number"] == "603903"
    assert result["mode_inheritance"] == "Autosomal recessive inheritance"
    assert "Sickle cell disease" in result["clinical_summary"]
    assert result["hpo_terms"] == [{"hpo_id": "HP:0002027", "hpo_name": "Abdominal pain"}]


def test_parse_medgen_conceptmeta_handles_missing_fields():
    from ingestion.medgen import parse_medgen_conceptmeta

    result = parse_medgen_conceptmeta("<Definitions></Definitions>")
    assert result == {
        "mim_number": "",
        "mode_inheritance": "",
        "clinical_summary": "",
        "hpo_terms": [],
    }
```

- [ ] **Step 10: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/ingestion/test_medgen.py -v`
Expected: FAIL avec `ImportError: cannot import name 'parse_medgen_conceptmeta'`

- [ ] **Step 11: Implémenter `parse_medgen_conceptmeta`**

Ajouter à `src/ingestion/medgen.py`:
```python
def parse_medgen_conceptmeta(conceptmeta: str) -> dict:
    """Extrait mim_number, mode_inheritance, clinical_summary et hpo_terms du XML conceptmeta."""
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

- [ ] **Step 12: Lancer tous les tests du fichier pour vérifier le succès**

Run: `pytest tests/ingestion/test_medgen.py -v`
Expected: PASS (7 tests)

- [ ] **Step 13: Commit**

```bash
git add src/ingestion/medgen.py tests/ingestion/test_medgen.py
git commit -m "feat: add MedGen CUI extraction, fetching and conceptmeta parsing"
```

---

### Task 6: HPO — téléchargement et parsing des fichiers publics

**Files:**
- Create: `src/ingestion/hpo.py`
- Create: `tests/ingestion/test_hpo.py`
- Create: `tests/fixtures/genes_to_phenotype_sample.txt`

**Interfaces:**
- Produces: `GENES_TO_PHENOTYPE_URL: str`, `PHENOTYPE_HPOA_URL: str`, `download_hpo_files(destination_dir: Path) -> dict[str, Path]`, `parse_genes_to_phenotype(path: Path, genes: list[str]) -> list[dict]`. `parse_genes_to_phenotype` est consommé par `orchestrate.py` (Task 7).

- [ ] **Step 1: Créer la fixture `tests/fixtures/genes_to_phenotype_sample.txt`**

```
ncbi_gene_id	gene_symbol	hpo_id	hpo_name	frequency	disease_id
10	NAT2	HP:0000007	Autosomal recessive inheritance	-	OMIM:243400
3043	HBB	HP:0001878	Hemolytic anemia	-	OMIM:603903
3043	HBB	HP:0002094	Dyspnea	-	OMIM:603903
672	BRCA1	HP:0003002	Breast carcinoma	-	OMIM:604370
```

- [ ] **Step 2: Écrire le test de parsing (failing)**

`tests/ingestion/test_hpo.py`:
```python
from pathlib import Path

FIXTURE = Path(__file__).parent.parent / "fixtures" / "genes_to_phenotype_sample.txt"


def test_parse_genes_to_phenotype_filters_target_genes():
    from ingestion.hpo import parse_genes_to_phenotype

    result = parse_genes_to_phenotype(FIXTURE, genes=["HBB"])
    assert len(result) == 2
    assert all(row["gene_symbol"] == "HBB" for row in result)
    assert result[0] == {
        "gene_symbol": "HBB",
        "hpo_id": "HP:0001878",
        "hpo_name": "Hemolytic anemia",
    }


def test_parse_genes_to_phenotype_excludes_genes_out_of_scope():
    from ingestion.hpo import parse_genes_to_phenotype

    result = parse_genes_to_phenotype(FIXTURE, genes=["HBB"])
    assert "NAT2" not in [row["gene_symbol"] for row in result]
```

- [ ] **Step 3: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/ingestion/test_hpo.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestion.hpo'`

- [ ] **Step 4: Implémenter `parse_genes_to_phenotype`**

`src/ingestion/hpo.py`:
```python
from __future__ import annotations

from pathlib import Path

import requests

GENES_TO_PHENOTYPE_URL = "https://purl.obolibrary.org/obo/hp/hpoa/genes_to_phenotype.txt"
PHENOTYPE_HPOA_URL = "https://purl.obolibrary.org/obo/hp/hpoa/phenotype.hpoa"


def parse_genes_to_phenotype(path: Path, genes: list[str]) -> list[dict]:
    """Parse genes_to_phenotype.txt et filtre sur les gènes cibles."""
    genes_set = set(genes)
    rows = []
    with open(path, encoding="utf-8") as fh:
        next(fh)  # header
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            gene_symbol = parts[1]
            if gene_symbol not in genes_set:
                continue
            rows.append(
                {"gene_symbol": gene_symbol, "hpo_id": parts[2], "hpo_name": parts[3]}
            )
    return rows
```

- [ ] **Step 5: Lancer les tests pour vérifier le succès**

Run: `pytest tests/ingestion/test_hpo.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Écrire le test de téléchargement (failing)**

Ajouter à `tests/ingestion/test_hpo.py`:
```python
import responses

from ingestion.hpo import GENES_TO_PHENOTYPE_URL, PHENOTYPE_HPOA_URL


@responses.activate
def test_download_hpo_files_writes_both_files(tmp_path):
    from ingestion.hpo import download_hpo_files

    responses.add(responses.GET, GENES_TO_PHENOTYPE_URL, body=b"gene-content", status=200)
    responses.add(responses.GET, PHENOTYPE_HPOA_URL, body=b"disease-content", status=200)

    result = download_hpo_files(tmp_path)

    assert result["genes_to_phenotype"] == tmp_path / "genes_to_phenotype.txt"
    assert result["phenotype_hpoa"] == tmp_path / "phenotype.hpoa"
    assert (tmp_path / "genes_to_phenotype.txt").read_bytes() == b"gene-content"
    assert (tmp_path / "phenotype.hpoa").read_bytes() == b"disease-content"
```

- [ ] **Step 7: Lancer le test pour vérifier l'échec**

Run: `pytest tests/ingestion/test_hpo.py -v`
Expected: FAIL avec `ImportError: cannot import name 'download_hpo_files'`

- [ ] **Step 8: Implémenter `download_file` et `download_hpo_files`**

Ajouter à `src/ingestion/hpo.py`:
```python
def download_file(url: str, destination: Path) -> Path:
    """Télécharge un fichier public HPO (pas de clé, pas de rate limit)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def download_hpo_files(destination_dir: Path) -> dict[str, Path]:
    """Télécharge les deux fichiers HPO publics dans `destination_dir`."""
    return {
        "genes_to_phenotype": download_file(
            GENES_TO_PHENOTYPE_URL, destination_dir / "genes_to_phenotype.txt"
        ),
        "phenotype_hpoa": download_file(
            PHENOTYPE_HPOA_URL, destination_dir / "phenotype.hpoa"
        ),
    }
```

- [ ] **Step 9: Lancer tous les tests du fichier pour vérifier le succès**

Run: `pytest tests/ingestion/test_hpo.py -v`
Expected: PASS (3 tests)

- [ ] **Step 10: Commit**

```bash
git add src/ingestion/hpo.py tests/ingestion/test_hpo.py tests/fixtures/genes_to_phenotype_sample.txt
git commit -m "feat: add HPO file download and gene-to-phenotype parsing"
```

---

### Task 7: Orchestration — assembler et écrire `data/raw/{gene}.json`

**Files:**
- Create: `src/ingestion/orchestrate.py`
- Create: `tests/ingestion/test_orchestrate.py`

**Interfaces:**
- Consumes: `extract_medgen_cuis` (Task 5, `ingestion.medgen`).
- Produces: `add_medgen_cuis(df: pl.DataFrame) -> pl.DataFrame`, `build_gene_documents(clinvar_variants: pl.DataFrame, gene_info_by_symbol: dict[str, dict], medgen_by_cui: dict[str, dict], hpo_rows_by_gene: dict[str, list[dict]]) -> dict[str, dict]`, `write_raw_gene_files(documents: dict[str, dict], output_dir: Path) -> list[Path]`. Consommés par `scripts/run_collection.py` (Task 8).

- [ ] **Step 1: Écrire le test de `add_medgen_cuis` (failing)**

`tests/ingestion/test_orchestrate.py`:
```python
import polars as pl


def test_add_medgen_cuis_extracts_list_column():
    from ingestion.orchestrate import add_medgen_cuis

    df = pl.DataFrame(
        {
            "#AlleleID": ["1"],
            "GeneSymbol": ["HBB"],
            "PhenotypeIDS": ["MedGen:C3661900,OMIM:603903"],
        }
    )
    result = add_medgen_cuis(df)
    assert result["medgen_cuis"].to_list() == [["C3661900"]]
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/ingestion/test_orchestrate.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestion.orchestrate'`

- [ ] **Step 3: Implémenter `add_medgen_cuis`**

`src/ingestion/orchestrate.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from ingestion.medgen import extract_medgen_cuis


def add_medgen_cuis(df: pl.DataFrame) -> pl.DataFrame:
    """Ajoute une colonne `medgen_cuis` (liste de CUI) dérivée de PhenotypeIDS."""
    return df.with_columns(
        pl.col("PhenotypeIDS")
        .map_elements(extract_medgen_cuis, return_dtype=pl.List(pl.Utf8))
        .alias("medgen_cuis")
    )
```

- [ ] **Step 4: Lancer le test pour vérifier le succès**

Run: `pytest tests/ingestion/test_orchestrate.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Écrire le test de `build_gene_documents` (failing)**

Ajouter à `tests/ingestion/test_orchestrate.py`:
```python
def test_build_gene_documents_assembles_variant_gene_medgen_hpo():
    from ingestion.orchestrate import add_medgen_cuis, build_gene_documents

    variants = add_medgen_cuis(
        pl.DataFrame(
            {
                "#AlleleID": ["1"],
                "GeneSymbol": ["HBB"],
                "PhenotypeIDS": ["MedGen:C3661900"],
                "ClinicalSignificance": ["Pathogenic"],
            }
        )
    )
    gene_info = {"HBB": {"name": "HBB", "description": "hemoglobin subunit beta"}}
    medgen = {"C3661900": {"title": "Hb SS disease", "mim_number": "603903"}}
    hpo = {"HBB": [{"hpo_id": "HP:0001878", "hpo_name": "Hemolytic anemia"}]}

    documents = build_gene_documents(variants, gene_info, medgen, hpo)

    assert set(documents.keys()) == {"HBB"}
    doc = documents["HBB"]
    assert doc["gene_info"]["name"] == "HBB"
    assert doc["variants"][0]["ClinicalSignificance"] == "Pathogenic"
    assert doc["medgen_concepts"] == [{"title": "Hb SS disease", "mim_number": "603903"}]
    assert doc["hpo_terms"] == [{"hpo_id": "HP:0001878", "hpo_name": "Hemolytic anemia"}]


def test_build_gene_documents_handles_gene_with_no_variants():
    from ingestion.orchestrate import add_medgen_cuis, build_gene_documents

    variants = add_medgen_cuis(
        pl.DataFrame(
            {"#AlleleID": [], "GeneSymbol": [], "PhenotypeIDS": []},
            schema={"#AlleleID": pl.Utf8, "GeneSymbol": pl.Utf8, "PhenotypeIDS": pl.Utf8},
        )
    )
    gene_info = {"ATM": {"name": "ATM"}}

    documents = build_gene_documents(variants, gene_info, {}, {})

    assert documents["ATM"]["variants"] == []
    assert documents["ATM"]["medgen_concepts"] == []
    assert documents["ATM"]["hpo_terms"] == []
```

- [ ] **Step 6: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/ingestion/test_orchestrate.py -v`
Expected: FAIL avec `ImportError: cannot import name 'build_gene_documents'`

- [ ] **Step 7: Implémenter `build_gene_documents`**

Ajouter à `src/ingestion/orchestrate.py`:
```python
def build_gene_documents(
    clinvar_variants: pl.DataFrame,
    gene_info_by_symbol: dict[str, dict],
    medgen_by_cui: dict[str, dict],
    hpo_rows_by_gene: dict[str, list[dict]],
) -> dict[str, dict]:
    """Assemble un document par gène combinant ClinVar, NCBI Gene, MedGen et HPO."""
    documents: dict[str, dict] = {}
    for gene_symbol in gene_info_by_symbol:
        variant_records = clinvar_variants.filter(
            pl.col("GeneSymbol") == gene_symbol
        ).to_dicts()

        cuis_for_gene: list[str] = []
        for record in variant_records:
            for cui in record.get("medgen_cuis") or []:
                if cui not in cuis_for_gene:
                    cuis_for_gene.append(cui)

        documents[gene_symbol] = {
            "gene_symbol": gene_symbol,
            "gene_info": gene_info_by_symbol.get(gene_symbol, {}),
            "variants": variant_records,
            "medgen_concepts": [
                medgen_by_cui[cui] for cui in cuis_for_gene if cui in medgen_by_cui
            ],
            "hpo_terms": hpo_rows_by_gene.get(gene_symbol, []),
        }
    return documents
```

- [ ] **Step 8: Lancer les tests pour vérifier le succès**

Run: `pytest tests/ingestion/test_orchestrate.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Écrire le test de `write_raw_gene_files` (failing)**

Ajouter à `tests/ingestion/test_orchestrate.py`:
```python
def test_write_raw_gene_files_creates_one_json_per_gene(tmp_path):
    from ingestion.orchestrate import write_raw_gene_files

    documents = {"HBB": {"gene_symbol": "HBB", "variants": []}}
    written = write_raw_gene_files(documents, tmp_path / "raw")

    assert written == [tmp_path / "raw" / "HBB.json"]
    content = (tmp_path / "raw" / "HBB.json").read_text(encoding="utf-8")
    assert '"gene_symbol": "HBB"' in content
```

- [ ] **Step 10: Lancer le test pour vérifier l'échec**

Run: `pytest tests/ingestion/test_orchestrate.py -v`
Expected: FAIL avec `ImportError: cannot import name 'write_raw_gene_files'`

- [ ] **Step 11: Implémenter `write_raw_gene_files`**

Ajouter à `src/ingestion/orchestrate.py`:
```python
def write_raw_gene_files(documents: dict[str, dict], output_dir: Path) -> list[Path]:
    """Écrit un fichier JSON par gène dans `output_dir`."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for gene_symbol, document in documents.items():
        path = output_dir / f"{gene_symbol}.json"
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    return written
```

- [ ] **Step 12: Lancer tous les tests du fichier pour vérifier le succès**

Run: `pytest tests/ingestion/test_orchestrate.py -v`
Expected: PASS (4 tests)

- [ ] **Step 13: Commit**

```bash
git add src/ingestion/orchestrate.py tests/ingestion/test_orchestrate.py
git commit -m "feat: assemble per-gene raw documents from all four sources"
```

---

### Task 8: Script CLI d'orchestration + vérification manuelle

**Files:**
- Create: `scripts/run_collection.py`

**Interfaces:**
- Consumes: tout ce qui a été produit dans les Tasks 1 à 7.
- Produces: exécutable en ligne de commande, aucune interface consommée par une tâche ultérieure (c'est le point d'entrée final de cette étape).

> Ce script effectue de vrais appels réseau (ClinVar FTP, NCBI E-utilities, HPO). Il n'est **pas** couvert par des tests automatisés — sa correction repose sur les fonctions déjà testées dans les Tasks 2 à 7. Sa validation se fait par une exécution manuelle (Step 3 ci-dessous).

- [ ] **Step 1: Implémenter `scripts/run_collection.py`**

```python
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from ingestion.clinvar import download_variant_summary, filter_clinvar
from ingestion.config import ALL_GENES, DATA_EXTERNAL_DIR, DATA_RAW_DIR
from ingestion.hpo import download_hpo_files, parse_genes_to_phenotype
from ingestion.http_client import NcbiClient
from ingestion.medgen import fetch_medgen_concept
from ingestion.ncbi_gene import fetch_gene_info
from ingestion.orchestrate import add_medgen_cuis, build_gene_documents, write_raw_gene_files


def run_collection(genes: list[str] = ALL_GENES) -> list[Path]:
    load_dotenv()
    client = NcbiClient(email=os.environ["NCBI_EMAIL"], api_key=os.environ.get("NCBI_API_KEY", ""))

    clinvar_path = download_variant_summary(DATA_EXTERNAL_DIR / "variant_summary.txt.gz")
    variants = add_medgen_cuis(filter_clinvar(clinvar_path, genes))

    gene_info_by_symbol = {gene: fetch_gene_info(client, gene) for gene in genes}

    all_cuis: list[str] = []
    for cui_list in variants["medgen_cuis"].to_list():
        for cui in cui_list:
            if cui not in all_cuis:
                all_cuis.append(cui)
    medgen_by_cui = {cui: fetch_medgen_concept(client, cui) for cui in all_cuis}

    hpo_paths = download_hpo_files(DATA_EXTERNAL_DIR)
    hpo_rows = parse_genes_to_phenotype(hpo_paths["genes_to_phenotype"], genes)
    hpo_rows_by_gene: dict[str, list[dict]] = {}
    for row in hpo_rows:
        hpo_rows_by_gene.setdefault(row["gene_symbol"], []).append(row)

    documents = build_gene_documents(variants, gene_info_by_symbol, medgen_by_cui, hpo_rows_by_gene)
    return write_raw_gene_files(documents, DATA_RAW_DIR)


if __name__ == "__main__":
    written_files = run_collection()
    print(f"{len(written_files)} fichiers écrits dans {DATA_RAW_DIR}/")
```

- [ ] **Step 2: Configurer `.env` avec de vraies valeurs (non commité)**

```bash
cp .env.example .env
```

Éditer `.env` et renseigner `NCBI_EMAIL` (obligatoire) et `NCBI_API_KEY` (recommandé, à obtenir sur son compte NCBI).

- [ ] **Step 3: Vérification manuelle sur un sous-ensemble restreint**

Avant de lancer sur les 17 gènes (le téléchargement bulk ClinVar fait ~440 Mo), valider le flux sur un seul gène :

```bash
python3 -c "
import sys
sys.path.insert(0, 'src')
from scripts.run_collection import run_collection
run_collection(genes=['HBB'])
"
```

Expected: un fichier `data/raw/HBB.json` est créé, contenant les clés `gene_symbol`, `gene_info` (nom + description NCBI Gene), `variants` (variants ClinVar filtrés du gène HBB), `medgen_concepts` (au moins un concept avec `mim_number`), `hpo_terms`.

- [ ] **Step 4: Exécution complète sur les 17 gènes**

```bash
python3 scripts/run_collection.py
```

Expected: `17 fichiers écrits dans data/raw/`, un fichier `{GENE}.json` par gène dans `BREAST_CANCER_GENES + SICKLE_CELL_GENES`.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_collection.py
git commit -m "feat: add CLI entrypoint wiring the full raw data collection"
```

---

## Suite après cette étape

Cette étape produit uniquement la **couche RAW** (`data/raw/{gene}.json`, un JSON brut par gène combinant ClinVar + NCBI Gene + MedGen + HPO). Elle ne construit **pas** encore l'architecture médaillon (Bronze/Silver/Gold) — ce sera l'objet du plan suivant, une fois cette étape validée et non avant, conformément à la consigne de travailler étape par étape sans mélanger les couches.
