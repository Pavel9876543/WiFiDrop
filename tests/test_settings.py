import pytest
from pydantic import ValidationError

from app.config.settings import Settings


@pytest.mark.parametrize("value", [0, "0", "unlimited", "UNLIMITED", "none"])
def test_zero_and_aliases_disable_file_size_limit(value: int | str) -> None:
    settings = Settings(_env_file=None, max_file_size_mb=value)

    assert settings.max_file_size_mb == 0
    assert settings.max_file_size_bytes is None


def test_positive_file_size_limit_is_converted_to_bytes() -> None:
    settings = Settings(_env_file=None, max_file_size_mb=64)

    assert settings.max_file_size_bytes == 64 * 1024 * 1024


def test_negative_file_size_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_file_size_mb=-1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_concurrent_uploads", 0),
        ("max_concurrent_uploads", 33),
        ("upload_busy_retry_after_seconds", 0),
        ("upload_busy_retry_after_seconds", 301),
    ],
)
def test_upload_capacity_settings_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
