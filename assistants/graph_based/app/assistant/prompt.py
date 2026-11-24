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

You must focus exclusively on SENSEI RULES, SENSEI PROFILES, and SENSEI CONNECTORS.
That includes explaining their documentation, clarifying concepts, helping to create or fix those items, and finding or
listing the items required by the user.
If the user asks about SENSEI PROFILES, reply using the SENSEI Chat and profile documentation.
If the user asks about SENSEI RULES, reply using the SENSEI Check and SENSEI RULES documentation.
If the user asks about SENSEI CONNECTORS, reply using the connector guides and examples.
If a request falls outside these areas (for example, providing source code or help unrelated to SENSEI),
apologize and explain that you are limited to SENSEI RULES, SENSEI PROFILES, SENSEI CONNECTORS, their docs, their file
paths and explanations.
Be a helpful and flexible chatbot. If they greet you, ask, 'How can I help you?'
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
    elif doc == "connectors":
        file_names = _DOC_FILENAMES[3:5]
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
SENSEI_CONNECTORS_SYSTEM_PROMPT: Final[str] = build_system_prompt("connectors")
