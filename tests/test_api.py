import asyncio
from datetime import date
from pathlib import Path

import pytest

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_upload_manager
from app.config.settings import Settings
from app.domain.files import FileCategory, StoredFile
from app.main import create_app
from app.services.file_classifier import FileClassifier
from app.services.upload_manager import UploadManager


def create_test_client(tmp_path: Path, max_size: int = 1024) -> TestClient:
    application = create_app()
    manager = UploadManager(
        upload_root=tmp_path,
        max_file_size_bytes=max_size,
        chunk_size_bytes=4,
        classifier=FileClassifier(),
        date_provider=lambda: date(2026, 7, 27),
    )
    application.dependency_overrides[get_upload_manager] = lambda: manager
    return TestClient(application)


def test_home_page_and_health(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        page = client.get("/")
        health = client.get("/api/health")
        service_worker = client.get("/service-worker.js")

    assert page.status_code == 200
    assert "WiFiDrop" in page.text
    assert 'rel="manifest"' in page.text
    assert 'id="install-app-button"' in page.text
    assert 'id="file-input" type="file" multiple hidden' in page.text
    assert 'for="file-input"' in page.text
    assert health.json() == {"status": "ok"}
    assert service_worker.status_code == 200
    assert service_worker.headers["service-worker-allowed"] == "/"
    assert "wifidrop-shell" in service_worker.text



def test_captive_home_shows_open_in_browser_action(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        captive_page = client.get("/?captive=1")
        normal_page = client.get("/")

    assert captive_page.status_code == 200
    assert 'id="open-browser-button"' in captive_page.text
    assert 'rel="external noopener noreferrer"' in captive_page.text
    assert 'id="android-browser-chooser"' in captive_page.text
    assert 'id="copy-browser-url"' in captive_page.text
    assert 'aria-label="Загрузка файлов" hidden' in captive_page.text
    assert 'id="open-browser-button"' not in normal_page.text


def test_upload_endpoint(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.post(
            "/api/uploads",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    assert payload["file"]["category"] == "Documents"
    assert payload["file"]["relative_path"] == "Documents/2026-07-27/notes.txt"


def test_home_page_shows_unlimited_file_size(tmp_path: Path, monkeypatch) -> None:
    unlimited_settings = Settings(_env_file=None, max_file_size_mb=0)
    monkeypatch.setattr("app.api.routes.pages.get_settings", lambda: unlimited_settings)

    with create_test_client(tmp_path) as client:
        page = client.get("/")

    assert 'data-max-file-size-mb="unlimited"' in page.text
    assert "Без ограничения размера" in page.text


def test_invalid_upload_has_safe_error(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.post("/api/uploads", content=b"broken")

    assert response.status_code == 422
    assert response.json() == {
        "success": False,
        "error": "invalid_request",
        "message": "Запрос повреждён или не содержит файл.",
    }
    assert "traceback" not in response.text.lower()


def test_oversized_upload_returns_413(tmp_path: Path) -> None:
    with create_test_client(tmp_path, max_size=3) as client:
        response = client.post(
            "/api/uploads",
            files={"file": ("large.bin", b"1234", "application/octet-stream")},
        )

    assert response.status_code == 413
    assert response.json()["error"] == "file_too_large"


def test_captive_portal_probe_redirects_to_wifidrop(tmp_path: Path, monkeypatch) -> None:
    portal_settings = Settings(_env_file=None, port=8000)
    monkeypatch.setattr("app.api.routes.captive_portal.get_settings", lambda: portal_settings)
    monkeypatch.setattr(
        "app.api.routes.captive_portal.get_preferred_local_ipv4_address",
        lambda: "192.168.1.42",
    )

    with create_test_client(tmp_path) as client:
        response = client.get("/generate_204", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "http://192.168.1.42:8000/?captive=1"
    assert response.headers["cache-control"] == "no-store"


def test_captive_portal_api_reports_portal_url(tmp_path: Path, monkeypatch) -> None:
    portal_settings = Settings(
        _env_file=None,
        port=8000,
        captive_portal_public_url="http://192.168.4.1:8000",
    )
    monkeypatch.setattr("app.api.routes.captive_portal.get_settings", lambda: portal_settings)

    with create_test_client(tmp_path) as client:
        response = client.get("/.well-known/captive-portal")

    assert response.status_code == 200
    assert response.json() == {
        "captive": True,
        "user-portal-url": "http://192.168.4.1:8000/?captive=1",
    }


@pytest.mark.asyncio
async def test_concurrent_upload_is_rejected_while_other_routes_stay_available() -> None:
    class BlockingUploadManager:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def store(self, upload: object, client_ip: str) -> StoredFile:
            del upload, client_ip
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return StoredFile(
                original_name="first.txt",
                saved_name="first.txt",
                category=FileCategory.DOCUMENTS,
                size=5,
                relative_path=Path("Documents/2026-07-27/first.txt"),
            )

    application = create_app()
    manager = BlockingUploadManager()
    application.dependency_overrides[get_upload_manager] = lambda: manager
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_upload = asyncio.create_task(
            client.post(
                "/api/uploads",
                files={"file": ("first.txt", b"first", "text/plain")},
            )
        )
        await asyncio.wait_for(manager.started.wait(), timeout=1)
        try:
            busy_response = await client.post(
                "/api/uploads",
                files={"file": ("second.txt", b"second", "text/plain")},
            )
            health_response = await client.get("/api/health")
        finally:
            manager.release.set()
        first_response = await first_upload

    assert first_response.status_code == 201
    assert busy_response.status_code == 503
    assert busy_response.headers["retry-after"].isdigit()
    assert busy_response.json() == {
        "success": False,
        "error": "server_busy",
        "message": (
            "Сервер занят другой загрузкой. Подождите немного "
            "и повторите отправку позже."
        ),
    }
    assert health_response.status_code == 200
    assert manager.calls == 1


@pytest.mark.asyncio
async def test_cancelled_request_releases_upload_slot() -> None:
    class CancelOnceUploadManager:
        def __init__(self) -> None:
            self.first_started = asyncio.Event()
            self.never_release_first = asyncio.Event()
            self.calls = 0

        async def store(self, upload: object, client_ip: str) -> StoredFile:
            del upload, client_ip
            self.calls += 1
            if self.calls == 1:
                self.first_started.set()
                await self.never_release_first.wait()
            return StoredFile(
                original_name="saved.txt",
                saved_name="saved.txt",
                category=FileCategory.DOCUMENTS,
                size=5,
                relative_path=Path("Documents/2026-07-27/saved.txt"),
            )

    application = create_app()
    manager = CancelOnceUploadManager()
    application.dependency_overrides[get_upload_manager] = lambda: manager
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        cancelled_upload = asyncio.create_task(
            client.post(
                "/api/uploads",
                files={"file": ("cancelled.txt", b"first", "text/plain")},
            )
        )
        await asyncio.wait_for(manager.first_started.wait(), timeout=1)
        cancelled_upload.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_upload

        next_response = await client.post(
            "/api/uploads",
            files={"file": ("saved.txt", b"saved", "text/plain")},
        )

    assert next_response.status_code == 201
    assert manager.calls == 2
