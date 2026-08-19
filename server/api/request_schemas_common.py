"""
Common validation helpers and patterns for API request schemas.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from rest_framework import serializers

# Regex patterns for allow-list validation (no blacklists)
PHONE_PATTERN = re.compile(r"^[\+]?[1-9][\d\s\-\(\)]{7,15}$")
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
NAME_PATTERN = re.compile(r"^[^\x00-\x1F\x7F<>]+$", re.UNICODE)
SHORT_TEXT_PATTERN = re.compile(r"^[^\x00-\x1F\x7F<>]+$", re.UNICODE)
LOCATION_PATTERN = re.compile(r"^[^\x00-\x1F\x7F<>]+$", re.UNICODE)
TAG_PATTERN = re.compile(r"^[^\x00-\x1F\x7F<>]+$", re.UNICODE)


def _strip_control(text: str) -> str:
    if not text:
        return ""
    return CONTROL_CHARS_PATTERN.sub("", text)


def validate_phone_format(phone: str) -> bool:
    """Validate phone number format."""
    if not phone:
        return True
    return bool(PHONE_PATTERN.match(phone))


def validate_email_format(email: str) -> bool:
    """Validate email format."""
    if not email:
        return True
    return bool(EMAIL_PATTERN.match(email))


def validate_url_format(url: str) -> bool:
    """Validate URL format."""
    if not url:
        return True
    validator = URLValidator()
    try:
        validator(url)
        return True
    except DjangoValidationError:
        return False


def validate_alphanumeric_only(value: str) -> bool:
    """Validate that input contains only alphanumeric characters and safe symbols."""
    if not value:
        return True
    return bool(NAME_PATTERN.match(value))


def validate_allowlist(value: str, pattern: re.Pattern[str], field: str) -> str:
    text = _strip_control(str(value or "")).strip()
    if text and not pattern.match(text):
        raise serializers.ValidationError(f"{field} contains invalid characters")
    return text


def validate_printable_text(value: str, field: str) -> str:
    text = _strip_control(str(value or "")).strip()
    if CONTROL_CHARS_PATTERN.search(text):
        raise serializers.ValidationError(f"{field} contains invalid characters")
    return text


def validate_template_text(value: str, field: str) -> str:
    text = _strip_control(str(value or ""))
    if "<" in text or ">" in text:
        raise serializers.ValidationError(f"{field} cannot include angle brackets")
    return text.strip()


__all__ = [
    "PHONE_PATTERN",
    "EMAIL_PATTERN",
    "CONTROL_CHARS_PATTERN",
    "NAME_PATTERN",
    "SHORT_TEXT_PATTERN",
    "LOCATION_PATTERN",
    "TAG_PATTERN",
    "validate_phone_format",
    "validate_email_format",
    "validate_url_format",
    "validate_alphanumeric_only",
    "validate_allowlist",
    "validate_printable_text",
    "validate_template_text",
]
