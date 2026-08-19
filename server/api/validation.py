"""
Request validation helpers for DRF views with enhanced security.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

from rest_framework import status
from rest_framework.response import Response
from rest_framework.serializers import Serializer

from .view_helpers import error

_S = TypeVar("_S", bound=Serializer)


def validate_payload(
    data: Mapping[str, object] | None,
    serializer_cls: type[_S],
    *,
    partial: bool = False,
    require_row_version: bool = False,
) -> tuple[dict[str, object] | None, Response | None]:
    """Validate request payload using a DRF serializer."""
    serializer = serializer_cls(data=data or {}, partial=partial)
    if not serializer.is_valid():
        return None, error(
            "Validation failed",
            status.HTTP_400_BAD_REQUEST,
            errors=serializer.errors,
        )
    validated = dict(serializer.validated_data)
    if require_row_version and validated.get("row_version") is None:
        return None, error(
            "Validation failed",
            status.HTTP_400_BAD_REQUEST,
            errors={"row_version": ["required"]},
        )
    return validated, None
