def sanitize_run_dir(raw_run_dir: str) -> str:
    normalized = (raw_run_dir or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    marker = "/out/"
    marker_index = normalized.lower().find(marker)
    if marker_index >= 0:
        return normalized[marker_index + 1 :]
    if normalized.startswith("out/"):
        return normalized
    return ""
