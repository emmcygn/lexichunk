"""LegalChunker — primary public interface for lexichunk.

Orchestrates the full pipeline:

1. :class:`~lexichunk.parsers.structure.StructureParser` — detect clause boundaries
2. :class:`~lexichunk.strategies.clause_aware.ClauseAwareChunker` — split into chunks
   (or :class:`~lexichunk.strategies.fallback.FallbackChunker` when no structure found)
3. :class:`~lexichunk.parsers.definitions.DefinitionsExtractor` — extract defined terms
4. :class:`~lexichunk.parsers.references.ReferenceDetector` — detect cross-references
5. :class:`~lexichunk.enrichment.clause_type.ClauseTypeClassifier` — classify clause types
6. :class:`~lexichunk.enrichment.context.ContextEnricher` — generate context headers
7. Second-pass cross-reference resolution
8. Attach relevant defined terms to each chunk
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

from .enrichment.clause_type import ClauseTypeClassifier
from .enrichment.context import ContextEnricher
from .models import (
    DefinedTerm,
    HierarchyNode,
    Jurisdiction,
    LegalChunk,
)
from .parsers.definitions import DefinitionsExtractor
from .parsers.references import ReferenceDetector, resolve_references
from .parsers.structure import StructureParser
from .strategies.clause_aware import ClauseAwareChunker
from .strategies.fallback import FallbackChunker


class LegalChunker:
    """Intelligent chunker for legal documents optimised for RAG pipelines.

    Detects clause boundaries, preserves hierarchy, extracts defined terms,
    resolves cross-references, classifies clause types, and generates
    Contextual Retrieval headers — all in a single ``chunk()`` call.

    Args:
        jurisdiction: ``"uk"`` or ``"us"`` (or a :class:`Jurisdiction` enum value).
        doc_type: Document type hint — ``"contract"`` or ``"terms_conditions"``.
            Currently informational; reserved for future specialisation.
        max_chunk_size: Maximum chunk size in approximate tokens (1 token ≈ 4
            characters).  Defaults to 512.
        min_chunk_size: Minimum chunk size in approximate tokens.  Clauses
            smaller than this are merged with their neighbour.  Defaults to 64.
        include_definitions: When ``True``, attach relevant defined-term
            definitions to each chunk via ``defined_terms_context``.
            Defaults to ``True``.
        include_context_header: When ``True``, populate ``context_header`` on
            every chunk.  Defaults to ``True``.
        document_id: Optional document identifier embedded in every chunk and
            in the context header.
        chars_per_token: Number of characters per token used for the
            approximate token count heuristic.  Defaults to 4.

    Example::

        from lexichunk import LegalChunker

        chunker = LegalChunker(jurisdiction="uk", doc_type="contract")
        chunks = chunker.chunk(contract_text)
        for chunk in chunks:
            print(chunk.clause_type, chunk.hierarchy_path)
    """

    _MAX_INPUT_CHARS = 10_000_000  # ~10 MB, configurable via subclass
    _VALID_DOC_TYPES = {"contract", "terms_conditions"}

    def __init__(
        self,
        jurisdiction: str | Jurisdiction = "uk",
        doc_type: str = "contract",
        max_chunk_size: int = 512,
        min_chunk_size: int = 64,
        include_definitions: bool = True,
        include_context_header: bool = True,
        document_id: Optional[str] = None,
        chars_per_token: int = 4,
    ) -> None:
        # Normalise jurisdiction to enum.
        if isinstance(jurisdiction, str):
            self._jurisdiction = Jurisdiction(jurisdiction.lower())
        else:
            self._jurisdiction = jurisdiction

        if doc_type not in self._VALID_DOC_TYPES:
            raise ValueError(
                f"Unknown doc_type {doc_type!r}. "
                f"Supported: {', '.join(sorted(self._VALID_DOC_TYPES))}"
            )
        self._doc_type = doc_type

        if max_chunk_size < min_chunk_size:
            raise ValueError(
                f"max_chunk_size ({max_chunk_size}) must be >= "
                f"min_chunk_size ({min_chunk_size})"
            )
        self._max_chunk_size = max_chunk_size
        self._min_chunk_size = min_chunk_size
        if chars_per_token < 1:
            raise ValueError(
                f"chars_per_token ({chars_per_token}) must be >= 1"
            )
        self._chars_per_token = chars_per_token
        self._include_definitions = include_definitions
        self._include_context_header = include_context_header
        self._document_id = document_id

        # Instantiate pipeline components.
        self._structure_parser = StructureParser(
            self._jurisdiction, doc_type=self._doc_type
        )
        self._definitions_extractor = DefinitionsExtractor(self._jurisdiction)
        self._reference_detector = ReferenceDetector(self._jurisdiction)
        self._clause_type_classifier = ClauseTypeClassifier()
        self._context_enricher = ContextEnricher()

    # ------------------------------------------------------------------
    # Primary public API
    # ------------------------------------------------------------------

    def chunk(self, text: str, document_id: Optional[str] = None) -> list[LegalChunk]:
        """Chunk a legal document into enriched :class:`~lexichunk.models.LegalChunk` objects.

        Runs the full pipeline:

        1. Structure parsing → flat list of ``ParsedClause`` objects.
        2. Clause-aware chunking (or fallback if no structure detected).
        3. Cross-reference detection on each chunk.
        4. Clause type classification.
        5. Context header generation (if enabled).
        6. Defined term extraction and attachment (if enabled).
        7. Cross-reference resolution (second pass).

        Args:
            text: Full legal document as a plain-text string.
            document_id: Override ``document_id`` for this call.  Falls back
                to the value passed to ``__init__``.

        Returns:
            List of :class:`~lexichunk.models.LegalChunk` objects in document
            order with all metadata populated.
        """
        if not text or not text.strip():
            return []

        if len(text) > self._MAX_INPUT_CHARS:
            raise ValueError(
                f"Input text too large ({len(text)} chars). "
                f"Maximum supported: {self._MAX_INPUT_CHARS} chars."
            )

        logger.info(
            "Chunking document (%d chars, jurisdiction=%s, doc_type=%s)",
            len(text), self._jurisdiction.value, self._doc_type,
        )

        doc_id = document_id if document_id is not None else self._document_id

        # ------------------------------------------------------------------
        # Stage 1: Structure parsing
        # ------------------------------------------------------------------
        clauses = self._structure_parser.parse(text)

        # ------------------------------------------------------------------
        # Stage 2: Chunking
        # ------------------------------------------------------------------
        if clauses:
            chunker = ClauseAwareChunker(
                jurisdiction=self._jurisdiction,
                max_chunk_size=self._max_chunk_size,
                min_chunk_size=self._min_chunk_size,
                document_id=doc_id,
                chars_per_token=self._chars_per_token,
            )
            chunks = chunker.chunk(clauses, text)
        else:
            # No structure detected — fall back to sentence-level splitting.
            logger.warning(
                "No clause structure detected — falling back to sentence-level splitting"
            )
            fallback = FallbackChunker(
                jurisdiction=self._jurisdiction,
                max_chunk_size=self._max_chunk_size,
                min_chunk_size=self._min_chunk_size,
                document_id=doc_id,
                chars_per_token=self._chars_per_token,
            )
            chunks = fallback.chunk(text)

        if not chunks:
            return []

        # Propagate document_id (ClauseAwareChunker already sets it, but
        # ensure fallback chunks also carry it).
        if doc_id is not None:
            for chunk in chunks:
                chunk.document_id = doc_id

        # ------------------------------------------------------------------
        # Stage 3: Cross-reference detection (first pass)
        # ------------------------------------------------------------------
        for chunk in chunks:
            chunk.cross_references = self._reference_detector.detect(chunk.content)

        # ------------------------------------------------------------------
        # Stage 4: Clause type classification
        # ------------------------------------------------------------------
        self._clause_type_classifier.classify_all(chunks)

        # ------------------------------------------------------------------
        # Stage 5: Context header generation
        # ------------------------------------------------------------------
        if self._include_context_header:
            self._context_enricher.enrich_all(chunks)

        # ------------------------------------------------------------------
        # Stage 6: Defined terms extraction and attachment
        # ------------------------------------------------------------------
        defined_terms: dict[str, DefinedTerm] | None = None
        if self._include_definitions:
            defined_terms = self._definitions_extractor.extract(text)
            _attach_defined_terms(chunks, defined_terms)

        # ------------------------------------------------------------------
        # Stage 7: Cross-reference resolution (second pass)
        # ------------------------------------------------------------------
        resolve_references(chunks, self._jurisdiction)

        logger.debug(
            "Pipeline complete: %d chunks, %d defined terms",
            len(chunks),
            len(defined_terms) if defined_terms else 0,
        )

        return chunks

    # ------------------------------------------------------------------
    # Additional public methods
    # ------------------------------------------------------------------

    def get_defined_terms(self, text: str) -> dict[str, DefinedTerm]:
        """Extract all defined terms from a legal document.

        Args:
            text: Full legal document as a plain-text string.

        Returns:
            Dict mapping term name to :class:`~lexichunk.models.DefinedTerm`.
        """
        return self._definitions_extractor.extract(text)

    def parse_structure(self, text: str) -> list[HierarchyNode]:
        """Return the parsed document structure as a list of hierarchy nodes.

        Useful for debugging and visualising the document hierarchy before
        chunking.

        Args:
            text: Full legal document as a plain-text string.

        Returns:
            List of :class:`~lexichunk.models.HierarchyNode` objects in
            document order.
        """
        return self._structure_parser.parse_structure(text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _attach_defined_terms(
    chunks: list[LegalChunk],
    defined_terms: dict[str, DefinedTerm],
) -> None:
    """Attach relevant defined terms to each chunk in-place.

    For each chunk, scans ``chunk.content`` for occurrences of each known
    defined term.  When a term is found:

    - Appends it to ``chunk.defined_terms_used``.
    - Adds it to ``chunk.defined_terms_context`` (term → definition text).

    Args:
        chunks: List of LegalChunk objects to enrich (mutated in-place).
        defined_terms: Dict of all defined terms in the document.
    """
    if not defined_terms:
        return

    for chunk in chunks:
        content = chunk.content
        for term, dt in defined_terms.items():
            if re.search(r'\b' + re.escape(term) + r'\b', content):
                if term not in chunk.defined_terms_used:
                    chunk.defined_terms_used.append(term)
                    chunk.defined_terms_context[term] = dt.definition
