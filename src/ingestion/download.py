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
    """Télécharge `url` vers `destination`, en réutilisant le fichier déjà présent.

    Les sources de ce projet sont des fichiers plats volumineux (440 Mo pour le bulk
    ClinVar), d'où deux garanties :

    - streaming par blocs, pour ne pas charger le fichier entier en mémoire ;
    - écriture dans un `.part` puis renommage atomique, pour qu'une coupure ne laisse
      jamais un fichier partiel que le skip-si-présent réutiliserait comme complet.

    La taille reçue est comparée au `Content-Length` annoncé quand il est présent :
    une réponse tronquée est rejetée au lieu d'être promue en fichier complet.

    `force=True` retélécharge ; en cas d'échec le fichier précédent reste intact.
    """
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
                # urllib3 détecte lui-même la troncature quand Content-Length est annoncé.
                # On conserve cette garantie de transport et on la présente sous le type
                # d'erreur du projet, plutôt que de désactiver urllib3 pour la refaire à
                # la main : l'attribut qui la désactive est un interne non épinglé, et une
                # assignation d'attribut ne lève jamais — un renommage la rendrait
                # silencieusement inopérante.
                raise IncompleteDownloadError(f"{url} : flux interrompu ({exc})") from exc
        # Seconde ligne de défense : couvre aussi une réponse plus longue qu'annoncée.
        if verify_size and expected is not None and written != int(expected):
            raise IncompleteDownloadError(
                f"{url} : {written} octets reçus pour {expected} annoncés"
            )
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return destination
