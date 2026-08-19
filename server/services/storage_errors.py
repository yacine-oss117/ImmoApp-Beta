"""Storage error types."""

from __future__ import annotations


class StorageError(RuntimeError):
    """Raised for storage operation failures."""


class StorageNotReadyError(StorageError):
    """Raised when storage is temporarily unavailable or still warming up."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "IMPORT_STORAGE_NOT_READY",
        retry_after_ms: int = 1500,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "IMPORT_STORAGE_NOT_READY")
        self.retry_after_ms = max(250, int(retry_after_ms or 1500))
