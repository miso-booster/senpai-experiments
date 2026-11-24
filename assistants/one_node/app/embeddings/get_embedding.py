"""Utilities for computing text embeddings with a HuggingFace sentence-transformer."""

import numpy as np
from langchain_community.embeddings import HuggingFaceEmbeddings

emb = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


def get_embedding(text: str) -> np.ndarray:
    """Returns the embedding of a text as a numpy vector.

    Args:
        text (str): Input text to embed.

    Returns:
        np.ndarray: Embedding vector in float32 format.
    """
    vec = emb.embed_query(text)
    return np.array(vec, dtype="float32")
