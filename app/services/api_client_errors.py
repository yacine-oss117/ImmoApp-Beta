"""API client error types."""

from __future__ import annotations


class ApiError(RuntimeError):
    """Exception raised when an API request fails with an error status code."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        code: str | None = None,
        payload: object | None = None,
    ) -> None:
        super().__init__(f"API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.code = code
        self.payload = payload
