"""Core data models for lexichunk."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from .exceptions import ParsingError


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


class Jurisdiction(str, Enum):
    """Supported legal jurisdictions.

    Inherits from ``str`` so instances compare equal to their raw string
    value (``Jurisdiction.UK == "uk"``) and can be used anywhere a plain
    string is expected (e.g. dict keys, JSON serialisation without a custom
    encoder).  ``__str__`` is defined explicitly to return ``.value`` because
    the default ``str(str_enum_member)`` behaviour changed between Python
    3.10 (returns the raw value) and 3.11+ (returns ``"ClassName.MEMBER"``
    unless overridden) — the explicit override keeps ``str(x)`` and
    ``f"{x}"`` consistent across interpreter versions.
    """

    UK = "uk"
    US = "us"
    EU = "eu"

    def __str__(self) -> str:
        return self.value


class ClauseType(str, Enum):
    """Legal clause type classification.

    Inherits from ``str`` so instances compare equal to their raw string
    value (``ClauseType.PAYMENT == "payment"``) and can be used anywhere a
    plain string is expected.  ``__str__`` is defined explicitly to return
    ``.value`` for consistent behaviour across Python 3.10 vs 3.11+ (see
    :class:`Jurisdiction` docstring for details).
    """

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
    SERVICES = "services"
    INSURANCE = "insurance"
    AUDIT = "audit"
    NON_SOLICITATION = "non_solicitation"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


class DocumentSection(str, Enum):
    """High-level document section classification.

    Inherits from ``str`` so instances compare equal to their raw string
    value (``DocumentSection.OPERATIVE == "operative"``) and can be used
    anywhere a plain string is expected.  ``__str__`` is defined explicitly
    to return ``.value`` for consistent behaviour across Python 3.10 vs
    3.11+ (see :class:`Jurisdiction` docstring for details).
    """

    PREAMBLE = "preamble"
    RECITALS = "recitals"
    DEFINITIONS = "definitions"
    OPERATIVE = "operative"
    SCHEDULES = "schedules"
    SIGNATURES = "signatures"

    def __str__(self) -> str:
        return self.value


@dataclass
class CrossReference:
    """A detected reference to another section/clause within the document.

    Attributes:
        raw_text: The matched reference text as it appears in the document
            (e.g. ``"subject to Clause 3.2"``).
        target_identifier: The identifier the reference points at
            (e.g. ``"3.2"``), without the label word.
        target_chunk_index: Index of the chunk this reference resolves to, or
            ``None`` when the target could not be resolved *or* was ambiguous.
        target_kind: Normalised, lower-case label word of the referenced unit —
            one of ``clause``, ``schedule``, ``exhibit``, ``annex``,
            ``article``, ``chapter``, ``recital``, ``section`` or
            ``paragraph``.  Defaults to ``"clause"`` when the reference carries
            only a number.  Resolution only matches candidates of a compatible
            kind, so ``Annex I`` can never resolve to numbered paragraph ``1``.
    """

    raw_text: str
    target_identifier: str
    target_chunk_index: Optional[int] = None
    target_kind: str = "clause"

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, ``json.dumps``-able dict representation."""
        return {
            "raw_text": self.raw_text,
            "target_identifier": self.target_identifier,
            "target_chunk_index": self.target_chunk_index,
            "target_kind": self.target_kind,
        }


@dataclass
class DefinedTerm:
    """A capitalised term with its contract-specific definition."""

    term: str
    definition: str
    source_clause: str

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, ``json.dumps``-able dict representation."""
        return {
            "term": self.term,
            "definition": self.definition,
            "source_clause": self.source_clause,
        }


@dataclass
class HierarchyNode:
    """Position in the document's clause hierarchy."""

    level: int
    identifier: str
    title: Optional[str] = None
    parent: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, ``json.dumps``-able dict representation."""
        return {
            "level": self.level,
            "identifier": self.identifier,
            "title": self.title,
            "parent": self.parent,
        }


@dataclass
class LegalChunk:
    """A single chunk of legal text with full metadata.

    **Offset invariant**: ``char_start`` and ``char_end`` mark the span of this
    clause's own text in the *original* (sanitised) document.  The ``content``
    field may additionally prepend ancestor header lines for retrieval context,
    so ``content`` is typically a superset of
    ``original_text[char_start:char_end]``.

    **Mutation warning**: Mutable container fields (``cross_references``,
    ``defined_terms_used``, ``defined_terms_context``) are populated by the
    pipeline.  Callers should treat returned chunks as read-only; mutations may
    affect cached state when ``enable_definition_cache`` is ``True``.
    """

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

    # Classification accuracy
    classification_confidence: float = 0.0
    secondary_clause_type: Optional[ClauseType] = None

    # Cross-reference resolution stats
    cross_ref_total: int = 0
    cross_ref_resolved: int = 0

    # Retrieval helpers
    context_header: str = ""
    document_id: Optional[str] = None
    char_start: int = 0
    char_end: int = 0
    token_count: int = 0
    original_header: str = ""

    # Provenance of ``clause_type``: ``"keyword"`` for the built-in scorer,
    # ``"hook"`` when a ``classification_hook`` overrode it.
    classification_source: str = "keyword"

    # Offsets into the *raw* text the caller passed in, before sanitisation.
    # ``-1`` means "not computed" — populate them by passing
    # ``raw_offsets=True`` to :meth:`~lexichunk.chunker.LegalChunker.chunk`.
    raw_char_start: int = -1
    raw_char_end: int = -1

    def __post_init__(self) -> None:
        """Enforce per-chunk structural invariants.

        These four checks hold for every chunk the pipeline produces today;
        a violation indicates an internal pipeline bug (not caller error),
        so :class:`~lexichunk.exceptions.ParsingError` is raised rather than
        ``ValueError`` directly (``ParsingError`` still subclasses
        ``ValueError`` for backward-compatible ``except`` handling).

        Note this checks only *per-chunk* invariants. Cross-chunk properties
        (e.g. that chunk spans do not overlap) are not enforced here — they
        are cross-chunk properties belonging in the test suite, and enforcing
        them at construction time would crash on real, already-shipped
        fixtures.
        """
        if self.index < 0:
            raise ParsingError(f"LegalChunk.index must be >= 0, got {self.index}")
        if self.char_start < 0:
            raise ParsingError(
                f"LegalChunk.char_start must be >= 0, got {self.char_start}"
            )
        if self.char_end < self.char_start:
            raise ParsingError(
                f"LegalChunk.char_end ({self.char_end}) must be >= "
                f"char_start ({self.char_start})"
            )
        if not 0.0 <= self.classification_confidence <= 1.0:
            raise ParsingError(
                f"LegalChunk.classification_confidence must be in [0.0, 1.0], "
                f"got {self.classification_confidence}"
            )
        if self.cross_ref_resolved > self.cross_ref_total:
            raise ParsingError(
                f"LegalChunk.cross_ref_resolved ({self.cross_ref_resolved}) "
                f"cannot exceed cross_ref_total ({self.cross_ref_total})"
            )
        # Raw offsets are optional: -1/-1 means "not computed". When they
        # *are* computed they obey the same ordering rule as the sanitised
        # pair, and both must be populated together.
        raw_unset = self.raw_char_start == -1 and self.raw_char_end == -1
        if not raw_unset:
            if self.raw_char_start < 0 or self.raw_char_end < 0:
                raise ParsingError(
                    f"LegalChunk raw offsets must both be >= 0 or both be -1, "
                    f"got ({self.raw_char_start}, {self.raw_char_end})"
                )
            if self.raw_char_end < self.raw_char_start:
                raise ParsingError(
                    f"LegalChunk.raw_char_end ({self.raw_char_end}) must be >= "
                    f"raw_char_start ({self.raw_char_start})"
                )

    @property
    def jurisdiction_value(self) -> str:
        """The jurisdiction as a plain string.

        Returns ``jurisdiction.value`` when ``jurisdiction`` is a
        :class:`Jurisdiction` enum member, or the jurisdiction string itself
        when it is a custom key registered via
        :func:`~lexichunk.jurisdiction.register_jurisdiction`. Use this
        instead of the ``x.value if isinstance(x, Enum) else x`` dance.
        """
        return (
            self.jurisdiction.value
            if isinstance(self.jurisdiction, Enum)
            else self.jurisdiction
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, ``json.dumps``-able dict representation.

        No custom JSON encoder is required: enums are rendered as their
        ``.value`` string, nested dataclasses are recursively converted via
        their own ``to_dict()``, and mutable containers (lists/dicts) are
        copied rather than aliased — mutating the returned dict never
        affects this chunk.  ``jurisdiction`` is rendered as its string
        value whether it is a :class:`Jurisdiction` enum member or a
        registered custom jurisdiction string.
        """
        jurisdiction_value = (
            self.jurisdiction.value
            if isinstance(self.jurisdiction, Jurisdiction)
            else self.jurisdiction
        )
        return {
            "content": self.content,
            "index": self.index,
            "hierarchy": self.hierarchy.to_dict(),
            "hierarchy_path": self.hierarchy_path,
            "document_section": self.document_section.value,
            "clause_type": self.clause_type.value,
            "jurisdiction": jurisdiction_value,
            "cross_references": [ref.to_dict() for ref in self.cross_references],
            "defined_terms_used": list(self.defined_terms_used),
            "defined_terms_context": dict(self.defined_terms_context),
            "classification_confidence": self.classification_confidence,
            "secondary_clause_type": (
                self.secondary_clause_type.value
                if self.secondary_clause_type is not None
                else None
            ),
            "cross_ref_total": self.cross_ref_total,
            "cross_ref_resolved": self.cross_ref_resolved,
            "context_header": self.context_header,
            "document_id": self.document_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "token_count": self.token_count,
            "original_header": self.original_header,
            "classification_source": self.classification_source,
            "raw_char_start": self.raw_char_start,
            "raw_char_end": self.raw_char_end,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LegalChunk":
        """Reconstruct a :class:`LegalChunk` from a :meth:`to_dict` output.

        Enum-valued fields are reconstructed from their string ``.value``.
        An unrecognised ``jurisdiction`` string (i.e. not a built-in
        :class:`Jurisdiction` value) is kept as a plain string, matching the
        custom-jurisdiction registration mechanism.

        This is the deserialisation entry point, so it is the method most
        likely to be handed data whose shape drifted crossing a system
        boundary (cache, database, message queue).  Every container field is
        therefore type-checked before use and every failure raises
        :class:`~lexichunk.exceptions.ParsingError` naming the offending
        field — the same rigour the numeric and enum fields already get from
        ``__post_init__``.

        In particular a ``str`` where a list or dict is expected is rejected
        rather than iterated: ``list("Services")`` silently produced
        ``['S', 'e', 'r', 'v', 'i', 'c', 'e', 's']`` and a ``LegalChunk``
        that looked entirely valid.

        Args:
            d: A mapping in the shape produced by :meth:`to_dict`.

        Returns:
            The reconstructed :class:`LegalChunk`.

        Raises:
            ParsingError: If *d* is not a mapping, a required key is missing,
                or any field has a type this method cannot honour.
        """
        if not isinstance(d, Mapping):
            raise ParsingError(
                f"LegalChunk.from_dict expects a mapping, got {type(d).__name__}."
            )

        def _require(key: str) -> Any:
            if key not in d:
                raise ParsingError(f"LegalChunk.from_dict: missing required key {key!r}")
            return d[key]

        def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
            if not isinstance(value, Mapping):
                raise ParsingError(
                    f"LegalChunk.from_dict: {field_name!r} must be a mapping, "
                    f"got {type(value).__name__}."
                )
            return value

        def _sequence(value: Any, field_name: str) -> Sequence[Any]:
            if isinstance(value, (str, bytes, bytearray)) or not isinstance(
                value, Sequence
            ):
                raise ParsingError(
                    f"LegalChunk.from_dict: {field_name!r} must be a list, "
                    f"got {type(value).__name__}."
                )
            return value

        hierarchy_d = _mapping(_require("hierarchy"), "hierarchy")
        if "level" not in hierarchy_d or "identifier" not in hierarchy_d:
            raise ParsingError(
                "LegalChunk.from_dict: 'hierarchy' must contain 'level' and "
                "'identifier'."
            )
        hierarchy = HierarchyNode(
            level=hierarchy_d["level"],
            identifier=hierarchy_d["identifier"],
            title=hierarchy_d.get("title"),
            parent=hierarchy_d.get("parent"),
        )

        raw_references = _sequence(
            d.get("cross_references", []), "cross_references"
        )
        cross_references: list[CrossReference] = []
        for position, raw_reference in enumerate(raw_references):
            reference = _mapping(raw_reference, f"cross_references[{position}]")
            if "raw_text" not in reference or "target_identifier" not in reference:
                raise ParsingError(
                    f"LegalChunk.from_dict: cross_references[{position}] must "
                    f"contain 'raw_text' and 'target_identifier'."
                )
            cross_references.append(
                CrossReference(
                    raw_text=reference["raw_text"],
                    target_identifier=reference["target_identifier"],
                    target_chunk_index=reference.get("target_chunk_index"),
                    target_kind=reference.get("target_kind", "clause"),
                )
            )

        terms_used = _sequence(
            d.get("defined_terms_used", []), "defined_terms_used"
        )
        terms_context = _mapping(
            d.get("defined_terms_context", {}), "defined_terms_context"
        )

        jurisdiction_raw = _require("jurisdiction")
        jurisdiction: Jurisdiction | str
        try:
            jurisdiction = Jurisdiction(jurisdiction_raw)
        except ValueError:
            jurisdiction = jurisdiction_raw

        secondary = d.get("secondary_clause_type")

        try:
            document_section = DocumentSection(_require("document_section"))
            clause_type = ClauseType(_require("clause_type"))
            secondary_clause_type = (
                ClauseType(secondary) if secondary is not None else None
            )
        except ValueError as exc:
            raise ParsingError(f"LegalChunk.from_dict: {exc}") from exc

        return cls(
            content=_require("content"),
            index=_require("index"),
            hierarchy=hierarchy,
            hierarchy_path=_require("hierarchy_path"),
            document_section=document_section,
            clause_type=clause_type,
            jurisdiction=jurisdiction,
            cross_references=cross_references,
            defined_terms_used=list(terms_used),
            defined_terms_context=dict(terms_context),
            classification_confidence=d.get("classification_confidence", 0.0),
            secondary_clause_type=secondary_clause_type,
            cross_ref_total=d.get("cross_ref_total", 0),
            cross_ref_resolved=d.get("cross_ref_resolved", 0),
            context_header=d.get("context_header", ""),
            document_id=d.get("document_id"),
            char_start=d.get("char_start", 0),
            char_end=d.get("char_end", 0),
            token_count=d.get("token_count", 0),
            original_header=d.get("original_header", ""),
            classification_source=d.get("classification_source", "keyword"),
            raw_char_start=d.get("raw_char_start", -1),
            raw_char_end=d.get("raw_char_end", -1),
        )


@dataclass
class BatchError:
    """Error from processing a single document in a batch.

    Args:
        index: Position of the failed document in the input list.
        text_preview: First 100 characters of the input text.
        error: Error message string.
        error_type: Fully-qualified exception class name.
    """

    index: int
    text_preview: str
    error: str
    error_type: str


@dataclass
class BatchResult:
    """Result of :meth:`~lexichunk.chunker.LegalChunker.chunk_batch`.

    Contains per-document chunk lists and any errors that occurred.
    Documents that errored out have an empty list at their index in
    ``results``.

    Args:
        results: Per-document chunk lists, in input order.  Failed documents
            have an empty list.
        errors: List of :class:`BatchError` objects for documents that
            failed processing.
    """

    results: list[list["LegalChunk"]]
    errors: list[BatchError]

    @property
    def total_chunks(self) -> int:
        """Total number of chunks across all successfully processed documents."""
        return sum(len(r) for r in self.results)

    @property
    def success_count(self) -> int:
        """Number of documents processed without errors."""
        error_indices = {e.index for e in self.errors}
        return len(self.results) - len(error_indices)

    @property
    def error_count(self) -> int:
        """Number of documents that failed processing."""
        return len(self.errors)
