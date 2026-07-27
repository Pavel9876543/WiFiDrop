from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


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

