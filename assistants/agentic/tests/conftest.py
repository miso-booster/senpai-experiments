# mypy: ignore-errors

"""Test-wide fixtures and patches."""

from __future__ import annotations

from typing import Any, cast

import langchain_community.embeddings as _lc_emb
import numpy as np
from langchain_community.embeddings import HuggingFaceEmbeddings

import app.embeddings.get_embedding as _ge


class _DummyHuggingFaceEmbeddings(HuggingFaceEmbeddings):
    """Lightweight stand-in to avoid downloading real models during tests."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def embed_query(self, text: str) -> list[float]:
        seed = abs(hash(text)) % 1000
        return [float(seed + i) for i in range(8)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


# Patch
_lc_emb.HuggingFaceEmbeddings = cast(Any, _DummyHuggingFaceEmbeddings)
_ge.emb = _DummyHuggingFaceEmbeddings()


def _fake_get_embedding(text: str) -> np.ndarray:
    emb = cast(Any, _ge.emb)
    return np.array(emb.embed_query(text), dtype="float32")


def _fake_get_embeddings_batch(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.empty((0, 0), dtype="float32")
    emb = cast(Any, _ge.emb)
    vectors = emb.embed_documents(texts)
    return np.array(vectors, dtype="float32")


_ge.get_embedding = _fake_get_embedding
_ge.get_embeddings_batch = _fake_get_embeddings_batch
