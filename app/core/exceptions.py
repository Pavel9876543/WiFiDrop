class WiFiDropError(Exception):
    """Base class for errors safe to translate into a client response."""

    status_code = 400
    error_code = "wifidrop_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class UnsafeFilenameError(WiFiDropError):
    error_code = "unsafe_filename"


class FileTooLargeError(WiFiDropError):
    status_code = 413
    error_code = "file_too_large"


class FileStorageError(WiFiDropError):
    status_code = 500
    error_code = "storage_error"
