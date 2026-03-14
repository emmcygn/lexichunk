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

import concurrent.futures
import hashlib
import logging
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

from .enrichment.clause_type import ClauseTypeClassifier
from .enrichment.context import ContextEnricher
from .exceptions import ConfigurationError, InputError
from .models import (
    BatchError,
    BatchResult,
    ClauseType,
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
        extra_abbreviations: list[str] | None = None,
        extra_clause_signals: dict[ClauseType, list[str]] | None = None,
        enable_definition_cache: bool = True,
    ) -> None:
        # Normalise jurisdiction: try enum first, then registry lookup.
        if isinstance(jurisdiction, str):
            try:
                self._jurisdiction: Jurisdiction | str = Jurisdiction(jurisdiction.lower())
            except ValueError:
                # Not a built-in enum value — check the registry.
                from .jurisdiction import _JURISDICTION_REGISTRY
                if jurisdiction.lower().strip() not in _JURISDICTION_REGISTRY:
                    raise ConfigurationError(
                        f"Unknown jurisdiction {jurisdiction!r}. "
                        f"Register it with register_jurisdiction() first."
                    )
                self._jurisdiction = jurisdiction.lower().strip()
        else:
            self._jurisdiction = jurisdiction

        if doc_type not in self._VALID_DOC_TYPES:
            raise ConfigurationError(
                f"Unknown doc_type {doc_type!r}. "
                f"Supported: {', '.join(sorted(self._VALID_DOC_TYPES))}"
            )
        self._doc_type = doc_type

        if max_chunk_size < 1:
            raise ConfigurationError(
                f"max_chunk_size ({max_chunk_size}) must be >= 1"
            )
        if min_chunk_size < 0:
            raise ConfigurationError(
                f"min_chunk_size ({min_chunk_size}) must be >= 0"
            )
        if max_chunk_size < min_chunk_size:
            raise ConfigurationError(
                f"max_chunk_size ({max_chunk_size}) must be >= "
                f"min_chunk_size ({min_chunk_size})"
            )
        self._max_chunk_size = max_chunk_size
        self._min_chunk_size = min_chunk_size
        if chars_per_token < 1:
            raise ConfigurationError(
                f"chars_per_token ({chars_per_token}) must be >= 1"
            )
        self._chars_per_token = chars_per_token
        self._include_definitions = include_definitions
        self._include_context_header = include_context_header
        self._document_id = document_id
        self._extra_abbreviations = extra_abbreviations
        self._extra_clause_signals = extra_clause_signals
        self._enable_definition_cache = enable_definition_cache
        self._definition_cache: dict[str, dict[str, DefinedTerm]] = {}

        # Instantiate pipeline components.
        self._structure_parser = StructureParser(
            self._jurisdiction, doc_type=self._doc_type
        )
        self._definitions_extractor = DefinitionsExtractor(self._jurisdiction)
        self._reference_detector = ReferenceDetector(self._jurisdiction)
        self._clause_type_classifier = ClauseTypeClassifier(
            extra_signals=extra_clause_signals,
        )
        self._context_enricher = ContextEnricher()

    # ------------------------------------------------------------------
    # Input sanitization
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_input(text: str) -> str:
        """Sanitize raw input text before processing.

        - Strips UTF-8 BOM (``\\ufeff``)
        - Normalizes ``\\r\\n`` → ``\\n``, stray ``\\r`` → ``\\n``
        - Removes null bytes (``\\x00``)
        - Applies Unicode NFC normalization
        """
        text = text.replace("\ufeff", "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\x00", "")
        text = unicodedata.normalize("NFC", text)
        return text

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
        text = self._sanitize_input(text)

        if not text or not text.strip():
            return []

        if len(text) > self._MAX_INPUT_CHARS:
            raise InputError(
                f"Input text too large ({len(text)} chars). "
                f"Maximum supported: {self._MAX_INPUT_CHARS} chars."
            )

        jur_label = (
            self._jurisdiction.value
            if isinstance(self._jurisdiction, Jurisdiction)
            else self._jurisdiction
        )
        logger.info(
            "Chunking document (%d chars, jurisdiction=%s, doc_type=%s)",
            len(text), jur_label, self._doc_type,
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
                extra_abbreviations=self._extra_abbreviations,
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
            if self._enable_definition_cache:
                cache_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if cache_key in self._definition_cache:
                    logger.debug("Definition cache hit (key=%s…)", cache_key[:12])
                    defined_terms = self._definition_cache[cache_key]
                else:
                    defined_terms = self._definitions_extractor.extract(text)
                    self._definition_cache[cache_key] = defined_terms
            else:
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
        return self._definitions_extractor.extract(self._sanitize_input(text))

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
        return self._structure_parser.parse_structure(self._sanitize_input(text))

    def chunk_iter(
        self, text: str, document_id: Optional[str] = None
    ) -> Iterator[LegalChunk]:
        """Yield chunks from a legal document one at a time.

        This is a convenience wrapper around :meth:`chunk` — it runs the
        full pipeline first, then yields results.  It does **not** provide
        true streaming (cross-reference resolution and context enrichment
        are multi-chunk operations).

        Args:
            text: Full legal document as a plain-text string.
            document_id: Override ``document_id`` for this call.

        Yields:
            :class:`~lexichunk.models.LegalChunk` objects in document order.
        """
        yield from self.chunk(text, document_id=document_id)

    def clear_definition_cache(self) -> None:
        """Clear the definition extraction cache.

        Useful when the same :class:`LegalChunker` instance is reused
        across different document versions whose definitions may have
        changed.
        """
        self._definition_cache.clear()

    def chunk_batch(
        self,
        texts: list[str | tuple[str, str | None]],
        workers: int | None = None,
    ) -> BatchResult:
        """Chunk multiple documents in one call, with optional parallelism.

        Each element of *texts* is either a plain text string or a
        ``(text, document_id)`` tuple.  Documents that raise during
        processing are recorded as errors and do not halt the batch.

        Args:
            texts: List of documents to chunk.
            workers: Number of parallel worker processes.  Defaults to
                ``min(cpu_count, len(texts))``.  When *workers* is 1 or
                the batch has ≤2 documents, processing is serial (no
                subprocess overhead).

        Returns:
            :class:`~lexichunk.models.BatchResult` containing per-document
            chunk lists and any errors.

        Raises:
            ConfigurationError: If a custom (non-built-in) jurisdiction
                is used with ``workers > 1``, since custom registrations
                cannot be pickled to child processes.
        """
        if not texts:
            return BatchResult(results=[], errors=[])

        # Normalize inputs to (text, doc_id) pairs with validation.
        pairs: list[tuple[str, str | None]] = []
        early_errors: list[BatchError] = []
        for i, item in enumerate(texts):
            if isinstance(item, tuple):
                if len(item) != 2:
                    early_errors.append(BatchError(
                        index=i,
                        text_preview=repr(item)[:100],
                        error=f"Tuple must have exactly 2 elements (text, doc_id), got {len(item)}",
                        error_type="ValueError",
                    ))
                    pairs.append(("", None))  # placeholder
                    continue
                text_val, doc_id_val = item
                if not isinstance(text_val, str):
                    early_errors.append(BatchError(
                        index=i,
                        text_preview=repr(text_val)[:100],
                        error=f"Expected str for text, got {type(text_val).__name__}",
                        error_type="TypeError",
                    ))
                    pairs.append(("", None))
                    continue
                pairs.append((text_val, doc_id_val))
            elif isinstance(item, str):
                pairs.append((item, None))
            else:
                early_errors.append(BatchError(
                    index=i,
                    text_preview=repr(item)[:100],
                    error=f"Expected str or (str, str|None) tuple, got {type(item).__name__}",
                    error_type="TypeError",
                ))
                pairs.append(("", None))  # placeholder

        # Indices that already failed validation — skip during processing.
        skip_indices = {e.index for e in early_errors}

        # Determine effective worker count.
        if workers is None:
            cpu = os.cpu_count() or 1
            effective_workers = min(cpu, len(pairs))
        else:
            if workers < 1:
                raise ConfigurationError(f"workers ({workers}) must be >= 1")
            effective_workers = workers

        # Cap to platform limit (Windows: max 61 workers).
        if sys.platform == "win32":
            effective_workers = min(effective_workers, 61)

        # Serial fallback for small batches or workers=1.
        use_parallel = effective_workers > 1 and len(pairs) > 2

        if use_parallel:
            # Validate: custom jurisdictions can't be pickled.
            if not isinstance(self._jurisdiction, Jurisdiction):
                raise ConfigurationError(
                    f"Custom jurisdiction {self._jurisdiction!r} cannot be used "
                    f"with workers > 1. Custom jurisdiction registrations are "
                    f"not inherited by child processes. Use workers=1 instead."
                )
            result = self._chunk_batch_parallel(pairs, effective_workers, skip_indices)
        else:
            result = self._chunk_batch_serial(pairs, skip_indices)

        # Merge early validation errors.
        result.errors.extend(early_errors)
        return result

    # ------------------------------------------------------------------
    # Batch internals
    # ------------------------------------------------------------------

    def _chunk_batch_serial(
        self,
        pairs: list[tuple[str, str | None]],
        skip_indices: set[int],
    ) -> BatchResult:
        """Process a batch of documents serially."""
        results: list[list[LegalChunk]] = []
        errors: list[BatchError] = []
        for i, (text, doc_id) in enumerate(pairs):
            if i in skip_indices:
                results.append([])
                continue
            try:
                chunks = self.chunk(text, document_id=doc_id)
                results.append(chunks)
            except Exception as exc:
                results.append([])
                errors.append(BatchError(
                    index=i,
                    text_preview=text[:100],
                    error=str(exc),
                    error_type=type(exc).__qualname__,
                ))
        return BatchResult(results=results, errors=errors)

    def _chunk_batch_parallel(
        self,
        pairs: list[tuple[str, str | None]],
        workers: int,
        skip_indices: set[int],
    ) -> BatchResult:
        """Process a batch of documents in parallel using ProcessPoolExecutor."""
        assert isinstance(self._jurisdiction, Jurisdiction)  # validated by caller
        config = _ChunkerConfig(
            jurisdiction=self._jurisdiction,
            doc_type=self._doc_type,
            max_chunk_size=self._max_chunk_size,
            min_chunk_size=self._min_chunk_size,
            include_definitions=self._include_definitions,
            include_context_header=self._include_context_header,
            document_id=self._document_id,
            chars_per_token=self._chars_per_token,
            extra_abbreviations=self._extra_abbreviations,
            extra_clause_signals=self._extra_clause_signals,
            enable_definition_cache=self._enable_definition_cache,
        )

        results: list[list[LegalChunk]] = [[] for _ in pairs]
        errors: list[BatchError] = []

        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            future_to_idx: dict[concurrent.futures.Future[list[LegalChunk]], int] = {}
            for i, (text, doc_id) in enumerate(pairs):
                if i in skip_indices:
                    continue
                fut = pool.submit(_chunk_single, config, text, doc_id)
                future_to_idx[fut] = i

            for fut in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[fut]
                try:
                    results[idx] = fut.result()
                except Exception as exc:
                    text_preview = pairs[idx][0][:100]
                    errors.append(BatchError(
                        index=idx,
                        text_preview=text_preview,
                        error=str(exc),
                        error_type=type(exc).__qualname__,
                    ))

        return BatchResult(results=results, errors=errors)


# ---------------------------------------------------------------------------
# Parallel worker config + function
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ChunkerConfig:
    """Serialisable snapshot of LegalChunker configuration for child processes."""

    jurisdiction: Jurisdiction
    doc_type: str
    max_chunk_size: int
    min_chunk_size: int
    include_definitions: bool
    include_context_header: bool
    document_id: str | None
    chars_per_token: int
    extra_abbreviations: list[str] | None
    extra_clause_signals: dict[ClauseType, list[str]] | None
    enable_definition_cache: bool


def _chunk_single(
    config: _ChunkerConfig, text: str, doc_id: str | None
) -> list[LegalChunk]:
    """Worker function for parallel batch processing.

    Creates a fresh :class:`LegalChunker` from the config and processes
    a single document.  Runs in a child process via ProcessPoolExecutor.
    """
    chunker = LegalChunker(
        jurisdiction=config.jurisdiction,
        doc_type=config.doc_type,
        max_chunk_size=config.max_chunk_size,
        min_chunk_size=config.min_chunk_size,
        include_definitions=config.include_definitions,
        include_context_header=config.include_context_header,
        document_id=config.document_id,
        chars_per_token=config.chars_per_token,
        extra_abbreviations=config.extra_abbreviations,
        extra_clause_signals=config.extra_clause_signals,
        enable_definition_cache=config.enable_definition_cache,
    )
    return chunker.chunk(text, document_id=doc_id)


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
