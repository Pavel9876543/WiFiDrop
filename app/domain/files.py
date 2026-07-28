from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class StrEnum(str, Enum):
    """Совместимый аналог enum.StrEnum для Python 3.10."""

    def __str__(self) -> str:
        return self.value

class FileCategory(StrEnum):
    DOCUMENTS = "Documents"
    IMAGES = "Images"
    VIDEOS = "Videos"
    MUSIC = "Music"
    ARCHIVES = "Archives"
    OTHER = "Other"


@dataclass(frozen=True, slots=True)
class StoredFile:
    original_name: str
    saved_name: str
    category: FileCategory
    size: int
    relative_path: Path

