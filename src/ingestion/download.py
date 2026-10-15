"""Téléchargement en flux de gros fichiers plats, avec renommage atomique."""
from __future__ import annotations

from pathlib import Path

import requests
from requests.exceptions import ChunkedEncodingError

CHUNK_SIZE = 8192


class IncompleteDownloadError(RuntimeError):
    """Le nombre d'octets reçus ne correspond pas au `Content-Length` annoncé."""


def download_to_file(
    url: str, destination: Path, force: bool = False, verify_size: bool = True
) -> Path:
    """Télécharge `url` via un `.part` renommé à la fin ; réutilise `destination` sauf si `force`."""
    if destination.exists() and not force:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    try:
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            expected = response.headers.get("Content-Length")
            written = 0
            try:
                with open(partial, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        fh.write(chunk)
                        written += len(chunk)
            except ChunkedEncodingError as exc:
                # Troncature détectée par urllib3, renvoyée sous le type d'erreur du projet.
                raise IncompleteDownloadError(f"{url} : flux interrompu ({exc})") from exc
        # Couvre aussi une réponse plus longue qu'annoncée.
        if verify_size and expected is not None and written != int(expected):
            raise IncompleteDownloadError(
                f"{url} : {written} octets reçus pour {expected} annoncés"
            )
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return destination
