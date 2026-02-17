
from typing import Any


def escape_multiline_text(value: Any) -> Any:
    """
    Normalize and escape newlines in text for CSV export.
    - If ``value`` is not a string, it is returned unchanged.
    - Windows (``\\r\\n``) and classic Mac (``\\r``) newlines are first normalized
      to Unix-style newlines (``\\n``).
    - All actual newline characters (``\\n``) are then replaced with the literal
      two-character sequence ``"\\n"`` (backslash followed by ``n``).
    This is useful to avoid multi-line cells in CSV consumers such as Excel.
    Note that this transformation is not automatically reversible: when reading
    data back, you will receive the literal string ``"\\n"`` in place of
    original newline characters. If you need to restore real newlines, you must
    explicitly convert ``"\\n"`` sequences back to newline characters.
    """
    if not isinstance(value, str):
        return value
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")