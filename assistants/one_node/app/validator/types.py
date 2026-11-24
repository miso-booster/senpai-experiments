"""Shared validation result structures for validator modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ValidationResult:
    """Structured outcome for validator operations."""

    is_valid: bool
    errors: list[str]
    warnings: list[str]
    data: dict[str, Any] | None = None


__all__ = ["ValidationResult"]
