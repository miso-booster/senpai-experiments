"""Utilities for validating Sensei-check rule snippets."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.types import StrictStr

from app.validator.types import ValidationResult
from app.validator.utils import check_required_keys, load_yaml_mapping

RuleValidationResult = ValidationResult


class RuleModel(BaseModel):
    """Pydantic v2 model reflecting the rule.

    - extra='allow' to be able to report unknown keys as *warnings* (not errors).
    - StrictStr to avoid coercions (e.g. 123 -> "123").
    """

    model_config = ConfigDict(extra="allow")

    # Private flags so mypy knows these attributes exist
    _has_oracle: bool = PrivateAttr(False)
    _has_if: bool = PrivateAttr(False)
    _has_then: bool = PrivateAttr(False)

    # Mandatory values
    name: StrictStr
    description: StrictStr
    conversations: int | Literal["all"]

    # Optional values
    active: bool | None = None
    when: StrictStr | None = None
    oracle: StrictStr | None = None
    if_: StrictStr | None = Field(None, alias="if")
    then: StrictStr | None = None
    on_error: StrictStr | None = Field(None, alias="on-error")
    yields: StrictStr | None = None

    @field_validator("when", mode="before")
    @classmethod
    def _validate_when(cls, v: object, info: ValidationInfo) -> str | None:
        if isinstance(v, str):
            return v
        raise ValueError(f"Field '{info.field_name}' must be a string when provided.")

    # Non-empty validation for name/description
    @field_validator("name", "description")
    @classmethod
    def _non_empty(cls, v: str, info: ValidationInfo) -> str:
        if not v.strip():
            raise ValueError(f"field '{info.field_name}' must be a non-empty string.")
        return v

    # conversations: >= 1 when is int; or 'all'
    @field_validator("conversations", mode="before")
    @classmethod
    def _validate_conversations(cls, v: object, info: ValidationInfo) -> int | Literal["all"]:
        if isinstance(v, str):
            if v.lower() == "all":
                return "all"
            raise ValueError(f"Field '{info.field_name}' must be an integer or 'all'.")
        if isinstance(v, int):
            if v < 1:
                raise ValueError(f"Field '{info.field_name}' must be >= 1 when numeric.")
            return v
        raise ValueError(f"Field '{info.field_name}' must be an integer or 'all'.")

    # Consistency rules among oracle / if / then.
    @model_validator(mode="after")
    def _oracle_if_then(self) -> "RuleModel":
        has_oracle = isinstance(self.oracle, str) and bool(self.oracle.strip())
        has_if = isinstance(self.if_, str) and bool(self.if_.strip())
        has_then = isinstance(self.then, str) and bool((self.then or "").strip())

        self._has_oracle = has_oracle
        self._has_if = has_if
        self._has_then = has_then
        return self


def validate_rule(rule_text: str) -> RuleValidationResult:
    """Validate a single Sensei-check rule represented as YAML text, using Pydantic."""
    warnings: list[str] = []

    loaded, load_errors = load_yaml_mapping(
        rule_text,
        empty_message="Rule text is empty.",
        invalid_message_prefix="Rule is not valid YAML",
        not_mapping_message="Rule must parse into a mapping.",
    )
    if load_errors or loaded is None:
        return RuleValidationResult(False, load_errors, warnings)

    errors: list[str] = []

    # 2) Warnings
    required_keys = {"name", "description", "conversations"}
    allowed_keys = {
        "name",
        "description",
        "active",
        "conversations",
        "when",
        "oracle",
        "if",
        "then",
        "on-error",
        "yields",
    }

    missing, unknown = check_required_keys(loaded, required_keys, allowed_keys)
    if missing:
        errors.append(f"Missing required fields: {', '.join(missing)}.")

    if unknown:
        warnings.append(f"Unexpected fields present: {', '.join(unknown)}.")

    # 3) Type/values validation
    model: RuleModel | None = None
    if not errors:
        try:
            model = RuleModel.model_validate(loaded)
        except ValidationError as ve:
            # Translate to original or equivalent messages
            for err in ve.errors():
                # loc = err.get("loc", [])
                msg = err.get("msg", "")
                errors.append(msg)

    # 4) Business rules for oracle/if/then, plus warning if both styles are present
    if model and not errors:
        if model._has_if and model._has_then and model._has_oracle:
            warnings.append("Rule defines both 'oracle' and 'if'; prefer one style.")
        elif model._has_if and not model._has_then:
            errors.append("Rule includes 'if' but missing 'then'.")
        elif model._has_then and not model._has_if:
            errors.append("Rule includes 'then' but missing 'if'.")
        elif not model._has_oracle and not (model._has_if and model._has_then):
            errors.append("Rule must define either 'oracle' or an 'if'/'then' pair.")

    is_valid = not errors
    # Normalizamos 'conversations' == 'all' (igual que tu lógica original)
    normalized = dict(loaded)
    if is_valid and model is not None and isinstance(model.conversations, str):
        normalized["conversations"] = "all"

    return RuleValidationResult(is_valid, errors, warnings, data=normalized if is_valid else None)


__all__ = ["RuleValidationResult", "validate_rule"]
