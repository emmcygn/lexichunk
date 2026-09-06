"""Jurisdiction-specific patterns and conventions."""

from __future__ import annotations

import logging
from typing import Callable, Optional, Union

from ..exceptions import ConfigurationError
from ..models import Jurisdiction, JurisdictionPatterns
from .eu import EU_PATTERNS, EUPatterns
from .eu import detect_level as eu_detect_level
from .uk import UK_PATTERNS, UKPatterns
from .uk import detect_level as uk_detect_level
from .us import US_PATTERNS, USPatterns
from .us import detect_level as us_detect_level

logger = logging.getLogger(__name__)

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

# Built-in jurisdiction keys — protected from accidental overwrite.
_BUILTIN_JURISDICTIONS = frozenset(j.value for j in Jurisdiction)


def register_jurisdiction(
    name: str,
    patterns: JurisdictionPatterns,
    detect_level_fn: DetectLevelFn,
    *,
    override: bool = False,
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
        override: When ``False`` (the default), registering over one of the
            built-in keys (``"uk"``, ``"us"``, ``"eu"``) raises
            :class:`ConfigurationError` instead of silently replacing it.
            Re-registering an existing *custom* key without ``override``
            succeeds but logs a ``WARNING``. Pass ``override=True`` only if
            you understand that this mutates process-global state shared by
            every :class:`~lexichunk.chunker.LegalChunker` instance, and is
            **not** reproduced in ``chunk_batch(workers>1)`` child processes
            (each spawned worker starts from a pristine registry).

    Raises:
        ConfigurationError: If *name* is not a ``str`` or is empty,
            *patterns* does not conform
            to the protocol, *detect_level_fn* is not callable, or *name*
            is a built-in jurisdiction key and ``override`` is not ``True``.
    """
    # ``name`` must be checked for type *before* anything duck-typed is done
    # with it.  ``bytes`` also has ``.strip()``/``.lower()``, so it used to
    # sail through every check and land in the registry as a non-``str`` key —
    # after which ``registered_jurisdictions()`` (``sorted(keys())``) raised
    # ``TypeError`` on every subsequent call for the life of the process, with
    # no way to enumerate or clear the offending key.
    if not isinstance(name, str):
        raise ConfigurationError(
            f"Jurisdiction name must be a str, got {type(name).__name__}."
        )
    if not name.strip():
        raise ConfigurationError("Jurisdiction name must be a non-empty string")
    if not isinstance(patterns, JurisdictionPatterns):
        raise ConfigurationError(
            f"patterns must conform to JurisdictionPatterns protocol, "
            f"got {type(patterns).__name__}"
        )
    if not callable(detect_level_fn):
        raise ConfigurationError("detect_level_fn must be callable")

    key = name.lower().strip()

    if key in _BUILTIN_JURISDICTIONS and not override:
        raise ConfigurationError(
            f"{key!r} is a built-in jurisdiction. Overriding it changes "
            f"behaviour for every LegalChunker in this process and is NOT "
            f"reproduced in chunk_batch(workers>1) child processes. "
            f"Pass override=True only if you understand this."
        )
    if key in _JURISDICTION_REGISTRY and not override:
        logger.warning("Re-registering custom jurisdiction %r", key)

    _JURISDICTION_REGISTRY[key] = (patterns, detect_level_fn)


def unregister_jurisdiction(name: str) -> None:
    """Remove a custom jurisdiction previously added via :func:`register_jurisdiction`.

    Args:
        name: The jurisdiction key to remove (case-insensitive, stripped).

    Raises:
        ConfigurationError: If *name* is not a ``str``, is a built-in
            jurisdiction (``"uk"``, ``"us"``, ``"eu"``) or is not currently
            registered.
    """
    if not isinstance(name, str):
        raise ConfigurationError(
            f"Jurisdiction name must be a str, got {type(name).__name__}."
        )
    key = name.lower().strip()
    if key in _BUILTIN_JURISDICTIONS:
        raise ConfigurationError(
            f"{key!r} is a built-in jurisdiction and cannot be unregistered."
        )
    if key not in _JURISDICTION_REGISTRY:
        raise ConfigurationError(f"{key!r} is not a registered jurisdiction.")
    del _JURISDICTION_REGISTRY[key]


def registered_jurisdictions() -> tuple[str, ...]:
    """Return a sorted snapshot of every registered jurisdiction key.

    Includes the three built-ins (``"uk"``, ``"us"``, ``"eu"``) plus any
    custom jurisdictions registered via :func:`register_jurisdiction`.
    Intended for test cleanup: snapshot before, diff after, and
    :func:`unregister_jurisdiction` anything new — never restore state by
    reading the (possibly mutated) registry directly.
    """
    return tuple(sorted(_JURISDICTION_REGISTRY.keys()))


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
    "unregister_jurisdiction",
    "registered_jurisdictions",
    "DetectLevelFn",
    "EU_PATTERNS",
    "EUPatterns",
    "UK_PATTERNS",
    "US_PATTERNS",
    "UKPatterns",
    "USPatterns",
]
