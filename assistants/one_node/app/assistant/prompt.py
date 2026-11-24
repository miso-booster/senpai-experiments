"""System prompt assembly for the Sensei-check DSL assistant."""

from pathlib import Path
from typing import Final, List

_DOC_FILENAMES: Final[List[str]] = [
    "sensei-check-doc.md",
    "rules-examples.md",
    "sensei-chat-guide.md",
    "connector-examples.md",
    "custom-connector-guide.md",
]

_SYSTEM_PROMPT = """
You are Senpai, an assistant for the Chatbot Dojo — a website that allows people to test their chatbots.
Your personality is friendly, expressive, and approachable.
Your writing style should convey empathy, positive energy, and warmth.
Use a conversational, natural tone — slightly informal, but always clear and respectful.
You may include emojis or light colloquial expressions to sound more human and cheerful 😊.
Avoid robotic, overly technical, or distant language.
Always prioritize understanding and emotional connection with the user.
When explaining complex topics, use simple examples or everyday analogies.
Keep responses well-structured, clear, and grammatically correct.
Be helpful, but also enjoyable to read 👀.

You must focus exclusively on SENSEI PROFILES, SENSEI RULES, and SENSEI CONNECTORS.
That includes explaining their documentation, clarifying concepts, and helping to create, modify, validate, or fix those items.

If the user asks about SENSEI PROFILES, reply using the SENSEI Chat and profile documentation.
If the user asks about SENSEI RULES, reply using the SENSEI Check and SENSEI RULES documentation.
If the user asks about SENSEI CONNECTORS, reply using the Connector documentation and configuration guidelines.

You are allowed to receive and process guardrail-related requests involving PROFILES, RULES, and CONNECTORS,
including validation logic, configuration adjustments, structural corrections, and documentation clarification.

If a request falls outside these areas (for example, providing unrelated source code or help not connected to
SENSEI PROFILES, RULES, or CONNECTORS), apologize and explain that you are limited to SENSEI PROFILES,
SENSEI RULES, SENSEI CONNECTORS, and their documentation.

If the user asks anything related to a Sensei project or Sensei project content, including retrieving or checking
project configuration involving profiles, rules, or connectors, you should attend the request if possible.

Be a helpful and flexible chatbot. If they greet you, ask, "How can I help you?"
Conveniently change language depending on how the user talks to you.
If the information is insufficient, say so explicitly and avoid speculation.

Reference documentation:
"""


def _read_doc(path: Path) -> str:
    """Read a documentation file and return its stripped contents."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError, UnicodeDecodeError) as exc:  # pragma: no cover - defensive guard
        return f"(Unable to read {path.name}: {exc})"


def build_system_prompt(doc: str = "complete") -> str:
    """Build the system prompt from the DSL documentation files."""
    docs_dir = Path(__file__).resolve().parent.parent / "docs"
    sections = []

    if doc == "profiles":
        file_names = [_DOC_FILENAMES[2]]
    elif doc == "rules":
        file_names = _DOC_FILENAMES[0:1]
    else:
        file_names = _DOC_FILENAMES

    for name in file_names:
        doc_path = docs_dir / name
        content = _read_doc(doc_path)
        sections.append(f"### {name}\n{content}")

    joined_docs = "\n\n".join(sections)

    return f"{_SYSTEM_PROMPT}\n{joined_docs}"


SYSTEM_PROMPT: Final[str] = build_system_prompt()
SENSEI_PROFILES_SYSTEM_PROMPT: Final[str] = build_system_prompt("profiles")
SENSEI_RULES_SYSTEM_PROMPT: Final[str] = build_system_prompt("rules")

PROMPT_NODE_GUIDELINES: Final[str] = """
### Assistant Responsibilities
- You are the only node in the system: there is no intent router or downstream validator after your reply.
- Read the full conversation and decide what the user needs (new Sensei rule, new Sensei profile, fixes, or an explanation) and respond directly.
- When sharing Sensei PROFILES, RULES, or CONNECTORS return exactly one YAML document per code block inside ```yaml``` fences that follows the docs above.
- Keep answers concise and friendly; add a short lead-in before YAML when it helps, otherwise go straight to the code block.
- Politely decline unrelated requests and remind the user you only handle Sensei rules, profiles, connectors, and their documentation.
"""


def build_prompt_node_system_prompt(*contexts: str) -> str:
    """Compose the single-node system prompt with optional extra contexts."""
    sections = [SYSTEM_PROMPT, PROMPT_NODE_GUIDELINES.strip()]

    for context in contexts:
        trimmed = context.strip()
        if trimmed:
            sections.append(trimmed)

    return "\n\n".join(sections)
