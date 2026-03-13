"""lexichunk — Legal document chunking SDK for RAG pipelines."""

from .chunker import LegalChunker
from .exceptions import (
    ConfigurationError,
    InputError,
    LexichunkError,
    ParsingError,
)
from .models import (
    ClauseType,
    CrossReference,
    DefinedTerm,
    DocumentSection,
    HierarchyNode,
    Jurisdiction,
    LegalChunk,
)

__version__ = "0.3.0"
__all__ = [
    "LegalChunker",
    "LegalChunk",
    "HierarchyNode",
    "CrossReference",
    "DefinedTerm",
    "ClauseType",
    "DocumentSection",
    "Jurisdiction",
    "LexichunkError",
    "ConfigurationError",
    "ParsingError",
    "InputError",
]
