import pytest

from app.domain.files import FileCategory
from app.services.file_classifier import FileClassifier


@pytest.mark.parametrize(
    ("filename", "mime_type", "expected"),
    [
        ("portrait.HEIC", "application/octet-stream", FileCategory.IMAGES),
        ("movie.mkv", None, FileCategory.VIDEOS),
        ("track.flac", "application/octet-stream", FileCategory.MUSIC),
        ("contract.pdf", "application/octet-stream", FileCategory.DOCUMENTS),
        ("backup.7z", "application/octet-stream", FileCategory.ARCHIVES),
        ("disk.iso", None, FileCategory.ARCHIVES),
        ("application.apk", "application/vnd.android.package-archive", FileCategory.OTHER),
        ("no-extension", "image/png", FileCategory.IMAGES),
        ("unknown.bin", "application/octet-stream", FileCategory.OTHER),
    ],
)
def test_classification(
    filename: str,
    mime_type: str | None,
    expected: FileCategory,
) -> None:
    assert FileClassifier().classify(filename, mime_type) is expected


def test_extension_has_priority_over_incorrect_mime() -> None:
    assert FileClassifier().classify("photo.jpg", "audio/mpeg") is FileCategory.IMAGES

