from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            msg = f"LOG_LEVEL must be one of: {', '.join(sorted(allowed))}"
            raise ValueError(msg)
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
