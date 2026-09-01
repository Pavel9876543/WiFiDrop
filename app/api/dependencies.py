from functools import lru_cache

from app.config.settings import get_settings
from app.services.file_classifier import FileClassifier
from app.services.upload_manager import UploadManager


@lru_cache(maxsize=1)
def get_upload_manager() -> UploadManager:
    settings = get_settings()
    return UploadManager(
        upload_root=settings.upload_dir,
        max_file_size_bytes=settings.max_file_size_bytes,
        chunk_size_bytes=settings.upload_chunk_size_bytes,
        classifier=FileClassifier(),
    )

