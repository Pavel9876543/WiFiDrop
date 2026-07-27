from pathlib import Path

from app.services.upload_cleanup import remove_orphaned_uploads


def test_remove_orphaned_uploads_keeps_completed_files(tmp_path: Path) -> None:
    nested = tmp_path / "Images" / "2026-07-27"
    nested.mkdir(parents=True)
    orphaned = nested / ".upload-deadbeef.part"
    completed = nested / "photo.jpg"
    unrelated = nested / "custom.part"
    for path in (orphaned, completed, unrelated):
        path.write_bytes(b"data")

    assert remove_orphaned_uploads(tmp_path) == 1
    assert not orphaned.exists()
    assert completed.exists()
    assert unrelated.exists()

