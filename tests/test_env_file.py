from pathlib import Path

from app.config.env_file import update_env_file


def test_update_env_file_preserves_comments_and_unknown_values(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# header\nAPP_NAME=Old\nUNKNOWN=keep\nPORT=8000\n", encoding="utf-8")

    update_env_file(env, {"APP_NAME": "WiFi Drop", "PORT": 9000, "NEW_FLAG": True})

    text = env.read_text(encoding="utf-8")
    assert "# header" in text
    assert 'APP_NAME="WiFi Drop"' in text
    assert "UNKNOWN=keep" in text
    assert "PORT=9000" in text
    assert "NEW_FLAG=true" in text
