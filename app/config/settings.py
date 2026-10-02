from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Validated runtime settings loaded from the project .env file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "WiFiDrop"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    upload_dir: Path = Path("Files")
    max_file_size_mb: int = Field(default=2048, ge=0)
    log_level: str = "INFO"
    log_dir: Path = Path("logs")
    log_retention_days: int = Field(default=30, ge=1)
    upload_chunk_size_kb: int = Field(default=1024, ge=64, le=16384)
    max_concurrent_uploads: int = Field(default=1, ge=1, le=32)
    upload_busy_retry_after_seconds: int = Field(default=5, ge=1, le=300)
    captive_portal_enabled: bool = True
    captive_portal_port: int = Field(default=80, ge=1, le=65535)
    captive_portal_public_url: str | None = None
    hotspot_enabled: bool = False
    auto_create_hotspot: bool = True
    connection_mode: Literal["hotspot", "router"] = "hotspot"
    router_ip: str | None = None
    local_name: str | None = None
    local_name_mode: Literal["mdns", "dns"] = "mdns"
    hotspot_ssid: str = "WiFiDrop"
    hotspot_password: str = "12347890"
    hotspot_gateway_ip: str = "192.168.50.1"

    @field_validator("router_ip")
    @classmethod
    def validate_router_ip(cls, value: str | None) -> str | None:
        from ipaddress import IPv4Address

        if value is None or not value.strip():
            return None
        address = IPv4Address(value.strip())
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError("ROUTER_IP must be a local interface IPv4 address")
        return str(address)

    @field_validator("local_name")
    @classmethod
    def validate_local_name(cls, value: str | None) -> str | None:
        from app.utils.local_name import normalize_local_name

        return normalize_local_name(value)

    @model_validator(mode="after")
    def validate_name_mode(self) -> "Settings":
        if self.local_name and self.local_name_mode == "mdns":
            name = self.local_name.removesuffix(".local")
            if "." in name:
                raise ValueError("Для mDNS введите одно имя; для DNS роутера выберите режим DNS")
            self.local_name = name
        return self

    @property
    def effective_hotspot_enabled(self) -> bool:
        return self.connection_mode == "hotspot" and self.hotspot_enabled

    @property
    def effective_captive_enabled(self) -> bool:
        return self.connection_mode == "hotspot" and (
            self.captive_portal_enabled or self.hotspot_enabled
        )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            msg = f"LOG_LEVEL must be one of: {', '.join(sorted(allowed))}"
            raise ValueError(msg)
        return normalized

    @field_validator("hotspot_ssid")
    @classmethod
    def validate_hotspot_ssid(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized.encode("utf-8")) > 32:
            raise ValueError("HOTSPOT_SSID must be 1-32 bytes")
        return normalized

    @field_validator("hotspot_password")
    @classmethod
    def validate_hotspot_password(cls, value: str) -> str:
        if not 8 <= len(value) <= 63:
            raise ValueError("HOTSPOT_PASSWORD must contain 8-63 characters")
        return value

    @field_validator("hotspot_gateway_ip")
    @classmethod
    def validate_hotspot_gateway_ip(cls, value: str) -> str:
        import ipaddress

        address = ipaddress.ip_address(value.strip())
        if address.version != 4 or not address.is_private:
            raise ValueError("HOTSPOT_GATEWAY_IP must be a private IPv4 address")
        return str(address)

    @field_validator("captive_portal_public_url")
    @classmethod
    def validate_captive_portal_public_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("CAPTIVE_PORTAL_PUBLIC_URL must start with http:// or https://")
        return normalized

    @field_validator("max_file_size_mb", mode="before")
    @classmethod
    def parse_max_file_size(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() in {"unlimited", "none"}:
            return 0
        return value

    @field_validator("upload_dir", "log_dir")
    @classmethod
    def resolve_project_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @property
    def max_file_size_bytes(self) -> int | None:
        if self.max_file_size_mb == 0:
            return None
        return self.max_file_size_mb * 1024 * 1024

    @property
    def upload_chunk_size_bytes(self) -> int:
        return self.upload_chunk_size_kb * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
