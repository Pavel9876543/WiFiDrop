import mimetypes
from pathlib import Path

from app.domain.files import FileCategory


class FileClassifier:
    """Classifies a file using both its declared MIME type and extension."""

    _extension_categories: dict[FileCategory, frozenset[str]] = {
        FileCategory.DOCUMENTS: frozenset(
            {
                ".csv", ".doc", ".docm", ".docx", ".epub", ".md", ".odg", ".odp",
                ".ods", ".odt", ".pdf", ".ppt", ".pptm", ".pptx", ".rtf", ".tex",
                ".tsv", ".txt", ".xls", ".xlsb", ".xlsm", ".xlsx", ".xml",
            }
        ),
        FileCategory.IMAGES: frozenset(
            {
                ".avif", ".bmp", ".gif", ".heic", ".heif", ".ico", ".jpeg", ".jpg",
                ".png", ".raw", ".svg", ".tif", ".tiff", ".webp",
            }
        ),
        FileCategory.VIDEOS: frozenset(
            {
                ".3gp", ".avi", ".flv", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4",
                ".mpeg", ".mpg", ".mts", ".webm", ".wmv",
            }
        ),
        FileCategory.MUSIC: frozenset(
            {
                ".aac", ".aiff", ".alac", ".amr", ".flac", ".m4a", ".mid", ".midi",
                ".mp3", ".ogg", ".opus", ".wav", ".wma",
            }
        ),
        FileCategory.ARCHIVES: frozenset(
            {
                ".7z", ".bz2", ".cab", ".gz", ".img", ".iso", ".rar", ".tar",
                ".tgz", ".xz", ".zip",
            }
        ),
    }

    def classify(self, filename: str, declared_mime_type: str | None) -> FileCategory:
        extension = Path(filename).suffix.lower()
        mime_type = self._normalize_mime_type(declared_mime_type)

        for category, extensions in self._extension_categories.items():
            if extension in extensions:
                return category

        if mime_type.startswith("image/"):
            return FileCategory.IMAGES
        if mime_type.startswith("video/"):
            return FileCategory.VIDEOS
        if mime_type.startswith("audio/"):
            return FileCategory.MUSIC
        if mime_type.startswith("text/") or mime_type in {
            "application/pdf",
            "application/rtf",
            "application/msword",
            "application/vnd.ms-excel",
            "application/vnd.ms-powerpoint",
            "application/vnd.oasis.opendocument.text",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }:
            return FileCategory.DOCUMENTS
        if mime_type in {
            "application/gzip",
            "application/vnd.rar",
            "application/x-7z-compressed",
            "application/x-bzip2",
            "application/x-tar",
            "application/zip",
        }:
            return FileCategory.ARCHIVES
        return FileCategory.OTHER

    @staticmethod
    def _normalize_mime_type(declared_mime_type: str | None) -> str:
        if declared_mime_type and declared_mime_type != "application/octet-stream":
            return declared_mime_type.partition(";")[0].strip().lower()
        return ""

    def guessed_mime_type(self, filename: str) -> str:
        return mimetypes.guess_type(filename)[0] or "application/octet-stream"

