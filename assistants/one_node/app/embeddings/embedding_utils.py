"""Utility functions for loading YAML profile files and converting them into text or compact YAML/Markdown contexts suitable for embedding models."""

from pathlib import Path
from typing import Any, Dict, List, Mapping, TypedDict, cast

import yaml


class FilesState(TypedDict):
    """Represents the on-disk state of project profile files."""

    profile_state: Dict[str, float]
    profiles: List[str]


class ProfileYaml(TypedDict):
    """Parsed YAML structure for a single user profile."""

    user: Dict[str, Any]


def load_yaml_file(path: Path) -> ProfileYaml:
    """Load a YAML file and return its contents as a dictionary.

    Args:
        path (Path): Path to the YAML file.

    Returns:
        ProfileYaml: Parsed YAML content.
    """
    raw_text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        return cast(ProfileYaml, {"__raw_text__": raw_text, "__parse_error__": str(exc)})

    if not isinstance(data, dict):
        return cast(
            ProfileYaml,
            {
                "__raw_text__": raw_text,
                "__parse_error__": "YAML file must contain a mapping at the top level",
            },
        )

    return cast(ProfileYaml, data)


def profile_to_text(profile: Mapping[str, Any], filename: str) -> str:
    """Convert a Sensei YAML profile into a text format suitable for embeddings.

    This function extracts relevant fields from a profile file and formats them
    into a structured plain-text representation adapted to real profile structures
    such as user_sim_pizzaorder_custom.yml.

    Args:
        profile (Dict[str, Any]): Parsed YAML profile data.
        filename (str): Name of the profile file.

    Returns:
        str: Plain-text representation of the profile content.
    """
    lines: List[str] = []
    lines.append(f"Profile file: {filename}")

    raw_text = profile.get("__raw_text__")
    if isinstance(raw_text, str):
        parse_error = profile.get("__parse_error__")
        if isinstance(parse_error, str) and parse_error:
            lines.append(f"YAML parse error: {parse_error}")
        lines.append("Raw YAML content:")
        lines.append(raw_text)
        return "\n".join(lines)

    # Test name
    test_name = profile.get("test_name")
    if test_name:
        lines.append(f"Test name: {test_name}")

    # LLM configuration (optional but gives context)
    llm = profile.get("llm", {})
    model = llm.get("model")
    model_prov = llm.get("model_prov")
    temperature = llm.get("temperature")
    if model or model_prov or temperature is not None:
        lines.append("LLM config:")
        if model:
            lines.append(f"- model: {model}")
        if model_prov:
            lines.append(f"- provider: {model_prov}")
        if temperature is not None:
            lines.append(f"- temperature: {temperature}")

    # --- USER SECTION ---
    user = profile.get("user", {})
    if user:
        language = user.get("language")
        role = user.get("role")
        if language:
            lines.append(f"User language: {language}")
        if role:
            lines.append(f"User role: {role}")

        # User context
        context = user.get("context", [])
        if context:
            lines.append("User context:")
            for c in context:
                if isinstance(c, str):
                    lines.append(f"- {c}")
                elif isinstance(c, dict):
                    for k, v in c.items():
                        lines.append(f"- {k}: {v}")
                else:
                    lines.append(f"- {repr(c)}")

        # Goals and variables (mixed list under user.goals)
        goals = user.get("goals", [])
        if goals:
            lines.append("User goals and variables:")
            for g in goals:
                if isinstance(g, str):
                    lines.append(f"- goal: {g}")

                elif isinstance(g, dict):
                    for var_name, details in g.items():
                        if isinstance(details, dict):
                            func = details.get("function")
                            vtype = details.get("type")
                            data = details.get("data")
                            desc_parts = []
                            if vtype:
                                desc_parts.append(f"type={vtype}")
                            if func:
                                desc_parts.append(f"function={func}")
                            if data is not None:
                                desc_parts.append(f"data={data}")
                            desc = ", ".join(desc_parts)
                            lines.append(f"- {var_name}: {desc}")
                        else:
                            lines.append(f"- {var_name}: {details}")
                else:
                    lines.append(f"- {repr(g)}")

    # --- CHATBOT SECTION ---
    chatbot = profile.get("chatbot", {})
    if chatbot:
        is_starter = chatbot.get("is_starter")
        fallback = chatbot.get("fallback")
        if is_starter is not None:
            lines.append(f"Chatbot is_starter: {is_starter}")
        if fallback:
            lines.append(f"Chatbot fallback: {fallback}")

        outputs = chatbot.get("output", [])
        if outputs:
            lines.append("Chatbot outputs:")
            for out in outputs:
                if isinstance(out, dict):
                    # e.g. {name: {type, description}}
                    for name, meta in out.items():
                        if isinstance(meta, dict):
                            otype = meta.get("type")
                            desc = meta.get("description") or ""
                            lines.append(f"- {name} ({otype}): {desc}")
                        else:
                            lines.append(f"- {name}: {meta}")
                else:
                    lines.append(f"- {repr(out)}")

    # --- CONVERSATION SECTION ---
    conv = profile.get("conversation", {})
    if conv:
        number = conv.get("number")
        goal_style = conv.get("goal_style")
        interaction_style = conv.get("interaction_style")
        if number is not None:
            lines.append(f"Number of conversations: {number}")
        if goal_style:
            lines.append(f"Goal style: {goal_style}")
        if interaction_style:
            lines.append(f"Interaction style: {interaction_style}")

    return "\n".join(lines)


def build_llm_context_from_profile(profile: Dict[str, Any], filename: str) -> str:
    """Build a compact YAML/Markdown-style context for an LLM from a Sensei profile.

    The output includes only natural-language goals, structured input variables, and
    chatbot output definitions, matching the structure used in profiles such as
    user_sim_pizzaorder_custom.yml.

    Args:
        profile (Dict[str, Any]): Parsed YAML profile data.
        filename (str): Profile file name.

    Returns:
        str: Compact context formatted as YAML/Markdown.
    """
    lines: List[str] = []
    lines.append(f"profile_name: {filename}")

    raw_text = profile.get("__raw_text__")
    if isinstance(raw_text, str):
        parse_error = profile.get("__parse_error__")
        if isinstance(parse_error, str) and parse_error:
            lines.append(f'parse_error: "{parse_error}"')
        lines.append("raw_yaml: |")
        for line in raw_text.splitlines():
            lines.append(f"  {line}")
        return "\n".join(lines)

    # Extract GOALS (plain text goals only)
    user = profile.get("user", {})
    user_goals = user.get("goals", [])

    goal_texts = []
    inputs = []

    for g in user_goals:
        if isinstance(g, str):
            goal_texts.append(g)

        elif isinstance(g, dict):
            for var_name, meta in g.items():
                if isinstance(meta, dict):
                    inputs.append(
                        {
                            "name": var_name,
                            "type": meta.get("type"),
                            "data": meta.get("data"),
                            "function": meta.get("function"),
                        }
                    )

    if goal_texts:
        lines.append("goals:")
        for g in goal_texts:
            lines.append(f'  - "{g}"')

    # Extract INPUTS (structured variable definitions)
    if inputs:
        lines.append("inputs:")
        for inp in inputs:
            lines.append(f"  - name: {inp['name']}")
            lines.append(f"    type: {inp['type']}")
            if inp.get("data") is not None:
                lines.append(f"    data: {inp['data']}")
            if inp.get("function"):
                lines.append(f"    function: {inp['function']}")

    # Extract OUTPUTS (chatbot.output)
    chatbot = profile.get("chatbot", {})
    outputs_raw = chatbot.get("output", [])

    outputs = []

    for out in outputs_raw:
        if isinstance(out, dict):
            for out_name, meta in out.items():
                if isinstance(meta, dict):
                    outputs.append({"name": out_name, "type": meta.get("type"), "description": meta.get("description")})

    if outputs:
        lines.append("outputs:")
        for out in outputs:
            lines.append(f"  - name: {out['name']}")
            if out.get("type"):
                lines.append(f"    type: {out['type']}")
            if out.get("description"):
                lines.append(f'    description: "{out["description"]}"')

    return "\n".join(lines)
