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


def test_hotspot_settings_validation() -> None:
    settings = Settings(
        _env_file=None,
        hotspot_enabled=True,
        hotspot_ssid="WiFiDrop",
        hotspot_password="12345678",
        hotspot_gateway_ip="192.168.50.1",
    )
    assert settings.hotspot_enabled is True
    assert settings.hotspot_gateway_ip == "192.168.50.1"
