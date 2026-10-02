"""Client HTTP du service d'embedding (Text Embeddings Inference).

Comportements vérifiés le 02/10/2026 sur l'image cpu-1.9 :
- sans `Authorization: Bearer <clé>`, toute requête hors `/health` reçoit 401 ;
- un texte de plus de `max_input_length` tokens, envoyé avec `truncate: false`,
  reçoit 422 au lieu d'être tronqué en silence (`auto_truncate` vaut true par défaut) ;
- plus de 32 textes dans une requête reçoivent 422.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import batched

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from RAG.src.utils.config import MAX_CLIENT_BATCH_SIZE
from RAG.src.utils.errors import EmbeddingRequestError, EmbeddingServiceError

EMBEDDING_DIM = 768
_TRANSIENT_STATUSES = (429, 500, 502, 503, 504)


def build_session() -> requests.Session:
    """Session qui relance, avec un délai croissant, les erreurs transitoires.

    `POST` est inclus, contrairement à `ingestion.http_client` : vectoriser un texte
    n'a aucun effet de bord, le rejouer est sans risque. Une indexation de plusieurs
    heures ne doit pas échouer sur un 503 isolé."""
    retry = Retry(
        total=5,
        backoff_factor=2.0,
        status_forcelist=_TRANSIENT_STATUSES,
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class EmbeddingClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = 60.0,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise EmbeddingRequestError("clé d'API du service d'embedding vide (RAG_EMBEDDINGS_API_KEY)")
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout_s
        self._session = session or build_session()

    def _request(self, method: str, path: str, payload: dict | None = None):
        try:
            response = self._session.request(
                method,
                f"{self._base_url}{path}",
                json=payload,
                headers=self._headers,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            # Le message ne reprend ni les en-têtes ni la clé.
            raise EmbeddingServiceError(
                f"service d'embedding injoignable ({path}) : {type(exc).__name__}"
            ) from exc
        status = response.status_code
        if status in _TRANSIENT_STATUSES:
            raise EmbeddingServiceError(f"service d'embedding indisponible ({status}) sur {path}")
        if status in (401, 403):
            raise EmbeddingRequestError(
                f"service d'embedding : accès refusé ({status}), vérifier RAG_EMBEDDINGS_API_KEY"
            )
        if status >= 400:
            raise EmbeddingRequestError(
                f"service d'embedding : requête refusée ({status}) sur {path} : {response.text[:300]}"
            )
        return response.json()

    def max_input_length(self) -> int:
        """Fenêtre du modèle servi, en tokens (spéciaux compris)."""
        return int(self._request("GET", "/info")["max_input_length"])

    def token_counts(self, texts: Sequence[str]) -> list[int]:
        """Nombre de tokens de chaque texte, comptés par le tokenizer du modèle servi."""
        counts: list[int] = []
        for batch in batched(texts, MAX_CLIENT_BATCH_SIZE):
            tokens = self._request("POST", "/tokenize", {"inputs": list(batch), "add_special_tokens": True})
            counts.extend(len(item) for item in tokens)
        return counts

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Vecteurs normalisés de `texts`, un lot d'au plus 32 textes."""
        if not 0 < len(texts) <= MAX_CLIENT_BATCH_SIZE:
            raise ValueError(f"un lot doit compter entre 1 et {MAX_CLIENT_BATCH_SIZE} textes, reçu {len(texts)}")
        data = self._request("POST", "/embed", {"inputs": list(texts), "truncate": False, "normalize": True})
        vectors = np.asarray(data, dtype=np.float32)
        if vectors.shape != (len(texts), EMBEDDING_DIM):
            raise EmbeddingServiceError(
                f"forme inattendue {vectors.shape}, attendu ({len(texts)}, {EMBEDDING_DIM})"
            )
        return vectors
