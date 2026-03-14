"""Core data models for lexichunk."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class JurisdictionPatterns(Protocol):
    """Protocol defining the attributes a jurisdiction pattern set must expose.

    Any object with these six attributes structurally conforms — no
    explicit inheritance required.  Both :class:`UKPatterns` and
    :class:`USPatterns` satisfy this protocol as-is.
    """

    cross_ref: re.Pattern[str]
    definition: re.Pattern[str]
    definition_curly: re.Pattern[str]
    definitions_headers: tuple[str, ...]
    boilerplate_headers: tuple[str, ...]
    signature_markers: tuple[str, ...]


class Jurisdiction(Enum):
    """Supported legal jurisdictions."""

    UK = "uk"
    US = "us"


class ClauseType(Enum):
    """Legal clause type classification."""

    DEFINITIONS = "definitions"
    REPRESENTATIONS = "representations"
    WARRANTIES = "warranties"
    COVENANTS = "covenants"
    CONDITIONS = "conditions"
    INDEMNIFICATION = "indemnification"
    TERMINATION = "termination"
    CONFIDENTIALITY = "confidentiality"
    GOVERNING_LAW = "governing_law"
    FORCE_MAJEURE = "force_majeure"
    ASSIGNMENT = "assignment"
    AMENDMENT = "amendment"
    NOTICES = "notices"
    ENTIRE_AGREEMENT = "entire_agreement"
    SEVERABILITY = "severability"
    LIMITATION_OF_LIABILITY = "limitation_of_liability"
    PAYMENT = "payment"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    DATA_PROTECTION = "data_protection"
    DISPUTE_RESOLUTION = "dispute_resolution"
    BOILERPLATE = "boilerplate"
    PREAMBLE = "preamble"
    RECITALS = "recitals"
    ACCEPTABLE_USE = "acceptable_use"
    USER_RESTRICTIONS = "user_restrictions"
    ACCOUNT_SECURITY = "account_security"
    UNKNOWN = "unknown"


class DocumentSection(Enum):
    """High-level document section classification."""

    PREAMBLE = "preamble"
    RECITALS = "recitals"
    DEFINITIONS = "definitions"
    OPERATIVE = "operative"
    SCHEDULES = "schedules"
    SIGNATURES = "signatures"


@dataclass
class CrossReference:
    """A detected reference to another section/clause within the document."""

    raw_text: str
    target_identifier: str
    target_chunk_index: Optional[int] = None


@dataclass
class DefinedTerm:
    """A capitalised term with its contract-specific definition."""

    term: str
    definition: str
    source_clause: str


@dataclass
class HierarchyNode:
    """Position in the document's clause hierarchy."""

    level: int
    identifier: str
    title: Optional[str] = None
    parent: Optional[str] = None


@dataclass
class LegalChunk:
    """A single chunk of legal text with full metadata."""

    content: str
    index: int

    # Structure
    hierarchy: HierarchyNode
    hierarchy_path: str
    document_section: DocumentSection

    # Legal metadata
    clause_type: ClauseType
    jurisdiction: Jurisdiction | str

    # Cross-references and terms
    cross_references: list[CrossReference] = field(default_factory=list)
    defined_terms_used: list[str] = field(default_factory=list)
    defined_terms_context: dict[str, str] = field(default_factory=dict)

    # Retrieval helpers
    context_header: str = ""
    document_id: Optional[str] = None
    char_start: int = 0
    char_end: int = 0
    token_count: int = 0
    original_header: str = ""
