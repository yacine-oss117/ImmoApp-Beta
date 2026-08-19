"""
Tests for ImportValidator - input sanitization and validation.
"""

import pytest

from core.importer.validation import ImportValidationError, ImportValidator


class TestSanitizeString:
    """Tests for sanitize_string method."""

    def test_basic_string(self) -> None:
        """Test basic string sanitization."""
        result = ImportValidator.sanitize_string("Hello World")
        assert result == "Hello World"

    def test_strips_whitespace(self) -> None:
        """Test whitespace stripping."""
        result = ImportValidator.sanitize_string("  hello  ")
        assert result == "hello"

    def test_empty_allowed_by_default(self) -> None:
        """Test empty values allowed by default."""
        assert ImportValidator.sanitize_string("") == ""
        assert ImportValidator.sanitize_string(None) == ""

    def test_empty_not_allowed(self) -> None:
        """Test empty values rejected when not allowed."""
        with pytest.raises(ImportValidationError) as exc:
            ImportValidator.sanitize_string("", "field", allow_empty=False)
        assert exc.value.field == "field"
        assert "cannot be empty" in exc.value.message

    def test_max_length_enforced(self) -> None:
        """Test max length enforcement."""
        with pytest.raises(ImportValidationError) as exc:
            ImportValidator.sanitize_string("x" * 600, "field", max_length=500)
        assert "exceeds maximum length" in exc.value.message

    def test_sql_comment_rejected(self) -> None:
        """Test SQL comment patterns rejected."""
        with pytest.raises(ImportValidationError):
            ImportValidator.sanitize_string("test -- drop table")

    def test_sql_block_comment_rejected(self) -> None:
        """Test SQL block comment rejected."""
        with pytest.raises(ImportValidationError):
            ImportValidator.sanitize_string("test /* comment */")

    def test_sql_keywords_rejected(self) -> None:
        """Test SQL keywords rejected."""
        dangerous_inputs = [
            "SELECT * FROM users",
            "test; DROP TABLE clients;",
            "test UNION SELECT",
            "1 OR 1=1",
        ]
        for inp in dangerous_inputs:
            with pytest.raises(ImportValidationError):
                ImportValidator.sanitize_string(inp, "field")

    def test_control_chars_stripped(self) -> None:
        """Test control characters are stripped."""
        result = ImportValidator.sanitize_string("test\x00\x0bvalue")
        assert result == "testvalue"

    def test_arabic_text_allowed(self) -> None:
        """Test Arabic text is not stripped."""
        result = ImportValidator.sanitize_string("الجزائر")
        assert result == "الجزائر"

    def test_french_accents_allowed(self) -> None:
        """Test French accents are allowed."""
        result = ImportValidator.sanitize_string("Béjaïa")
        assert result == "Béjaïa"


class TestValidatePhone:
    """Tests for validate_phone method."""

    def test_valid_phone(self) -> None:
        """Test valid 10-digit phone."""
        assert ImportValidator.validate_phone("0551234567") == "0551234567"

    def test_empty_phone(self) -> None:
        """Test empty phone returns empty."""
        assert ImportValidator.validate_phone("") == ""

    def test_invalid_phone_length(self) -> None:
        """Test invalid phone length rejected."""
        with pytest.raises(ImportValidationError) as exc:
            ImportValidator.validate_phone("055123")
        assert "10 digits" in exc.value.message

    def test_phone_with_chars_rejected(self) -> None:
        """Test phone with non-digits rejected."""
        with pytest.raises(ImportValidationError):
            ImportValidator.validate_phone("055-123-456")


class TestValidatePrice:
    """Tests for validate_price method."""

    def test_valid_price(self) -> None:
        """Test valid price."""
        assert ImportValidator.validate_price(5000000) == 5000000

    def test_none_price(self) -> None:
        """Test None price returns None."""
        assert ImportValidator.validate_price(None) is None

    def test_string_price_converted(self) -> None:
        """Test string price is converted."""
        assert ImportValidator.validate_price("5000000") == 5000000  # type: ignore[arg-type]

    def test_word_based_price_matches_price_normalizer(self) -> None:
        assert ImportValidator.validate_price("1 milliard 500 DZD") == 1_500_000_000  # type: ignore[arg-type]

    def test_ambiguous_million_suffix_requires_review(self) -> None:
        with pytest.raises(ImportValidationError) as exc:
            ImportValidator.validate_price("1.5M")  # type: ignore[arg-type]
        assert "valid number" in exc.value.message

    def test_negative_price_rejected(self) -> None:
        """Test negative price rejected."""
        with pytest.raises(ImportValidationError) as exc:
            ImportValidator.validate_price(-1000)
        assert "cannot be negative" in exc.value.message

    def test_negative_string_price_rejected_without_type_parser_fallback(self) -> None:
        with pytest.raises(ImportValidationError) as exc:
            ImportValidator.validate_price("-1000")  # type: ignore[arg-type]
        assert "cannot be negative" in exc.value.message

    def test_negative_ambiguous_million_suffix_is_still_negative(self) -> None:
        with pytest.raises(ImportValidationError) as exc:
            ImportValidator.validate_price("-1.5M")  # type: ignore[arg-type]
        assert "cannot be negative" in exc.value.message

    def test_excessive_price_rejected(self) -> None:
        """Test excessive price rejected."""
        with pytest.raises(ImportValidationError) as exc:
            ImportValidator.validate_price(100_000_000_001)
        assert "exceeds reasonable maximum" in exc.value.message


class TestValidateName:
    """Tests for validate_name method."""

    def test_valid_name(self) -> None:
        """Test valid name."""
        assert ImportValidator.validate_name("Ahmed Ben Ali") == "Ahmed Ben Ali"

    def test_empty_name_allowed(self) -> None:
        """Test empty name allowed."""
        assert ImportValidator.validate_name("") == ""

    def test_name_with_digits_rejected(self) -> None:
        """Test name with digits rejected."""
        with pytest.raises(ImportValidationError):
            ImportValidator.validate_name("Ahmed123")

    def test_name_with_special_chars_rejected(self) -> None:
        """Test name with special characters rejected."""
        with pytest.raises(ImportValidationError):
            ImportValidator.validate_name("Ahmed@gmail.com")

    def test_arabic_name_allowed(self) -> None:
        """Test Arabic name allowed."""
        assert ImportValidator.validate_name("أحمد") == "أحمد"

    def test_name_with_hyphen_and_apostrophe(self) -> None:
        """Test name with hyphen and apostrophe allowed."""
        assert ImportValidator.validate_name("Jean-Pierre O'Brien") == "Jean-Pierre O'Brien"


class TestValidateEmail:
    """Tests for validate_email method."""

    def test_valid_email(self) -> None:
        """Test valid email."""
        assert ImportValidator.validate_email("test@example.com") == "test@example.com"

    def test_email_lowercase(self) -> None:
        """Test email is lowercased."""
        assert ImportValidator.validate_email("TEST@EXAMPLE.COM") == "test@example.com"

    def test_empty_email(self) -> None:
        """Test empty email returns empty."""
        assert ImportValidator.validate_email("") == ""

    def test_invalid_email_rejected(self) -> None:
        """Test invalid email rejected."""
        with pytest.raises(ImportValidationError):
            ImportValidator.validate_email("not-an-email")


class TestValidatePositiveInteger:
    """Tests for validate_positive_integer method."""

    def test_valid_integer(self) -> None:
        """Test valid integer."""
        assert ImportValidator.validate_positive_integer(5, "beds") == 5

    def test_none_returns_none(self) -> None:
        """Test None returns None."""
        assert ImportValidator.validate_positive_integer(None, "beds") is None

    def test_empty_string_returns_none(self) -> None:
        """Test empty string returns None."""
        assert ImportValidator.validate_positive_integer("", "beds") is None

    def test_string_converted(self) -> None:
        """Test string is converted."""
        assert ImportValidator.validate_positive_integer("5", "beds") == 5

    def test_negative_rejected(self) -> None:
        """Test negative value rejected."""
        with pytest.raises(ImportValidationError):
            ImportValidator.validate_positive_integer(-1, "beds")

    def test_max_value_enforced(self) -> None:
        """Test max value is enforced."""
        with pytest.raises(ImportValidationError):
            ImportValidator.validate_positive_integer(100, "floor", max_value=50)
