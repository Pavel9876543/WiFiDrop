from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.dependencies import get_upload_manager
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

    assert page.status_code == 200
    assert "WiFiDrop" in page.text
    assert health.json() == {"status": "ok"}


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

