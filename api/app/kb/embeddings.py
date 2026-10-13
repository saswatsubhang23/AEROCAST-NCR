"""Embedding providers. The knowledge base only depends on the `Embedder` protocol, so another provider can be added
without touching ingestion or retrieval. Ollama is the one implemented so far."""

import math
from typing import Protocol

import httpx

from app.core.config import Settings


class EmbeddingError(Exception):
    code = "embedding_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class EmbeddingUnavailable(EmbeddingError):
    code = "embedding_unavailable"


class EmbeddingModelMissing(EmbeddingError):
    code = "embedding_model_missing"


class EmbeddingBadResponse(EmbeddingError):
    code = "embedding_bad_response"


class Embedder(Protocol):
    model: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def check(self) -> None:
        """Raise an EmbeddingError if embeddings cannot be produced right now."""


def _missing(model: str) -> EmbeddingModelMissing:
    return EmbeddingModelMissing(f"The embedding model '{model}' is not installed on the Ollama host. Run: ollama pull {model}")


class OllamaEmbedder:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.model = settings.ollama_embed_model
        self._base = settings.ollama_base_url.rstrip("/")
        self._batch = max(1, settings.kb_embed_batch)
        self._doc_prefix, self._query_prefix = settings.embedding_doc_prefix, settings.embedding_query_prefix
        self._timeout = settings.embedding_timeout_s
        self._status_timeout = settings.ollama_timeout_s
        self._transport = transport

    async def _post(self, inputs: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as c:
                r = await c.post(f"{self._base}/api/embed", json={"model": self.model, "input": inputs})
        except httpx.ReadTimeout:
            raise EmbeddingUnavailable("The embedding model took too long to respond.") from None
        except httpx.HTTPError:
            raise EmbeddingUnavailable("The embedding service (Ollama) is not reachable.") from None
        if r.status_code == 404:
            raise _missing(self.model)
        if r.status_code >= 400:
            try:
                text = str(r.json().get("error", ""))[:200]
            except ValueError:
                text = ""
            if "not found" in text.lower():
                raise _missing(self.model)
            raise EmbeddingBadResponse(f"The embedding service reported an error: {text or f'HTTP {r.status_code}'}")
        try:
            vectors = r.json()["embeddings"]
        except (ValueError, KeyError, TypeError):
            raise EmbeddingBadResponse("The embedding service returned an unreadable response.") from None
        ok = (
            isinstance(vectors, list) and len(vectors) == len(inputs)
            and all(isinstance(v, list) and v and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v) for v in vectors)
            and len({len(v) for v in vectors}) == 1
        )
        if not ok:
            raise EmbeddingBadResponse("The embedding service returned malformed vectors.")
        return [[float(x) for x in v] for v in vectors]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            out += await self._post([self._doc_prefix + t for t in texts[i:i + self._batch]])
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self._post([self._query_prefix + text]))[0]

    async def check(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._status_timeout, transport=self._transport) as c:
                r = await c.get(f"{self._base}/api/tags")
            r.raise_for_status()
            names = [m["name"] for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError, KeyError):
            raise EmbeddingUnavailable("The embedding service (Ollama) is not reachable.") from None
        if not any(n == self.model or (":" not in self.model and n == f"{self.model}:latest") for n in names):
            raise _missing(self.model)


def make_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "ollama":
        return OllamaEmbedder(settings)
    raise ValueError(f"Unknown embedding provider '{settings.embedding_provider}'")
