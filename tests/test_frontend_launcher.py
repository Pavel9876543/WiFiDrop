from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_drop_zone_prefers_show_picker_with_click_fallback() -> None:
    source = (ROOT / "app/static/js/drop-zone.js").read_text(encoding="utf-8")
    assert "fileInput.showPicker()" in source
    assert "fileInput.click()" in source
    assert "browseButton.contains(event.target)" not in source


def test_gui_launcher_installs_missing_dependencies() -> None:
    source = (ROOT / "run_gui.bat").read_text(encoding="utf-8")
    assert "-m ensurepip --upgrade" in source
    assert "-m pip install --disable-pip-version-check -r" in source
    assert "import PyQt6, aiofiles, fastapi" in source
