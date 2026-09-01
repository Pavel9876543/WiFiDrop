from datetime import datetime, timedelta
from os import utime
from pathlib import Path

from app.core.logging import remove_expired_logs


def test_remove_expired_logs_only_removes_old_wifidrop_logs(tmp_path: Path) -> None:
    old_log = tmp_path / "wifidrop.log.2026-01-01"
    recent_log = tmp_path / "wifidrop.log"
    unrelated = tmp_path / "other.log"
    for path in (old_log, recent_log, unrelated):
        path.write_text("log", encoding="utf-8")

    old_timestamp = (datetime.now() - timedelta(days=40)).timestamp()
    utime(old_log, (old_timestamp, old_timestamp))

    assert remove_expired_logs(tmp_path, retention_days=30) == 1
    assert not old_log.exists()
    assert recent_log.exists()
    assert unrelated.exists()

