"""Custom exception hierarchy for lexichunk.

All exceptions inherit from both :class:`LexichunkError` and :class:`ValueError`
so that existing ``except ValueError`` handlers continue to work (backward
compatibility).
"""


class LexichunkError(Exception):
    """Base exception for all lexichunk errors."""


class ConfigurationError(LexichunkError, ValueError):
    """Raised for invalid configuration / initialisation parameters."""


class ParsingError(LexichunkError, ValueError):
    """Raised when runtime parsing of document content fails."""


class InputError(LexichunkError, ValueError):
    """Raised when input text is invalid or too large."""
