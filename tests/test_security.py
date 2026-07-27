from pathlib import Path

import pytest

from app.core.exceptions import UnsafeFilenameError
from app.core.security import ensure_within_directory, sanitize_filename


@pytest.mark.parametrize("filename", ["../secret.txt", "..\\secret.txt", "folder/file.txt"])
def test_sanitize_filename_rejects_paths(filename: str) -> None:
    with pytest.raises(UnsafeFilenameError):
        sanitize_filename(filename)


@pytest.mark.parametrize("filename", ["", "..", ".", "bad\x00name.txt"])
def test_sanitize_filename_rejects_invalid_names(filename: str) -> None:
    with pytest.raises(UnsafeFilenameError):
        sanitize_filename(filename)


def test_sanitize_filename_handles_windows_names() -> None:
    assert sanitize_filename("CON.txt") == "_CON.txt"
    assert sanitize_filename("report?.pdf") == "report_.pdf"
    assert sanitize_filename("photo.jpg. ") == "photo.jpg"


def test_ensure_within_directory_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(UnsafeFilenameError):
        ensure_within_directory(tmp_path / ".." / "escape.txt", tmp_path)

