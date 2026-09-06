"""lexichunk — Legal document chunking SDK for RAG pipelines."""

import logging

from .chunker import LegalChunker
from .enrichment.clause_type import ClassificationResult
from .exceptions import (
    ConfigurationError,
    InputError,
    LexichunkError,
    ParsingError,
)
from .jurisdiction import (
    register_jurisdiction,
    registered_jurisdictions,
    unregister_jurisdiction,
)
from .metrics import PipelineMetrics, StageMetric
from .offsets import OffsetMap, sanitize_with_map

# Library hygiene: don't emit "no handlers found" warnings for consumers who
# haven't configured logging. See docs/architecture.md "Logging and
# observability" for the DEBUG/WARNING policy this package follows.
logging.getLogger(__name__).addHandler(logging.NullHandler())
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

__version__ = "0.8.0b1"
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
    "PipelineMetrics",
    "StageMetric",
    "OffsetMap",
    "sanitize_with_map",
    "register_jurisdiction",
    "unregister_jurisdiction",
    "registered_jurisdictions",
    "LexichunkError",
    "ConfigurationError",
    "ParsingError",
    "InputError",
]
