"""Shared hashing helpers for embedding utilities."""

import hashlib


def hash_text(text: str) -> str:
    """Return a stable hash for the provided text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
