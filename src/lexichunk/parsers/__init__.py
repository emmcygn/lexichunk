"""Parsers for legal document structure, definitions, and cross-references."""

from .definitions import DefinitionsExtractor
from .references import ReferenceDetector, detect_references, resolve_references
from .structure import ParsedClause, StructureParser, parse_structure

__all__ = [
    "DefinitionsExtractor",
    "ParsedClause",
    "ReferenceDetector",
    "StructureParser",
    "detect_references",
    "parse_structure",
    "resolve_references",
]
