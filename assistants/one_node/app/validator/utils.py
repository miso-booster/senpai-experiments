"""Shared helper functions for validator modules."""

from __future__ import annotations

from typing import Any

import yaml


def load_yaml_mapping(
    yaml_text: str,
    *,
    empty_message: str,
    invalid_message_prefix: str,
    not_mapping_message: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse YAML text ensuring a mapping structure; return (data, errors)."""
    errors: list[str] = []
    if not yaml_text.strip():
        errors.append(empty_message)
        return None, errors

    try:
        loaded = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        errors.append(f"{invalid_message_prefix}: {exc}.")
        return None, errors

    if not isinstance(loaded, dict):
        errors.append(not_mapping_message)
        return None, errors

    return loaded, errors


def check_required_keys(
    node: dict[str, Any],
    required: set[str],
    allowed: set[str],
) -> tuple[list[str], list[str]]:
    """Return sorted missing and unexpected keys for a mapping."""
    present = set(node)
    missing = sorted(required - present)
    unexpected = sorted(present - allowed)
    return missing, unexpected


__all__ = ["load_yaml_mapping", "check_required_keys"]
