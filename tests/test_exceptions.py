"""Tests for custom exception hierarchy — v0.3.0 robustness."""

from __future__ import annotations

import pickle

import pytest

from lexichunk.exceptions import (
    ConfigurationError,
    InputError,
    LexichunkError,
    ParsingError,
)

# ---------------------------------------------------------------------------
# Hierarchy checks
# ---------------------------------------------------------------------------

class TestExceptionHierarchy:
    """Verify the exception class relationships."""

    def test_lexichunk_error_is_exception(self) -> None:
        assert issubclass(LexichunkError, Exception)

    def test_configuration_error_inherits_lexichunk_and_value(self) -> None:
        assert issubclass(ConfigurationError, LexichunkError)
        assert issubclass(ConfigurationError, ValueError)

    def test_parsing_error_inherits_lexichunk_and_value(self) -> None:
        assert issubclass(ParsingError, LexichunkError)
        assert issubclass(ParsingError, ValueError)

    def test_input_error_inherits_lexichunk_and_value(self) -> None:
        assert issubclass(InputError, LexichunkError)
        assert issubclass(InputError, ValueError)


# ---------------------------------------------------------------------------
# Backward compatibility — existing except ValueError catches all
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    """Existing code with `except ValueError` must still work."""

    def test_configuration_error_caught_by_value_error(self) -> None:
        with pytest.raises(ValueError):
            raise ConfigurationError("bad config")

    def test_parsing_error_caught_by_value_error(self) -> None:
        with pytest.raises(ValueError):
            raise ParsingError("bad parse")

    def test_input_error_caught_by_value_error(self) -> None:
        with pytest.raises(ValueError):
            raise InputError("bad input")

    def test_all_caught_by_lexichunk_error(self) -> None:
        for exc_cls in (ConfigurationError, ParsingError, InputError):
            with pytest.raises(LexichunkError):
                raise exc_cls("test")


# ---------------------------------------------------------------------------
# Raise-site tests — verify LegalChunker raises the correct subclass
# ---------------------------------------------------------------------------

class TestRaiseSites:
    """Each raise site in the codebase must raise the expected custom exception."""

    def test_invalid_doc_type_raises_configuration_error(self) -> None:
        from lexichunk import LegalChunker
        with pytest.raises(ConfigurationError, match="Unknown doc_type"):
            LegalChunker(jurisdiction="uk", doc_type="email")

    def test_max_lt_min_raises_configuration_error(self) -> None:
        from lexichunk import LegalChunker
        with pytest.raises(ConfigurationError, match="max_chunk_size"):
            LegalChunker(jurisdiction="uk", max_chunk_size=10, min_chunk_size=100)

    def test_bad_chars_per_token_raises_configuration_error(self) -> None:
        from lexichunk import LegalChunker
        with pytest.raises(ConfigurationError, match="chars_per_token"):
            LegalChunker(jurisdiction="uk", chars_per_token=0)

    def test_bad_jurisdiction_raises_configuration_error(self) -> None:
        from lexichunk import LegalChunker
        with pytest.raises(ConfigurationError):
            LegalChunker(jurisdiction="fr")

    def test_input_too_large_raises_input_error(self) -> None:
        from lexichunk import LegalChunker
        chunker = LegalChunker(jurisdiction="uk")
        huge = "x" * (chunker._MAX_INPUT_CHARS + 1)
        with pytest.raises(InputError, match="too large"):
            chunker.chunk(huge)

    def test_roman_numeral_empty_raises_parsing_error(self) -> None:
        from lexichunk.jurisdiction.us import roman_to_int
        with pytest.raises(ParsingError, match="Empty string"):
            roman_to_int("")

    def test_roman_numeral_invalid_raises_parsing_error(self) -> None:
        from lexichunk.jurisdiction.us import roman_to_int
        with pytest.raises(ParsingError, match="Invalid Roman numeral"):
            roman_to_int("ABC")

    def test_unsupported_jurisdiction_patterns_raises_configuration_error(self) -> None:
        from unittest.mock import MagicMock

        from lexichunk.jurisdiction import get_patterns

        fake = MagicMock()
        fake.__eq__ = lambda self, other: False  # matches neither UK nor US
        with pytest.raises(ConfigurationError):
            get_patterns(fake)  # type: ignore[arg-type]

    def test_unsupported_jurisdiction_detect_level_raises_configuration_error(self) -> None:
        from unittest.mock import MagicMock

        from lexichunk.jurisdiction import get_detect_level

        fake = MagicMock()
        fake.__eq__ = lambda self, other: False
        with pytest.raises(ConfigurationError):
            get_detect_level(fake)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Adversarial / edge-case tests
# ---------------------------------------------------------------------------

class TestAdversarial:
    """Edge cases for exception behavior."""

    def test_exception_message_preserved(self) -> None:
        msg = "something went wrong"
        exc = ConfigurationError(msg)
        assert str(exc) == msg

    def test_exception_pickling(self) -> None:
        for cls in (LexichunkError, ConfigurationError, ParsingError, InputError):
            exc = cls("pickle test")
            roundtripped = pickle.loads(pickle.dumps(exc))
            assert str(roundtripped) == "pickle test"
            assert type(roundtripped) is cls

    def test_exception_repr(self) -> None:
        exc = InputError("bad bytes")
        assert "InputError" in repr(exc)
        assert "bad bytes" in repr(exc)

    def test_exception_chaining(self) -> None:
        try:
            try:
                raise ValueError("root cause")
            except ValueError as e:
                raise ParsingError("wrapped") from e
        except ParsingError as pe:
            assert pe.__cause__ is not None
            assert str(pe.__cause__) == "root cause"
