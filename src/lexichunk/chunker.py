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
import time
import unicodedata
from dataclasses import dataclass
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

from .enrichment.clause_type import ClauseTypeClassifier
from .enrichment.context import ContextEnricher
from .exceptions import ConfigurationError, InputError
from .metrics import PipelineMetrics, StageMetric
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
        max_cache_size: int = 128,
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
        if document_id is not None and not isinstance(document_id, str):
            raise ConfigurationError(
                f"document_id must be a string or None, got {type(document_id).__name__}"
            )
        self._document_id = document_id
        self._extra_abbreviations = extra_abbreviations
        self._extra_clause_signals = extra_clause_signals
        self._enable_definition_cache = enable_definition_cache
        self._max_cache_size = max(max_cache_size, 1)
        self._definition_cache: dict[str, dict[str, DefinedTerm]] = {}
        self._last_cross_ref_stats: dict[str, int | float] = {}

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
            order with all metadata populated.  Returned chunks are fully
            enriched; callers should not mutate the list or its elements if the
            chunker instance is reused with caching enabled.
        """
        chunks, _ = self._run_pipeline(text, document_id, collect_metrics=False)
        return chunks

    def chunk_with_metrics(
        self, text: str, document_id: Optional[str] = None
    ) -> tuple[list[LegalChunk], PipelineMetrics]:
        """Chunk a legal document and return pipeline metrics.

        Runs the same pipeline as :meth:`chunk` but additionally
        instruments each stage with :func:`time.perf_counter`, emits
        per-stage ``DEBUG``-level log messages, and returns a
        :class:`~lexichunk.metrics.PipelineMetrics` object alongside
        the chunks.

        Args:
            text: Full legal document as a plain-text string.
            document_id: Override ``document_id`` for this call.  Falls back
                to the value passed to ``__init__``.

        Returns:
            A ``(chunks, metrics)`` tuple.
        """
        chunks, metrics = self._run_pipeline(text, document_id, collect_metrics=True)
        # metrics is guaranteed non-None when collect_metrics=True; cast for
        # type checkers without relying on assert (stripped by python -O).
        return chunks, metrics  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Pipeline internals
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        text: str,
        document_id: Optional[str],
        collect_metrics: bool,
    ) -> tuple[list[LegalChunk], PipelineMetrics | None]:
        """Run the full chunking pipeline.

        Args:
            text: Raw document text.
            document_id: Override document ID for this call.
            collect_metrics: When ``True``, time each stage and return
                :class:`PipelineMetrics`.

        Returns:
            ``(chunks, metrics)`` — *metrics* is ``None`` when
            *collect_metrics* is ``False``.
        """
        if not isinstance(text, str):
            raise InputError(
                f"Expected str, got {type(text).__name__}. "
                f"Pass a plain-text string to chunk()."
            )

        pipeline_start = time.perf_counter() if collect_metrics else 0.0
        stage_metrics: list[StageMetric] = []

        text = self._sanitize_input(text)

        if not text or not text.strip():
            self._last_cross_ref_stats = {"total": 0, "resolved": 0, "rate": 1.0}
            if collect_metrics:
                return [], PipelineMetrics(
                    total_duration_ms=(time.perf_counter() - pipeline_start) * 1000,
                    stage_metrics=(),
                    chunk_count=0,
                    defined_term_count=0,
                    cross_ref_total=0,
                    cross_ref_resolved=0,
                    input_chars=0,
                    fallback_used=False,
                )
            return [], None

        input_chars = len(text)

        if input_chars > self._MAX_INPUT_CHARS:
            raise InputError(
                f"Input text too large ({input_chars} chars). "
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

        if document_id is not None and not isinstance(document_id, str):
            raise InputError(
                f"document_id must be a string or None, got {type(document_id).__name__}"
            )
        doc_id = document_id if document_id is not None else self._document_id
        fallback_used = False

        # ------------------------------------------------------------------
        # Stage 1: Structure parsing
        # Input: sanitised text string.
        # Output: list[ParsedClause] with char_start/char_end/content/level.
        # ------------------------------------------------------------------
        if collect_metrics:
            logger.debug("Stage 1: structure_parsing — start")
            t0 = time.perf_counter()
        clauses = self._structure_parser.parse(text)
        if collect_metrics:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug(
                "Stage 1: structure_parsing — done (%d items, %.1fms)",
                len(clauses), elapsed,
            )
            stage_metrics.append(StageMetric("structure_parsing", elapsed, len(clauses)))

        # ------------------------------------------------------------------
        # Stage 2: Chunking
        # Input: list[ParsedClause].
        # Output: list[LegalChunk] with content, index, hierarchy,
        #   hierarchy_path, document_section, char_start, char_end,
        #   token_count, jurisdiction, document_id.
        # Unpopulated: cross_references, clause_type (UNKNOWN),
        #   classification_confidence, context_header, defined_terms_*.
        # ------------------------------------------------------------------
        if collect_metrics:
            logger.debug("Stage 2: chunking — start")
            t0 = time.perf_counter()
        # Treat preamble-only results (single level=-99 clause from headerless
        # documents) as "no structure detected" so the fallback chunker handles
        # them with proper sentence-level splitting.
        has_structure = clauses and not (
            len(clauses) == 1 and clauses[0].level == -99
        )
        if has_structure:
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
            fallback_used = True
            fallback = FallbackChunker(
                jurisdiction=self._jurisdiction,
                max_chunk_size=self._max_chunk_size,
                min_chunk_size=self._min_chunk_size,
                document_id=doc_id,
                chars_per_token=self._chars_per_token,
                extra_abbreviations=self._extra_abbreviations,
            )
            chunks = fallback.chunk(text)
        if collect_metrics:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug(
                "Stage 2: chunking — done (%d items, %.1fms)",
                len(chunks), elapsed,
            )
            stage_metrics.append(StageMetric("chunking", elapsed, len(chunks)))

        if not chunks:
            if collect_metrics:
                return [], PipelineMetrics(
                    total_duration_ms=(time.perf_counter() - pipeline_start) * 1000,
                    stage_metrics=tuple(stage_metrics),
                    chunk_count=0,
                    defined_term_count=0,
                    cross_ref_total=0,
                    cross_ref_resolved=0,
                    input_chars=input_chars,
                    fallback_used=fallback_used,
                )
            return [], None

        # Propagate document_id (ClauseAwareChunker already sets it, but
        # ensure fallback chunks also carry it).
        if doc_id is not None:
            for chunk in chunks:
                chunk.document_id = doc_id

        # ------------------------------------------------------------------
        # Stage 3: Cross-reference detection (first pass)
        # Populates: cross_references (target_chunk_index=None).
        # ------------------------------------------------------------------
        if collect_metrics:
            logger.debug("Stage 3: cross_reference_detection — start")
            t0 = time.perf_counter()
        for chunk in chunks:
            chunk.cross_references = self._reference_detector.detect(chunk.content)
        if collect_metrics:
            ref_count = sum(len(c.cross_references) for c in chunks)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug(
                "Stage 3: cross_reference_detection — done (%d items, %.1fms)",
                ref_count, elapsed,
            )
            stage_metrics.append(StageMetric("cross_reference_detection", elapsed, ref_count))

        # ------------------------------------------------------------------
        # Stage 4: Clause type classification
        # Populates: clause_type, classification_confidence,
        #   secondary_clause_type.
        # ------------------------------------------------------------------
        if collect_metrics:
            logger.debug("Stage 4: clause_type_classification — start")
            t0 = time.perf_counter()
        self._clause_type_classifier.classify_all(chunks)
        if collect_metrics:
            classified = sum(1 for c in chunks if c.clause_type is not None)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug(
                "Stage 4: clause_type_classification — done (%d items, %.1fms)",
                classified, elapsed,
            )
            stage_metrics.append(StageMetric("clause_type_classification", elapsed, classified))

        # ------------------------------------------------------------------
        # Stage 5: Context header generation
        # Populates: context_header (if include_context_header).
        # ------------------------------------------------------------------
        if collect_metrics:
            logger.debug("Stage 5: context_enrichment — start")
            t0 = time.perf_counter()
        if self._include_context_header:
            self._context_enricher.enrich_all(chunks)
        if collect_metrics:
            enriched = (
                sum(1 for c in chunks if c.context_header)
                if self._include_context_header
                else 0
            )
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug(
                "Stage 5: context_enrichment — done (%d items, %.1fms)",
                enriched, elapsed,
            )
            stage_metrics.append(StageMetric("context_enrichment", elapsed, enriched))

        # ------------------------------------------------------------------
        # Stage 6: Defined terms extraction and attachment
        # Populates: defined_terms_used, defined_terms_context.
        # ------------------------------------------------------------------
        if collect_metrics:
            logger.debug("Stage 6: defined_terms — start")
            t0 = time.perf_counter()
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
                    # Evict oldest entry (FIFO) when cache exceeds max size.
                    while len(self._definition_cache) > self._max_cache_size:
                        oldest = next(iter(self._definition_cache))
                        del self._definition_cache[oldest]
            else:
                defined_terms = self._definitions_extractor.extract(text)
            _attach_defined_terms(chunks, defined_terms)
        dt_count = len(defined_terms) if defined_terms else 0
        if collect_metrics:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug(
                "Stage 6: defined_terms — done (%d items, %.1fms)",
                dt_count, elapsed,
            )
            stage_metrics.append(StageMetric("defined_terms", elapsed, dt_count))

        # ------------------------------------------------------------------
        # Stage 7: Cross-reference resolution (second pass)
        # Populates: cross_references (with target_chunk_index resolved),
        #   cross_ref_total, cross_ref_resolved.
        # ------------------------------------------------------------------
        if collect_metrics:
            logger.debug("Stage 7: cross_reference_resolution — start")
            t0 = time.perf_counter()
        resolve_references(chunks, self._jurisdiction)

        # Populate cross-ref stats for external access.
        total = sum(c.cross_ref_total for c in chunks)
        resolved_count = sum(c.cross_ref_resolved for c in chunks)
        rate = resolved_count / total if total > 0 else 1.0
        self._last_cross_ref_stats = {
            "total": total,
            "resolved": resolved_count,
            "rate": rate,
        }
        if collect_metrics:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug(
                "Stage 7: cross_reference_resolution — done (%d items, %.1fms)",
                resolved_count, elapsed,
            )
            stage_metrics.append(StageMetric("cross_reference_resolution", elapsed, resolved_count))

        logger.debug(
            "Pipeline complete: %d chunks, %d defined terms",
            len(chunks), dt_count,
        )

        metrics: PipelineMetrics | None = None
        if collect_metrics:
            metrics = PipelineMetrics(
                total_duration_ms=(time.perf_counter() - pipeline_start) * 1000,
                stage_metrics=tuple(stage_metrics),
                chunk_count=len(chunks),
                defined_term_count=dt_count,
                cross_ref_total=total,
                cross_ref_resolved=resolved_count,
                input_chars=input_chars,
                fallback_used=fallback_used,
            )

        return chunks, metrics

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
        if not isinstance(text, str):
            raise InputError(
                f"Expected str, got {type(text).__name__}."
            )
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
        if not isinstance(text, str):
            raise InputError(
                f"Expected str, got {type(text).__name__}."
            )
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

    @property
    def cross_ref_resolution_rate(self) -> float:
        """Resolution rate from the last ``chunk()`` call (0.0–1.0).

        Returns 1.0 if no cross-references were found or if ``chunk()``
        has not been called yet.
        """
        return self._last_cross_ref_stats.get("rate", 1.0)

    @property
    def cross_ref_stats(self) -> dict[str, int | float]:
        """Cross-reference stats from the last ``chunk()`` call.

        Returns a dict with ``total``, ``resolved``, and ``rate`` keys.
        Empty dict if ``chunk()`` has not been called.
        """
        return dict(self._last_cross_ref_stats)

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
            max_cache_size=self._max_cache_size,
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
    max_cache_size: int


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
        max_cache_size=config.max_cache_size,
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
