import pytest
import responses
from requests.exceptions import ConnectionError

from ingestion.download import download_to_file, IncompleteDownloadError

URL = "https://example.org/big-file.txt"


@responses.activate
def test_download_to_file_streams_content_to_destination(tmp_path):
    responses.add(responses.GET, URL, body=b"contenu complet", status=200)

    destination = tmp_path / "external" / "big-file.txt"
    result = download_to_file(URL, destination)

    assert result == destination
    assert destination.read_bytes() == b"contenu complet"


@responses.activate
def test_download_to_file_reuses_existing_file(tmp_path):
    destination = tmp_path / "external" / "big-file.txt"
    destination.parent.mkdir(parents=True)
    destination.write_bytes("déjà téléchargé".encode())

    result = download_to_file(URL, destination)

    assert result == destination
    assert destination.read_bytes() == "déjà téléchargé".encode()
    assert len(responses.calls) == 0


@responses.activate
def test_download_to_file_force_redownloads(tmp_path):
    responses.add(responses.GET, URL, body=b"frais", status=200)
    destination = tmp_path / "external" / "big-file.txt"
    destination.parent.mkdir(parents=True)
    destination.write_bytes("périmé".encode())

    download_to_file(URL, destination, force=True)

    assert destination.read_bytes() == b"frais"


@responses.activate
def test_download_to_file_leaves_nothing_behind_when_interrupted(tmp_path):
    """Une coupure ne doit pas laisser de fichier partiel : le skip-si-présent le
    réutiliserait ensuite comme s'il était complet."""
    responses.add(responses.GET, URL, body=ConnectionError("coupure réseau"))

    destination = tmp_path / "external" / "big-file.txt"

    with pytest.raises(ConnectionError):
        download_to_file(URL, destination)

    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


@responses.activate
def test_download_to_file_keeps_previous_file_when_refresh_fails(tmp_path):
    responses.add(responses.GET, URL, body=ConnectionError("coupure réseau"))
    destination = tmp_path / "external" / "big-file.txt"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"ancienne version valide")

    with pytest.raises(ConnectionError):
        download_to_file(URL, destination, force=True)

    assert destination.read_bytes() == b"ancienne version valide"


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
