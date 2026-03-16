import re

import pandas as pd


def prompt_sort_key(value: object) -> tuple[int, str]:
    text = "" if value is None else str(value).strip().lower()
    match = re.fullmatch(r"p(\d+)(?:_(.+))?", text)
    if not match:
        return (10**9, text)
    return (int(match.group(1)), text)


def to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y", "x"}
