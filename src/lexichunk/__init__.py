"""lexichunk — Legal document chunking SDK for RAG pipelines."""

from .chunker import LegalChunker
from .models import (
    LegalChunk,
    HierarchyNode,
    CrossReference,
    DefinedTerm,
    ClauseType,
    DocumentSection,
    Jurisdiction,
)

__version__ = "0.1.0"
__all__ = [
    "LegalChunker",
    "LegalChunk",
    "HierarchyNode",
    "CrossReference",
    "DefinedTerm",
    "ClauseType",
    "DocumentSection",
    "Jurisdiction",
]
