"""lexichunk — Legal document chunking SDK for RAG pipelines."""

from .chunker import LegalChunker
from .models import (
    ClauseType,
    CrossReference,
    DefinedTerm,
    DocumentSection,
    HierarchyNode,
    Jurisdiction,
    LegalChunk,
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
