from __future__ import annotations

import json
from pathlib import Path


def _encode_env_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if not text:
        return ""
    safe = all(character not in text for character in " \t\r\n#=\"'")
    return text if safe else json.dumps(text, ensure_ascii=False)


def update_env_file(path: Path, values: dict[str, object]) -> None:
    """Update selected keys in a dotenv file without destroying comments/order."""
    normalized = {key.upper(): _encode_env_value(value) for key, value in values.items()}
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    seen: set[str] = set()
    output: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(line)
            continue
        key = stripped.split("=", 1)[0].strip().upper()
        if key not in normalized:
            output.append(line)
            continue
        output.append(f"{key}={normalized[key]}")
        seen.add(key)

    missing = [key for key in normalized if key not in seen]
    if missing and output and output[-1] != "":
        output.append("")
    output.extend(f"{key}={normalized[key]}" for key in missing)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
