from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_drop_zone_prefers_show_picker_with_click_fallback() -> None:
    source = (ROOT / "app/static/js/drop-zone.js").read_text(encoding="utf-8")
    assert "fileInput.showPicker()" in source
    assert "fileInput.click()" in source
    assert "browseButton.contains(event.target)" in source
    assert "browseButton.addEventListener(\"keydown\"" in source


def test_gui_launcher_installs_missing_dependencies() -> None:
    source = (ROOT / "run_gui.bat").read_text(encoding="utf-8")
    assert "-m ensurepip --upgrade" in source
    assert "-m pip install --disable-pip-version-check -r" in source
    assert "import PyQt6, aiofiles, fastapi" in source


def test_frontend_assets_are_versioned_and_service_worker_is_network_only() -> None:
    template = (ROOT / "app/templates/index.html").read_text(encoding="utf-8")
    app_source = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    service_worker = (ROOT / "app/static/js/service-worker.js").read_text(encoding="utf-8")

    assert "/js/app.js') }}?v=14" in template
    assert "/css/components.css') }}?v=14" in template
    assert 'from "./drop-zone.js?v=14";' in app_source
    assert 'from "./queue-state.js?v=14";' in app_source
    assert 'event.respondWith(fetch(request));' in service_worker
    assert "cache.addAll" not in service_worker
    assert "networkFirst" not in service_worker
