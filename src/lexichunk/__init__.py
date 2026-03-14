"""lexichunk — Legal document chunking SDK for RAG pipelines."""

from .chunker import LegalChunker
from .enrichment.clause_type import ClassificationResult
from .exceptions import (
    ConfigurationError,
    InputError,
    LexichunkError,
    ParsingError,
)
from .jurisdiction import register_jurisdiction
from .models import (
    BatchError,
    BatchResult,
    ClauseType,
    CrossReference,
    DefinedTerm,
    DocumentSection,
    HierarchyNode,
    Jurisdiction,
    JurisdictionPatterns,
    LegalChunk,
)

__version__ = "0.6.0"
__all__ = [
    "LegalChunker",
    "LegalChunk",
    "HierarchyNode",
    "CrossReference",
    "ClassificationResult",
    "DefinedTerm",
    "ClauseType",
    "DocumentSection",
    "Jurisdiction",
    "JurisdictionPatterns",
    "BatchResult",
    "BatchError",
    "register_jurisdiction",
    "LexichunkError",
    "ConfigurationError",
    "ParsingError",
    "InputError",
]
