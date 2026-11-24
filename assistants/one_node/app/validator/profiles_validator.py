"""Utilities for validating Sensei profile YAMLs (Sensei-chat).

- Parallel structure to the rules validator (pydantic v2, extra='allow', StrictStr, result dataclass).
- Validates required keys, types, and business rules described in the profiles guide.
- Reports *warnings* for unknown keys in each section (maintaining extra='allow').
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.types import StrictStr

from app.validator.types import ValidationResult
from app.validator.utils import check_required_keys, load_yaml_mapping

# ──────────────────────────────────────────────────────────────────────────────
# Structured result
# ──────────────────────────────────────────────────────────────────────────────


ProfileValidationResult = ValidationResult


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_PLACEHOLDER_RE = re.compile(r"{{\s*([A-Za-z_]\w*)\s*}}")

_COMBINATIONS_RE = re.compile(
    r"""^combinations(?:\(
         \s*(?:
             (?:(?:0(?:\.\d+)?|1(?:\.0+)?|\d+))    # percentage/fraction/int
             (?:\s*,\s*(forward|pairwise))?        # optional function
           |
             (forward|pairwise)                    # also allows only function
         )?
         \s*
    \))?$""",
    re.IGNORECASE | re.VERBOSE,
)

_LIST_TYPE_RE = re.compile(r"^list\[\s*([A-Za-z_]\w*)\s*\]$")
_TIME_TYPE_RE = re.compile(r'^time\(".*"\)$')
_DATE_TYPE_RE = re.compile(r'^date\(".*"\)$')

_FUNC_RE = re.compile(
    r"""^(?P<name>default|random|another|forward|pairwise)
         \(
           (?P<args>[^)]*)?
         \)$""",
    re.VERBOSE,
)


_INTERACTION_STYLES = {
    "long phrases",
    "change your mind",
    "change language",
    "make spelling mistakes",
    "single questions",
    "all questions",
    "default",
}


def _extract_placeholders(text: str) -> set[str]:
    return set(m.group(1) for m in _PLACEHOLDER_RE.finditer(text))


def _validate_function_syntax(func: str) -> tuple[bool, str, list[str] | None, str | None]:
    """Return (ok, name, args_list_or_none, error_msg_or_none).

    Accepts:
      - default()
      - random(), random(n), random(rand)
      - another(), another(n)
      - forward(), forward(dep_var)
      - pairwise()
    """
    m = _FUNC_RE.match(func.strip())
    if not m:
        return False, "", None, "Unsupported function."

    name = m.group("name")
    args = (m.group("args") or "").strip()

    # Normalize empty args
    if args == "":
        if name in {"default", "random", "another", "forward", "pairwise"}:
            return True, name, [], None

    # Specific validations
    if name == "random":
        # random(n) with n int > 0 OR random(rand)
        if args.lower() == "rand":
            return True, name, ["rand"], None
        if args.isdigit():
            if int(args) > 0:
                return True, name, [args], None
            return False, name, None, "random(n) requires n > 0."
        return False, name, None, "random() accepts no args, (n), or (rand)."

    if name == "another":
        if args.isdigit():
            if int(args) > 0:
                return True, name, [args], None
            return False, name, None, "another(n) requires n > 0."
        # Allow empty handled above → here it's non-empty but not digit
        return False, name, None, "another() accepts no args or (n)."

    if name == "forward":
        # forward() or forward(dep_var)
        if re.fullmatch(r"[A-Za-z_]\w*", args):
            return True, name, [args], None
        if args == "":
            return True, name, [], None
        return False, name, None, "forward() optionally takes a single dependency variable."

    if name == "pairwise":
        # only zero args allowed per guide
        return False, name, None, "pairwise() takes no arguments."

    if name == "default":
        return False, name, None, "default() takes no arguments."

    return False, name, None, "Unsupported function."


def _is_valid_output_type(type_str: str) -> bool:
    t = type_str.strip()
    if t in {"string", "int", "float"}:
        return True
    if _LIST_TYPE_RE.match(t):
        return True
    if _TIME_TYPE_RE.match(t) or _DATE_TYPE_RE.match(t):
        return True
    # Custom types: allow any identifier
    if re.fullmatch(r"[A-Za-z_]\w*", t):
        return True
    return False


def _validate_number_expr(v: object) -> bool:
    if isinstance(v, int):
        return v >= 1
    if isinstance(v, str):
        return _COMBINATIONS_RE.match(v.strip()) is not None
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic models (structure + basic types)
# ──────────────────────────────────────────────────────────────────────────────


class LLMFormatModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["text", "speech"]
    config: StrictStr | None = None


class LLMModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    temperature: float | None = None
    model: StrictStr | None = None
    model_prov: StrictStr | None = Field(None, alias="model_prov")
    format: LLMFormatModel | None = None


class ChatbotModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    is_starter: bool | None = None
    fallback: StrictStr | None = None
    output: list[dict[str, Any]] | None = None

    @field_validator("fallback")
    @classmethod
    def _non_empty_fallback(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.strip():
            raise ValueError("field 'fallback' must be a non-empty string if provided.")
        return v


class AllAnsweredModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    export: bool | None = None
    limit: int | None = None


class GoalStyleModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    steps: int | None = None
    random_steps: int | None = Field(None, alias="random steps")
    all_answered: AllAnsweredModel | None = None
    max_cost: float | None = None

    @model_validator(mode="after")
    def _mutual_exclusion(self) -> "GoalStyleModel":
        chosen = [
            k
            for k, v in {
                "steps": self.steps,
                "random steps": self.random_steps,
                "all_answered": self.all_answered,
            }.items()
            if v is not None
        ]
        if len(chosen) == 0:
            raise ValueError("goal_style must define one of: 'steps', 'random steps', or 'all_answered'.")
        if len(chosen) > 1:
            raise ValueError(f"goal_style must pick exactly one. Found: {', '.join(chosen)}.")
        if self.steps is not None and self.steps < 1:
            raise ValueError("goal_style.steps must be >= 1.")
        if self.random_steps is not None:
            if self.random_steps < 1:
                raise ValueError("'random steps' must be >= 1.")
            if self.random_steps > 20:
                # per guide: "random steps: M (random 1..M, M ≤ 20)"
                raise ValueError("'random steps' must be ≤ 20.")
        if self.all_answered is not None:
            # auto default limit 30 if not available
            if self.all_answered.limit is None:
                self.all_answered.limit = 30
        return self


class ConversationModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    number: int | StrictStr
    max_cost: float | None = None
    goal_style: GoalStyleModel | None = None
    interaction_style: list[Any] | None = None

    @field_validator("number", mode="before")
    @classmethod
    def _validate_number(cls, v: object) -> object:
        if not _validate_number_expr(v):
            raise ValueError("conversation.number must be an integer >= 1 or a 'combinations[...]' expression.")
        return v


class UserModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    language: StrictStr
    role: StrictStr
    context: list[Any] | None = None
    goals: list[Any]

    @field_validator("language", "role")
    @classmethod
    def _non_empty(cls, v: str, info: ValidationInfo) -> str:
        if not v.strip():
            raise ValueError(f"field '{info.field_name}' must be a non-empty string.")
        return v

    @field_validator("goals")
    @classmethod
    def _goals_non_empty(cls, v: list[Any]) -> list[Any]:
        if not isinstance(v, list) or not v:
            raise ValueError("user.goals must be a non-empty list.")
        return v


class ProfileModel(BaseModel):
    """Pydantic v2 model for a Sensei profile."""

    model_config = ConfigDict(extra="allow")

    # Top-level
    test_name: StrictStr
    llm: LLMModel | None = None
    user: UserModel
    chatbot: ChatbotModel
    conversation: ConversationModel

    @field_validator("test_name")
    @classmethod
    def _non_empty_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field 'test_name' must be a non-empty string.")
        return v


# ──────────────────────────────────────────────────────────────────────────────
# Main validation
# ──────────────────────────────────────────────────────────────────────────────


def validate_profile(profile_text: str) -> ProfileValidationResult:
    """Validate a single Sensei profile represented as YAML text, using Pydantic."""
    warnings: list[str] = []

    loaded, load_errors = load_yaml_mapping(
        profile_text,
        empty_message="Profile text is empty.",
        invalid_message_prefix="Profile is not valid YAML",
        not_mapping_message="Profile must parse into a mapping.",
    )
    if load_errors or loaded is None:
        return ProfileValidationResult(False, load_errors, warnings)

    errors: list[str] = []

    # 2) Warnings/errors of top-level keys
    required_top = {"test_name", "user", "chatbot", "conversation"}
    allowed_top = {"test_name", "llm", "user", "chatbot", "conversation"}

    missing, unknown = check_required_keys(loaded, required_top, allowed_top)
    if missing:
        errors.append(f"Missing required top-level fields: {', '.join(missing)}.")
        return ProfileValidationResult(False, errors, warnings)

    if unknown:
        errors.append(f"Unexpected top-level fields present: {', '.join(unknown)}.")
        return ProfileValidationResult(False, errors, warnings)

    # 2.1) Know section warnings (extra='allow')
    def warn_unknown(section: str, allowed: set[str]) -> None:
        node = loaded.get(section)
        if isinstance(node, dict):
            unk = sorted(set(node) - allowed)
            if unk:
                warnings.append(f"{section}: unexpected fields present: {', '.join(unk)}.")

    # LLM
    if "llm" in loaded and isinstance(loaded["llm"], dict):
        warn_unknown(
            "llm",
            {"temperature", "model", "model_prov", "format"},
        )
        if isinstance(loaded["llm"].get("format"), dict):
            fmt_allowed = {"type", "config"}
            fmt_unk = sorted(set(loaded["llm"]["format"]) - fmt_allowed)
            if fmt_unk:
                errors.append(f"llm.format: unexpected fields present: {', '.join(fmt_unk)}.")

    # user
    if "user" in loaded and isinstance(loaded["user"], dict):
        warn_unknown("user", {"language", "role", "context", "goals"})

    # chatbot
    if "chatbot" in loaded and isinstance(loaded["chatbot"], dict):
        warn_unknown("chatbot", {"is_starter", "fallback", "output"})

    # conversation
    if "conversation" in loaded and isinstance(loaded["conversation"], dict):
        warn_unknown("conversation", {"number", "max_cost", "goal_style", "interaction_style"})
        gs = loaded["conversation"].get("goal_style")
        if isinstance(gs, dict):
            gs_allowed = {"steps", "random steps", "all_answered", "max_cost"}
            gs_unk = sorted(set(gs) - gs_allowed)
            if gs_unk:
                errors.append(f"conversation.goal_style: unexpected fields present: {', '.join(gs_unk)}.")
            if isinstance(gs.get("all_answered"), dict):
                aa_allowed = {"export", "limit"}
                aa_unk = sorted(set(gs["all_answered"]) - aa_allowed)
                if aa_unk:
                    errors.append(
                        f"conversation.goal_style.all_answered: unexpected fields present: {', '.join(aa_unk)}."
                    )

    # 3) Types/values via Pydantic
    model: ProfileModel | None = None
    if not errors:
        try:
            model = ProfileModel.model_validate(loaded)
        except ValidationError as ve:
            for err in ve.errors():
                msg = err.get("msg", "")
                errors.append(msg)

    # 4) Additional business rules
    if model and not errors:
        # 4.1) llm.format: speech → config recommended
        if model.llm and model.llm.format:
            if model.llm.format.type == "speech" and not model.llm.format.config:
                warnings.append("llm.format.type is 'speech' but 'config' is not provided.")

        # 4.2) chatbot.output: each input must be { field_name: {type, description}}
        if model.chatbot.output is not None:
            seen_fields: set[str] = set()
            for idx, item in enumerate(model.chatbot.output, start=1):
                if not isinstance(item, dict) or len(item) != 1:
                    errors.append(f"chatbot.output entry #{idx} must be a mapping with a single field name.")
                    continue
                field_name, spec = next(iter(item.items()))
                if not re.fullmatch(r"[A-Za-z_]\w*", field_name):
                    errors.append(f"chatbot.output field name '{field_name}' is not a valid identifier.")
                if field_name in seen_fields:
                    errors.append(f"chatbot.output field '{field_name}' is duplicated.")
                seen_fields.add(field_name)
                if not isinstance(spec, dict):
                    errors.append(f"chatbot.output '{field_name}' spec must be a mapping.")
                    errors.append(f"chatbot.output '{field_name}' must include 'type' and 'description'.")
                    continue
                if "type" not in spec or "description" not in spec:
                    errors.append(f"chatbot.output '{field_name}' must include 'type' and 'description'.")
                    continue
                t = spec["type"]
                if not isinstance(t, str) or not t.strip():
                    errors.append(f"chatbot.output '{field_name}': 'type' must be a non-empty string.")
                elif not _is_valid_output_type(t):
                    errors.append(
                        f"chatbot.output '{field_name}': unsupported type '{t}'. "
                        'Use primitives (string|int|float), list[...], time(".."), date("..") or a custom type name.'
                    )
                d = spec["description"]
                if not isinstance(d, str) or not d.strip():
                    errors.append(f"chatbot.output '{field_name}': 'description' must be a non-empty string.")

        # 4.3) user.context: each item string or {'personality': <path>}
        if model.user.context is not None:
            for i, c in enumerate(model.user.context, start=1):
                if isinstance(c, str):
                    if not c.strip():
                        warnings.append(f"user.context entry #{i} is an empty string.")
                elif isinstance(c, dict):
                    if "personality" not in c:
                        warnings.append(f"user.context entry #{i}: mapping should contain 'personality' key.")
                    else:
                        personality = c.get("personality")
                        if not isinstance(personality, str) or not personality.strip():
                            errors.append(f"user.context entry #{i}: 'personality' must be a non-empty string path.")
                    extra = set(c) - {"personality"}
                    if extra:
                        warnings.append(f"user.context entry #{i}: unexpected keys: {', '.join(sorted(extra))}.")
                else:
                    warnings.append(f"user.context entry #{i}: unsupported item type ({type(c).__name__}).")

        # 4.4) user.goals:
        declared_vars: dict[str, dict[str, Any]] = {}
        mentioned_vars: set[str] = set()
        pairwise_count: int = 0
        # a) iterate the list
        for gi, g in enumerate(model.user.goals, start=1):
            if isinstance(g, str):
                if not g.strip():
                    errors.append(f"user.goals entry #{gi} must be a non-empty string or variable declaration.")
                else:
                    mentioned_vars |= _extract_placeholders(g)
            elif isinstance(g, dict):
                if len(g) != 1:
                    errors.append(f"user.goals variable declaration #{gi} must have exactly one variable name.")
                    continue
                var_name, spec = next(iter(g.items()))
                if not re.fullmatch(r"[A-Za-z_]\w*", var_name):
                    errors.append(f"user.goals variable name '{var_name}' is not a valid identifier.")
                if not isinstance(spec, dict):
                    errors.append(f"user.goals variable '{var_name}' spec must be a mapping.")
                    continue
                # required: function, type, data
                for req_key in ("function", "type", "data"):
                    if req_key not in spec:
                        errors.append(f"user.goals variable '{var_name}' missing required key '{req_key}'.")
                # validate function
                func = spec.get("function")
                if isinstance(func, str):
                    ok, fname, fargs, ferr = _validate_function_syntax(func)
                    if not ok:
                        errors.append(f"user.goals variable '{var_name}': invalid function '{func}': {ferr}")
                    else:
                        # forward(dep) → warns if dep is not declared
                        if fname == "forward" and fargs:
                            dep = fargs[0]
                            if not re.fullmatch(r"[A-Za-z_]\w*", dep):
                                errors.append(
                                    f"user.goals variable '{var_name}': forward(dep) requires a valid identifier."
                                )
                        if fname == "pairwise":
                            pairwise_count += 1
                else:
                    errors.append(f"user.goals variable '{var_name}': 'function' must be a string.")

                # validate type
                vtype = spec.get("type")
                if not isinstance(vtype, str) or not vtype.strip():
                    errors.append(f"user.goals variable '{var_name}': 'type' must be a non-empty string.")

                # validate data
                data = spec.get("data")
                if data is None:
                    errors.append(f"user.goals variable '{var_name}': 'data' must be provided.")
                else:
                    # list of literals or 'any(...)' strings, OR range mapping, OR file/function mapping
                    if isinstance(data, list):
                        if not data:
                            errors.append(f"user.goals variable '{var_name}': 'data' list must not be empty.")
                        for di, val in enumerate(data, start=1):
                            if isinstance(val, (str, int, float)):
                                if isinstance(val, str) and not val.strip():
                                    errors.append(f"user.goals variable '{var_name}': data[{di}] is an empty string.")
                                # allow strings like any(...)
                            else:
                                # allow nested selectors like {'file':..., 'function_name':..., 'args':...} via dict
                                if isinstance(val, dict):
                                    # pass, validated later by user
                                    pass
                                else:
                                    warnings.append(
                                        f"user.goals variable '{var_name}': data[{di}] has unsupported type '{type(val).__name__}'."
                                    )
                    elif isinstance(data, dict):
                        keys = set(data)
                        # Numeric range: min/max/(step|linspace)
                        if {"min", "max"} <= keys:
                            vmin = data["min"]
                            vmax = data["max"]
                            if not isinstance(vmin, (int, float)) or not isinstance(vmax, (int, float)):
                                errors.append(f"user.goals variable '{var_name}': range 'min'/'max' must be numeric.")
                            else:
                                if vmax < vmin:
                                    errors.append(f"user.goals variable '{var_name}': range 'max' must be >= 'min'.")
                            if "step" in data and not isinstance(data["step"], (int, float)):
                                errors.append(
                                    f"user.goals variable '{var_name}': range 'step' must be numeric when provided."
                                )
                            # linspace is optional flag/shape – we accept presence
                        elif {"file", "function_name"} <= keys:
                            if not isinstance(data["file"], str) or not data["file"].strip():
                                errors.append(
                                    f"user.goals variable '{var_name}': data.file must be a non-empty string."
                                )
                            if not isinstance(data["function_name"], str) or not data["function_name"].strip():
                                errors.append(
                                    f"user.goals variable '{var_name}': data.function_name must be a non-empty string."
                                )
                            # args is free-form (list/str/number/dict) → accept
                        else:
                            warnings.append(
                                f"user.goals variable '{var_name}': data mapping not recognized; "
                                "expected range {min,max[,step|linspace]} or {file,function_name[,args]}."
                            )
                    elif isinstance(data, (str, int, float)):
                        # Simple literal or "any(...)" string – accept
                        pass
                    else:
                        warnings.append(
                            f"user.goals variable '{var_name}': 'data' type '{type(data).__name__}' is unusual."
                        )

                if var_name in declared_vars:
                    errors.append(f"user.goals variable '{var_name}' is declared more than once.")
                declared_vars[var_name] = spec
            else:
                errors.append(f"user.goals entry #{gi}: unsupported item type '{type(g).__name__}'.")

        if pairwise_count == 1:
            errors.append(
                "invalid function 'pairwise()': A minimum of 2 pairwise() functions must be assigned when used."
            )

        # a.1) forward(dep) available dependencies -> warning if they don't exist
        for vname, spec in declared_vars.items():
            func = spec.get("function")
            if isinstance(func, str):
                ok, fname, fargs, ferr = _validate_function_syntax(func)
                if ok and fname == "forward" and fargs:
                    dep = fargs[0]
                    if dep not in declared_vars:
                        warnings.append(
                            f"user.goals variable '{vname}': forward({dep}) refers to a variable not declared in goals."
                        )

        # b) used placeholders must be declared
        missing_decls = sorted(mentioned_vars - set(declared_vars))
        if missing_decls:
            errors.append("user.goals text contains placeholders without declaration: " + ", ".join(missing_decls))

        # c) unused declarations → warning
        unused = sorted(set(declared_vars) - mentioned_vars)
        if unused:
            warnings.append("user.goals declared variables not referenced in any goal text: " + ", ".join(unused))

        # 4.5) conversation.interaction_style: validate in a basic way
        if model.conversation.interaction_style is not None:
            unk_styles: list[str | dict[str, str]] = []
            for i, item in enumerate(model.conversation.interaction_style, start=1):
                if isinstance(item, str):
                    if not item.strip():
                        warnings.append(f"conversation.interaction_style entry #{i} is an empty string.")
                    elif item not in _INTERACTION_STYLES:
                        unk_styles.append(item)
                elif isinstance(item, dict):
                    # supported keys: 'random' (list), 'change language' (list)
                    if "random" in item:
                        lst = item["random"]
                        if not isinstance(lst, list) or not lst:
                            errors.append("conversation.interaction_style 'random' must be a non-empty list.")
                        else:
                            unk_rand_styles: list[str | dict[str, str]] = []
                            for style in lst:
                                if isinstance(style, dict):
                                    d_style = list(style.keys())[0]
                                    if d_style != "change language":
                                        unk_rand_styles.append(style)
                                else:
                                    if style not in _INTERACTION_STYLES:
                                        unk_rand_styles.append(style)
                            if unk_rand_styles:
                                errors.append(
                                    f"conversation.interaction_style '{unk_rand_styles}' are invalid interaction styles "
                                    f" inside 'random' key. Only these can be admitted: {_INTERACTION_STYLES}."
                                )

                    if "change language" in item:
                        langs = item["change language"]
                        if not isinstance(langs, list) or not all(isinstance(x, str) and x.strip() for x in langs):
                            errors.append(
                                "conversation.interaction_style 'change language' must be a list of non-empty strings."
                            )
                    extra = set(item) - {"random", "change language"}
                    if extra:
                        warnings.append(
                            f"conversation.interaction_style entry #{i}: unexpected keys: {', '.join(sorted(extra))}."
                        )
                else:
                    warnings.append(
                        f"conversation.interaction_style entry #{i}: unsupported item type '{type(item).__name__}'."
                    )
            if unk_styles:
                errors.append(
                    f"conversation.interaction_style '{unk_styles}' are invalid interaction styles. "
                    f"Only these can be admitted: {_INTERACTION_STYLES}."
                )

        # 4.6) chatbot.fallback recommended
        if model.chatbot.fallback is None or not model.chatbot.fallback.strip():
            warnings.append("chatbot.fallback is recommended to avoid loops in conversations.")

    is_valid = not errors

    # Minimum normalization
    normalized = dict(loaded)
    # goal_style.all_answered.limit default (already applied within the model)
    if is_valid and model and model.conversation.goal_style and model.conversation.goal_style.all_answered:
        # Write default in normalized dict if missing
        try:
            gs = normalized.setdefault("conversation", {}).setdefault("goal_style", {})
            aa = gs.setdefault("all_answered", {})
            aa.setdefault("limit", model.conversation.goal_style.all_answered.limit)
        except Exception:
            pass

    return ProfileValidationResult(is_valid, errors, warnings, data=normalized if is_valid else None)


__all__ = ["ProfileValidationResult", "validate_profile", "load_yaml_mapping"]
