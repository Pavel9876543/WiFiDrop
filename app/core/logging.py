import logging
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.config.settings import Settings


LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def remove_expired_logs(log_dir: Path, retention_days: int) -> int:
    cutoff = datetime.now().timestamp() - timedelta(days=retention_days).total_seconds()
    removed = 0

    for log_file in log_dir.glob("wifidrop.log*"):
        try:
            if log_file.is_file() and log_file.stat().st_mtime < cutoff:
                log_file.unlink()
                removed += 1
        except OSError:
            logging.getLogger(__name__).warning(
                "Could not remove expired log file: %s", log_file, exc_info=True
            )

    return removed


def configure_logging(settings: Settings) -> logging.Logger:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    remove_expired_logs(settings.log_dir, settings.log_retention_days)

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)
    root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = TimedRotatingFileHandler(
        filename=settings.log_dir / "wifidrop.log",
        when="midnight",
        backupCount=settings.log_retention_days,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    return logging.getLogger("wifidrop")

