"""Utilities for computing text embeddings with a HuggingFace sentence-transformer."""

import logging
import threading

import numpy as np
from langchain_huggingface import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-m3"
emb: HuggingFaceEmbeddings | None = None
_emb_lock = threading.Lock()


def _ensure_embeddings_model() -> HuggingFaceEmbeddings:
    """Lazily initialize and return the HuggingFace embeddings model."""
    global emb
    if emb is None:
        with _emb_lock:
            if emb is None:
                emb = HuggingFaceEmbeddings(
                    model_name=MODEL_NAME,
                )
    return emb


def get_embedding(text: str) -> np.ndarray:
    """Returns the embedding of a text as a numpy vector.

    Args:
        text (str): Input text to embed.

    Returns:
        np.ndarray: Embedding vector in float32 format.
    """
    model = _ensure_embeddings_model()
    vec = model.embed_query(text)
    return np.array(vec, dtype="float32")


def get_embeddings_batch(texts: list[str]) -> np.ndarray:
    """Returns embeddings for multiple texts as a numpy matrix.

    This is more efficient than calling get_embedding() in a loop
    because it uses batch processing under the hood.

    Args:
        texts: List of input texts to embed.

    Returns:
        np.ndarray: Embedding matrix of shape (len(texts), embedding_dim) in float32 format.
            Returns an empty 2D array with shape (0, 0) when texts is empty.
    """
    if not texts:
        return np.empty((0, 0), dtype="float32")
    model = _ensure_embeddings_model()
    vectors = model.embed_documents(texts)
    return np.array(vectors, dtype="float32")
