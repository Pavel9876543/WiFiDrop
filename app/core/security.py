import re
import unicodedata
from pathlib import Path

from app.core.exceptions import UnsafeFilenameError

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
INVALID_WINDOWS_CHARACTERS = re.compile(r'[<>:"/\\|?*]')
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
MAX_FILENAME_LENGTH = 240


def sanitize_filename(filename: str | None) -> str:
    if not filename:
        raise UnsafeFilenameError("Не удалось определить имя файла.")

    normalized = unicodedata.normalize("NFKC", filename).strip()
    if "/" in normalized or "\\" in normalized:
        raise UnsafeFilenameError("Имя файла содержит недопустимый путь.")
    if normalized in {".", ".."} or CONTROL_CHARACTERS.search(normalized):
        raise UnsafeFilenameError("Имя файла содержит недопустимые символы.")

    sanitized = INVALID_WINDOWS_CHARACTERS.sub("_", normalized).rstrip(". ")
    if not sanitized:
        raise UnsafeFilenameError("Имя файла стало пустым после проверки.")

    path = Path(sanitized)
    if path.stem.upper() in WINDOWS_RESERVED_NAMES:
        sanitized = f"_{sanitized}"

    if len(sanitized) > MAX_FILENAME_LENGTH:
        suffix = Path(sanitized).suffix[:20]
        stem_limit = MAX_FILENAME_LENGTH - len(suffix)
        sanitized = f"{Path(sanitized).stem[:stem_limit]}{suffix}"

    return sanitized


def ensure_within_directory(candidate: Path, parent: Path) -> Path:
    resolved_parent = parent.resolve()
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_parent):
        raise UnsafeFilenameError("Недопустимый путь сохранения файла.")
    return resolved_candidate

