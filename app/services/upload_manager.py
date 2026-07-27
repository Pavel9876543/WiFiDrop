import asyncio
import logging
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import UploadFile

from app.core.exceptions import FileStorageError, FileTooLargeError
from app.core.security import ensure_within_directory, sanitize_filename
from app.domain.files import StoredFile
from app.services.file_classifier import FileClassifier


logger = logging.getLogger("wifidrop.uploads")


class UploadManager:
    def __init__(
        self,
        upload_root: Path,
        max_file_size_bytes: int,
        chunk_size_bytes: int,
        classifier: FileClassifier,
        date_provider: Callable[[], date] = date.today,
    ) -> None:
        self._upload_root = upload_root.resolve()
        self._max_file_size_bytes = max_file_size_bytes
        self._chunk_size_bytes = chunk_size_bytes
        self._classifier = classifier
        self._date_provider = date_provider
        self._finalize_lock = asyncio.Lock()

    async def store(self, upload: UploadFile, client_ip: str) -> StoredFile:
        original_name = upload.filename or ""
        safe_name = sanitize_filename(original_name)
        category = self._classifier.classify(safe_name, upload.content_type)
        date_folder = self._date_provider().isoformat()
        destination_dir = ensure_within_directory(
            self._upload_root / category.value / date_folder,
            self._upload_root,
        )
        await asyncio.to_thread(destination_dir.mkdir, parents=True, exist_ok=True)

        temporary_path = ensure_within_directory(
            destination_dir / f".upload-{uuid4().hex}.part",
            self._upload_root,
        )
        total_size = 0

        try:
            async with aiofiles.open(temporary_path, "xb") as destination:
                while chunk := await upload.read(self._chunk_size_bytes):
                    total_size += len(chunk)
                    if total_size > self._max_file_size_bytes:
                        raise FileTooLargeError(
                            "Файл превышает разрешённый размер "
                            f"({self._max_file_size_bytes // (1024 * 1024)} МБ)."
                        )
                    await destination.write(chunk)
                await destination.flush()

            final_path = await self._finalize(temporary_path, destination_dir, safe_name)
        except FileTooLargeError:
            await self._remove_partial_file(temporary_path)
            logger.warning("Upload rejected from %s: %s", client_ip, original_name)
            raise
        except Exception as error:
            await self._remove_partial_file(temporary_path)
            logger.exception("Failed to store upload from %s: %s", client_ip, original_name)
            raise FileStorageError(
                "Не удалось сохранить файл. Проверьте свободное место и права на папку."
            ) from error

        relative_path = final_path.relative_to(self._upload_root)
        logger.info(
            "Upload completed | client=%s | file=%s | saved=%s | size=%s | category=%s",
            client_ip,
            original_name,
            relative_path,
            total_size,
            category.value,
        )
        return StoredFile(
            original_name=original_name,
            saved_name=final_path.name,
            category=category,
            size=total_size,
            relative_path=relative_path,
        )

    async def _finalize(
        self,
        temporary_path: Path,
        destination_dir: Path,
        safe_name: str,
    ) -> Path:
        async with self._finalize_lock:
            final_path = self._available_path(destination_dir, safe_name)
            await asyncio.to_thread(os.replace, temporary_path, final_path)
            return final_path

    @staticmethod
    def _available_path(destination_dir: Path, filename: str) -> Path:
        candidate = destination_dir / filename
        if not candidate.exists():
            return candidate

        path = Path(filename)
        counter = 1
        while True:
            candidate = destination_dir / f"{path.stem} ({counter}){path.suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    async def _remove_partial_file(path: Path) -> None:
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError:
            logger.warning("Could not remove partial upload: %s", path, exc_info=True)
