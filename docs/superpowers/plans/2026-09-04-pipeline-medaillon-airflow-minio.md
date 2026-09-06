# Pipeline médaillon Airflow + MinIO — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer la sortie `data/raw/{GENE}.json` de l'étape 1 par une couche Bronze sur stockage objet MinIO, alimentée par cinq tâches d'ingestion ordonnancées par Airflow 3, avec Silver et Gold livrées en stubs.

**Architecture :** Les modules de `src/ingestion/` gardent leur logique métier intacte et deviennent des unités d'exécution appelées par de minces wrappers CLI. Une nouvelle couche `storage.py` écrit les partitions Bronze (`file://` en local, `s3://` sur MinIO) avec manifest et marqueur `_SUCCESS`. Un DAG d'acquisition partagé dépose les fichiers plats communs et publie un Asset Airflow qui déclenche un DAG par panel.

**Tech Stack :** Python 3.12, Airflow 3.3.1 (`airflow.sdk`), MinIO (S3), boto3, PostgreSQL, Docker Compose, pytest + responses.

**Spec :** `docs/superpowers/specs/2026-09-04-pipeline-medaillon-airflow-minio-design.md`

## Global Constraints

- **La logique métier de `src/ingestion/` n'est pas réécrite.** Seuls les chemins de sortie, les URL de source et la vérification d'intégrité changent.
- **Les 63 tests existants doivent rester verts et rapides** (`pytest -q` < 3 s, sans réseau ni conteneur). C'est la propriété centrale du projet.
- **Flux strictement unidirectionnel** : source → bronze → silver → gold. Aucune couche n'écrit dans une couche inférieure.
- **Idempotence par date logique** : rejouer un `logical_date` réécrit uniquement sa partition `dt=`.
- **Bronze est strictement brut** : aucun filtrage, aucun typage, aucune jointure. Le bulk ClinVar est déposé non filtré.
- **Aucun moteur de transformation n'est choisi.** Ne pas importer polars, pandas, pyspark ni deltalake dans `src/transformations/`.
- `pythonpath = src` est déjà configuré dans `pytest.ini` : les tests importent `from ingestion.xxx import ...`.
- Python 3.12. Airflow 3.3.1 exactement. Imports de DAG depuis `airflow.sdk`, opérateurs depuis `airflow.providers.standard.operators.*`.
- Commentaires, docstrings et messages en français, comme le reste du dépôt.

---

## Structure des fichiers

**Créés :**

| Fichier | Responsabilité |
|---|---|
| `src/ingestion/storage.py` | Résolution d'URI, écriture d'objets, manifest, `_SUCCESS` |
| `src/ingestion/refseq.py` | 5ᵉ source : catalogue des transcrits RefSeq (`db=nuccore`) |
| `src/transformations/bronze_to_silver.py` | Stub, contrat documenté |
| `src/transformations/silver_to_gold.py` | Stub, contrat documenté |
| `scripts/ingest_clinvar.py` | Dépôt du bulk ClinVar en Bronze |
| `scripts/ingest_hpo_files.py` | Dépôt de `genes_to_phenotype.txt` en Bronze |
| `scripts/ingest_ncbi_gene.py` | Métadonnées de gènes, par panel |
| `scripts/ingest_refseq.py` | Transcrits RefSeq, par panel |
| `scripts/ingest_medgen.py` | Concepts MedGen, par panel |
| `scripts/ingest_hpo_terms.py` | Enrichissement des termes HPO, par panel |
| `dags/common/panels.py` | Mapping panel → gènes, source unique de vérité |
| `dags/dag_acquisition_sources.py` | DAG d'acquisition partagé |
| `dags/dag_genomic_pipeline.py` | Fabrique des DAGs de panel |
| `docker-compose.yml`, `docker/airflow/Dockerfile`, `docker/minio/create-buckets.sh` | Infrastructure |

**Modifiés :** `src/ingestion/config.py` (URI du lac), `src/ingestion/download.py` (intégrité), `src/ingestion/clinvar.py` (URL archivée), `src/ingestion/hpo.py` (URL de release), `requirements.txt`, `pytest.ini`.

**Écart assumé par rapport à la spec :** la spec prévoyait `config/panels.yml`. Le plan définit les panels dans `dags/common/panels.py` en important `ingestion.config`, pour éviter de dupliquer la liste de gènes qui est déjà sous test (`test_config.py` vérifie 12 + 6 = 18). Un YAML dupliquerait cette vérité sans la protéger.

---

### Task 1: Dépendances et URI du lac

**Files:**
- Modify: `requirements.txt`
- Modify: `src/ingestion/config.py`
- Modify: `pytest.ini`
- Test: `tests/ingestion/test_config.py`

**Interfaces:**
- Consumes: rien.
- Produces: `ingestion.config.current_lake_uri() -> str`, `ingestion.config.DEFAULT_LAKE_DIR: Path`, `ingestion.config.BRONZE, SILVER, GOLD: str`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/ingestion/test_config.py` — **les `import` vont dans le bloc d'imports en tête de fichier, pas au milieu (E402) ; seules les fonctions de test vont à la fin** :

```python
from pathlib import Path

from ingestion.config import BRONZE, GOLD, SILVER, current_lake_uri


def test_current_lake_uri_defaults_to_local_data_lake(monkeypatch):
    monkeypatch.delenv("LAKE_URI", raising=False)
    uri = current_lake_uri()
    assert uri.startswith("file://")
    assert uri.endswith("/data/lake")
    assert Path(uri[len("file://"):]).is_absolute()


def test_current_lake_uri_reads_environment(monkeypatch):
    monkeypatch.setenv("LAKE_URI", "s3://")
    assert current_lake_uri() == "s3://"


def test_layer_names_are_the_three_medallion_buckets():
    assert (BRONZE, SILVER, GOLD) == ("bronze", "silver", "gold")
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/ingestion/test_config.py -q`
Expected: FAIL avec `ImportError: cannot import name 'BRONZE' from 'ingestion.config'`

- [ ] **Step 3: Implémenter dans `src/ingestion/config.py`**

Ajouter `import os` en tête du fichier, puis à la suite des constantes de chemin :

```python
# Couches du médaillon. Sur MinIO, chaque couche est un bucket ; en local, un
# sous-dossier de DEFAULT_LAKE_DIR.
BRONZE = "bronze"
SILVER = "silver"
GOLD = "gold"

DEFAULT_LAKE_DIR = PROJECT_ROOT / "data" / "lake"


def current_lake_uri() -> str:
    """Racine du lac, lue à l'appel (et non à l'import) pour rester testable.

    `file://<chemin>` en local et dans les tests, `s3://` quand les couches sont
    des buckets MinIO. Le défaut local garantit que la suite de tests tourne sans
    conteneur ni réseau.
    """
    return os.environ.get("LAKE_URI") or f"file://{DEFAULT_LAKE_DIR}"
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `venv/bin/pytest tests/ingestion/test_config.py -q`
Expected: PASS, 7 tests

- [ ] **Step 5: Ajouter les dépendances et le marqueur d'intégration**

Dans `requirements.txt`, remplacer la ligne `polars==1.43.0` (version **retirée de PyPI**) et ajouter boto3 :

```
requests==2.34.2
polars==1.44.1
python-dotenv==1.2.2
boto3==1.41.5
```

Dans `pytest.ini`, déclarer le marqueur et exclure l'intégration par défaut :

```ini
[pytest]
# `.` en plus de `src` : les tests de DAG importent `dags.*`, qui vit à la racine.
pythonpath = src .
testpaths = tests
markers =
    integration: nécessite un MinIO joignable (exclu de la passe rapide)
addopts = -m "not integration"
```

- [ ] **Step 6: Vérifier que rien n'a régressé**

Run: `venv/bin/pip install -r requirements-dev.txt && venv/bin/pytest -q`
Expected: PASS, 66 tests, aucun échec

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pytest.ini src/ingestion/config.py tests/ingestion/test_config.py
git commit -m "feat: add lake URI configuration and medallion layer names"
```

---

### Task 2: Couche de stockage (`storage.py`)

**Files:**
- Create: `src/ingestion/storage.py`
- Test: `tests/ingestion/test_storage.py`

**Interfaces:**
- Consumes: `ingestion.config.current_lake_uri`, `BRONZE`.
- Produces:
  - `layer_uri(layer: str, lake_uri: str | None = None) -> str`
  - `partition_uri(layer: str, source: str, logical_date: str, panel: str | None = None, lake_uri: str | None = None) -> str`
  - `put_bytes(uri: str, data: bytes, client=None) -> None`
  - `put_file(uri: str, local_path: Path, client=None) -> None`
  - `get_bytes(uri: str, client=None) -> bytes`
  - `open_stream(uri: str, client=None) -> IO[bytes]`
  - `exists(uri: str, client=None) -> bool`
  - `build_manifest(source: str, logical_date: str, source_url: str, source_version: str, files: dict[str, int], record_count: int, panel: str | None = None) -> dict`
  - `finalize_partition(partition: str, manifest: dict, client=None) -> None`
  - `partition_is_complete(partition: str, client=None) -> bool`

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/ingestion/test_storage.py` :

```python
import io
import json

import pytest

from ingestion.storage import (
    build_manifest,
    exists,
    finalize_partition,
    get_bytes,
    layer_uri,
    open_stream,
    partition_is_complete,
    partition_uri,
    put_bytes,
    put_file,
)


class FakeS3:
    """Client S3 minimal : le projet injecte déjà ses clients HTTP, on garde ce style."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def upload_file(self, Filename, Bucket, Key):
        with open(Filename, "rb") as fh:
            self.objects[(Bucket, Key)] = fh.read()

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FileNotFoundError(Key)
        return {"Body": _Body(self.objects[(Bucket, Key)])}


    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FileNotFoundError(Key)
        return {"ContentLength": len(self.objects[(Bucket, Key)])}


class _Body:
    """Imite `StreamingBody` de boto3 : lecture par tranches et context manager."""

    def __init__(self, data):
        self._buffer = io.BytesIO(data)

    def read(self, size=-1):
        return self._buffer.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._buffer.close()
        return False


def test_layer_uri_joins_a_local_directory():
    assert layer_uri("bronze", "file:///tmp/lac/") == "file:///tmp/lac/bronze"


def test_layer_uri_treats_each_layer_as_a_bucket_on_s3():
    assert layer_uri("bronze", "s3://") == "s3://bronze"


def test_partition_uri_without_panel():
    uri = partition_uri("bronze", "clinvar", "2026-09-01", lake_uri="s3://")
    assert uri == "s3://bronze/clinvar/dt=2026-09-01"


def test_partition_uri_with_panel():
    uri = partition_uri("bronze", "medgen", "2026-09-01", panel="brca", lake_uri="s3://")
    assert uri == "s3://bronze/medgen/dt=2026-09-01/panel=brca"


def test_put_and_get_bytes_on_local_filesystem(tmp_path):
    uri = f"file://{tmp_path}/bronze/clinvar/dt=2026-09-01/data.txt"
    put_bytes(uri, b"contenu")
    assert get_bytes(uri) == b"contenu"
    assert exists(uri) is True


def test_put_and_get_bytes_on_s3():
    client = FakeS3()
    uri = "s3://bronze/clinvar/dt=2026-09-01/data.txt"
    put_bytes(uri, b"contenu", client=client)
    assert client.objects[("bronze", "clinvar/dt=2026-09-01/data.txt")] == b"contenu"
    assert get_bytes(uri, client=client) == b"contenu"


def test_put_file_streams_from_disk(tmp_path):
    """Le bulk ClinVar fait 442 Mo : il ne doit jamais transiter par la mémoire."""
    source = tmp_path / "bulk.gz"
    source.write_bytes(b"donnees volumineuses")
    client = FakeS3()

    put_file("s3://bronze/clinvar/dt=2026-09-01/bulk.gz", source, client=client)

    assert client.objects[("bronze", "clinvar/dt=2026-09-01/bulk.gz")] == b"donnees volumineuses"


def test_exists_is_false_for_missing_object(tmp_path):
    assert exists(f"file://{tmp_path}/absent.txt") is False


def test_open_stream_reads_without_materialising_the_whole_object(tmp_path):
    """Le bulk ClinVar fait 442 Mo compressés (~4 Go décompressés) : les
    consommateurs doivent pouvoir le parcourir sans le charger en mémoire."""
    uri = f"file://{tmp_path}/bronze/clinvar/dt=2026-09-01/data.bin"
    put_bytes(uri, b"premier|second")

    with open_stream(uri) as stream:
        assert stream.read(7) == b"premier"
        assert stream.read() == b"|second"


def test_open_stream_reads_from_s3():
    client = FakeS3()
    uri = "s3://bronze/clinvar/dt=2026-09-01/data.bin"
    put_bytes(uri, b"flux s3", client=client)

    with open_stream(uri, client=client) as stream:
        assert stream.read() == b"flux s3"


def test_build_manifest_records_source_version_and_sizes():
    manifest = build_manifest(
        source="clinvar",
        logical_date="2026-09-01",
        source_url="https://example.org/variant_summary_2026-09.txt.gz",
        source_version="2026-09",
        files={"variant_summary.txt.gz": 442495433},
        record_count=1,
    )
    assert manifest["source"] == "clinvar"
    assert manifest["logical_date"] == "2026-09-01"
    assert manifest["source_version"] == "2026-09"
    assert manifest["files"] == {"variant_summary.txt.gz": 442495433}
    assert manifest["record_count"] == 1
    assert manifest["panel"] is None
    assert manifest["written_at"].endswith("+00:00")


def test_finalize_partition_writes_manifest_then_success_marker(tmp_path):
    partition = f"file://{tmp_path}/bronze/clinvar/dt=2026-09-01"
    manifest = build_manifest(
        source="clinvar", logical_date="2026-09-01", source_url="u",
        source_version="v", files={}, record_count=0,
    )

    finalize_partition(partition, manifest)

    written = json.loads(get_bytes(f"{partition}/manifest.json"))
    assert written["source"] == "clinvar"
    assert exists(f"{partition}/_SUCCESS") is True


def test_partition_is_complete_only_after_finalize(tmp_path):
    partition = f"file://{tmp_path}/bronze/hpo/dt=2026-09-01"
    put_bytes(f"{partition}/genes_to_phenotype.txt.gz", b"x")

    assert partition_is_complete(partition) is False

    finalize_partition(partition, build_manifest(
        source="hpo", logical_date="2026-09-01", source_url="u",
        source_version="v", files={}, record_count=0,
    ))

    assert partition_is_complete(partition) is True
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/ingestion/test_storage.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestion.storage'`

- [ ] **Step 3: Implémenter `src/ingestion/storage.py`**

```python
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ingestion.config import current_lake_uri

S3_SCHEME = "s3://"
FILE_SCHEME = "file://"

SUCCESS_MARKER = "_SUCCESS"
MANIFEST_NAME = "manifest.json"


def layer_uri(layer: str, lake_uri: str | None = None) -> str:
    """URI d'une couche du médaillon.

    Sur MinIO chaque couche est un bucket (`s3://bronze`) ; en local c'est un
    sous-dossier de la racine du lac.
    """
    base = lake_uri if lake_uri is not None else current_lake_uri()
    # "s3://".rstrip("/") vaut "s3:" : c'est la forme "racine S3, la couche est le bucket".
    if base.rstrip("/") == "s3:":
        return f"{S3_SCHEME}{layer}"
    return f"{base.rstrip('/')}/{layer}"


def partition_uri(
    layer: str,
    source: str,
    logical_date: str,
    panel: str | None = None,
    lake_uri: str | None = None,
) -> str:
    """Chemin d'une partition : `<couche>/<source>/dt=<date>[/panel=<panel>]`.

    La date logique est le seul discriminant : rejouer un run réécrit cette
    partition et aucune autre.
    """
    parts = [layer_uri(layer, lake_uri), source, f"dt={logical_date}"]
    if panel:
        parts.append(f"panel={panel}")
    return "/".join(parts)


def _split_s3(uri: str) -> tuple[str, str]:
    bucket, _, key = uri[len(S3_SCHEME):].partition("/")
    return bucket, key


def _local_path(uri: str) -> Path:
    return Path(uri[len(FILE_SCHEME):]) if uri.startswith(FILE_SCHEME) else Path(uri)


def _s3_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )


def put_bytes(uri: str, data: bytes, client=None) -> None:
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        (client or _s3_client()).put_object(Bucket=bucket, Key=key, Body=data)
        return
    path = _local_path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def put_file(uri: str, local_path: Path, client=None) -> None:
    """Dépose un fichier depuis le disque, sans le charger en mémoire.

    Indispensable pour le bulk ClinVar (442 Mo).
    """
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        (client or _s3_client()).upload_file(
            Filename=str(local_path), Bucket=bucket, Key=key
        )
        return
    destination = _local_path(uri)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(local_path, destination)


def get_bytes(uri: str, client=None) -> bytes:
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        return (client or _s3_client()).get_object(Bucket=bucket, Key=key)["Body"].read()
    return _local_path(uri).read_bytes()


def open_stream(uri: str, client=None):
    """Ouvre un objet en lecture binaire, sans le matérialiser en mémoire.

    Nécessaire pour le bulk ClinVar : 442 Mo compressés, ~4 Go décompressés, à
    parcourir sur un worker qui ne dispose que de quelques Go.
    """
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        return (client or _s3_client()).get_object(Bucket=bucket, Key=key)["Body"]
    return open(_local_path(uri), "rb")


def exists(uri: str, client=None) -> bool:
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        try:
            (client or _s3_client()).head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False
    return _local_path(uri).exists()


def build_manifest(
    source: str,
    logical_date: str,
    source_url: str,
    source_version: str,
    files: dict[str, int],
    record_count: int,
    panel: str | None = None,
) -> dict:
    """Décrit une partition Bronze de façon auto-portante.

    `source_version` est la version épinglée de la source (mois d'archive ClinVar,
    tag de release HPO), et non l'horodatage local : c'est ce qui rend deux rejeux
    du même `logical_date` comparables.
    """
    return {
        "source": source,
        "logical_date": logical_date,
        "panel": panel,
        "source_url": source_url,
        "source_version": source_version,
        "files": files,
        "record_count": record_count,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }


def finalize_partition(partition: str, manifest: dict, client=None) -> None:
    """Clôt une partition : manifest d'abord, marqueur `_SUCCESS` en dernier.

    L'ordre compte : sur un stockage objet il n'y a pas de renommage atomique, donc
    `_SUCCESS` écrit en dernier est ce qui distingue une partition complète d'une
    partition interrompue.
    """
    payload = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    put_bytes(f"{partition}/{MANIFEST_NAME}", payload, client=client)
    put_bytes(f"{partition}/{SUCCESS_MARKER}", b"", client=client)


def partition_is_complete(partition: str, client=None) -> bool:
    return exists(f"{partition}/{SUCCESS_MARKER}", client=client)
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `venv/bin/pytest tests/ingestion/test_storage.py -q`
Expected: PASS, 13 tests

- [ ] **Step 5: Ajouter le test d'intégration contre un vrai MinIO**

Ajouter à `tests/ingestion/test_storage.py` — imports en tête de fichier, test à la fin :

```python
@pytest.mark.integration
def test_storage_round_trip_against_a_real_minio():
    """Le client factice valide la logique ; ce test valide le contrat S3 réel.

    Exclu de la passe rapide (`addopts = -m "not integration"`). Prérequis :
    un MinIO joignable et les variables AWS_* renseignées, avec un bucket `bronze`.
    """
    partition = partition_uri("bronze", "test_integration", "2026-09-01", lake_uri="s3://")
    put_bytes(f"{partition}/data.txt", b"aller-retour")

    assert get_bytes(f"{partition}/data.txt") == b"aller-retour"

    finalize_partition(partition, build_manifest(
        source="test_integration", logical_date="2026-09-01", source_url="u",
        source_version="v", files={"data.txt": 12}, record_count=1,
    ))
    assert partition_is_complete(partition) is True
```

Run: `venv/bin/pytest tests/ingestion/test_storage.py -q`
Expected: PASS, 13 tests — le test d'intégration est **désélectionné**, pas exécuté

- [ ] **Step 6: Vérifier la suite complète**

Run: `venv/bin/pytest -q`
Expected: PASS, 79 tests

- [ ] **Step 7: Commit**

```bash
git add src/ingestion/storage.py tests/ingestion/test_storage.py
git commit -m "feat: add object-storage layer with manifest and _SUCCESS markers"
```

---

### Task 3: Vérification d'intégrité du téléchargement

**Files:**
- Modify: `src/ingestion/download.py`
- Test: `tests/ingestion/test_download.py`

**Interfaces:**
- Consumes: rien.
- Produces: `ingestion.download.IncompleteDownloadError`, `download_to_file(url, destination, force=False, verify_size=True) -> Path`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/ingestion/test_download.py` — **les `import` vont dans le bloc d'imports en tête de fichier, pas au milieu (E402) ; seules les fonctions de test vont à la fin** :

```python
from ingestion.download import IncompleteDownloadError


@responses.activate
def test_download_to_file_rejects_a_truncated_response(tmp_path):
    """Un fichier tronqué ne doit jamais être conservé : le skip-si-présent le
    réutiliserait ensuite comme complet."""
    responses.add(
        responses.GET,
        URL,
        body=b"court",
        status=200,
        headers={"Content-Length": "999999"},
    )
    destination = tmp_path / "external" / "big-file.txt"

    with pytest.raises(IncompleteDownloadError):
        download_to_file(URL, destination)

    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


@responses.activate
def test_download_to_file_accepts_a_response_without_content_length(tmp_path):
    responses.add(responses.GET, URL, body=b"sans entete de taille", status=200)
    destination = tmp_path / "external" / "big-file.txt"

    download_to_file(URL, destination)

    assert destination.read_bytes() == b"sans entete de taille"
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/ingestion/test_download.py -q`
Expected: FAIL avec `ImportError: cannot import name 'IncompleteDownloadError'`

- [ ] **Step 3: Modifier `src/ingestion/download.py`**

Ajouter la classe d'exception après `CHUNK_SIZE = 8192` :

```python
class IncompleteDownloadError(RuntimeError):
    """Le nombre d'octets reçus ne correspond pas au `Content-Length` annoncé."""
```

Puis, dans `download_to_file`, remplacer le bloc `with requests.get(...)` par :

```python
    try:
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            expected = response.headers.get("Content-Length")
            written = 0
            with open(partial, "wb") as fh:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    fh.write(chunk)
                    written += len(chunk)
        if verify_size and expected is not None and written != int(expected):
            raise IncompleteDownloadError(
                f"{url} : {written} octets reçus pour {expected} annoncés"
            )
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return destination
```

Et adapter la signature ainsi que sa docstring :

```python
def download_to_file(
    url: str, destination: Path, force: bool = False, verify_size: bool = True
) -> Path:
```

Ajouter au corps de la docstring existante :

```
    La taille reçue est comparée au `Content-Length` annoncé quand il est présent :
    une réponse tronquée est rejetée au lieu d'être promue en fichier complet.
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `venv/bin/pytest tests/ingestion/test_download.py -q`
Expected: PASS, 7 tests — les 5 tests existants inclus

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/download.py tests/ingestion/test_download.py
git commit -m "feat: verify Content-Length to reject truncated downloads"
```

---

### Task 4: URL de sources épinglées sur une version

**Files:**
- Modify: `src/ingestion/clinvar.py`
- Modify: `src/ingestion/hpo.py`
- Test: `tests/ingestion/test_clinvar.py`, `tests/ingestion/test_hpo.py`

**Interfaces:**
- Consumes: `ingestion.http_client.build_retrying_session`.
- Produces:
  - `ingestion.clinvar.archive_url_for(logical_date: str) -> str`
  - `ingestion.clinvar.archive_version_for(logical_date: str) -> str`
  - `ingestion.hpo.resolve_release_tag(session=None) -> str`
  - `ingestion.hpo.release_url_for(release_tag: str) -> str`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/ingestion/test_clinvar.py` — **les `import` vont dans le bloc d'imports en tête de fichier, pas au milieu (E402) ; seules les fonctions de test vont à la fin** :

```python
from ingestion.clinvar import archive_url_for, archive_version_for


def test_archive_url_for_pins_the_monthly_release():
    """ClinVar publie des archives mensuelles immuables. Le fichier « latest »
    change sous les pieds : rejouer août téléchargerait septembre."""
    assert archive_url_for("2026-09-01") == (
        "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/"
        "variant_summary_2026-09.txt.gz"
    )


def test_archive_version_for_is_the_year_month():
    assert archive_version_for("2026-09-01") == "2026-09"
    assert archive_version_for("2026-12-31") == "2026-12"
```

Ajouter à `tests/ingestion/test_hpo.py` — **les `import` vont dans le bloc d'imports en tête de fichier, pas au milieu (E402) ; seules les fonctions de test vont à la fin** :

```python
import responses

from ingestion.hpo import release_url_for, resolve_release_tag


def test_release_url_for_builds_a_tagged_download_url():
    assert release_url_for("v2026-09-01") == (
        "https://github.com/obophenotype/human-phenotype-ontology/releases/"
        "download/v2026-09-01/genes_to_phenotype.txt"
    )


@responses.activate
def test_resolve_release_tag_reads_the_redirect_from_latest():
    responses.add(
        responses.GET,
        "https://github.com/obophenotype/human-phenotype-ontology/releases/latest",
        status=302,
        headers={
            "Location": "https://github.com/obophenotype/human-phenotype-ontology"
            "/releases/tag/v2026-09-01"
        },
    )
    assert resolve_release_tag() == "v2026-09-01"
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/ingestion/test_clinvar.py tests/ingestion/test_hpo.py -q`
Expected: FAIL avec `ImportError: cannot import name 'archive_url_for'`

- [ ] **Step 3: Implémenter dans `src/ingestion/clinvar.py`**

Ajouter après `CLINVAR_BULK_URL` :

```python
# Archives mensuelles immuables. Le fichier « latest » est rafraîchi plus souvent
# que la publication mensuelle : l'épingler par mois est ce qui rend un rejeu de
# `dt=2026-08-01` réellement identique à l'exécution d'origine.
CLINVAR_ARCHIVE_URL_TEMPLATE = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/"
    "variant_summary_{version}.txt.gz"
)


def archive_version_for(logical_date: str) -> str:
    """Version d'archive ClinVar correspondant à une date logique (`YYYY-MM`)."""
    return logical_date[:7]


def archive_url_for(logical_date: str) -> str:
    """URL de l'archive ClinVar épinglée sur le mois de la date logique."""
    return CLINVAR_ARCHIVE_URL_TEMPLATE.format(version=archive_version_for(logical_date))
```

- [ ] **Step 4: Implémenter dans `src/ingestion/hpo.py`**

Ajouter après `GENES_TO_PHENOTYPE_URL` :

```python
# HPO publie des releases taguées (`v2026-09-01`). La PURL pointe sur « latest »,
# qui change : on résout le tag une fois, on l'enregistre au manifest, et on
# télécharge l'URL taguée — un rejeu retéléchargera exactement le même fichier.
HPO_LATEST_RELEASE_URL = (
    "https://github.com/obophenotype/human-phenotype-ontology/releases/latest"
)
HPO_RELEASE_URL_TEMPLATE = (
    "https://github.com/obophenotype/human-phenotype-ontology/releases/"
    "download/{release_tag}/genes_to_phenotype.txt"
)


def release_url_for(release_tag: str) -> str:
    """URL de téléchargement de `genes_to_phenotype.txt` pour un tag de release."""
    return HPO_RELEASE_URL_TEMPLATE.format(release_tag=release_tag)


def resolve_release_tag(session: requests.Session | None = None) -> str:
    """Résout le tag de la release HPO courante via la redirection de `/releases/latest`."""
    session = session or build_retrying_session()
    response = session.get(HPO_LATEST_RELEASE_URL, allow_redirects=False, timeout=30)
    location = response.headers["Location"]
    return location.rstrip("/").rsplit("/", 1)[-1]
```

- [ ] **Step 5: Lancer les tests pour vérifier qu'ils passent**

Run: `venv/bin/pytest tests/ingestion/test_clinvar.py tests/ingestion/test_hpo.py -q`
Expected: PASS, tous les tests existants inclus

- [ ] **Step 6: Commit**

```bash
git add src/ingestion/clinvar.py src/ingestion/hpo.py tests/ingestion/test_clinvar.py tests/ingestion/test_hpo.py
git commit -m "feat: pin ClinVar and HPO sources to immutable versioned releases"
```

---

### Task 5: Cinquième source — catalogue des transcrits RefSeq

**Files:**
- Create: `src/ingestion/refseq.py`
- Test: `tests/ingestion/test_refseq.py`

**Interfaces:**
- Consumes: `ingestion.http_client.NcbiClient`.
- Produces: `ingestion.refseq.fetch_transcripts(client: NcbiClient, gene_symbol: str) -> list[dict]`, `REFSEQ_SEARCH_TEMPLATE: str`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/ingestion/test_refseq.py` :

```python
import responses

from ingestion.http_client import NcbiClient, RateLimiter

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


@responses.activate
def test_fetch_transcripts_returns_one_summary_per_uid():
    from ingestion.refseq import fetch_transcripts

    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": ["2778098787", "2240897268"]}}, status=200)
    responses.add(responses.GET, ESUMMARY, json={"result": {
        "2778098787": {"accessionversion": "NM_001432077.1", "slen": 11863}}}, status=200)
    responses.add(responses.GET, ESUMMARY, json={"result": {
        "2240897268": {"accessionversion": "NM_000059.4", "slen": 11986}}}, status=200)

    result = fetch_transcripts(_client(), "BRCA2")

    assert [t["accessionversion"] for t in result] == ["NM_001432077.1", "NM_000059.4"]
    assert result[0]["slen"] == 11863


@responses.activate
def test_fetch_transcripts_returns_empty_list_when_no_transcript():
    from ingestion.refseq import fetch_transcripts

    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": []}}, status=200)

    assert fetch_transcripts(_client(), "HBS1L") == []


@responses.activate
def test_fetch_transcripts_restricts_to_human_refseq_mrna():
    from ingestion.refseq import fetch_transcripts

    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": []}}, status=200)

    fetch_transcripts(_client(), "BRCA1")

    sent = responses.calls[0].request.params
    assert sent["db"] == "nuccore"
    assert sent["term"] == (
        "BRCA1[gene] AND human[orgn] AND srcdb_refseq[prop] AND biomol_mrna[prop]"
    )
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/ingestion/test_refseq.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestion.refseq'`

- [ ] **Step 3: Implémenter `src/ingestion/refseq.py`**

```python
from __future__ import annotations

from ingestion.http_client import NcbiClient

# Les variants ClinVar sont nommés en HGVS (`NM_000059.4:c.1234A>G`). La
# normalisation HGVS prévue en Silver a besoin du catalogue des transcrits de
# référence — accession, version, longueur — qu'aucune autre source du projet ne
# fournit. Les filtres restreignent aux ARNm RefSeq humains, seuls porteurs des
# accessions `NM_` citées par ClinVar.
REFSEQ_SEARCH_TEMPLATE = (
    "{gene}[gene] AND human[orgn] AND srcdb_refseq[prop] AND biomol_mrna[prop]"
)


def fetch_transcripts(client: NcbiClient, gene_symbol: str) -> list[dict]:
    """Récupère les transcrits RefSeq d'un gène (esearch nuccore puis esummary).

    Un gène sans transcrit RefSeq renvoie une liste vide plutôt qu'une erreur :
    c'est le cas légitime des loci GWAS du panel (HBS1L, MYB), traité comme
    l'absence de terme HPO ou de CUI MedGen résolvable.
    """
    uids = client.esearch(
        db="nuccore", term=REFSEQ_SEARCH_TEMPLATE.format(gene=gene_symbol)
    )
    return [client.esummary(db="nuccore", uid=uid) for uid in uids]
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `venv/bin/pytest tests/ingestion/test_refseq.py -q`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/refseq.py tests/ingestion/test_refseq.py
git commit -m "feat: add RefSeq transcript catalogue as fifth source"
```

---

### Task 6: Scripts d'acquisition partagée

**Files:**
- Create: `scripts/ingest_clinvar.py`
- Create: `scripts/ingest_hpo_files.py`
- Test: `tests/scripts/test_ingest_clinvar.py`, `tests/scripts/__init__.py`

**Interfaces:**
- Consumes: `ingestion.storage.partition_uri/put_file/build_manifest/finalize_partition`, `ingestion.clinvar.archive_url_for/archive_version_for`, `ingestion.download.download_to_file`, `ingestion.hpo.resolve_release_tag/release_url_for`, `ingestion.config.BRONZE`.
- Produces: `scripts.ingest_clinvar.ingest_clinvar(logical_date, lake_uri=None, cache_dir=None) -> str` (renvoie l'URI de partition), même forme pour `scripts.ingest_hpo_files.ingest_hpo_files`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/scripts/__init__.py` (fichier vide) puis `tests/scripts/test_ingest_clinvar.py` :

```python
import json

import responses

from ingestion.storage import get_bytes, partition_is_complete
from scripts.ingest_clinvar import ingest_clinvar

ARCHIVE = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/"
    "variant_summary_2026-09.txt.gz"
)


@responses.activate
def test_ingest_clinvar_deposits_the_bulk_and_finalises_the_partition(tmp_path):
    responses.add(responses.GET, ARCHIVE, body=b"bulk gzippe", status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_clinvar("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    assert partition == f"{lake}/bronze/clinvar/dt=2026-09-01"
    assert get_bytes(f"{partition}/variant_summary.txt.gz") == b"bulk gzippe"
    assert partition_is_complete(partition) is True


@responses.activate
def test_ingest_clinvar_manifest_pins_the_source_version(tmp_path):
    responses.add(responses.GET, ARCHIVE, body=b"bulk gzippe", status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_clinvar("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    manifest = json.loads(get_bytes(f"{partition}/manifest.json"))
    assert manifest["source"] == "clinvar"
    assert manifest["source_version"] == "2026-09"
    assert manifest["source_url"] == ARCHIVE
    assert manifest["files"] == {"variant_summary.txt.gz": len(b"bulk gzippe")}


@responses.activate
def test_ingest_clinvar_deposits_the_bulk_unfiltered(tmp_path):
    """Bronze est strictement brut : aucun filtrage sur le panel à ce stade."""
    contenu = b"#AlleleID\tGeneSymbol\n1\tINCONNU\n2\tBRCA1\n"
    responses.add(responses.GET, ARCHIVE, body=contenu, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_clinvar("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    assert get_bytes(f"{partition}/variant_summary.txt.gz") == contenu
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `venv/bin/pytest tests/scripts/test_ingest_clinvar.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'scripts.ingest_clinvar'`

- [ ] **Step 3: Implémenter `scripts/ingest_clinvar.py`**

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.clinvar import archive_url_for, archive_version_for
from ingestion.config import BRONZE, DATA_EXTERNAL_DIR
from ingestion.download import download_to_file
from ingestion.storage import (
    build_manifest,
    finalize_partition,
    partition_uri,
    put_file,
)

OBJECT_NAME = "variant_summary.txt.gz"


def ingest_clinvar(
    logical_date: str, lake_uri: str | None = None, cache_dir: Path | None = None
) -> str:
    """Dépose le bulk ClinVar du mois de `logical_date` en Bronze, sans le filtrer.

    Le fichier est d'abord téléchargé sur disque puis téléversé en flux : à 442 Mo,
    il ne doit jamais transiter par la mémoire du worker Airflow.
    """
    url = archive_url_for(logical_date)
    cache_dir = cache_dir or DATA_EXTERNAL_DIR
    local = download_to_file(url, cache_dir / f"variant_summary_{archive_version_for(logical_date)}.txt.gz")

    partition = partition_uri(BRONZE, "clinvar", logical_date, lake_uri=lake_uri)
    put_file(f"{partition}/{OBJECT_NAME}", local)

    finalize_partition(
        partition,
        build_manifest(
            source="clinvar",
            logical_date=logical_date,
            source_url=url,
            source_version=archive_version_for(logical_date),
            files={OBJECT_NAME: local.stat().st_size},
            record_count=1,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose le bulk ClinVar en Bronze.")
    parser.add_argument("--logical-date", required=True, help="date logique du run (YYYY-MM-DD)")
    parser.add_argument("--lake-uri", default=None, help="racine du lac (défaut : LAKE_URI)")
    args = parser.parse_args()
    print(ingest_clinvar(args.logical_date, lake_uri=args.lake_uri))
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `venv/bin/pytest tests/scripts/test_ingest_clinvar.py -q`
Expected: PASS, 3 tests

- [ ] **Step 5: Implémenter `scripts/ingest_hpo_files.py`**

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import BRONZE, DATA_EXTERNAL_DIR
from ingestion.download import download_to_file
from ingestion.hpo import release_url_for, resolve_release_tag
from ingestion.storage import (
    build_manifest,
    finalize_partition,
    partition_uri,
    put_file,
)

OBJECT_NAME = "genes_to_phenotype.txt"


def ingest_hpo_files(
    logical_date: str,
    lake_uri: str | None = None,
    cache_dir: Path | None = None,
    release_tag: str | None = None,
) -> str:
    """Dépose `genes_to_phenotype.txt` en Bronze, épinglé sur un tag de release.

    Le tag résolu est inscrit au manifest : c'est lui, et non la date du run, qui
    identifie la version de la source.
    """
    release_tag = release_tag or resolve_release_tag()
    url = release_url_for(release_tag)
    cache_dir = cache_dir or DATA_EXTERNAL_DIR
    local = download_to_file(url, cache_dir / f"genes_to_phenotype_{release_tag}.txt")

    partition = partition_uri(BRONZE, "hpo", logical_date, lake_uri=lake_uri)
    put_file(f"{partition}/{OBJECT_NAME}", local)

    finalize_partition(
        partition,
        build_manifest(
            source="hpo",
            logical_date=logical_date,
            source_url=url,
            source_version=release_tag,
            files={OBJECT_NAME: local.stat().st_size},
            record_count=1,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les fichiers plats HPO en Bronze.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--lake-uri", default=None)
    parser.add_argument("--release-tag", default=None, help="défaut : résolu depuis /releases/latest")
    args = parser.parse_args()
    print(ingest_hpo_files(args.logical_date, lake_uri=args.lake_uri, release_tag=args.release_tag))
```

- [ ] **Step 6: Vérifier la suite complète**

Run: `venv/bin/pytest -q`
Expected: PASS, 91 tests

- [ ] **Step 7: Commit**

```bash
git add scripts/ingest_clinvar.py scripts/ingest_hpo_files.py tests/scripts/
git commit -m "feat: add shared acquisition scripts writing raw Bronze partitions"
```

---

### Task 7: Scripts d'ingestion par panel — NCBI Gene et RefSeq

**Files:**
- Create: `scripts/ingest_ncbi_gene.py`
- Create: `scripts/ingest_refseq.py`
- Create: `src/ingestion/jsonl.py`
- Test: `tests/ingestion/test_jsonl.py`, `tests/scripts/test_ingest_ncbi_gene.py`

**Interfaces:**
- Consumes: `ingestion.ncbi_gene.fetch_gene_info`, `ingestion.refseq.fetch_transcripts`, `ingestion.storage.*`.
- Produces: `ingestion.jsonl.dumps_gzipped(records: list[dict]) -> bytes`, `scripts.ingest_ncbi_gene.ingest_ncbi_gene(logical_date, panel, genes, client, lake_uri=None) -> str`, `scripts.ingest_refseq.ingest_refseq(logical_date, panel, genes, client, lake_uri=None) -> str`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/ingestion/test_jsonl.py` :

```python
import gzip
import json

from ingestion.jsonl import dumps_gzipped


def test_dumps_gzipped_writes_one_json_object_per_line():
    payload = dumps_gzipped([{"a": 1}, {"b": "é"}])
    lines = gzip.decompress(payload).decode("utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [{"a": 1}, {"b": "é"}]


def test_dumps_gzipped_preserves_non_ascii_characters():
    payload = dumps_gzipped([{"nom": "drépanocytose"}])
    assert "drépanocytose" in gzip.decompress(payload).decode("utf-8")


def test_dumps_gzipped_handles_an_empty_list():
    assert gzip.decompress(dumps_gzipped([])) == b""
```

Créer `tests/scripts/test_ingest_ncbi_gene.py` :

```python
import gzip
import json

import responses

from ingestion.http_client import NcbiClient, RateLimiter
from ingestion.storage import get_bytes, partition_is_complete
from scripts.ingest_ncbi_gene import ingest_ncbi_gene

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


@responses.activate
def test_ingest_ncbi_gene_writes_one_jsonl_record_per_gene(tmp_path):
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": ["3043"]}}, status=200)
    responses.add(responses.GET, ESUMMARY,
                  json={"result": {"3043": {"name": "HBB"}}}, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_ncbi_gene("2026-09-01", "sickle", ["HBB"], _client(), lake_uri=lake)

    assert partition == f"{lake}/bronze/ncbi_gene/dt=2026-09-01/panel=sickle"
    raw = gzip.decompress(get_bytes(f"{partition}/gene_summaries.jsonl.gz")).decode()
    records = [json.loads(line) for line in raw.splitlines()]
    assert records == [{"gene_symbol": "HBB", "esummary": {"name": "HBB"}}]
    assert partition_is_complete(partition) is True


@responses.activate
def test_ingest_ncbi_gene_keeps_unresolved_genes_as_empty_summaries(tmp_path):
    """Un symbole non résolu est une information, pas une erreur : il doit rester
    traçable depuis la partition."""
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": []}}, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_ncbi_gene("2026-09-01", "sickle", ["HBS1L"], _client(), lake_uri=lake)

    raw = gzip.decompress(get_bytes(f"{partition}/gene_summaries.jsonl.gz")).decode()
    assert json.loads(raw.strip()) == {"gene_symbol": "HBS1L", "esummary": {}}
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/ingestion/test_jsonl.py tests/scripts/test_ingest_ncbi_gene.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestion.jsonl'`

- [ ] **Step 3: Implémenter `src/ingestion/jsonl.py`**

```python
from __future__ import annotations

import gzip
import json


def dumps_gzipped(records: list[dict]) -> bytes:
    """Sérialise des enregistrements en JSONL gzippé.

    JSONL parce que c'est le seul format qui préserve la réponse d'API mot pour mot
    tout en restant lisible ligne à ligne, sans imposer de schéma — donc sans
    transformation, ce qu'exige le contrat Bronze.
    """
    body = "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in records
    )
    return gzip.compress(body.encode("utf-8"))
```

- [ ] **Step 4: Implémenter `scripts/ingest_ncbi_gene.py`**

```python
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from ingestion.config import BRONZE
from ingestion.http_client import NcbiClient
from ingestion.jsonl import dumps_gzipped
from ingestion.ncbi_gene import fetch_gene_info
from ingestion.storage import build_manifest, finalize_partition, partition_uri, put_bytes

OBJECT_NAME = "gene_summaries.jsonl.gz"


class ConfigurationError(RuntimeError):
    """Erreur permanente : la relancer ne peut pas la résoudre."""


def build_client() -> NcbiClient:
    load_dotenv()
    if not os.environ.get("NCBI_EMAIL"):
        raise ConfigurationError(
            "NCBI_EMAIL manquant : renseigner la variable d'environnement (voir README)."
        )
    return NcbiClient(
        email=os.environ["NCBI_EMAIL"], api_key=os.environ.get("NCBI_API_KEY", "")
    )


def ingest_ncbi_gene(
    logical_date: str,
    panel: str,
    genes: list[str],
    client: NcbiClient,
    lake_uri: str | None = None,
) -> str:
    """Dépose les esummary NCBI Gene du panel en Bronze, un enregistrement par gène.

    Un gène que NCBI Gene ne résout pas conserve une entrée à `esummary` vide : le
    verdict qualité appartient à la tâche `check_bronze`, pas à l'ingestion.
    """
    records = [
        {"gene_symbol": gene, "esummary": fetch_gene_info(client, gene)}
        for gene in genes
    ]
    partition = partition_uri(BRONZE, "ncbi_gene", logical_date, panel=panel, lake_uri=lake_uri)
    payload = dumps_gzipped(records)
    put_bytes(f"{partition}/{OBJECT_NAME}", payload)

    finalize_partition(
        partition,
        build_manifest(
            source="ncbi_gene",
            logical_date=logical_date,
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=gene",
            source_version=logical_date,
            files={OBJECT_NAME: len(payload)},
            record_count=len(records),
            panel=panel,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les métadonnées NCBI Gene en Bronze.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--genes", required=True, help="symboles séparés par des virgules")
    parser.add_argument("--lake-uri", default=None)
    args = parser.parse_args()
    print(ingest_ncbi_gene(
        args.logical_date, args.panel, args.genes.split(","), build_client(),
        lake_uri=args.lake_uri,
    ))
```

- [ ] **Step 5: Lancer les tests pour vérifier qu'ils passent**

Run: `venv/bin/pytest tests/ingestion/test_jsonl.py tests/scripts/test_ingest_ncbi_gene.py -q`
Expected: PASS, 5 tests

- [ ] **Step 6: Implémenter `scripts/ingest_refseq.py`**

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import BRONZE
from ingestion.http_client import NcbiClient
from ingestion.jsonl import dumps_gzipped
from ingestion.refseq import fetch_transcripts
from ingestion.storage import build_manifest, finalize_partition, partition_uri, put_bytes
from scripts.ingest_ncbi_gene import build_client

OBJECT_NAME = "transcripts.jsonl.gz"


def ingest_refseq(
    logical_date: str,
    panel: str,
    genes: list[str],
    client: NcbiClient,
    lake_uri: str | None = None,
) -> str:
    """Dépose le catalogue des transcrits RefSeq du panel en Bronze.

    Un gène sans transcrit garde une entrée à liste vide : l'absence est une
    information, et le verdict qualité appartient à `check_bronze`.
    """
    records = [
        {"gene_symbol": gene, "transcripts": fetch_transcripts(client, gene)}
        for gene in genes
    ]
    partition = partition_uri(BRONZE, "refseq", logical_date, panel=panel, lake_uri=lake_uri)
    payload = dumps_gzipped(records)
    put_bytes(f"{partition}/{OBJECT_NAME}", payload)

    finalize_partition(
        partition,
        build_manifest(
            source="refseq",
            logical_date=logical_date,
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=nuccore",
            source_version=logical_date,
            files={OBJECT_NAME: len(payload)},
            record_count=len(records),
            panel=panel,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les transcrits RefSeq en Bronze.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--genes", required=True, help="symboles séparés par des virgules")
    parser.add_argument("--lake-uri", default=None)
    args = parser.parse_args()
    print(ingest_refseq(
        args.logical_date, args.panel, args.genes.split(","), build_client(),
        lake_uri=args.lake_uri,
    ))
```

- [ ] **Step 7: Vérifier la suite complète**

Run: `venv/bin/pytest -q`
Expected: PASS, 96 tests

- [ ] **Step 8: Commit**

```bash
git add src/ingestion/jsonl.py scripts/ingest_ncbi_gene.py scripts/ingest_refseq.py tests/
git commit -m "feat: add per-panel NCBI Gene and RefSeq Bronze ingestion"
```

---

### Task 8: Scripts d'ingestion par panel — MedGen et termes HPO

**Files:**
- Create: `scripts/ingest_medgen.py`
- Create: `scripts/ingest_hpo_terms.py`
- Test: `tests/scripts/test_ingest_medgen.py`

**Interfaces:**
- Consumes: `ingestion.storage.get_bytes/partition_uri`, `ingestion.medgen.extract_medgen_cuis/fetch_medgen_concept`, `ingestion.hpo.parse_genes_to_phenotype/fetch_hpo_term_details`.
- Produces: `scripts.ingest_medgen.cuis_from_bronze_clinvar(partition, genes, client=None) -> list[str]`, `scripts.ingest_medgen.ingest_medgen(logical_date, panel, genes, client, lake_uri=None) -> str`, `scripts.ingest_hpo_terms.ingest_hpo_terms(logical_date, panel, genes, lake_uri=None) -> str`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/scripts/test_ingest_medgen.py` :

```python
import gzip
import json

import responses

from ingestion.http_client import NcbiClient, RateLimiter
from ingestion.storage import get_bytes, put_bytes
from scripts.ingest_medgen import cuis_from_bronze_clinvar, ingest_medgen

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

BULK = (
    "#AlleleID\tGeneSymbol\tPhenotypeIDS\n"
    "1\tHBB\tMedGen:C0002895,OMIM:603903\n"
    "2\tINCONNU\tMedGen:C9999999\n"
    "3\tHBB\tMedGen:C0002895\n"
)


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


def _seed_bronze_clinvar(tmp_path) -> str:
    partition = f"file://{tmp_path}/lake/bronze/clinvar/dt=2026-09-01"
    put_bytes(f"{partition}/variant_summary.txt.gz", gzip.compress(BULK.encode()))
    return partition


def test_cuis_from_bronze_clinvar_keeps_only_panel_genes(tmp_path):
    """La lecture du bulk sert à piloter les appels d'API ; rien n'est persisté,
    donc le flux reste unidirectionnel."""
    partition = _seed_bronze_clinvar(tmp_path)

    assert cuis_from_bronze_clinvar(partition, ["HBB"]) == ["C0002895"]


def test_cuis_from_bronze_clinvar_deduplicates_in_order(tmp_path):
    partition = _seed_bronze_clinvar(tmp_path)

    assert cuis_from_bronze_clinvar(partition, ["HBB", "INCONNU"]) == [
        "C0002895",
        "C9999999",
    ]


@responses.activate
def test_ingest_medgen_writes_one_record_per_cui(tmp_path):
    _seed_bronze_clinvar(tmp_path)
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": ["287"]}}, status=200)
    responses.add(responses.GET, ESUMMARY, json={"result": {
        "287": {"conceptid": "C0002895", "conceptmeta": "<OMIM><MIM>603903</MIM></OMIM>"}
    }}, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_medgen("2026-09-01", "sickle", ["HBB"], _client(), lake_uri=lake)

    raw = gzip.decompress(get_bytes(f"{partition}/concepts.jsonl.gz")).decode()
    records = [json.loads(line) for line in raw.splitlines()]
    assert records[0]["cui"] == "C0002895"
    assert records[0]["esummary"]["conceptmeta"] == "<OMIM><MIM>603903</MIM></OMIM>"


@responses.activate
def test_ingest_medgen_keeps_the_raw_conceptmeta_xml_unparsed(tmp_path):
    """Bronze est brut : l'aplatissement du XML appartient à Silver."""
    _seed_bronze_clinvar(tmp_path)
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": ["287"]}}, status=200)
    responses.add(responses.GET, ESUMMARY, json={"result": {
        "287": {"conceptid": "C0002895", "conceptmeta": "<OMIM><MIM>603903</MIM></OMIM>"}
    }}, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_medgen("2026-09-01", "sickle", ["HBB"], _client(), lake_uri=lake)

    record = json.loads(
        gzip.decompress(get_bytes(f"{partition}/concepts.jsonl.gz")).decode().splitlines()[0]
    )
    assert "mim_number" not in record["esummary"]
    assert isinstance(record["esummary"]["conceptmeta"], str)
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/scripts/test_ingest_medgen.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'scripts.ingest_medgen'`

- [ ] **Step 3: Implémenter `scripts/ingest_medgen.py`**

```python
from __future__ import annotations

import argparse
import csv
import gzip
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import BRONZE
from ingestion.http_client import NcbiClient
from ingestion.jsonl import dumps_gzipped
from ingestion.medgen import extract_medgen_cuis, fetch_medgen_concept
from ingestion.storage import (
    build_manifest,
    finalize_partition,
    open_stream,
    partition_uri,
    put_bytes,
)
from scripts.ingest_ncbi_gene import build_client

OBJECT_NAME = "concepts.jsonl.gz"
BULK_OBJECT = "variant_summary.txt.gz"


def cuis_from_bronze_clinvar(
    clinvar_partition: str, genes: list[str], client=None
) -> list[str]:
    """Extrait les CUI MedGen du bulk Bronze, pour les gènes du panel.

    MedGen a une dépendance de données sur ClinVar : les CUI viennent du champ
    `PhenotypeIDS`. Cette lecture pilote les appels d'API et ne persiste rien —
    le flux reste unidirectionnel.

    Le bulk est parcouru en flux : 442 Mo compressés, ~4 Go décompressés. Le
    décompresser en mémoire épuiserait la marge du worker, d'où la chaîne
    `open_stream` -> `GzipFile` -> `TextIOWrapper` -> `DictReader`, qui ne tient
    qu'une ligne à la fois.
    """
    genes_set = set(genes)
    cuis: list[str] = []

    with open_stream(f"{clinvar_partition}/{BULK_OBJECT}", client=client) as raw:
        with gzip.GzipFile(fileobj=raw, mode="rb") as decompressed:
            reader = csv.DictReader(
                io.TextIOWrapper(decompressed, encoding="utf-8"), delimiter="\t"
            )
            for row in reader:
                if row.get("GeneSymbol") not in genes_set:
                    continue
                for cui in extract_medgen_cuis(row.get("PhenotypeIDS") or ""):
                    if cui not in cuis:
                        cuis.append(cui)
    return cuis


def ingest_medgen(
    logical_date: str,
    panel: str,
    genes: list[str],
    client: NcbiClient,
    lake_uri: str | None = None,
) -> str:
    """Dépose les concepts MedGen du panel en Bronze, XML `conceptmeta` intact."""
    clinvar_partition = partition_uri(BRONZE, "clinvar", logical_date, lake_uri=lake_uri)
    cuis = cuis_from_bronze_clinvar(clinvar_partition, genes)

    records = [
        {"cui": cui, "esummary": fetch_medgen_concept(client, cui)} for cui in cuis
    ]
    partition = partition_uri(BRONZE, "medgen", logical_date, panel=panel, lake_uri=lake_uri)
    payload = dumps_gzipped(records)
    put_bytes(f"{partition}/{OBJECT_NAME}", payload)

    finalize_partition(
        partition,
        build_manifest(
            source="medgen",
            logical_date=logical_date,
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=medgen",
            source_version=logical_date,
            files={OBJECT_NAME: len(payload)},
            record_count=len(records),
            panel=panel,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les concepts MedGen en Bronze.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--genes", required=True, help="symboles séparés par des virgules")
    parser.add_argument("--lake-uri", default=None)
    args = parser.parse_args()
    print(ingest_medgen(
        args.logical_date, args.panel, args.genes.split(","), build_client(),
        lake_uri=args.lake_uri,
    ))
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `venv/bin/pytest tests/scripts/test_ingest_medgen.py -q`
Expected: PASS, 4 tests

- [ ] **Step 5: Implémenter `scripts/ingest_hpo_terms.py`**

```python
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import BRONZE
from ingestion.hpo import HP_TERMS_URL, fetch_hpo_term_details, parse_genes_to_phenotype
from ingestion.jsonl import dumps_gzipped
from ingestion.storage import (
    build_manifest,
    finalize_partition,
    get_bytes,
    partition_uri,
    put_bytes,
)

OBJECT_NAME = "hpo_terms.jsonl.gz"
GENES_TO_PHENOTYPE_OBJECT = "genes_to_phenotype.txt"


def ingest_hpo_terms(
    logical_date: str, panel: str, genes: list[str], lake_uri: str | None = None
) -> str:
    """Dépose les détails des termes HPO du panel en Bronze.

    Les IDs viennent du fichier plat déposé par le DAG d'acquisition ; leur
    enrichissement dépend des gènes du panel, d'où le partitionnement `panel=`.
    """
    hpo_partition = partition_uri(BRONZE, "hpo", logical_date, lake_uri=lake_uri)
    flat = get_bytes(f"{hpo_partition}/{GENES_TO_PHENOTYPE_OBJECT}")

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
        handle.write(flat)
        flat_path = Path(handle.name)
    try:
        rows = parse_genes_to_phenotype(flat_path, genes)
    finally:
        flat_path.unlink(missing_ok=True)

    details = fetch_hpo_term_details([row["hpo_id"] for row in rows])
    records = [
        {"hpo_id": hpo_id, "details": detail} for hpo_id, detail in details.items()
    ]

    partition = partition_uri(BRONZE, "hpo_terms", logical_date, panel=panel, lake_uri=lake_uri)
    payload = dumps_gzipped(records)
    put_bytes(f"{partition}/{OBJECT_NAME}", payload)

    finalize_partition(
        partition,
        build_manifest(
            source="hpo_terms",
            logical_date=logical_date,
            source_url=HP_TERMS_URL,
            source_version=logical_date,
            files={OBJECT_NAME: len(payload)},
            record_count=len(records),
            panel=panel,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les détails de termes HPO en Bronze.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--genes", required=True, help="symboles séparés par des virgules")
    parser.add_argument("--lake-uri", default=None)
    args = parser.parse_args()
    print(ingest_hpo_terms(
        args.logical_date, args.panel, args.genes.split(","), lake_uri=args.lake_uri,
    ))
```

- [ ] **Step 6: Vérifier la suite complète**

Run: `venv/bin/pytest -q`
Expected: PASS, 100 tests

- [ ] **Step 7: Commit**

```bash
git add scripts/ingest_medgen.py scripts/ingest_hpo_terms.py tests/scripts/test_ingest_medgen.py
git commit -m "feat: add per-panel MedGen and HPO term Bronze ingestion"
```

---

### Task 9: Stubs de transformation

**Files:**
- Create: `src/transformations/__init__.py`
- Create: `src/transformations/bronze_to_silver.py`
- Create: `src/transformations/silver_to_gold.py`
- Test: `tests/transformations/__init__.py`, `tests/transformations/test_stubs.py`

**Interfaces:**
- Consumes: rien.
- Produces: `transformations.bronze_to_silver.bronze_to_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None`, `transformations.silver_to_gold.silver_to_gold(logical_date: str, panel: str, lake_uri: str | None = None) -> None`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/transformations/__init__.py` (vide) puis `tests/transformations/test_stubs.py` :

```python
import pytest

from transformations.bronze_to_silver import bronze_to_silver
from transformations.silver_to_gold import silver_to_gold


def test_bronze_to_silver_fails_explicitly_while_the_engine_is_undecided():
    with pytest.raises(NotImplementedError, match="moteur de transformation"):
        bronze_to_silver("2026-09-01", "brca")


def test_silver_to_gold_fails_explicitly_while_the_engine_is_undecided():
    with pytest.raises(NotImplementedError, match="moteur de transformation"):
        silver_to_gold("2026-09-01", "brca")
```

Ajouter `pythonpath = src` couvre déjà `transformations` puisque le paquet vit sous `src/`.

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'transformations'`

- [ ] **Step 3: Implémenter les stubs**

`src/transformations/__init__.py` : fichier vide.

`src/transformations/bronze_to_silver.py` :

```python
from __future__ import annotations

MESSAGE = (
    "moteur de transformation non arbitré : voir la section 12 de "
    "docs/superpowers/specs/2026-09-04-pipeline-medaillon-airflow-minio-design.md"
)


def bronze_to_silver(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Normalise les partitions Bronze du panel en tables Silver.

    Contrat d'entrée — partitions Bronze complètes (marqueur `_SUCCESS` présent) :
      bronze/clinvar/dt=<date>/variant_summary.txt.gz        (bulk NON filtré)
      bronze/hpo/dt=<date>/genes_to_phenotype.txt
      bronze/ncbi_gene/dt=<date>/panel=<panel>/gene_summaries.jsonl.gz
      bronze/refseq/dt=<date>/panel=<panel>/transcripts.jsonl.gz
      bronze/medgen/dt=<date>/panel=<panel>/concepts.jsonl.gz
      bronze/hpo_terms/dt=<date>/panel=<panel>/hpo_terms.jsonl.gz

    Contrat de sortie — tables Silver, partitionnées par `panel` :
      silver/clinvar_variant, silver/clinvar_variant_gene,
      silver/ncbi_gene, silver/refseq_transcript,
      silver/medgen_concept, silver/medgen_mim, silver/medgen_inheritance,
      silver/hpo_gene_phenotype, silver/hpo_term

    Traitements attendus : filtrage sur le panel, éclatement des lignes ClinVar
    multi-gènes (`GeneSymbol` joint par `;`) en table de liaison, aplatissement du
    XML `conceptmeta`, éclatement de `PhenotypeIDS`, normalisation HGVS adossée au
    catalogue de transcrits, typage, déduplication, et historisation SCD2 de la
    signification clinique pour tracer les reclassifications de variants.

    Non implémenté : le moteur de calcul n'est pas encore choisi. Le format de
    table (Delta) est arrêté et compatible avec tous les candidats, donc cette
    décision reste ouverte sans bloquer le reste du pipeline.
    """
    raise NotImplementedError(MESSAGE)
```

`src/transformations/silver_to_gold.py` :

```python
from __future__ import annotations

from transformations.bronze_to_silver import MESSAGE


def silver_to_gold(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Joint les tables Silver en documents Gold consommables par le RAG.

    Contrat d'entrée : les tables Silver du panel produites par `bronze_to_silver`.

    Contrat de sortie :
      gold/variant_enriched  variant × gène × phénotype HPO × signification clinique
      gold/rag_document      texte en langue naturelle pré-rendu + charge de citation
      gold/rag_chunk         chunks dont l'identifiant est un hash déterministe du
                             contenu, pour ne ré-embedder que ce qui a changé d'un
                             run mensuel au suivant

    `gold/` est la seule couche que le RAG lit.

    Non implémenté : même raison que `bronze_to_silver`.
    """
    raise NotImplementedError(MESSAGE)
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `venv/bin/pytest tests/transformations -q`
Expected: PASS, 2 tests

- [ ] **Step 5: Commit**

```bash
git add src/transformations/ tests/transformations/
git commit -m "feat: add documented Silver and Gold transformation stubs"
```

---

### Task 10: Panels et DAG d'acquisition partagé

**Files:**
- Create: `dags/__init__.py`, `dags/common/__init__.py`, `dags/common/panels.py`
- Create: `dags/dag_acquisition_sources.py`
- Test: `tests/dags/__init__.py`, `tests/dags/test_panels.py`, `tests/dags/test_dag_acquisition.py`
- Modify: `requirements-dev.txt`

**Interfaces:**
- Consumes: `ingestion.config.BREAST_CANCER_GENES/SICKLE_CELL_GENES`, `scripts.ingest_clinvar.ingest_clinvar`, `scripts.ingest_hpo_files.ingest_hpo_files`.
- Produces: `dags.common.panels.PANELS: dict[str, list[str]]`, `dags.common.panels.SOURCES_READY: Asset`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter `apache-airflow==3.3.1` à `requirements-dev.txt`.

Créer `tests/dags/__init__.py` (vide) et `tests/dags/test_panels.py` :

```python
from ingestion.config import BREAST_CANCER_GENES, SICKLE_CELL_GENES
from dags.common.panels import PANELS


def test_panels_reuse_the_tested_gene_lists_without_duplicating_them():
    """La liste de gènes a une seule source de vérité, déjà couverte par
    test_config.py. La dupliquer dans un YAML la copierait sans la protéger."""
    assert PANELS["brca"] == BREAST_CANCER_GENES
    assert PANELS["sickle"] == SICKLE_CELL_GENES


def test_panels_cover_every_gene_of_the_project():
    covered = {gene for genes in PANELS.values() for gene in genes}
    assert covered == set(BREAST_CANCER_GENES) | set(SICKLE_CELL_GENES)
    assert len(covered) == 18
```

Créer `tests/dags/test_dag_acquisition.py` :

```python
from dags.dag_acquisition_sources import dag
from dags.common.panels import SOURCES_READY


def test_acquisition_dag_runs_monthly_without_catchup():
    assert dag.schedule == "@monthly"
    assert dag.catchup is False


def test_acquisition_dag_has_the_expected_tasks():
    assert sorted(t.task_id for t in dag.tasks) == [
        "check_bronze_shared",
        "download_clinvar_bulk",
        "download_hpo_files",
    ]


def test_both_downloads_run_in_parallel_then_gate_on_the_check():
    check = dag.get_task("check_bronze_shared")
    assert check.upstream_task_ids == {"download_clinvar_bulk", "download_hpo_files"}
    assert dag.get_task("download_clinvar_bulk").upstream_task_ids == set()
    assert dag.get_task("download_hpo_files").upstream_task_ids == set()


def test_the_check_publishes_the_asset_that_triggers_panel_dags():
    assert SOURCES_READY in dag.get_task("check_bronze_shared").outlets
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `venv/bin/pip install -r requirements-dev.txt && venv/bin/pytest tests/dags -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'dags'`

- [ ] **Step 3: Implémenter `dags/common/panels.py`**

Créer `dags/__init__.py` et `dags/common/__init__.py` vides, puis :

```python
from __future__ import annotations

from airflow.sdk import Asset

from ingestion.config import BREAST_CANCER_GENES, SICKLE_CELL_GENES

# Source unique de vérité : les listes de gènes vivent dans ingestion.config, où
# elles sont déjà sous test. Les recopier dans un fichier de configuration
# créerait une seconde vérité non protégée.
PANELS: dict[str, list[str]] = {
    "brca": BREAST_CANCER_GENES,
    "sickle": SICKLE_CELL_GENES,
}

PANEL_LABELS: dict[str, str] = {
    "brca": "Cancer du sein héréditaire",
    "sickle": "Drépanocytose et modificateurs HbF",
}

# Couplage par la donnée et non par l'horaire : les DAGs de panel se déclenchent
# quand les fichiers partagés sont réellement déposés.
SOURCES_READY = Asset("s3://bronze/_sources_pretes")
```

- [ ] **Step 4: Implémenter `dags/dag_acquisition_sources.py`**

```python
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT / "src"), str(REPO_ROOT)]

from airflow.sdk import DAG, task

from dags.common.panels import SOURCES_READY
from ingestion.storage import partition_is_complete, partition_uri
from ingestion.config import BRONZE
from scripts.ingest_clinvar import ingest_clinvar
from scripts.ingest_hpo_files import ingest_hpo_files

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": dt.timedelta(minutes=5),
    "execution_timeout": dt.timedelta(hours=2),
}

with DAG(
    dag_id="dag_acquisition_sources",
    description="Dépose en Bronze les sources communes à tous les panels",
    schedule="@monthly",
    start_date=dt.datetime(2026, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["bronze", "acquisition"],
) as dag:

    @task(task_id="download_clinvar_bulk")
    def download_clinvar_bulk(**context) -> str:
        return ingest_clinvar(context["ds"])

    @task(task_id="download_hpo_files")
    def download_hpo_files(**context) -> str:
        return ingest_hpo_files(context["ds"])

    @task(task_id="check_bronze_shared", outlets=[SOURCES_READY])
    def check_bronze_shared(clinvar_partition: str, hpo_partition: str, **context) -> None:
        """Bloque la propagation si une partition partagée est incomplète.

        Le verdict qualité vit ici, pas dans les scripts d'ingestion : une collecte
        partielle mais déterministe ne doit pas être relancée trois fois par le
        mécanisme de retry.
        """
        for partition in (clinvar_partition, hpo_partition):
            if not partition_is_complete(partition):
                raise ValueError(f"partition Bronze incomplète : {partition}")

        expected = partition_uri(BRONZE, "clinvar", context["ds"])
        if clinvar_partition != expected:
            raise ValueError(
                f"partition ClinVar inattendue : {clinvar_partition} au lieu de {expected}"
            )

    check_bronze_shared(download_clinvar_bulk(), download_hpo_files())
```

- [ ] **Step 5: Lancer les tests pour vérifier qu'ils passent**

Run: `venv/bin/pytest tests/dags -q`
Expected: PASS, 6 tests

- [ ] **Step 6: Vérifier la suite complète**

Run: `venv/bin/pytest -q`
Expected: PASS, 108 tests

- [ ] **Step 7: Commit**

```bash
git add dags/__init__.py dags/common/ dags/dag_acquisition_sources.py tests/dags/ requirements-dev.txt
git commit -m "feat: add shared acquisition DAG publishing a sources-ready Asset"
```

---

### Task 11: DAGs de panel

**Files:**
- Create: `dags/dag_genomic_pipeline.py`
- Test: `tests/dags/test_dag_genomic_pipeline.py`

**Interfaces:**
- Consumes: `dags.common.panels.PANELS/SOURCES_READY`, les cinq fonctions `ingest_*`, `transformations.bronze_to_silver/silver_to_gold`.
- Produces: `dags.dag_genomic_pipeline.client_or_fail() -> NcbiClient`, `dags.dag_genomic_pipeline.build_panel_dag(panel: str, genes: list[str]) -> DAG`, et les objets `dag_genomic_pipeline_brca` / `dag_genomic_pipeline_sickle` dans le module.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/dags/test_dag_genomic_pipeline.py` :

```python
import pytest

from dags.common.panels import SOURCES_READY
from dags.dag_genomic_pipeline import build_panel_dag

EXPECTED_TASKS = [
    "bronze_to_silver",
    "check_bronze",
    "ingest_hpo_terms",
    "ingest_medgen",
    "ingest_ncbi_gene",
    "ingest_refseq",
    "publish_gold",
    "quality_check_silver",
    "silver_to_gold",
]


@pytest.fixture
def dag():
    return build_panel_dag("brca", ["BRCA1", "BRCA2"])


def test_panel_dag_is_triggered_by_the_shared_sources_asset(dag):
    assert dag.schedule == [SOURCES_READY]
    assert dag.catchup is False


def test_panel_dag_has_the_expected_tasks(dag):
    assert sorted(t.task_id for t in dag.tasks) == EXPECTED_TASKS


def test_the_three_independent_ingestions_have_no_upstream(dag):
    for task_id in ("ingest_ncbi_gene", "ingest_refseq", "ingest_hpo_terms"):
        assert dag.get_task(task_id).upstream_task_ids == set()


def test_check_bronze_waits_for_all_four_ingestions(dag):
    assert dag.get_task("check_bronze").upstream_task_ids == {
        "ingest_ncbi_gene",
        "ingest_refseq",
        "ingest_hpo_terms",
        "ingest_medgen",
    }


def test_the_medallion_stages_are_strictly_sequential(dag):
    assert dag.get_task("bronze_to_silver").upstream_task_ids == {"check_bronze"}
    assert dag.get_task("quality_check_silver").upstream_task_ids == {"bronze_to_silver"}
    assert dag.get_task("silver_to_gold").upstream_task_ids == {"quality_check_silver"}
    assert dag.get_task("publish_gold").upstream_task_ids == {"silver_to_gold"}


def test_transient_failures_are_retried(dag):
    assert dag.get_task("ingest_ncbi_gene").retries == 3


def test_configuration_errors_fail_without_consuming_retries(monkeypatch):
    """Une erreur de configuration est permanente : la retenter trois fois coûte
    ~21 minutes d'appels d'API pour rien. AirflowFailException échoue la tâche
    immédiatement, sans passer par les retries."""
    from airflow.sdk.exceptions import AirflowFailException

    from dags import dag_genomic_pipeline
    from scripts.ingest_ncbi_gene import ConfigurationError

    def refuser():
        raise ConfigurationError("NCBI_EMAIL manquant")

    monkeypatch.setattr(dag_genomic_pipeline, "build_client", refuser)

    with pytest.raises(AirflowFailException, match="NCBI_EMAIL"):
        dag_genomic_pipeline.client_or_fail()


def test_both_panel_dags_are_exposed_at_module_level():
    from dags import dag_genomic_pipeline

    assert dag_genomic_pipeline.dag_genomic_pipeline_brca.dag_id == "dag_genomic_pipeline_brca"
    assert dag_genomic_pipeline.dag_genomic_pipeline_sickle.dag_id == "dag_genomic_pipeline_sickle"
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/dags/test_dag_genomic_pipeline.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'dags.dag_genomic_pipeline'`

- [ ] **Step 3: Implémenter `dags/dag_genomic_pipeline.py`**

```python
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT / "src"), str(REPO_ROOT)]

from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowFailException

from dags.common.panels import PANEL_LABELS, PANELS, SOURCES_READY
from ingestion.http_client import NcbiClient
from ingestion.storage import partition_is_complete
from scripts.ingest_hpo_terms import ingest_hpo_terms
from scripts.ingest_medgen import ingest_medgen
from scripts.ingest_ncbi_gene import ConfigurationError, build_client, ingest_ncbi_gene
from scripts.ingest_refseq import ingest_refseq
from transformations.bronze_to_silver import bronze_to_silver
from transformations.silver_to_gold import silver_to_gold

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": dt.timedelta(minutes=5),
    "execution_timeout": dt.timedelta(hours=3),
}


def client_or_fail() -> NcbiClient:
    """Construit le client NCBI, ou échoue définitivement.

    Une configuration manquante est une erreur permanente : la retenter trois fois
    ne peut pas la résoudre et coûterait ~21 minutes. `AirflowFailException` marque
    la tâche en échec sans consommer les retries, contrairement à une exception
    ordinaire.
    """
    try:
        return build_client()
    except ConfigurationError as exc:
        raise AirflowFailException(str(exc)) from exc


def build_panel_dag(panel: str, genes: list[str]) -> DAG:
    """Construit le DAG médaillon d'un panel de gènes.

    Déclenché par l'Asset publié par le DAG d'acquisition : le couplage est porté
    par la donnée, pas par un horaire à synchroniser à la main.
    """
    with DAG(
        dag_id=f"dag_genomic_pipeline_{panel}",
        description=f"Pipeline médaillon — {PANEL_LABELS.get(panel, panel)}",
        schedule=[SOURCES_READY],
        start_date=dt.datetime(2026, 1, 1),
        catchup=False,
        default_args=DEFAULT_ARGS,
        tags=["medaillon", panel],
    ) as dag:

        @task(task_id="ingest_ncbi_gene")
        def task_ncbi_gene(**context) -> str:
            return ingest_ncbi_gene(context["ds"], panel, genes, client_or_fail())

        @task(task_id="ingest_refseq")
        def task_refseq(**context) -> str:
            return ingest_refseq(context["ds"], panel, genes, client_or_fail())

        @task(task_id="ingest_hpo_terms")
        def task_hpo_terms(**context) -> str:
            return ingest_hpo_terms(context["ds"], panel, genes)

        @task(task_id="ingest_medgen")
        def task_medgen(**context) -> str:
            # Dépendance de données sur ClinVar : les CUI sont extraits de
            # PhenotypeIDS, déposé par le DAG d'acquisition.
            return ingest_medgen(context["ds"], panel, genes, client_or_fail())

        @task(task_id="check_bronze")
        def task_check_bronze(
            ncbi_gene_partition: str,
            refseq_partition: str,
            hpo_terms_partition: str,
            medgen_partition: str,
        ) -> None:
            """Bloque la propagation vers Silver si une partition est incomplète.

            Paramètres nommés plutôt que varargs : même forme que
            `check_bronze_shared` du DAG d'acquisition, et dépendances explicites.
            """
            for partition in (
                ncbi_gene_partition,
                refseq_partition,
                hpo_terms_partition,
                medgen_partition,
            ):
                if not partition_is_complete(partition):
                    raise ValueError(f"partition Bronze incomplète : {partition}")

        @task(task_id="bronze_to_silver")
        def task_bronze_to_silver(**context) -> None:
            bronze_to_silver(context["ds"], panel)

        @task(task_id="quality_check_silver")
        def task_quality_check_silver(**context) -> None:
            """Contrôles Silver — à écrire avec la transformation qu'ils valident."""
            raise NotImplementedError(
                "contrôles Silver à définir avec le moteur de transformation"
            )

        @task(task_id="silver_to_gold")
        def task_silver_to_gold(**context) -> None:
            silver_to_gold(context["ds"], panel)

        @task(task_id="publish_gold")
        def task_publish_gold(**context) -> None:
            """Publication de Gold — définie avec la couche qu'elle publie."""
            raise NotImplementedError(
                "publication Gold à définir avec le moteur de transformation"
            )

        checked = task_check_bronze(
            task_ncbi_gene(), task_refseq(), task_hpo_terms(), task_medgen()
        )
        silver = task_bronze_to_silver()
        quality = task_quality_check_silver()
        gold = task_silver_to_gold()
        published = task_publish_gold()

        checked >> silver >> quality >> gold >> published

    return dag


dag_genomic_pipeline_brca = build_panel_dag("brca", PANELS["brca"])
dag_genomic_pipeline_sickle = build_panel_dag("sickle", PANELS["sickle"])
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `venv/bin/pytest tests/dags/test_dag_genomic_pipeline.py -q`
Expected: PASS, 8 tests

- [ ] **Step 5: Vérifier la suite complète**

Run: `venv/bin/pytest -q`
Expected: PASS, 116 tests

- [ ] **Step 6: Commit**

```bash
git add dags/dag_genomic_pipeline.py tests/dags/test_dag_genomic_pipeline.py
git commit -m "feat: add per-panel medallion DAGs triggered by the sources Asset"
```

---

### Task 12: Infrastructure Docker

**Files:**
- Create: `docker-compose.yml`
- Create: `docker/airflow/Dockerfile`
- Create: `docker/minio/create-buckets.sh`
- Create: `.env.docker.example`
- Modify: `README.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `requirements.txt`, `dags/`, `src/`, `scripts/`.
- Produces: une stack lancée par `docker compose up -d`, buckets `bronze`/`silver`/`gold` créés, Airflow joignable sur `http://localhost:8080`.

- [ ] **Step 1: Écrire le Dockerfile Airflow**

`docker/airflow/Dockerfile` :

```dockerfile
FROM apache/airflow:3.3.1-python3.12

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Les dépendances d'ingestion sont installées dans un venv dédié : Airflow épingle
# ses propres versions (requests notamment) via un fichier de contraintes, et les
# mélanger casserait l'une ou l'autre.
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/ingestion-venv \
    && /opt/ingestion-venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# boto3 côté Airflow : les tâches écrivent dans MinIO depuis le processus worker.
RUN pip install --no-cache-dir boto3==1.41.5
```

- [ ] **Step 2: Écrire le script de création des buckets**

`docker/minio/create-buckets.sh` :

```bash
#!/bin/sh
set -e

# Une couche du médaillon = un bucket. Idempotent : relancer la stack ne casse rien.
mc alias set local "http://minio:9000" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
for bucket in bronze silver gold; do
  mc mb --ignore-existing "local/${bucket}"
  echo "bucket ${bucket} pret"
done
```

- [ ] **Step 3: Écrire le docker-compose**

`docker-compose.yml` :

```yaml
x-airflow-common: &airflow-common
  build:
    context: .
    dockerfile: docker/airflow/Dockerfile
  environment: &airflow-env
    AIRFLOW__CORE__EXECUTOR: LocalExecutor
    AIRFLOW__CORE__LOAD_EXAMPLES: "false"
    AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:${POSTGRES_PASSWORD}@postgres:5432/airflow
    AIRFLOW__CORE__DAGS_FOLDER: /opt/projet/dags
    PYTHONPATH: /opt/projet:/opt/projet/src
    LAKE_URI: "s3://"
    AWS_ENDPOINT_URL: "http://minio:9000"
    AWS_ACCESS_KEY_ID: ${MINIO_ROOT_USER}
    AWS_SECRET_ACCESS_KEY: ${MINIO_ROOT_PASSWORD}
    AWS_REGION: us-east-1
    NCBI_EMAIL: ${NCBI_EMAIL}
    NCBI_API_KEY: ${NCBI_API_KEY:-}
  volumes:
    - .:/opt/projet
  working_dir: /opt/projet
  depends_on:
    postgres:
      condition: service_healthy
    minio:
      condition: service_healthy

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: airflow
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: airflow
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U airflow"]
      interval: 10s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 1g

  minio:
    image: quay.io/minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio-data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 10s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 1g

  minio-init:
    image: quay.io/minio/mc
    depends_on:
      minio:
        condition: service_healthy
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    entrypoint: ["/bin/sh", "/scripts/create-buckets.sh"]
    volumes:
      - ./docker/minio/create-buckets.sh:/scripts/create-buckets.sh:ro

  airflow-init:
    <<: *airflow-common
    entrypoint: /bin/bash
    command:
      - -c
      - airflow db migrate && airflow users create --username admin --password "${AIRFLOW_ADMIN_PASSWORD}" --firstname admin --lastname admin --role Admin --email admin@example.com || true
    restart: "no"

  airflow-apiserver:
    <<: *airflow-common
    command: api-server
    ports:
      - "8080:8080"
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1536m

  airflow-scheduler:
    <<: *airflow-common
    command: scheduler
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2g

  airflow-dag-processor:
    <<: *airflow-common
    command: dag-processor
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1g

  airflow-triggerer:
    <<: *airflow-common
    command: triggerer
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 768m

volumes:
  postgres-data:
  minio-data:
```

- [ ] **Step 4: Écrire le modèle d'environnement**

`.env.docker.example` :

```
# Modèle. Copier en .env.docker et y saisir de vraies valeurs (fichier gitignoré).
POSTGRES_PASSWORD=
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=
AIRFLOW_ADMIN_PASSWORD=

# Obligatoire (politique NCBI E-utilities).
NCBI_EMAIL=
# Recommandée : 10 req/s au lieu de 3. Laisser VIDE si absente — une valeur
# factice ferait passer le limiteur en cadence rapide et provoquerait des erreurs.
NCBI_API_KEY=
```

Ajouter `.env.docker` à `.gitignore`, sous la ligne `.env`.

- [ ] **Step 5: Vérifier que la stack démarre**

```bash
cp .env.docker.example .env.docker   # puis renseigner les mots de passe
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps
```
Expected: `postgres`, `minio`, `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor`, `airflow-triggerer` en état `running` ; `minio-init` et `airflow-init` sortis en code 0.

- [ ] **Step 6: Vérifier les buckets et les DAGs**

```bash
docker compose --env-file .env.docker logs minio-init | grep "pret"
docker compose --env-file .env.docker exec airflow-scheduler airflow dags list
```
Expected: trois lignes `bucket <nom> pret`, et les trois DAGs `dag_acquisition_sources`, `dag_genomic_pipeline_brca`, `dag_genomic_pipeline_sickle` listés sans erreur d'import.

- [ ] **Step 7: Vérifier l'empreinte mémoire réelle**

```bash
docker stats --no-stream --format '{{.Name}}: {{.MemUsage}}'
```
Expected: total au repos inférieur à 7,25 Go — la marge prévue pour les tâches sur un VPS 12 Go.

- [ ] **Step 8: Documenter dans le README**

Ajouter une section « Lancer le pipeline médaillon » après la section « Tests », décrivant : la copie de `.env.docker.example`, `docker compose up -d --build`, l'accès à Airflow sur `http://localhost:8080` et à la console MinIO sur `http://localhost:9001`, et le fait que les tâches `bronze_to_silver`, `quality_check_silver`, `silver_to_gold` et `publish_gold` échouent volontairement tant que le moteur de transformation n'est pas arbitré.

- [ ] **Step 9: Retirer NiFi du chemin d'implémentation**

La spec (§2.1) retire NiFi de l'implémentation tout en le conservant dans le dépôt
comme alternative évaluée. Sans cette étape, `CLAUDE.md` continuerait d'affirmer que
NiFi orchestre l'étape 1, ce qui devient faux.

1. Dans `CLAUDE.md`, remplacer le titre de section `## Orchestration (NiFi) — scoped to
   stage 1 only` par `## Orchestration — Airflow (NiFi : alternative évaluée, écartée)`,
   et ouvrir la section par :

```markdown
**Statut : NiFi est retiré du chemin d'implémentation.** Le dossier `nifi/` est conservé
comme alternative implémentée, mesurée et écartée — matière pour l'annexe du mémoire, pas
composant actif. L'orchestration est assurée par Airflow (`dags/`), voir
`docs/superpowers/specs/2026-09-04-pipeline-medaillon-airflow-minio-design.md`.

Raison de l'arbitrage : les apports de NiFi ici (déclenchement planifié, routage
succès/échec, journalisation) sont un sous-ensemble strict de ceux d'Airflow, lequel est
requis de toute façon pour Bronze/Silver/Gold — pour un coût mesuré de 1,37 Gio de RAM au
repos avec un flow vide (image de 2,25 Go, démarrage en 61,6 s), sur un VPS qui doit aussi
loger Airflow, PostgreSQL et MinIO. Chiffres et protocole : `docs/choix_contexte.md`. Le profil des sources (deux fichiers
plats mensuels, appels REST séquentiels) ne présente ni flux, ni backpressure, ni routage.
```

2. Ajouter en tête de `nifi/README.md`, juste après le titre :

```markdown
> ⚠️ **Alternative écartée.** Ce dossier n'est plus le chemin d'orchestration du projet.
> Il est conservé pour documenter un choix évalué puis écarté avec mesures — voir
> `CLAUDE.md`. L'orchestration active vit dans `dags/`.
```

3. Ajouter une sous-section à `CLAUDE.md` décrivant la nouvelle arborescence
   (`dags/`, `src/transformations/`, `docker/`) et la règle non négociable : **la logique
   métier vit dans `src/`, testée sans infrastructure ; Airflow ne fait qu'appeler des
   fonctions ; MinIO ne fait que stocker.**

- [ ] **Step 10: Commit**

```bash
git add docker-compose.yml docker/ .env.docker.example .gitignore README.md CLAUDE.md nifi/README.md
git commit -m "feat: add Airflow 3 + MinIO docker compose stack with memory limits"
```

---

## Vérification finale

- [ ] **Suite de tests complète et rapide**

Run: `venv/bin/pytest -q`
Expected: PASS, 116 tests, en moins de 3 secondes, sans réseau ni conteneur

- [ ] **Aucune régression sur le chemin autonome**

Run: `venv/bin/python -c "import sys; sys.path.insert(0,'src'); from ingestion.orchestrate import build_gene_documents; print('ok')"`
Expected: `ok` — `run_collection.py` reste utilisable hors Airflow

- [ ] **Aucun moteur de transformation importé**

Run: `grep -rE "polars|pandas|pyspark|deltalake" src/transformations/ dags/ || echo "aucun moteur importe"`
Expected: `aucun moteur importe`
