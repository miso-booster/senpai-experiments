
from typing import Any


def escape_multiline_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")