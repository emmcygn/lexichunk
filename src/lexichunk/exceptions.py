"""Custom exception hierarchy for lexichunk.

:class:`LexichunkError` is the common base and inherits only from
``Exception``.  Every exception this package actually raises —
:class:`ConfigurationError`, :class:`ParsingError` and :class:`InputError` —
inherits from both :class:`LexichunkError` and :class:`ValueError`, so an
existing ``except ValueError`` handler keeps working.  Catch
:class:`LexichunkError` to catch everything lexichunk raises.
"""


class LexichunkError(Exception):
    """Base exception for all lexichunk errors."""


class ConfigurationError(LexichunkError, ValueError):
    """Raised for invalid configuration / initialisation parameters."""


class ParsingError(LexichunkError, ValueError):
    """Raised when runtime parsing of document content fails."""


class InputError(LexichunkError, ValueError):
    """Raised when input text is invalid or too large."""
