# -*- coding: utf-8 -*-
from __future__ import annotations

from textwrap import dedent
from typing import Any, cast

import pytest
import yaml

import app.validator.profiles_validator as profiles_validator
from app.validator.profiles_validator import ProfileValidationResult, validate_profile

_INTERACTION_STYLES = {
    "long phrases",
    "change your mind",
    "change language",
    "make spelling mistakes",
    "single questions",
    "all questions",
    "default",
}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def mk_profile_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "test_name": "Demo",
        "llm": {"temperature": 0.3, "model": "gpt-4o"},
        "user": {
            "language": "en",
            "role": "customer",
            "goals": ["Find a product"],
        },
        "chatbot": {
            "is_starter": True,
            "fallback": "Sorry, I didn't get that.",
            "output": [{"result": {"type": "string", "description": "Final result"}}],
        },
        "conversation": {
            "number": 1,
            "goal_style": {"steps": 3},
            "interaction_style": ["default"],
        },
    }
    for dotted_key, value in overrides.items():
        node: dict[str, Any] = base
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = cast(dict[str, Any], child)
        node[parts[-1]] = value
    return base


def dump_yaml(profile: dict[str, Any]) -> str:
    return yaml.safe_dump(profile, sort_keys=False)


def has_error(res: ProfileValidationResult, substr: str) -> bool:
    return any(substr in error for error in res.errors)


def has_warning(res: ProfileValidationResult, substr: str) -> bool:
    return any(substr in warning for warning in res.warnings)


# ---------------------------------------------------------------------
# 1) Pydantic validators & top-level simple errors
# ---------------------------------------------------------------------
def test_test_name_must_be_non_empty() -> None:
    d = mk_profile_dict()
    d["test_name"] = ""
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "field 'test_name' must be a non-empty string.")


@pytest.mark.parametrize("field", ["user.language", "user.role"])
def test_user_language_and_role_non_empty(field: str) -> None:
    d = mk_profile_dict()
    # set empty string to trigger non-empty validation
    node = d
    parts = field.split(".")
    for p in parts[:-1]:
        node = node[p]
    node[parts[-1]] = ""
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "must be a non-empty string.")


def test_user_goals_non_empty_list() -> None:
    d = mk_profile_dict()
    d["user"]["goals"] = []
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "user.goals must be a non-empty list.")


# ---------------------------------------------------------------------
# 2) warn_unknown(...) and format extra fields
# ---------------------------------------------------------------------
def test_warn_unknown_nested_keys_and_llm_format_extra_key() -> None:
    d = mk_profile_dict()
    d["llm"]["extra"] = True
    d["llm"]["format"] = {"type": "text", "bogus": 1}  # triggers error in llm.format
    d["user"]["x"] = 1
    d["chatbot"]["y"] = 2
    d["conversation"]["z"] = 3
    res = validate_profile(dump_yaml(d))
    # llm.format unexpected -> error
    assert not res.is_valid
    assert has_error(res, "llm.format: unexpected fields present: bogus")
    # nested unknown keys -> warnings
    assert has_warning(res, "llm: unexpected fields present: extra")
    assert has_warning(res, "user: unexpected fields present: x")
    assert has_warning(res, "chatbot: unexpected fields present: y")
    assert has_warning(res, "conversation: unexpected fields present: z")


def test_conversation_goal_style_unknown_keys_and_all_answered_unknown_keys() -> None:
    d = mk_profile_dict()
    d["conversation"]["goal_style"] = {"steps": 2, "unknown": True}
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "conversation.goal_style: unexpected fields present: unknown")

    d = mk_profile_dict()
    d["conversation"]["goal_style"] = {"all_answered": {"foo": True}}
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "conversation.goal_style.all_answered: unexpected fields present: foo")


# ---------------------------------------------------------------------
# 3) Goal style numeric bounds (extra branches)
# ---------------------------------------------------------------------
def test_goal_style_steps_and_random_steps_lower_bounds() -> None:
    d = mk_profile_dict()
    d["conversation"]["goal_style"] = {"steps": 0}
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "goal_style.steps must be >= 1.")

    d = mk_profile_dict()
    d["conversation"]["goal_style"] = {"random steps": 0}
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "'random steps' must be >= 1.")


# ---------------------------------------------------------------------
# 4) Chatbot.fallback validator (None path + empty string error)
# ---------------------------------------------------------------------
def test_chatbot_fallback_none_warns_and_empty_string_is_error() -> None:
    # Explicit None -> valid but warns
    d = mk_profile_dict()
    d["chatbot"]["fallback"] = None
    res = validate_profile(dump_yaml(d))
    assert res.is_valid
    assert has_warning(res, "chatbot.fallback is recommended")

    # Empty string -> pydantic error
    d = mk_profile_dict()
    d["chatbot"]["fallback"] = ""
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "field 'fallback' must be a non-empty string if provided.")


# ---------------------------------------------------------------------
# 5) chatbot.output deeper validation branches
# ---------------------------------------------------------------------
def test_chatbot_output_entry_must_be_single_field_mapping() -> None:
    d = mk_profile_dict()
    d["chatbot"]["output"] = ["not-a-mapping"]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "chatbot.output entry #1 must be a mapping with a single field name.") or has_error(
        res, "Input should be a valid dictionary"
    )


def test_chatbot_output_missing_type_or_description_and_bad_types() -> None:
    d = mk_profile_dict()
    d["chatbot"]["output"] = [
        {"onlyType": {"type": "string"}},  # missing description -> 400-401
        {"emptyType": {"type": "", "description": "x"}},  # empty type -> 404
        {"badType": {"type": "list[123]", "description": "x"}},  # unsupported type -> 406
        {"emptyDesc": {"type": "string", "description": ""}},  # empty description -> 412
    ]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "onlyType' must include 'type' and 'description")
    assert has_error(res, "'emptyType': 'type' must be a non-empty string")
    assert has_error(res, "unsupported type 'list[123]'")
    assert has_error(res, "'emptyDesc': 'description' must be a non-empty string.")


# ---------------------------------------------------------------------
# 6) user.context unsupported item type
# ---------------------------------------------------------------------
def test_user_context_unsupported_item_type_warning() -> None:
    d = mk_profile_dict()
    d["user"]["context"] = [123]
    res = validate_profile(dump_yaml(d))
    assert res.is_valid
    assert has_warning(res, "user.context entry #1: unsupported item type (int).")


# ---------------------------------------------------------------------
# 7) user.goals – exercise many branches including _validate_function_syntax
# ---------------------------------------------------------------------
def test_user_goals_invalid_function_forms_covering_edges() -> None:
    d = mk_profile_dict()
    d["user"]["goals"] = [
        {"r0": {"function": "random(0)", "type": "string", "data": ["x"]}},
        {"rfoo": {"function": "random(foo)", "type": "string", "data": ["x"]}},
        {"a0": {"function": "another(0)", "type": "string", "data": ["x"]}},
        {"afoo": {"function": "another(foo)", "type": "string", "data": ["x"]}},
        {"fnum": {"function": "forward(123)", "type": "string", "data": ["x"]}},
        {"pw": {"function": "pairwise(1)", "type": "string", "data": ["x"]}},
        {"def": {"function": "default(1)", "type": "string", "data": ["x"]}},
        {"myst": {"function": "mystery()", "type": "string", "data": ["x"]}},
    ]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "invalid function 'random(0)': random(n) requires n > 0.")
    assert has_error(res, "invalid function 'random(foo)': random() accepts no args")
    assert has_error(res, "invalid function 'another(0)': another(n) requires n > 0.")
    assert has_error(res, "invalid function 'another(foo)': another() accepts no args")
    assert has_error(res, "invalid function 'forward(123)': forward() optionally takes a single dependency variable.")
    assert has_error(res, "invalid function 'pairwise(1)': pairwise() takes no arguments.")
    assert has_error(res, "invalid function 'default(1)': default() takes no arguments.")
    assert has_error(res, "invalid function 'mystery()': Unsupported function.")


def test_user_goals_invalid_single_pairwise_function() -> None:
    d = mk_profile_dict()
    d["user"]["goals"] = [{"pw": {"function": "pairwise()", "type": "string", "data": ["x"]}}]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(
        res, "invalid function 'pairwise()': A minimum of 2 pairwise() functions must be assigned when used."
    )


def test_user_goals_var_declaration_shape_name_and_duplicates_and_spec_mapping() -> None:
    d = mk_profile_dict()
    d["user"]["goals"] = [
        {"bad1": {"function": "default()", "type": "string", "data": ["x"]}},
        {"bad2": {"function": "default()", "type": "string", "data": ["x"]}},
        {"two": {"function": "default()", "type": "string", "data": ["x"]}},
        {"two2": {"function": "default()", "type": "string", "data": ["x"]}},
    ]
    # introduce shape error (two keys) and invalid name + spec-not-mapping
    d["user"]["goals"][2] = {"x": {}, "y": {}}  # two keys -> 446-447
    d["user"]["goals"][3] = {"1abc": {"function": "default()", "type": "string", "data": ["x"]}}  # 450
    d["user"]["goals"].append({"spec": "not-a-mapping"})  # 452-453
    # duplicate declaration
    d["user"]["goals"].append({"bad1": {"function": "default()", "type": "string", "data": ["y"]}})  # 543
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "must have exactly one variable name")
    assert has_error(res, "variable name '1abc' is not a valid identifier")
    assert has_error(res, "spec must be a mapping")
    assert has_error(res, "variable 'bad1' is declared more than once.")


def test_user_goals_type_and_data_validations() -> None:
    d = mk_profile_dict()
    d["user"]["goals"] = [
        {"t1": {"function": "default()", "type": "", "data": ["x"]}},  # empty type -> 478
        {"t2": {"function": "default()", "type": "string", "data": None}},  # data must be provided -> 483
        {"t3": {"function": "default()", "type": "string", "data": []}},  # data list not empty -> 488
        {"t4": {"function": "default()", "type": "string", "data": ["", {"ok": 1}, ["nested-list"]]}},  # 492 + 500
    ]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, " 'type' must be a non-empty string")
    assert has_error(res, "'data' must be provided")
    assert has_error(res, "'data' list must not be empty")
    assert has_error(res, "data[1] is an empty string") or has_error(res, "data[2] is an empty string")
    assert has_warning(res, "unsupported type 'list'")


def test_user_goals_range_and_file_function_name_validations_and_mapping_not_recognized() -> None:
    d = mk_profile_dict()
    d["user"]["goals"] = [
        {"r1": {"function": "default()", "type": "float", "data": {"min": "a", "max": 10}}},  # 510
        {"r2": {"function": "default()", "type": "float", "data": {"min": 10, "max": 5}}},  # 513
        {"r3": {"function": "default()", "type": "float", "data": {"min": 1, "max": 2, "step": "foo"}}},  # 515
        {"f1": {"function": "default()", "type": "string", "data": {"file": "", "function_name": ""}}},  # 521 + 525
        {"unrec": {"function": "default()", "type": "string", "data": {"hello": "world"}}},  # 530-533
    ]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "range 'min'/'max' must be numeric")
    assert has_error(res, "range 'max' must be >= 'min'")
    assert has_error(res, "range 'step' must be numeric")
    assert has_error(res, "data.file must be a non-empty string")
    assert has_error(res, "data.function_name must be a non-empty string")
    assert has_warning(res, "data mapping not recognized; expected range")


def test_user_goals_entry_empty_string_and_unsupported_type_item() -> None:
    d = mk_profile_dict()
    d["user"]["goals"] = [
        "",  # -> 441
        123,  # -> 546
        {"ok": {"function": "default()", "type": "string", "data": ["x"]}},
    ]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "must be a non-empty string or variable declaration")
    assert has_error(res, "unsupported item type 'int'")


# ---------------------------------------------------------------------
# 8) conversation.interaction_style branches
# ---------------------------------------------------------------------
def test_conversation_interaction_style_various_cases() -> None:
    d = mk_profile_dict()
    unk_styles = ["extra"]
    unk_random_styles = ["extra", {"x": ["x"]}]

    d["conversation"]["interaction_style"] = [
        "",  # empty string -> warning
        "extra",
        {"random": []},  # non-empty list required -> error
        {"random": unk_random_styles},  # unsupported item in random -> error
        {"change language": ["", "en"]},  # non-empty strings -> error
        {"extra": 1},  # unexpected keys -> warning
        123,  # unsupported item type -> warning
    ]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_warning(res, "entry #1 is an empty string.")
    assert has_error(
        res,
        f"conversation.interaction_style '{unk_random_styles}' are invalid interaction styles "
        f" inside 'random' key. Only these can be admitted: {_INTERACTION_STYLES}.",
    )
    assert has_error(res, "'random' must be a non-empty list.")
    assert has_error(res, "'change language' must be a list of non-empty strings.")
    assert has_error(
        res,
        f"conversation.interaction_style '{unk_styles}' are invalid interaction styles. "
        f"Only these can be admitted: {_INTERACTION_STYLES}.",
    )
    assert has_warning(res, "unexpected keys: extra")
    assert has_warning(res, "unsupported item type 'int'")


# ---------------------------------------------------------------------
# 9) Extra: chatbot.output invalid identifier forces _is_valid_output_type return False path too
# (We already checked unsupported type above; this ensures the False branch is executed.)
# ---------------------------------------------------------------------
def test_output_type_invalid_hits_false_branch() -> None:
    d = mk_profile_dict()
    d["chatbot"]["output"] = [{"bad": {"type": "bad type!", "description": "x"}}]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "unsupported type 'bad type!'")


# ---------------------------------------------------------------------
# 10) Basic structural guards and early returns
# ---------------------------------------------------------------------
def test_validate_profile_empty_text_returns_error() -> None:
    res = validate_profile("")
    assert not res.is_valid
    assert has_error(res, "Profile text is empty.")


def test_validate_profile_missing_required_top_level_fields() -> None:
    d = mk_profile_dict()
    d.pop("chatbot")
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "Missing required top-level fields: chatbot.")


def test_validate_profile_unexpected_top_level_field() -> None:
    d = mk_profile_dict(extra=True)
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "Unexpected top-level fields present: extra.")


# ---------------------------------------------------------------------
# 11) Goal style combinatorics and defaults
# ---------------------------------------------------------------------
def test_goal_style_requires_one_selector_and_disallows_multiple() -> None:
    d = mk_profile_dict()
    d["conversation"]["goal_style"] = {}
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "goal_style must define one of: 'steps', 'random steps', or 'all_answered'.")

    d = mk_profile_dict()
    d["conversation"]["goal_style"] = {"steps": 2, "random steps": 3}
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "goal_style must pick exactly one.")


def test_goal_style_random_steps_upper_bound_and_all_answered_limit_default() -> None:
    d = mk_profile_dict()
    d["conversation"]["goal_style"] = {"random steps": 25}
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "must be ≤ 20.")

    d = mk_profile_dict()
    d["conversation"]["goal_style"] = {"all_answered": {}}
    res = validate_profile(dump_yaml(d))
    assert res.is_valid
    assert res.data is not None
    assert res.data["conversation"]["goal_style"]["all_answered"]["limit"] == 30


# ---------------------------------------------------------------------
# 12) Conversation.number combinations expression coverage
# ---------------------------------------------------------------------
def test_conversation_number_accepts_combinations_expression() -> None:
    d = mk_profile_dict()
    d["conversation"]["number"] = "combinations(0.6, pairwise)"
    res = validate_profile(dump_yaml(d))
    assert res.is_valid


def test_conversation_number_invalid_expression() -> None:
    d = mk_profile_dict()
    d["conversation"]["number"] = "invalid"
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "conversation.number must be an integer >= 1 or a 'combinations")


# ---------------------------------------------------------------------
# 13) LLM speech format warning coverage
# ---------------------------------------------------------------------
def test_llm_speech_without_config_warns() -> None:
    d = mk_profile_dict()
    d["llm"]["format"] = {"type": "speech"}
    res = validate_profile(dump_yaml(d))
    assert res.is_valid
    assert has_warning(res, "llm.format.type is 'speech' but 'config' is not provided.")


# ---------------------------------------------------------------------
# 14) chatbot.output additional validation coverage
# ---------------------------------------------------------------------
def test_chatbot_output_additional_error_paths() -> None:
    d = mk_profile_dict()
    d["chatbot"]["output"] = [
        {"multi": {"type": "string", "description": "ok"}, "extra": {}},
        {"bad name": {"type": "string", "description": "ok"}},
        {"dup": {"type": "string", "description": "ok"}},
        {"dup": {"type": "string", "description": "ok"}},
        {"nodict": "value"},
        {"missing": {"type": "string"}},
    ]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "must be a mapping with a single field name.")
    assert has_error(res, "field name 'bad name' is not a valid identifier.")
    assert has_error(res, "field 'dup' is duplicated.")
    assert has_error(res, "spec must be a mapping.")
    assert has_error(res, "'missing' must include 'type' and 'description'.")


# ---------------------------------------------------------------------
# 15) user.context coverage for empty strings, missing keys, extra keys
# ---------------------------------------------------------------------
def test_user_context_various_warning_and_error_paths() -> None:
    d = mk_profile_dict()
    d["user"]["context"] = [
        "",
        {"personality": ""},
        {"personality": "persona.yml", "extra": 1},
        {"foo": "bar"},
        123,
    ]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_warning(res, "user.context entry #1 is an empty string.")
    assert has_error(res, "user.context entry #2: 'personality' must be a non-empty string path.")
    assert has_warning(res, "user.context entry #3: unexpected keys: extra.")
    assert has_warning(res, "user.context entry #4: mapping should contain 'personality' key.")
    assert has_warning(res, "user.context entry #4: unexpected keys: foo.")
    assert has_warning(res, "user.context entry #5: unsupported item type (int).")


# ---------------------------------------------------------------------
# 16) user.goals positive variants covering helper success paths
# ---------------------------------------------------------------------
def test_user_goals_function_positive_variants() -> None:
    d = mk_profile_dict()
    d["user"]["goals"] = [
        "Order {{size}} with {{topping}} and {{addon}} then {{dependent}}",
        "Follow {{sequence}} then {{dependent}}",
        {"size": {"function": "random(2)", "type": "string", "data": ["small", "large"]}},
        {"topping": {"function": "random(rand)", "type": "string", "data": ["pepperoni", "onions"]}},
        {"addon": {"function": "another(1)", "type": "string", "data": ["drink"]}},
        {"sequence": {"function": "forward()", "type": "string", "data": ["step1"]}},
        {"dependent": {"function": "forward(sequence)", "type": "string", "data": ["step2"]}},
    ]
    res = validate_profile(dump_yaml(d))
    assert res.is_valid


# ---------------------------------------------------------------------
# 17) user.goals missing keys, unusual data, and forward dependency warning
# ---------------------------------------------------------------------
def test_user_goals_missing_keys_and_unusual_data_types() -> None:
    d = mk_profile_dict()
    d["user"]["goals"] = [
        "Need {{missing}} value",
        {"no_function": {"type": "string", "data": ["x"]}},
        {"no_type": {"function": "default()", "data": ["x"]}},
        {"no_data": {"function": "default()", "type": "string"}},
        {"func_not_str": {"function": ["default"], "type": "string", "data": ["x"]}},
        {"data_str": {"function": "default()", "type": "string", "data": "literal"}},
        {"data_unusual": {"function": "default()", "type": "string", "data": {1, 2}}},
        {"fwd_missing": {"function": "forward(sequence)", "type": "string", "data": ["a"]}},
    ]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "variable 'no_function' missing required key 'function'.")
    assert has_error(res, "variable 'no_type' missing required key 'type'.")
    assert has_error(res, "variable 'no_data' missing required key 'data'.")
    assert has_error(res, "variable 'func_not_str': 'function' must be a string.")
    assert has_warning(res, "variable 'fwd_missing': forward(sequence) refers to a variable not declared in goals.")
    assert has_warning(res, "variable 'data_unusual': 'data' type 'set' is unusual.")
    assert has_error(res, "user.goals text contains placeholders without declaration: missing")


# ---------------------------------------------------------------------
# 18) chatbot.output valid types hit positive helper branches
# ---------------------------------------------------------------------
def test_chatbot_output_accepts_extended_type_variants() -> None:
    d = mk_profile_dict()
    d["chatbot"]["output"] = [
        {"items": {"type": "list[int]", "description": "numbers"}},
        {"call_time": {"type": 'time("%H:%M")', "description": "call time"}},
        {"ship_date": {"type": 'date("%Y-%m-%d")', "description": "shipping"}},
        {"custom": {"type": "custom_type", "description": "custom"}},
    ]
    res = validate_profile(dump_yaml(d))
    assert res.is_valid


# ---------------------------------------------------------------------
# 19) conversation.number validator rejects non int/str inputs (return False branch)
# ---------------------------------------------------------------------
def test_conversation_number_rejects_non_supported_type() -> None:
    d = mk_profile_dict()
    d["conversation"]["number"] = ["invalid"]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "conversation.number must be an integer >= 1 or a 'combinations")


# ---------------------------------------------------------------------
# 20) Force forward(dep) identifier error via monkeypatch
# ---------------------------------------------------------------------
def test_user_goals_forward_identifier_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original = profiles_validator._validate_function_syntax

    def fake_validate(func: str) -> tuple[bool, str, list[str] | None, str | None]:
        if func == "forward(sequence)":
            return True, "forward", ["not-valid!"], None
        return original(func)

    monkeypatch.setattr(profiles_validator, "_validate_function_syntax", fake_validate)

    d = mk_profile_dict()
    d["user"]["goals"] = [
        "Use {{sequence}} and {{other}}",
        {"sequence": {"function": "default()", "type": "string", "data": ["s"]}},
        {"other": {"function": "forward(sequence)", "type": "string", "data": ["o"]}},
    ]
    res = validate_profile(dump_yaml(d))
    assert not res.is_valid
    assert has_error(res, "forward(dep) requires a valid identifier.")
    # still warns about missing declared variable because of patched dep
    assert has_warning(res, "forward(not-valid!) refers to a variable not declared in goals.")


# ---------------------------------------------------------------------
# 21) Ensure normalization handles setdefault failures gracefully
# ---------------------------------------------------------------------
def test_all_answered_limit_handles_setdefault_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    d = mk_profile_dict()
    d["conversation"]["goal_style"] = {"all_answered": {}}

    original_load = profiles_validator.load_yaml_mapping

    class ExplodingDict(dict[str, Any]):
        def setdefault(self, key: str, default: Any | None = None) -> Any:
            raise RuntimeError("boom")

    def fake_load(
        profile_text: str,
        *,
        empty_message: str,
        invalid_message_prefix: str,
        not_mapping_message: str,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        loaded, errors = original_load(
            profile_text,
            empty_message=empty_message,
            invalid_message_prefix=invalid_message_prefix,
            not_mapping_message=not_mapping_message,
        )
        if loaded is not None:
            cloned = dict(loaded)
            conversation = dict(cloned.get("conversation", {}))
            cloned["conversation"] = ExplodingDict(conversation)
            return cloned, errors
        return loaded, errors

    monkeypatch.setattr(profiles_validator, "load_yaml_mapping", fake_load)

    res = validate_profile(dump_yaml(d))
    assert res.is_valid
    assert res.data is not None
    assert "limit" not in res.data["conversation"]["goal_style"]["all_answered"]


# ---------------------------------------------------------------------
# 22) Real profile fixture stays valid
# ---------------------------------------------------------------------
def test_real_profile() -> None:
    """This is a profile generated by TRACER and it is valid, lets check that the validator accepts it."""
    profile_yaml = dedent(
        """\
        test_name: Usuarios Nuevos y Admisiones
        llm:
          temperature: 0.3
          model: gpt-4o-mini
          format:
            type: text
        user:
          language: Spanish
          role: Estudiante potencial que busca información sobre el proceso de admisión y recursos disponibles.
          context:
          - "personality: personalities/conversational-user"
          - Estás considerando inscribirte en una universidad y buscas información detallada sobre el proceso de admisión y las opciones académicas disponibles.
          - Te gustaría conocer más sobre los diferentes grados y cursos que ofrece la universidad para poder tomar una decisión informada.
          - Además, tienes interés en participar en eventos como Welcome Day, ya que crees que podrían ayudarte a integrarte mejor como nuevo estudiante.
          goals:
          - "Solicitar información sobre el proceso de admisión para {{grados}} en la UAM."
          - "Pedir detalles sobre los procedimientos de lista de espera para admisiones a grados."
          - "Consultar la información disponible para futuros estudiantes sobre los {{cursos}} y grados ofrecidos."
          - "Solicitar información sobre el evento de Welcome Day y su relevancia para los nuevos estudiantes."
          - cursos:
              function: forward()
              type: string
              data:
              - "Ingeniería en Sistemas Computacionales"
              - "Licenciatura en Psicología"
              - "Arquitectura"
              - "Biología"
              - "Administración de Empresas"
              - "Química"
          - grados:
              function: forward()
              type: string
              data:
              - "Licenciatura en Psicología"
              - "Máster en Ingeniería de Software"
              - "Grado en Business Administration"
              - "Doctorado en Educación"
              - "Licenciatura en Medicina"
              - "Grado en Ciencias Políticas"
        chatbot:
          is_starter: false
          fallback: |-
            ¿Puedes preguntármelo de otra forma? o, si lo prefieres, puedes consultar nuestro
            catálogo de servicios
            .
            Respondo a preguntas dirigidas al
            Centro de Atención a Usuarios del servicio de Tecnologías de la Información.
          output:
          - admission_to_grados_link:
              type: string
              description: URL con detalles sobre los procesos de admisión
          - waitlist_info_link:
              type: string
              description: URL con detalles sobre listas de espera de admisión
          - future_students_link:
              type: string
              description: URL con recursos para estudiantes potenciales
          - welcome_day_link:
              type: string
              description: URL con detalles sobre el Welcome Day
          - grados_available:
              type: string
              description: Lista de grados ofrecidos
          - cursos_available:
              type: string
              description: Lista de cursos ofrecidos
          - waitlist_procedures:
              type: string
              description: Procedimientos para lista de espera
          - welcome_day_date:
              type: date
              description: Fecha del evento Welcome Day
          - welcome_day_time:
              type: time
              description: Hora del evento Welcome Day
          - admission_deadline:
              type: date
              description: Fecha límite para admisión
          - future_students_info:
              type: string
              description: Información general para futuros estudiantes
          - admission_requirements:
              type: string
              description: Requisitos de admisión para grados
          - event_location:
              type: string
              description: Ubicación del evento Welcome Day
          - enrollment_process:
              type: string
              description: Proceso de inscripción para nuevos estudiantes
          - contact_admissions:
              type: string
              description: Información de contacto de admisiones
          - application_fee:
              type: money
              description: Costo de la solicitud de admisión
        conversation:
          number: 3
          max_cost: 0.9
          goal_style:
            steps: 4
          interaction_style:
            - single questions
        """
    )
    res = validate_profile(profile_yaml)
    assert res.is_valid
    assert res.errors == []
    assert res.warnings == []
