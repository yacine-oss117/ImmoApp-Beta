from __future__ import annotations

from app.services.api_client_utils import compact_error_text


def test_compact_error_text_extracts_title_from_html() -> None:
    html = """
    <html>
      <head><title>AmbiguousColumn at /api/v1/matches/client/1/</title></head>
      <body><h1>Server Error (500)</h1></body>
    </html>
    """
    result = compact_error_text(html)
    assert "AmbiguousColumn" in result
    assert "<html>" not in result.lower()


def test_compact_error_text_truncates_long_plain_text() -> None:
    text = "x" * 500
    result = compact_error_text(text, max_len=32)
    assert len(result) <= 35
    assert result.endswith("...")
