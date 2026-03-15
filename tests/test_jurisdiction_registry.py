"""Tests for the jurisdiction registry and custom jurisdiction support."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import pytest

from lexichunk import (
    ConfigurationError,
    JurisdictionPatterns,
    LegalChunker,
    register_jurisdiction,
)
from lexichunk.jurisdiction import (
    _JURISDICTION_REGISTRY,
    UK_PATTERNS,
    US_PATTERNS,
    get_detect_level,
    get_patterns,
)
from lexichunk.jurisdiction.uk import detect_level as uk_detect_level
from lexichunk.models import Jurisdiction

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@dataclass
class EUPatterns:
    """Minimal pattern set conforming to JurisdictionPatterns."""

    cross_ref: re.Pattern[str] = field(
        default_factory=lambda: re.compile(
            r"\b(?:Article|Regulation)\s+(\d+(?:\.\d+)*)", re.IGNORECASE
        )
    )
    definition: re.Pattern[str] = field(
        default_factory=lambda: re.compile(
            r'"([A-Z][A-Za-z\s\-]{1,60})"\s+means', re.MULTILINE
        )
    )
    definition_curly: re.Pattern[str] = field(
        default_factory=lambda: re.compile(
            r'\u201c([A-Z][A-Za-z\s\-]{1,60})\u201d\s+means', re.MULTILINE
        )
    )
    definitions_headers: tuple[str, ...] = ("definitions", "interpretation")
    boilerplate_headers: tuple[str, ...] = ("general provisions",)
    signature_markers: tuple[str, ...] = ("signed by",)


def _eu_detect_level(line: str) -> Optional[tuple[int, str]]:
    """Trivial detect_level for the EU test jurisdiction."""
    m = re.match(r"^Article\s+(\d+)", line.strip())
    if m:
        return (0, f"Article {m.group(1)}")
    m = re.match(r"^(\d+)\.\s", line.strip())
    if m:
        return (1, m.group(1))
    return None


@pytest.fixture(autouse=True)
def _cleanup_registry():
    """Remove the 'eu' entry from the registry after each test."""
    yield
    _JURISDICTION_REGISTRY.pop("eu", None)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_uk_patterns_conform(self) -> None:
        assert isinstance(UK_PATTERNS, JurisdictionPatterns)

    def test_us_patterns_conform(self) -> None:
        assert isinstance(US_PATTERNS, JurisdictionPatterns)

    def test_custom_patterns_conform(self) -> None:
        assert isinstance(EUPatterns(), JurisdictionPatterns)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_and_retrieve_patterns(self) -> None:
        eu = EUPatterns()
        register_jurisdiction("eu", eu, _eu_detect_level)
        assert get_patterns("eu") is eu

    def test_register_and_retrieve_detect_level(self) -> None:
        register_jurisdiction("eu", EUPatterns(), _eu_detect_level)
        fn = get_detect_level("eu")
        assert fn is _eu_detect_level

    def test_overwrite_builtin(self) -> None:
        """Overwriting a built-in jurisdiction is allowed."""
        eu = EUPatterns()
        register_jurisdiction("uk", eu, _eu_detect_level)
        assert get_patterns("uk") is eu
        # Restore original (use imported uk_detect_level directly, not
        # get_detect_level() which reads from the already-overwritten registry)
        _JURISDICTION_REGISTRY["uk"] = (UK_PATTERNS, uk_detect_level)

    def test_invalid_empty_name(self) -> None:
        with pytest.raises(ConfigurationError, match="non-empty"):
            register_jurisdiction("", EUPatterns(), _eu_detect_level)

    def test_invalid_whitespace_name(self) -> None:
        with pytest.raises(ConfigurationError, match="non-empty"):
            register_jurisdiction("   ", EUPatterns(), _eu_detect_level)

    def test_invalid_non_conforming_patterns(self) -> None:
        with pytest.raises(ConfigurationError, match="JurisdictionPatterns"):
            register_jurisdiction("bad", object(), _eu_detect_level)  # type: ignore[arg-type]

    def test_invalid_non_callable_detect_level(self) -> None:
        with pytest.raises(ConfigurationError, match="callable"):
            register_jurisdiction("bad", EUPatterns(), "not_callable")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_get_patterns_with_enum(self) -> None:
        assert get_patterns(Jurisdiction.UK) is UK_PATTERNS
        assert get_patterns(Jurisdiction.US) is US_PATTERNS

    def test_get_detect_level_with_enum(self) -> None:
        fn = get_detect_level(Jurisdiction.UK)
        assert callable(fn)

    def test_legal_chunker_with_string_uk(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        assert chunker is not None

    def test_unregistered_jurisdiction_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            LegalChunker(jurisdiction="mars")


# ---------------------------------------------------------------------------
# End-to-end: custom jurisdiction through the pipeline
# ---------------------------------------------------------------------------


class TestCustomJurisdictionE2E:
    def test_chunk_with_custom_jurisdiction(self) -> None:
        register_jurisdiction("eu", EUPatterns(), _eu_detect_level)

        text = (
            "Article 1\n"
            "This regulation establishes rules for data processing.\n\n"
            "Article 2\n"
            "Personal data shall be collected for specified purposes.\n"
        )
        chunker = LegalChunker(jurisdiction="eu")
        chunks = chunker.chunk(text)
        assert len(chunks) > 0
        assert chunks[0].jurisdiction == "eu"
