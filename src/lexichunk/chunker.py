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
import concurrent.futures.process
import hashlib
import logging
import os
import re
import sys
import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Iterable, Mapping
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
            Affects document-section detection: with ``"terms_conditions"``,
            the signature-block heuristic is relaxed (recitals/signature
            keyword matching is skipped), which changes which chunks are
            classified as :attr:`~lexichunk.models.DocumentSection.SIGNATURES`
            (and :attr:`~lexichunk.models.DocumentSection.RECITALS`).
        max_chunk_size: Maximum chunk size in approximate tokens (1 token ≈ 4
            characters).  Enforced as a hard cap.  Defaults to 512.
        min_chunk_size: Minimum chunk size in approximate tokens.  Clauses
            smaller than this are merged with an adjacent sibling where the
            hierarchy allows; where it does not, a short chunk is emitted
            rather than folding unrelated clauses together.  Defaults to 64.
        include_definitions: When ``True``, attach relevant defined-term
            definitions to each chunk via ``defined_terms_context``.
            Defaults to ``True``.
        include_context_header: When ``True``, populate ``context_header`` on
            every chunk.  Defaults to ``True``.
        document_id: Optional document identifier embedded in every chunk and
            in the context header.  Must be ``None`` or a ``str``; invalid
            values raise :class:`~lexichunk.exceptions.ConfigurationError`
            here in ``__init__`` (the same rule is re-checked per call in
            :meth:`chunk`, where a violation raises
            :class:`~lexichunk.exceptions.InputError` instead — both
            exception types subclass ``ValueError``, so a bare
            ``except ValueError`` catches either).
        chars_per_token: Number of characters per token used for the
            approximate token count heuristic.  Defaults to 4.

    Example::

        from lexichunk import LegalChunker

        chunker = LegalChunker(jurisdiction="uk", doc_type="contract")
        chunks = chunker.chunk(contract_text)
        for chunk in chunks:
            print(chunk.clause_type, chunk.hierarchy_path)

    Thread safety:
        A single :class:`LegalChunker` instance is safe to share across
        threads for :meth:`chunk`, :meth:`chunk_with_metrics`, and
        :meth:`chunk_iter` — the definition cache is protected by an
        internal lock. The :attr:`cross_ref_stats` and
        :attr:`cross_ref_resolution_rate` properties are **not**
        thread-safe in the sense of being call-scoped: they reflect
        whichever ``chunk()`` call finished last, so under concurrent use
        from multiple threads you may read another thread's numbers. Use
        :meth:`chunk_with_metrics` for statistics scoped to a single call.
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
        # Normalise jurisdiction: Jurisdiction enum, then a stripped/lowered
        # str looked up first against the enum, then the registry.  A
        # string with padding/casing (" UK ") now resolves to the enum
        # member, not a downgraded plain string.
        if isinstance(jurisdiction, Jurisdiction):
            self._jurisdiction: Jurisdiction | str = jurisdiction
        elif isinstance(jurisdiction, str):
            key = jurisdiction.strip().lower()
            try:
                self._jurisdiction = Jurisdiction(key)
            except ValueError:
                from .jurisdiction import _JURISDICTION_REGISTRY
                if key not in _JURISDICTION_REGISTRY:
                    raise ConfigurationError(
                        f"Unknown jurisdiction {jurisdiction!r}. Built-ins: "
                        f"{', '.join(sorted(j.value for j in Jurisdiction))}. "
                        f"Register others with register_jurisdiction() first."
                    ) from None
                self._jurisdiction = key
        else:
            raise ConfigurationError(
                f"jurisdiction must be a str or Jurisdiction, got "
                f"{type(jurisdiction).__name__}"
            )

        if doc_type not in self._VALID_DOC_TYPES:
            raise ConfigurationError(
                f"Unknown doc_type {doc_type!r}. "
                f"Supported: {', '.join(sorted(self._VALID_DOC_TYPES))}"
            )
        self._doc_type = doc_type

        validated_abbreviations, validated_signals = _validate_config(
            max_chunk_size=max_chunk_size,
            min_chunk_size=min_chunk_size,
            chars_per_token=chars_per_token,
            max_cache_size=max_cache_size,
            include_definitions=include_definitions,
            include_context_header=include_context_header,
            enable_definition_cache=enable_definition_cache,
            extra_abbreviations=extra_abbreviations,
            extra_clause_signals=extra_clause_signals,
        )
        self._max_chunk_size = max_chunk_size
        self._min_chunk_size = min_chunk_size
        self._chars_per_token = chars_per_token
        self._include_definitions = include_definitions
        self._include_context_header = include_context_header
        if document_id is not None and not isinstance(document_id, str):
            raise ConfigurationError(
                f"document_id must be a string or None, got {type(document_id).__name__}"
            )
        self._document_id = document_id
        self._extra_abbreviations = validated_abbreviations
        self._extra_clause_signals = validated_signals
        self._enable_definition_cache = enable_definition_cache
        self._max_cache_size = max_cache_size
        self._definition_cache: OrderedDict[str, dict[str, DefinedTerm]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._last_cross_ref_stats: dict[str, int | float] = {}

        # Instantiate pipeline components.
        self._structure_parser = StructureParser(
            self._jurisdiction, doc_type=self._doc_type
        )
        self._definitions_extractor = DefinitionsExtractor(self._jurisdiction)
        self._reference_detector = ReferenceDetector(self._jurisdiction)
        self._clause_type_classifier = ClauseTypeClassifier(
            extra_signals=self._extra_clause_signals,
        )
        self._context_enricher = ContextEnricher()

    @property
    def jurisdiction(self) -> Jurisdiction | str:
        """The normalised jurisdiction for this chunker instance.

        A :class:`~lexichunk.models.Jurisdiction` enum member for built-ins
        (``"uk"``, ``"us"``, ``"eu"`` -- including whitespace/casing variants
        passed to ``__init__``, e.g. ``" UK "``), or the lowercase, stripped
        registry key ``str`` for a custom jurisdiction registered via
        :func:`~lexichunk.jurisdiction.register_jurisdiction`.
        """
        return self._jurisdiction

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

    @staticmethod
    def sanitize(text: str) -> str:
        """Public alias of the internal input-sanitisation step.

        :meth:`chunk`, :meth:`get_defined_terms`, and :meth:`parse_structure`
        all sanitise their input before any further processing -- stripping a
        UTF-8 BOM, normalising line endings (CRLF/CR to LF), removing null
        bytes, and applying Unicode NFC normalisation.
        Every ``LegalChunk.char_start``/``char_end`` offset indexes into
        *this sanitised string*, not the raw text you originally passed in.
        If you need to align those offsets against your original source
        (e.g. for highlighting), call ``LegalChunker.sanitize(text)``
        yourself first and index into its result.

        Args:
            text: Raw input text.

        Returns:
            The sanitised text, identical to what the pipeline processes
            internally.
        """
        return LegalChunker._sanitize_input(text)

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
                to the value passed to ``__init__``.  Must be ``None`` or a
                ``str``.

        Returns:
            List of :class:`~lexichunk.models.LegalChunk` objects in document
            order with all metadata populated.  Returned chunks are fully
            enriched; callers should not mutate the list or its elements if the
            chunker instance is reused with caching enabled.

        Raises:
            InputError: If *text* is not a ``str``, *text* exceeds the
                maximum supported input size, or *document_id* is not
                ``None``/``str``. Note this is the same ``document_id`` rule
                enforced in ``__init__`` — but a violation *there* raises
                :class:`~lexichunk.exceptions.ConfigurationError` instead.
                Both subclass ``ValueError``, so a bare
                ``except ValueError`` catches either.
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
        logger.debug(
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
                extra_abbreviations=self._extra_abbreviations,
            )
            chunks = chunker.chunk(clauses, text)
        else:
            # No structure detected — fall back to sentence-level splitting.
            # DEBUG, not WARNING: this is a normal, first-class code path
            # (FallbackChunker), and the fact is already available
            # programmatically via PipelineMetrics.fallback_used.
            logger.debug(
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
            # Detect on the chunk's own body only — `content` may have ancestor
            # headers prepended, and a reference sitting in a heading must not
            # be attributed to every descendant chunk.  The body is the trailing
            # `char_end - char_start` characters of `content` by construction.
            body_len = chunk.char_end - chunk.char_start
            body = (
                chunk.content[-body_len:]
                if 0 < body_len <= len(chunk.content)
                else chunk.content
            )
            chunk.cross_references = self._reference_detector.detect(body)
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
                with self._cache_lock:
                    hit = self._definition_cache.get(cache_key)
                    if hit is not None:
                        # True LRU: touching an entry moves it to the
                        # most-recently-used end.
                        self._definition_cache.move_to_end(cache_key)
                        defined_terms = hit
                if defined_terms is None:
                    logger.debug("Definition cache miss (key=%s…)", cache_key[:12])
                    # Extraction runs outside the lock so a slow parse on one
                    # document never blocks other threads' cache lookups.
                    defined_terms = self._definitions_extractor.extract(text)
                    with self._cache_lock:
                        self._definition_cache[cache_key] = defined_terms
                        self._definition_cache.move_to_end(cache_key)
                        # Evict least-recently-used entries. popitem(last=False)
                        # is atomic under the lock, so concurrent evictions
                        # cannot race on the same key (unlike the old
                        # next(iter(...)); del pattern).
                        while len(self._definition_cache) > self._max_cache_size:
                            self._definition_cache.popitem(last=False)
                else:
                    logger.debug("Definition cache hit (key=%s…)", cache_key[:12])
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

        Applies the same input guards as :meth:`chunk`: an empty or
        whitespace-only document short-circuits to ``{}`` without invoking
        the extractor, and input larger than ``_MAX_INPUT_CHARS`` (~10 MB)
        raises :class:`~lexichunk.exceptions.InputError`.

        Args:
            text: Full legal document as a plain-text string.

        Returns:
            Dict mapping term name to :class:`~lexichunk.models.DefinedTerm`.

        Raises:
            InputError: If *text* is not a ``str``, or exceeds the maximum
                supported input size.
        """
        if not isinstance(text, str):
            raise InputError(
                f"Expected str, got {type(text).__name__}."
            )
        text = self._sanitize_input(text)
        if not text or not text.strip():
            return {}
        if len(text) > self._MAX_INPUT_CHARS:
            raise InputError(
                f"Input text too large ({len(text)} chars). "
                f"Maximum supported: {self._MAX_INPUT_CHARS} chars."
            )
        return self._definitions_extractor.extract(text)

    def parse_structure(self, text: str) -> list[HierarchyNode]:
        """Return the parsed document structure as a list of hierarchy nodes.

        Useful for debugging and visualising the document hierarchy before
        chunking.

        Applies the same input guards as :meth:`chunk`: an empty or
        whitespace-only document short-circuits to ``[]`` without invoking
        the parser, and input larger than ``_MAX_INPUT_CHARS`` (~10 MB)
        raises :class:`~lexichunk.exceptions.InputError`.

        Args:
            text: Full legal document as a plain-text string.

        Returns:
            List of :class:`~lexichunk.models.HierarchyNode` objects in
            document order.

        Raises:
            InputError: If *text* is not a ``str``, or exceeds the maximum
                supported input size.
        """
        if not isinstance(text, str):
            raise InputError(
                f"Expected str, got {type(text).__name__}."
            )
        text = self._sanitize_input(text)
        if not text or not text.strip():
            return []
        if len(text) > self._MAX_INPUT_CHARS:
            raise InputError(
                f"Input text too large ({len(text)} chars). "
                f"Maximum supported: {self._MAX_INPUT_CHARS} chars."
            )
        return self._structure_parser.parse_structure(text)

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
        with self._cache_lock:
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

        Not call-scoped under concurrency: if this instance is shared
        across threads, this reflects whichever ``chunk()`` call finished
        most recently, which may not be the call your thread made. Use
        :meth:`chunk_with_metrics` for statistics scoped to one call.
        """
        return dict(self._last_cross_ref_stats)

    def chunk_batch(
        self,
        texts: Iterable[str | tuple[str, str | None]],
        workers: int | None = None,
    ) -> BatchResult:
        """Chunk multiple documents in one call, with optional parallelism.

        Each element of *texts* is either a plain text string or a
        ``(text, document_id)`` tuple.  Documents that raise during
        processing are recorded as errors and do not halt the batch.
        Any iterable is accepted (not just a list) and is materialised
        exactly once — including a generator, which today only worked "by
        accident" and is now a deliberate, documented part of the contract.

        Args:
            texts: An iterable of documents to chunk.  **Not** a bare
                ``str``/``bytes``/``bytearray`` — those raise
                :class:`~lexichunk.exceptions.InputError` (a bare string
                is itself an iterable of one-character strings, which
                would otherwise silently chunk it one character at a
                time). Pass ``chunk_batch([text])`` for a single document.
            workers: Number of parallel worker **processes**. ``None``
                (the default) picks ``min(cpu_count, len(texts))``. When
                *workers* is 1, or the batch has 2 or fewer documents,
                processing is serial (no subprocess overhead) regardless
                of *workers*. On Windows, *workers* is silently capped at
                61 (the ``WaitForMultipleObjects`` handle limit
                underlying :class:`~concurrent.futures.ProcessPoolExecutor`),
                logged at ``INFO`` when it actually reduces the count.

        Returns:
            :class:`~lexichunk.models.BatchResult` containing per-document
            chunk lists and any errors.

        Raises:
            InputError: If *texts* is a ``str``/``bytes``/``bytearray``, or
                is not iterable at all.
            ConfigurationError: If *workers* is not an ``int`` or is ``< 1``;
                or if a custom (non-built-in) jurisdiction is used with
                effective parallel processing, since custom registrations
                cannot be pickled to child processes.

        Note:
            **Windows/macOS entry-point guard.** ``workers > 1`` starts
            worker *processes* via :class:`~concurrent.futures.ProcessPoolExecutor`.
            On platforms using the ``spawn`` start method (Windows and
            macOS), the calling script **must** guard its entry point with
            ``if __name__ == "__main__":`` — otherwise the workers
            re-import and re-execute the calling module. If the pool
            cannot start for this reason (or any other spawn-time
            ``RuntimeError``/``OSError``), lexichunk logs a ``WARNING`` and
            falls back to processing the batch serially rather than
            raising out of ``chunk_batch`` — this preserves the "errors do
            not halt the batch" contract even when the *entire* pool fails
            to start, not just an individual document.

            **Cache asymmetry.** In serial mode, this instance's
            definition cache (see :attr:`_definition_cache`) is shared
            across every document in the batch, so duplicate documents
            benefit from cache hits. In parallel mode, each document is
            processed by a *fresh* :class:`LegalChunker` in its own worker
            process with an empty cache — duplicate content is never
            deduplicated across documents, and nothing is added to this
            instance's own cache.
        """
        if isinstance(texts, (str, bytes, bytearray)):
            raise InputError(
                f"chunk_batch() expects a sequence of documents, got "
                f"{type(texts).__name__}. Did you mean chunk_batch([text])?"
            )
        if not isinstance(texts, Iterable):
            raise InputError(
                f"chunk_batch() expects an iterable of documents, got "
                f"{type(texts).__name__}."
            )
        items = list(texts)  # materialise generators exactly once

        # Validate `workers` before any other work, per the documented
        # contract — a bad value should fail fast, not after partially
        # processing the batch.
        if workers is not None:
            if isinstance(workers, bool) or not isinstance(workers, int):
                raise ConfigurationError(
                    f"workers must be an int, got {type(workers).__name__}"
                )
            if workers < 1:
                raise ConfigurationError(f"workers ({workers}) must be >= 1")

        if not items:
            return BatchResult(results=[], errors=[])

        # Normalize inputs to (text, doc_id) pairs with validation.
        pairs: list[tuple[str, str | None]] = []
        early_errors: list[BatchError] = []
        for i, item in enumerate(items):
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
            effective_workers = workers

        # Cap to platform limit (Windows: max 61 workers).
        if sys.platform == "win32" and effective_workers > 61:
            logger.info(
                "workers (%d) exceeds the Windows ProcessPoolExecutor limit "
                "of 61 handles; using 61",
                effective_workers,
            )
            effective_workers = 61

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

        try:
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
        except (RuntimeError, OSError, concurrent.futures.process.BrokenProcessPool) as exc:
            # The pool itself failed to start (or died outright) — e.g. no
            # `if __name__ == "__main__":` guard on spawn platforms. This is
            # NOT the same as an individual document failing (handled
            # above); it means every future submitted so far is unusable.
            # Fall back to serial processing so the documented "errors do
            # not halt the batch" contract still holds even in this case.
            logger.warning(
                "Parallel batch could not start (%s: %s); falling back to "
                "serial processing. On Windows and macOS, "
                "chunk_batch(workers>1) requires the calling script to "
                "guard its entry point with: if __name__ == '__main__':",
                type(exc).__name__, exc,
            )
            return self._chunk_batch_serial(pairs, skip_indices)

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

    def __post_init__(self) -> None:
        # Re-run the same validation LegalChunker.__init__ uses, so this
        # dataclass and __init__ cannot silently drift apart (a forgotten
        # edit here used to only surface the first time an unstructured
        # document reached a worker process).
        _validate_config(
            max_chunk_size=self.max_chunk_size,
            min_chunk_size=self.min_chunk_size,
            chars_per_token=self.chars_per_token,
            max_cache_size=self.max_cache_size,
            include_definitions=self.include_definitions,
            include_context_header=self.include_context_header,
            enable_definition_cache=self.enable_definition_cache,
            extra_abbreviations=self.extra_abbreviations,
            extra_clause_signals=self.extra_clause_signals,
        )


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


def _validate_config(
    *,
    max_chunk_size: object,
    min_chunk_size: object,
    chars_per_token: object,
    max_cache_size: object,
    include_definitions: object,
    include_context_header: object,
    enable_definition_cache: object,
    extra_abbreviations: object,
    extra_clause_signals: object,
) -> tuple[list[str] | None, dict[ClauseType, list[str]] | None]:
    """Validate and normalise shared :class:`LegalChunker` configuration.

    Used by both :meth:`LegalChunker.__init__` and
    :meth:`_ChunkerConfig.__post_init__` so the two validation paths cannot
    drift out of sync — previously, adding a constructor parameter required
    four coordinated edits, and a forgotten one would silently drop that
    setting in parallel batch mode with no test to catch it.

    Args:
        max_chunk_size: Must be an ``int`` (not ``bool``), ``>= 1``.
        min_chunk_size: Must be an ``int`` (not ``bool``), ``>= 0``, and
            ``<= max_chunk_size``.
        chars_per_token: Must be an ``int`` (not ``bool``), ``>= 1``.
        max_cache_size: Must be an ``int`` (not ``bool``), ``>= 1`` (no
            longer silently clamped to 1 when out of range).
        include_definitions: Must be a ``bool``.
        include_context_header: Must be a ``bool``.
        enable_definition_cache: Must be a ``bool``.
        extra_abbreviations: ``None`` or a ``list``/``tuple`` of non-empty
            ``str``.
        extra_clause_signals: ``None`` or a :class:`~collections.abc.Mapping`
            with :class:`~lexichunk.models.ClauseType` keys and
            ``list``/``tuple`` of non-empty, non-whitespace ``str`` values.

    Returns:
        ``(extra_abbreviations, extra_clause_signals)`` as freshly
        deep-copied values safe to store on an instance — later mutation of
        the caller's original objects cannot reach the classifier or
        fallback chunker.

    Raises:
        ConfigurationError: On any invalid value.
    """

    def _check_int(name: str, value: object, minimum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigurationError(
                f"{name} must be an int, got {type(value).__name__}"
            )
        if value < minimum:
            raise ConfigurationError(f"{name} ({value}) must be >= {minimum}")

    _check_int("max_chunk_size", max_chunk_size, 1)
    _check_int("min_chunk_size", min_chunk_size, 0)
    assert isinstance(max_chunk_size, int) and isinstance(min_chunk_size, int)
    if max_chunk_size < min_chunk_size:
        raise ConfigurationError(
            f"max_chunk_size ({max_chunk_size}) must be >= "
            f"min_chunk_size ({min_chunk_size})"
        )
    _check_int("chars_per_token", chars_per_token, 1)
    _check_int("max_cache_size", max_cache_size, 1)

    for name, value in (
        ("include_definitions", include_definitions),
        ("include_context_header", include_context_header),
        ("enable_definition_cache", enable_definition_cache),
    ):
        if not isinstance(value, bool):
            raise ConfigurationError(
                f"{name} must be a bool, got {type(value).__name__}"
            )

    validated_abbreviations: list[str] | None = None
    if extra_abbreviations is not None:
        if not isinstance(extra_abbreviations, (list, tuple)):
            raise ConfigurationError(
                f"extra_abbreviations must be a list or tuple of str, got "
                f"{type(extra_abbreviations).__name__}"
            )
        for i, item in enumerate(extra_abbreviations):
            if not isinstance(item, str) or not item:
                raise ConfigurationError(
                    f"extra_abbreviations[{i}] must be a non-empty str, "
                    f"got {item!r}"
                )
        validated_abbreviations = list(extra_abbreviations)

    validated_signals: dict[ClauseType, list[str]] | None = None
    if extra_clause_signals is not None:
        if not isinstance(extra_clause_signals, Mapping):
            raise ConfigurationError(
                f"extra_clause_signals must be a Mapping, got "
                f"{type(extra_clause_signals).__name__}"
            )
        validated_signals = {}
        for key, value in extra_clause_signals.items():
            if not isinstance(key, ClauseType):
                hint = f" — use ClauseType.{key.upper()}" if isinstance(key, str) else ""
                raise ConfigurationError(
                    f"extra_clause_signals keys must be ClauseType members, "
                    f"got {key!r} ({type(key).__name__}){hint}"
                )
            if not isinstance(value, (list, tuple)):
                raise ConfigurationError(
                    f"extra_clause_signals[{key!r}] must be a list or tuple "
                    f"of str, got {type(value).__name__}"
                )
            signals: list[str] = []
            for i, sig in enumerate(value):
                if not isinstance(sig, str) or not sig.strip():
                    raise ConfigurationError(
                        f"extra_clause_signals[{key!r}][{i}] must be a "
                        f"non-empty, non-whitespace str, got {sig!r}"
                    )
                signals.append(sig)
            validated_signals[key] = signals

    return validated_abbreviations, validated_signals


def _attach_defined_terms(
    chunks: list[LegalChunk],
    defined_terms: dict[str, DefinedTerm],
) -> None:
    """Attach relevant defined terms to each chunk in-place.

    Builds a **single** alternation regex for the whole document (longest
    term first, escaped) and scans each chunk's content with one
    ``finditer()`` pass, instead of running one ``re.search()`` per
    chunk per term. This is O(chunks) rather than O(chunks × terms) — on a
    54-chunk / 20-term fixture this stage previously accounted for over a
    third of total pipeline wall time.

    The alternation is wrapped as a **zero-width lookahead**
    (``\\b(?=(?:term1|term2|...)\\b)``) rather than an ordinary consuming
    match. A consuming ``finditer`` would advance past the *entire* matched
    alternative, silently hiding any other, shorter defined term that
    starts at the same position (e.g. "SOW" inside "SOW Effective Date" —
    two independent defined terms in the same document). The zero-width
    form only *locates* candidate start positions; at each one, a small
    per-first-character bucket of individually compiled term patterns
    determines exactly which term(s) start there. This matches the
    semantics of running ``re.search()`` per term independently (every
    term that occurs anywhere is found, regardless of overlap), just in a
    single regex pass over the content instead of one Python-level loop
    iteration per term.

    For each chunk, in document order of first occurrence:

    - Appends the term to ``chunk.defined_terms_used``.
    - Adds it to ``chunk.defined_terms_context`` (term → definition text).

    Args:
        chunks: List of LegalChunk objects to enrich (mutated in-place).
        defined_terms: Dict of all defined terms in the document.
    """
    if not defined_terms:
        return

    # Longest-first is cosmetic here (candidate-position detection does not
    # depend on ordering, since the bucket check re-verifies every term
    # independently) but keeps the alternation's own match preference
    # sensible if it is ever inspected directly.
    terms = sorted((t for t in defined_terms if t), key=len, reverse=True)
    if not terms:
        return

    alternation = '|'.join(re.escape(t) for t in terms)
    candidate_pattern = re.compile(r'\b(?=(?:' + alternation + r')\b)')

    # Group individually compiled term patterns by first character, so the
    # per-position check below only re-tests the handful of terms that
    # could plausibly start there.
    by_first_char: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
    for term in terms:
        by_first_char.setdefault(term[0], []).append(
            (term, re.compile(re.escape(term) + r'\b'))
        )

    for chunk in chunks:
        content = chunk.content
        seen: set[str] = set()
        for match in candidate_pattern.finditer(content):
            pos = match.start()
            for term, term_pattern in by_first_char.get(content[pos], ()):
                if term in seen:
                    continue
                if not term_pattern.match(content, pos):
                    continue
                seen.add(term)
                dt = defined_terms.get(term)
                if dt is None:
                    continue
                chunk.defined_terms_used.append(term)
                chunk.defined_terms_context[term] = dt.definition
