"""Refus et ordre des étapes de scripts/restaurer.sh, avec un faux `docker` qui note ses appels."""
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "restaurer.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash absent")


@pytest.fixture
def depot(tmp_path):
    """Racine de dépôt factice : `.env` édité sous Windows (CRLF), faux `docker` sur le PATH."""
    racine = tmp_path / "depot"
    racine.mkdir()
    (racine / "docker-compose.yml").write_text("services: {}\n")
    (racine / ".env").write_bytes(b"MINIO_ROOT_USER=racine\r\nMINIO_ROOT_PASSWORD=secret\r\n")
    faux = tmp_path / "bin"
    faux.mkdir()
    journal = tmp_path / "appels.log"
    (faux / "docker").write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{journal}"\ncat > /dev/null\n')
    (faux / "docker").chmod(0o755)
    return racine, faux, journal


def _copie(tmp_path, *, sans=()):
    copie = tmp_path / "copie"
    for bucket in ("raw", "bronze", "silver", "gold"):
        if bucket not in sans:
            (copie / bucket).mkdir(parents=True)
    for dump in ("airflow.dump", "rag.dump"):
        if dump not in sans:
            (copie / dump).write_bytes(b"PGDMP")
    return copie


def _lancer(depot, *args):
    racine, faux, _ = depot
    return subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=racine, capture_output=True, text=True,
        env={"PATH": f"{faux}:/usr/bin:/bin", "HOME": str(racine)}, stdin=subprocess.DEVNULL, check=False,
    )


def _appels(depot):
    journal = depot[2]
    return journal.read_text().splitlines() if journal.exists() else []


@pytest.mark.parametrize("args", [(), ("--pile", "genomique-e3b"), ("--inconnue", "x")])
def test_incomplete_arguments_are_refused_without_calling_docker(depot, args):
    resultat = _lancer(depot, *args)

    assert resultat.returncode == 2
    assert "usage" in resultat.stderr
    assert _appels(depot) == []


def test_the_main_stack_is_refused_without_its_explicit_option(depot, tmp_path):
    """La pile principale porte le seul lac : l'écraser doit se demander en toutes lettres."""
    resultat = _lancer(depot, "--pile", "genomique", str(_copie(tmp_path)))

    assert resultat.returncode == 2
    assert "--pile-principale" in resultat.stderr
    assert _appels(depot) == []


def test_an_unknown_stack_is_refused(depot, tmp_path):
    resultat = _lancer(depot, "--pile", "genomique-test", str(_copie(tmp_path)))

    assert resultat.returncode == 2
    assert _appels(depot) == []


@pytest.mark.parametrize("manquant", ["airflow.dump", "rag.dump", "silver"])
def test_an_incomplete_backup_is_refused_before_any_change(depot, tmp_path, manquant):
    resultat = _lancer(depot, "--pile", "genomique-e3b", str(_copie(tmp_path, sans=(manquant,))))

    assert resultat.returncode == 1
    assert manquant in resultat.stderr
    assert _appels(depot) == []


def test_the_isolated_stack_is_restored_in_the_documented_order(depot, tmp_path):
    resultat = _lancer(depot, "--pile", "genomique-e3b", str(_copie(tmp_path)))

    assert resultat.returncode == 0, resultat.stderr
    appels = _appels(depot)
    etapes = [
        "stop airflow-scheduler",
        "exec -i genomique-e3b-postgres pg_restore",
        "run --rm minio-init",
        "--network genomique-e3b_genomique-network",
        "run --rm rag-postgres-init",
        "exec -i genomique-e3b-rag-postgres pg_restore",
        "up -d --wait postgres minio-server minio airflow-apiserver",
    ]
    positions = [next(i for i, a in enumerate(appels) if e in a) for e in etapes]
    assert positions == sorted(positions), appels
    compose = [a for a in appels if a.startswith("compose")]
    assert all("-p genomique-e3b -f docker-compose.yml -f docker/e3b/docker-compose.e3b.yml" in a for a in compose)
    # Le dernier `up` ne relance pas l'API RAG, absente de la pile isolée.
    assert "rag-api" not in appels[-1]


def test_minio_credentials_lose_the_windows_carriage_return(depot, tmp_path):
    _lancer(depot, "--pile", "genomique-e3b", str(_copie(tmp_path)))

    miroir = next(a for a in _appels(depot) if "MC_HOST_lac" in a)
    assert "MC_HOST_lac=http://racine:secret@minio:9000" in miroir
    assert "\r" not in miroir


def test_the_main_stack_is_restored_with_its_explicit_option(depot, tmp_path):
    resultat = _lancer(depot, "--pile", "genomique", "--pile-principale", str(_copie(tmp_path)))

    assert resultat.returncode == 0, resultat.stderr
    appels = _appels(depot)
    assert any("exec -i genomique-postgres pg_restore" in a for a in appels)
    assert not any("e3b" in a for a in appels)
