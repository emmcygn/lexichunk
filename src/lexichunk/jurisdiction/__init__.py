"""Jurisdiction-specific patterns and conventions."""

from __future__ import annotations

from ..models import Jurisdiction
from .uk import UK_PATTERNS, UKPatterns
from .uk import detect_level as uk_detect_level
from .us import US_PATTERNS, USPatterns
from .us import detect_level as us_detect_level


def get_patterns(jurisdiction: Jurisdiction) -> UKPatterns | USPatterns:
    """Return the compiled pattern set for the given jurisdiction.

    Args:
        jurisdiction: The target jurisdiction.

    Returns:
        The jurisdiction-specific pattern dataclass.

    Raises:
        ValueError: If the jurisdiction is not supported.
    """
    if jurisdiction == Jurisdiction.UK:
        return UK_PATTERNS
    if jurisdiction == Jurisdiction.US:
        return US_PATTERNS
    raise ValueError(f"Unsupported jurisdiction: {jurisdiction}")


def get_detect_level(jurisdiction: Jurisdiction):
    """Return the detect_level function for the given jurisdiction.

    Args:
        jurisdiction: The target jurisdiction.

    Returns:
        A callable that takes a line string and returns (level, identifier) or None.
    """
    if jurisdiction == Jurisdiction.UK:
        return uk_detect_level
    if jurisdiction == Jurisdiction.US:
        return us_detect_level
    raise ValueError(f"Unsupported jurisdiction: {jurisdiction}")


__all__ = [
    "get_patterns",
    "get_detect_level",
    "UK_PATTERNS",
    "US_PATTERNS",
    "UKPatterns",
    "USPatterns",
]
