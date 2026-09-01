import asyncio
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.core.exceptions import FileTooLargeError
from app.services.file_classifier import FileClassifier
from app.services.upload_manager import UploadManager


def build_manager(tmp_path: Path, max_size: int | None = 1024) -> UploadManager:
    return UploadManager(
        upload_root=tmp_path,
        max_file_size_bytes=max_size,
        chunk_size_bytes=4,
        classifier=FileClassifier(),
        date_provider=lambda: date(2026, 7, 27),
    )


@pytest.mark.asyncio
async def test_store_classifies_and_writes_file(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    upload = UploadFile(filename="photo.jpg", file=BytesIO(b"image-content"))

    stored = await manager.store(upload, "192.168.1.20")

    assert stored.relative_path == Path("Images/2026-07-27/photo.jpg")
    assert (tmp_path / stored.relative_path).read_bytes() == b"image-content"


@pytest.mark.asyncio
async def test_store_generates_unique_name(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)

    first = await manager.store(
        UploadFile(filename="report.pdf", file=BytesIO(b"first")),
        "192.168.1.20",
    )
    second = await manager.store(
        UploadFile(filename="report.pdf", file=BytesIO(b"second")),
        "192.168.1.20",
    )

    assert first.saved_name == "report.pdf"
    assert second.saved_name == "report (1).pdf"
    assert (tmp_path / first.relative_path).read_bytes() == b"first"
    assert (tmp_path / second.relative_path).read_bytes() == b"second"


@pytest.mark.asyncio
async def test_oversized_upload_is_removed(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, max_size=5)
    upload = UploadFile(filename="large.zip", file=BytesIO(b"too-large"))

    with pytest.raises(FileTooLargeError):
        await manager.store(upload, "192.168.1.20")

    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("large.zip"))


@pytest.mark.asyncio
async def test_empty_upload_is_stored(tmp_path: Path) -> None:
    manager = build_manager(tmp_path)
    upload = UploadFile(filename="empty.txt", file=BytesIO())

    stored = await manager.store(upload, "192.168.1.20")

    assert stored.size == 0
    assert (tmp_path / stored.relative_path).read_bytes() == b""


@pytest.mark.asyncio
async def test_unlimited_upload_is_stored(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, max_size=None)
    content = b"large-content" * 1024
    upload = UploadFile(filename="unlimited.bin", file=BytesIO(content))

    stored = await manager.store(upload, "192.168.1.20")

    assert stored.size == len(content)
    assert (tmp_path / stored.relative_path).read_bytes() == content


@pytest.mark.asyncio
async def test_cancelled_upload_removes_partial_file(tmp_path: Path) -> None:
    class CancellableUpload:
        filename = "cancelled.bin"
        content_type = "application/octet-stream"

        def __init__(self) -> None:
            self.read_count = 0
            self.waiting_for_more_data = asyncio.Event()

        async def read(self, _: int) -> bytes:
            self.read_count += 1
            if self.read_count == 1:
                return b"partial"
            self.waiting_for_more_data.set()
            await asyncio.Event().wait()
            return b""

    manager = build_manager(tmp_path)
    upload = CancellableUpload()
    task = asyncio.create_task(manager.store(upload, "192.168.1.20"))  # type: ignore[arg-type]
    await upload.waiting_for_more_data.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("cancelled.bin"))
