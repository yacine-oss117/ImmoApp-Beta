"""Template rendering helpers for WhatsApp messages."""

from __future__ import annotations

from collections.abc import Mapping


def render_template(template: str, context: Mapping[str, object]) -> str:
    """
    Replace placeholders in template with actual values.

    Args:
        template: Template text with {placeholder} markers
        context: Dictionary mapping placeholder names to values

    Returns:
        Rendered message text
    """
    result = template
    for key, value in context.items():
        placeholder = "{" + key + "}"
        result = result.replace(placeholder, str(value) if value else "")
    return result
