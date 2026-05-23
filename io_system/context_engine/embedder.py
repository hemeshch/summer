"""Pluggable embedder.

Default backend: sentence-transformers (`all-MiniLM-L6-v2`, 384-dim). Local,
zero new API keys, ~80MB download on first use. Swap to a different backend
by setting SUMMER_EMBEDDER=openai (requires OPENAI_API_KEY) — anything else
falls back to sentence-transformers.

All embedders return Python lists of floats so downstream code never depends
on whether numpy or torch is installed.
"""

from __future__ import annotations

import os
from typing import List, Protocol


class Embedder(Protocol):
    dim: int

    def embed(self, texts: List[str]) -> List[List[float]]:
        ...


class SentenceTransformersEmbedder:
    """Local embeddings via sentence-transformers.

    The model is loaded lazily on the first embed() call so import cost is
    free for callers that only construct the FactStore but never search.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self.dim = 384  # all-MiniLM-L6-v2 dimensionality

    def _ensure_loaded(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import
            self._model = SentenceTransformer(self.model_name)
            self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]


class OpenAIEmbedder:
    """OpenAI embeddings via text-embedding-3-small (1536-dim, $0.02/1M tokens)."""

    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        self.dim = 1536
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from openai import OpenAI  # type: ignore
            self._client = OpenAI()  # honors OPENAI_API_KEY

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        self._ensure_client()
        resp = self._client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]


def build_default_embedder() -> Embedder:
    """Resolve the embedder backend from SUMMER_EMBEDDER env var."""
    backend = os.environ.get("SUMMER_EMBEDDER", "sentence-transformers").lower()
    if backend in {"openai", "oai"}:
        return OpenAIEmbedder()
    return SentenceTransformersEmbedder()
