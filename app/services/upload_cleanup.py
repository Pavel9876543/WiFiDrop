import logging
from pathlib import Path


logger = logging.getLogger("wifidrop.uploads")


def remove_orphaned_uploads(upload_root: Path) -> int:
    """Remove temporary uploads left by a forced process termination."""
    removed = 0
    if not upload_root.exists():
        return removed

    for temporary_file in upload_root.rglob(".upload-*.part"):
        try:
            if temporary_file.is_file():
                temporary_file.unlink()
                removed += 1
        except OSError:
            logger.warning("Could not remove orphaned upload: %s", temporary_file, exc_info=True)

    if removed:
        logger.warning("Removed %s orphaned partial upload(s) during startup", removed)
    return removed

