"""Jurisdiction-specific patterns and conventions."""

from __future__ import annotations

from typing import Callable, Optional, Union

from ..exceptions import ConfigurationError
from ..models import Jurisdiction, JurisdictionPatterns
from .eu import EU_PATTERNS, EUPatterns
from .eu import detect_level as eu_detect_level
from .uk import UK_PATTERNS, UKPatterns
from .uk import detect_level as uk_detect_level
from .us import US_PATTERNS, USPatterns
from .us import detect_level as us_detect_level

# Type alias for jurisdiction-specific level detection functions.
DetectLevelFn = Callable[[str], Optional[tuple[int, str]]]

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_JURISDICTION_REGISTRY: dict[str, tuple[JurisdictionPatterns, DetectLevelFn]] = {
    "uk": (UK_PATTERNS, uk_detect_level),
    "us": (US_PATTERNS, us_detect_level),
    "eu": (EU_PATTERNS, eu_detect_level),
}


def register_jurisdiction(
    name: str,
    patterns: JurisdictionPatterns,
    detect_level_fn: DetectLevelFn,
) -> None:
    """Register a custom jurisdiction for use in the chunking pipeline.

    After registration, the jurisdiction can be used by passing its *name*
    string to :class:`~lexichunk.chunker.LegalChunker` and all other
    pipeline components.

    Args:
        name: Short lowercase identifier (e.g. ``"eu"``).
        patterns: An object conforming to the :class:`JurisdictionPatterns`
            protocol — must expose ``cross_ref``, ``definition``,
            ``definition_curly``, ``definitions_headers``,
            ``boilerplate_headers``, and ``signature_markers`` attributes.
        detect_level_fn: A callable ``(str) -> Optional[tuple[int, str]]``
            that detects clause headers in a line of text.

    Raises:
        ConfigurationError: If *name* is empty, *patterns* does not conform
            to the protocol, or *detect_level_fn* is not callable.
    """
    if not name or not name.strip():
        raise ConfigurationError("Jurisdiction name must be a non-empty string")
    if not isinstance(patterns, JurisdictionPatterns):
        raise ConfigurationError(
            f"patterns must conform to JurisdictionPatterns protocol, "
            f"got {type(patterns).__name__}"
        )
    if not callable(detect_level_fn):
        raise ConfigurationError("detect_level_fn must be callable")
    _JURISDICTION_REGISTRY[name.lower().strip()] = (patterns, detect_level_fn)


# ---------------------------------------------------------------------------
# Factory functions (updated to support registry lookup)
# ---------------------------------------------------------------------------


def get_patterns(
    jurisdiction: Union[Jurisdiction, str],
) -> EUPatterns | UKPatterns | USPatterns | JurisdictionPatterns:
    """Return the compiled pattern set for the given jurisdiction.

    Args:
        jurisdiction: A :class:`Jurisdiction` enum value or a string key
            registered via :func:`register_jurisdiction`.

    Returns:
        The jurisdiction-specific pattern object.

    Raises:
        ConfigurationError: If the jurisdiction is not supported.
    """
    key = jurisdiction.value if isinstance(jurisdiction, Jurisdiction) else jurisdiction.lower()
    entry = _JURISDICTION_REGISTRY.get(key)
    if entry is not None:
        return entry[0]
    raise ConfigurationError(f"Unsupported jurisdiction: {jurisdiction}")


def get_detect_level(
    jurisdiction: Union[Jurisdiction, str],
) -> DetectLevelFn:
    """Return the detect_level function for the given jurisdiction.

    Args:
        jurisdiction: A :class:`Jurisdiction` enum value or a string key
            registered via :func:`register_jurisdiction`.

    Returns:
        A callable that takes a line string and returns (level, identifier) or None.

    Raises:
        ConfigurationError: If the jurisdiction is not supported.
    """
    key = jurisdiction.value if isinstance(jurisdiction, Jurisdiction) else jurisdiction.lower()
    entry = _JURISDICTION_REGISTRY.get(key)
    if entry is not None:
        return entry[1]
    raise ConfigurationError(f"Unsupported jurisdiction: {jurisdiction}")


__all__ = [
    "get_patterns",
    "get_detect_level",
    "register_jurisdiction",
    "DetectLevelFn",
    "EU_PATTERNS",
    "EUPatterns",
    "UK_PATTERNS",
    "US_PATTERNS",
    "UKPatterns",
    "USPatterns",
]
