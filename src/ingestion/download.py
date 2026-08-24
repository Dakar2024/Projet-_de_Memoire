from __future__ import annotations

from pathlib import Path

import requests

CHUNK_SIZE = 8192


def download_to_file(url: str, destination: Path, force: bool = False) -> Path:
    """Télécharge `url` vers `destination`, en réutilisant le fichier déjà présent.

    Les sources de ce projet sont des fichiers plats volumineux (440 Mo pour le bulk
    ClinVar), d'où deux garanties :

    - streaming par blocs, pour ne pas charger le fichier entier en mémoire ;
    - écriture dans un `.part` puis renommage atomique, pour qu'une coupure ne laisse
      jamais un fichier partiel que le skip-si-présent réutiliserait comme complet.

    `force=True` retélécharge ; en cas d'échec le fichier précédent reste intact.
    """
    if destination.exists() and not force:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    try:
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with open(partial, "wb") as fh:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    fh.write(chunk)
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return destination
