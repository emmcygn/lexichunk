"""LegalChunker — primary public interface for lexichunk.

Orchestrates the full pipeline.  The numbering below matches the stage
numbering in ``_run_pipeline`` and the ``StageMetric.name`` values reported
by :meth:`LegalChunker.chunk_with_metrics`:

1. :class:`~lexichunk.parsers.structure.StructureParser` — detect clause boundaries
2. :class:`~lexichunk.strategies.clause_aware.ClauseAwareChunker` — split into chunks
   (or :class:`~lexichunk.strategies.fallback.FallbackChunker` when no structure found)
3. :class:`~lexichunk.parsers.references.ReferenceDetector` — detect cross-references
   (first pass, targets not yet resolved)
4. :class:`~lexichunk.enrichment.clause_type.ClauseTypeClassifier` — classify clause types
5. :class:`~lexichunk.enrichment.context.ContextEnricher` — generate context headers
6. :class:`~lexichunk.parsers.definitions.DefinitionsExtractor` — extract defined
   terms and attach the relevant ones to each chunk
7. Second-pass cross-reference resolution — fill in ``target_chunk_index``

A final bookkeeping step aggregates the cross-reference statistics exposed by
:attr:`LegalChunker.cross_ref_resolution_rate` and
:attr:`LegalChunker.cross_ref_stats`.
"""

from __future__ import annotations

import concurrent.futures
import concurrent.futures.process
import hashlib
import logging
import os
import pickle
import re
import sys
import threading
import time
import unicodedata
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Literal, Optional, overload

logger = logging.getLogger(__name__)

from .documents import build_document
from .enrichment.clause_type import ClassificationResult, ClauseTypeClassifier
from .enrichment.context import ContextEnricher
from .exceptions import ConfigurationError, InputError
from .metrics import PipelineMetrics, StageMetric
from .models import (
    BatchError,
    BatchResult,
    ClauseType,
    DefinedTerm,
    DocumentSection,
    HierarchyNode,
    Jurisdiction,
    LegalChunk,
    Section,
)
from .offsets import OffsetMap, sanitize_with_map
from .parsers.definitions import DefinitionsExtractor
from .parsers.references import ReferenceDetector, resolve_references
from .parsers.structure import ParsedClause, StructureParser
from .strategies.clause_aware import ClauseAwareChunker
from .strategies.fallback import FallbackChunker

#: Signature of the optional low-confidence classification hook.  It is
#: handed the chunk and the keyword scorer's own
#: :class:`~lexichunk.enrichment.clause_type.ClassificationResult`, and
#: returns a replacement :class:`~lexichunk.models.ClauseType` or ``None``
#: to keep the keyword verdict.
ClassificationHook = Callable[[LegalChunk, ClassificationResult], Optional[ClauseType]]


class LegalChunker:
    """Clause-aware chunker for legal documents in RAG pipelines.

    Detects clause boundaries, preserves hierarchy, extracts defined terms,
    resolves cross-references, classifies clause types, and generates
    Contextual Retrieval headers — all in a single ``chunk()`` call.

    Args:
        jurisdiction: ``"uk"``, ``"us"`` or ``"eu"`` (or a
            :class:`Jurisdiction` enum value), or the key of a custom
            jurisdiction registered via
            :func:`~lexichunk.jurisdiction.register_jurisdiction`.
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
            every chunk.  Defaults to ``True``.  This is a *separate* field
            and does not affect ``content``; see ``include_ancestor_headers``
            for that.
        include_ancestor_headers: Controls what ``chunk.content`` contains.
            When ``True`` (the default), ``content`` is the chunk's span with
            its ancestor headings prepended, so a retrieved sub-clause still
            says which clause it came from — and ``content`` is therefore
            **not** ``sanitized_text[char_start:char_end]``.  When ``False``,
            ``content`` is exactly that slice and ``original_header`` is
            empty, which is what you want when the offsets drive highlighting
            or answer-span mapping in the source document.  Either way the
            offsets themselves are correct; only ``content`` differs.
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
        extra_abbreviations: Additional abbreviations (``"e.g."``,
            ``"Ltd."``) that must not be treated as sentence boundaries.
            Passed to whichever chunking strategy runs — clause-aware or
            fallback — and merged with the built-in list, which is never
            mutated.  Defaults to ``None``.
        extra_clause_signals: Additional keyword signals per
            :class:`~lexichunk.models.ClauseType`, merged with the built-in
            signal table for classification.  The built-in table is never
            mutated.  Defaults to ``None``.  See ``docs/extending.md`` for
            the merge rules.
        enable_definition_cache: When ``True``, extracted defined terms are
            cached per instance, keyed by a SHA-256 digest of the sanitised
            text, so re-chunking the same document skips extraction.
            Defaults to ``True``.
        max_cache_size: Maximum number of documents held in that cache.
            Eviction is least-recently-used.  Defaults to 128.
        classification_hook: Optional callable
            ``(chunk, result) -> ClauseType | None`` invoked after Stage 4
            for every chunk the keyword scorer was unsure about — this is
            the seam for an LLM (or a bespoke model) that you only want to
            pay for on the hard cases.  It receives the chunk and the
            scorer's own
            :class:`~lexichunk.enrichment.clause_type.ClassificationResult`,
            including the per-clause-type ``scores`` mapping.  Return
            ``None`` to keep the keyword verdict; return a
            :class:`~lexichunk.models.ClauseType` to replace
            ``clause_type`` and set ``classification_source`` to
            ``"hook"``.  ``classification_confidence`` is left as the
            keyword scorer computed it, so the number stays comparable
            across a corpus.  Must be picklable to be used with
            ``chunk_batch(workers>1)``; a lambda or closure raises
            :class:`~lexichunk.exceptions.ConfigurationError` up front
            rather than breaking the worker pool.
        classification_hook_threshold: Confidence *strictly below* which a
            chunk is offered to *classification_hook*.  Defaults to 0.5;
            ``0.0`` never fires the hook, ``1.0`` offers every chunk.
            Note that ``classification_confidence`` is a saturation-scaled
            margin, not a calibrated probability — see
            :class:`~lexichunk.enrichment.clause_type.ClassificationResult`
            before picking a value.

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
        include_ancestor_headers: bool = True,
        document_id: Optional[str] = None,
        chars_per_token: int = 4,
        extra_abbreviations: list[str] | None = None,
        extra_clause_signals: dict[ClauseType, list[str]] | None = None,
        enable_definition_cache: bool = True,
        max_cache_size: int = 128,
        classification_hook: ClassificationHook | None = None,
        classification_hook_threshold: float = 0.5,
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
            include_ancestor_headers=include_ancestor_headers,
            enable_definition_cache=enable_definition_cache,
            extra_abbreviations=extra_abbreviations,
            extra_clause_signals=extra_clause_signals,
        )
        self._max_chunk_size = max_chunk_size
        self._min_chunk_size = min_chunk_size
        self._chars_per_token = chars_per_token
        self._include_definitions = include_definitions
        self._include_context_header = include_context_header
        self._include_ancestor_headers = include_ancestor_headers
        if document_id is not None and not isinstance(document_id, str):
            raise ConfigurationError(
                f"document_id must be a string or None, got {type(document_id).__name__}"
            )
        self._document_id = document_id
        self._extra_abbreviations = validated_abbreviations
        self._extra_clause_signals = validated_signals
        self._enable_definition_cache = enable_definition_cache
        self._max_cache_size = max_cache_size
        self._classification_hook = _validate_classification_hook(
            classification_hook, classification_hook_threshold
        )
        self._classification_hook_threshold = classification_hook_threshold
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
    # Input sanitisation
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_input(text: str) -> str:
        """Sanitize raw input text before processing.

        - Strips UTF-8 BOM (``\\ufeff``)
        - Normalises ``\\r\\n`` → ``\\n``, stray ``\\r`` → ``\\n``
        - Removes null bytes (``\\x00``)
        - Applies Unicode NFC normalisation
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
        all sanitise their input before any further processing — stripping a
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

    @staticmethod
    def sanitize_with_map(text: str) -> tuple[str, OffsetMap]:
        """Sanitise *text* and return the offset map back to the raw input.

        Same output string as :meth:`sanitize`, plus an
        :class:`~lexichunk.offsets.OffsetMap` that converts between
        sanitised offsets (what every ``LegalChunk.char_start`` /
        ``char_end`` refers to) and offsets into the string you passed in.

        Use this when you need to point at the original file — highlighting
        a chunk in a source viewer, citing back into a PDF text layer,
        producing a redline against the untouched bytes.  If you only want
        the offsets on the chunks themselves, pass ``raw_offsets=True`` to
        :meth:`chunk` instead and read ``raw_char_start``/``raw_char_end``.

        Args:
            text: Raw input text.

        Returns:
            ``(sanitised_text, offset_map)``.

        Raises:
            TypeError: If *text* is not a ``str``.

        Example::

            sanitised, offsets = LegalChunker.sanitize_with_map(raw)
            chunk = chunker.chunk(raw)[0]
            start, end = offsets.to_raw_span(chunk.char_start, chunk.char_end)
            assert LegalChunker.sanitize(raw[start:end]) == \\
                sanitised[chunk.char_start:chunk.char_end]
        """
        return sanitize_with_map(text)

    # ------------------------------------------------------------------
    # Primary public API
    # ------------------------------------------------------------------

    def chunk(
        self,
        text: str,
        document_id: Optional[str] = None,
        *,
        raw_offsets: bool = False,
    ) -> list[LegalChunk]:
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
            raw_offsets: When ``True``, also populate ``raw_char_start`` and
                ``raw_char_end`` on every chunk with offsets into *text* as
                you passed it in, before sanitisation stripped the BOM,
                folded CRLF, dropped null bytes and applied NFC.  They stay
                at their ``-1`` sentinel otherwise.  See
                :meth:`sanitize_with_map` for the mapping this uses and for
                the run-boundary semantics it guarantees.

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
        chunks, _ = self._run_pipeline(
            text, document_id, collect_metrics=False, raw_offsets=raw_offsets
        )
        return chunks

    def chunk_with_metrics(
        self,
        text: str,
        document_id: Optional[str] = None,
        *,
        raw_offsets: bool = False,
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
            raw_offsets: As for :meth:`chunk` — populate
                ``raw_char_start``/``raw_char_end`` on every chunk.

        Returns:
            A ``(chunks, metrics)`` tuple.
        """
        chunks, metrics = self._run_pipeline(
            text, document_id, collect_metrics=True, raw_offsets=raw_offsets
        )
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
        raw_offsets: bool = False,
    ) -> tuple[list[LegalChunk], PipelineMetrics | None]:
        """Run the full chunking pipeline.

        Args:
            text: Raw document text.
            document_id: Override document ID for this call.
            collect_metrics: When ``True``, time each stage and return
                :class:`PipelineMetrics`.
            raw_offsets: When ``True``, track the sanitisation offset map and
                populate ``raw_char_start``/``raw_char_end`` on every chunk.

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

        # The size guard runs on the *raw* input, before sanitisation. Running
        # it afterwards defeated its documented purpose for any content that
        # sanitises away — 15,000,000 BOM characters normalise to '' and were
        # accepted with no InputError — and, more importantly, left the cost of
        # the regex-based sanitisation pass itself unbounded: a caller could
        # force an arbitrarily large string through it before any size check
        # ran. _MAX_INPUT_CHARS is meant to be usable as a sizing contract for
        # an HTTP endpoint, which requires it to bound the raw input.
        if len(text) > self._MAX_INPUT_CHARS:
            raise InputError(
                f"Input text too large ({len(text)} chars). "
                f"Maximum supported: {self._MAX_INPUT_CHARS} chars."
            )

        offset_map: OffsetMap | None = None
        if raw_offsets:
            text, offset_map = sanitize_with_map(text)
        else:
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

        # ------------------------------------------------------------------
        # Stage 1: Structure parsing
        # Input: sanitised text string.
        # Output: list[ParsedClause] with char_start/char_end/content/level.
        # ------------------------------------------------------------------
        if collect_metrics:
            logger.debug("Stage 1: structure_parsing — start")
            t0 = time.perf_counter()
        clauses = self._structure_parser.parse(text)
        heading_candidates_rejected = self._structure_parser.last_rejected_headings
        if collect_metrics:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug(
                "Stage 1: structure_parsing — done (%d items, %.1fms)",
                len(clauses), elapsed,
            )
            stage_metrics.append(StageMetric("structure_parsing", elapsed, len(clauses)))

        return self._run_stages(
            text,
            clauses,
            doc_id,
            collect_metrics=collect_metrics,
            pipeline_start=pipeline_start,
            stage_metrics=stage_metrics,
            input_chars=input_chars,
            heading_candidates_rejected=heading_candidates_rejected,
            raw_span=offset_map.to_raw_span if offset_map is not None else None,
        )

    # ------------------------------------------------------------------
    # Pre-parsed structure entry point
    # ------------------------------------------------------------------

    @overload
    def chunk_documents(
        self,
        sections: Sequence[Section] | Sequence[ParsedClause],
        *,
        document_id: Optional[str] = ...,
        return_metrics: Literal[False] = ...,
    ) -> list[LegalChunk]: ...

    @overload
    def chunk_documents(
        self,
        sections: Sequence[Section] | Sequence[ParsedClause],
        *,
        document_id: Optional[str] = ...,
        return_metrics: Literal[True],
    ) -> tuple[list[LegalChunk], PipelineMetrics]: ...

    def chunk_documents(
        self,
        sections: Sequence[Section] | Sequence[ParsedClause],
        *,
        document_id: Optional[str] = None,
        return_metrics: bool = False,
    ) -> list[LegalChunk] | tuple[list[LegalChunk], PipelineMetrics]:
        """Chunk a document whose structure you already have.

        Runs stages 2–8 — chunking, cross-reference detection,
        classification, context headers, defined terms, resolution — on
        structure supplied by an *external* parser, skipping lexichunk's own
        line-based heading detection entirely.

        This is the "after Docling, not instead of Docling" path.  A PDF's
        own layout, or a DOCX's own outline, records where the headings were;
        flattening that to text and re-detecting headings throws the
        information away and then guesses at it.  When you have it, hand it
        over.

        Input is either a sequence of :class:`~lexichunk.models.Section`
        records — the usual case, and what
        :mod:`lexichunk.ingestion` produces — or a sequence of ready-made
        :class:`~lexichunk.parsers.structure.ParsedClause` objects, for a
        caller who has written a full parser of their own.  The two must not
        be mixed in one call.

        A document text is reconstructed from the sections, with a header
        line per section and a blank line between them, and each clause's
        ``content`` is the exact slice of it that the clause owns.  Every
        invariant ``chunk()`` guarantees therefore still holds: chunk bodies
        are literal slices, spans tile without overlap, ``max_chunk_size`` is
        a hard cap.  ``chunk.char_start``/``char_end`` index that
        reconstructed text, **not** your original source.  To get back to the
        source, give each section a ``char_start``/``char_end`` — when all of
        them carry both, ``raw_char_start``/``raw_char_end`` are populated on
        every chunk.

        Args:
            sections: The structure to chunk, in document order.
            document_id: Override ``document_id`` for this call.  Falls back
                to the value passed to ``__init__``.
            return_metrics: When ``True``, return
                ``(chunks, PipelineMetrics)`` instead of just the chunks.
                A flag rather than a second ``chunk_with_metrics_documents``
                method: the metrics are the same object
                :meth:`chunk_with_metrics` returns, and the call already
                takes keyword-only arguments, so a flag keeps one entry point
                instead of two names that would have to stay in step.
                ``PipelineMetrics.clause_count`` is the number of sections
                you supplied and ``heading_candidates_rejected`` is ``0``,
                because no heading detection ran.

        Returns:
            The chunks, or ``(chunks, metrics)`` when *return_metrics* is
            ``True``.

        Raises:
            InputError: If *sections* is not a sequence, is empty, mixes
                record types, contains an invalid record, or *document_id*
                is not ``None``/``str``.

        Example::

            from lexichunk import LegalChunker
            from lexichunk.ingestion import from_markdown

            chunker = LegalChunker(jurisdiction="uk")
            chunks = chunker.chunk_documents(from_markdown(markdown_text))
        """
        if document_id is not None and not isinstance(document_id, str):
            raise InputError(
                f"document_id must be a string or None, got "
                f"{type(document_id).__name__}"
            )
        doc_id = document_id if document_id is not None else self._document_id

        pipeline_start = time.perf_counter() if return_metrics else 0.0
        stage_metrics: list[StageMetric] = []

        # Every caller-supplied string is sanitised *before* the document is
        # assembled, so the reconstruction is sanitised by construction and
        # each clause's content is still an exact slice of it. Sanitising the
        # assembled text instead would shift offsets out from under the
        # clauses that were built from the unsanitised pieces.
        text, clauses, source_spans = build_document(
            sections,
            self._structure_parser.classify_document_section,
            self._sanitize_input,
        )
        if len(text) > self._MAX_INPUT_CHARS:
            raise InputError(
                f"Reconstructed document too large ({len(text)} chars). "
                f"Maximum supported: {self._MAX_INPUT_CHARS} chars."
            )
        if self._sanitize_input(text) != text:  # pragma: no cover - defensive
            raise InputError(
                "The reconstructed document is not stable under sanitisation, "
                "which would break the exact-slice offset invariant. This "
                "means a section's text composes with its neighbour's under "
                "Unicode NFC; please report it with the offending sections."
            )

        if return_metrics:
            stage_metrics.append(
                StageMetric("structure_parsing", 0.0, len(clauses))
            )

        chunks, metrics = self._run_stages(
            text,
            clauses,
            doc_id,
            collect_metrics=return_metrics,
            pipeline_start=pipeline_start,
            stage_metrics=stage_metrics,
            input_chars=len(text),
            heading_candidates_rejected=0,
            raw_span=source_spans,
        )
        if return_metrics:
            return chunks, metrics  # type: ignore[return-value]
        return chunks

    def _run_stages(
        self,
        text: str,
        clauses: list[ParsedClause],
        doc_id: Optional[str],
        *,
        collect_metrics: bool,
        pipeline_start: float,
        stage_metrics: list[StageMetric],
        input_chars: int,
        heading_candidates_rejected: int,
        raw_span: Callable[[int, int], tuple[int, int]] | None = None,
    ) -> tuple[list[LegalChunk], PipelineMetrics | None]:
        """Run pipeline stages 2–8 over an already-parsed clause list.

        Split out of :meth:`_run_pipeline` so that :meth:`chunk_documents`
        can supply structure from an external parser (Docling, unstructured,
        a markdown converter) and get exactly the same downstream treatment
        — chunking, cross-references, classification, context headers,
        defined terms, resolution — without lexichunk's own line-based
        heading detection ever running.

        Args:
            text: The document text *clauses* index into.  Chunk bodies are
                sliced from it directly, so the clauses' ``char_start`` and
                ``content`` must agree with it.
            clauses: Parsed clauses in document order.
            doc_id: The resolved document identifier, or ``None``.
            collect_metrics: Time each stage and build
                :class:`PipelineMetrics`.
            pipeline_start: ``time.perf_counter()`` at pipeline entry.
            stage_metrics: Accumulator the earlier stages already wrote to.
            input_chars: Character count of *text*.
            heading_candidates_rejected: Stage 1's rejection count, or ``0``
                when the structure parser was bypassed.
            raw_span: Optional ``(start, end) -> (raw_start, raw_end)``
                mapping used to populate ``raw_char_start``/``raw_char_end``.
                :meth:`~lexichunk.offsets.OffsetMap.to_raw_span` for
                :meth:`chunk`; a section-span lookup for
                :meth:`chunk_documents`.

        Returns:
            ``(chunks, metrics)`` — *metrics* is ``None`` when
            *collect_metrics* is ``False``.
        """
        fallback_used = False

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
        # Identifiers absorbed into a merged chunk (clause-aware path only);
        # handed to Stage 7 so a reference to a swallowed sub-clause still
        # resolves to the chunk that actually contains it.
        merged_identifiers: dict[int, list[str]] | None = None
        # Chunks that continue an over-sized clause started in an earlier
        # chunk; they must not register that clause's identifier a second time.
        continuation_indices: set[int] | None = None
        if has_structure:
            chunker = ClauseAwareChunker(
                jurisdiction=self._jurisdiction,
                max_chunk_size=self._max_chunk_size,
                min_chunk_size=self._min_chunk_size,
                document_id=doc_id,
                chars_per_token=self._chars_per_token,
                extra_abbreviations=self._extra_abbreviations,
                include_ancestor_headers=self._include_ancestor_headers,
            )
            chunks = chunker.chunk(clauses, text)
            merged_identifiers = chunker.last_merged_identifiers
            continuation_indices = chunker.last_continuation_indices
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
                    clause_count=len(clauses),
                    top_level_clause_count=sum(
                        1 for c in clauses if c.parent_uid is None
                    ),
                    heading_candidates_rejected=heading_candidates_rejected,
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
        classifications = self._clause_type_classifier.classify_all_detailed(chunks)
        if self._classification_hook is not None:
            self._apply_classification_hook(chunks, classifications)
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
                # ``surrogatepass`` (not plain ``utf-8``) because a document
                # decoded with ``errors="surrogateescape"`` — the standard way
                # to read a mis-encoded legal-document export without losing
                # bytes — carries unpaired surrogates that plain UTF-8 refuses
                # to encode.  Every other stage of the pipeline accepts such a
                # ``str`` happily, so the cache key must not be the one place
                # that raises.  Unpaired surrogates are preserved verbatim in
                # the chunk text; only the key derivation tolerates them.
                cache_key = hashlib.sha256(
                    text.encode("utf-8", errors="surrogatepass")
                ).hexdigest()
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
            container_terms = _extract_container_scoped_terms(
                self._definitions_extractor, text, chunks, defined_terms
            )
            _attach_defined_terms(
                chunks, defined_terms, container_terms=container_terms
            )
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
        resolve_references(
            chunks,
            self._jurisdiction,
            extra_identifiers=merged_identifiers,
            continuation_indices=continuation_indices,
        )

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

        if raw_span is not None:
            for chunk in chunks:
                chunk.raw_char_start, chunk.raw_char_end = raw_span(
                    chunk.char_start, chunk.char_end
                )

        logger.debug(
            "Pipeline complete: %d chunks, %d defined terms",
            len(chunks), dt_count,
        )

        metrics: PipelineMetrics | None = None
        if collect_metrics:
            root_units = [c for c in clauses if c.parent_uid is None]
            metrics = PipelineMetrics(
                total_duration_ms=(time.perf_counter() - pipeline_start) * 1000,
                stage_metrics=tuple(stage_metrics),
                chunk_count=len(chunks),
                defined_term_count=dt_count,
                cross_ref_total=total,
                cross_ref_resolved=resolved_count,
                input_chars=input_chars,
                fallback_used=fallback_used,
                clause_count=len(clauses),
                top_level_clause_count=len(root_units),
                chunks_spanning_multiple_top_level_clauses=(
                    _count_boundary_crossing_chunks(chunks, root_units)
                ),
                chunks_with_multiple_clauses=sum(
                    1
                    for identifiers in (merged_identifiers or {}).values()
                    if len(identifiers) > 1
                ),
                chunks_below_min=sum(
                    1 for c in chunks if c.token_count < self._min_chunk_size
                ),
                heading_candidates_rejected=heading_candidates_rejected,
                chunks_unclassified=sum(
                    1 for c in chunks if c.clause_type is ClauseType.UNKNOWN
                ),
            )

        return chunks, metrics

    def _apply_classification_hook(
        self,
        chunks: list[LegalChunk],
        classifications: list[ClassificationResult],
    ) -> None:
        """Offer every low-confidence chunk to the ``classification_hook``.

        Runs immediately after Stage 4, so the hook sees the keyword
        scorer's verdict (and its per-type scores) but nothing downstream
        has yet been derived from it — the context header generated in
        Stage 5 reflects whatever the hook decided.

        A chunk is offered when its ``classification_confidence`` is
        **strictly below** ``classification_hook_threshold``.  Returning
        ``None`` leaves the keyword result and its
        ``classification_source`` of ``"keyword"`` untouched; returning a
        :class:`~lexichunk.models.ClauseType` replaces ``clause_type`` and
        stamps ``classification_source = "hook"``.  ``confidence`` is
        deliberately *not* rewritten: it describes the keyword scorer's own
        certainty, and overwriting it with a number the hook invented would
        make the two incomparable across a corpus.

        Args:
            chunks: The chunks just classified, mutated in place.
            classifications: The matching per-chunk results.

        Raises:
            ConfigurationError: If the hook returns something that is
                neither ``None`` nor a :class:`ClauseType`.
        """
        hook = self._classification_hook
        if hook is None:  # pragma: no cover - guarded by the caller
            return
        threshold = self._classification_hook_threshold
        for chunk, result in zip(chunks, classifications):
            if result.confidence >= threshold:
                continue
            outcome = hook(chunk, result)
            if outcome is None:
                continue
            if not isinstance(outcome, ClauseType):
                raise ConfigurationError(
                    f"classification_hook must return a ClauseType or None, "
                    f"got {type(outcome).__name__} ({outcome!r}) for chunk "
                    f"{chunk.index}."
                )
            ranked_keyword_types = sorted(
                result.scores,
                key=result.scores.__getitem__,
                reverse=True,
            )
            chunk.clause_type = outcome
            chunk.secondary_clause_type = next(
                (
                    keyword_type
                    for keyword_type in ranked_keyword_types
                    if keyword_type is not outcome
                ),
                None,
            )
            chunk.classification_source = "hook"

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
        # Size guard on the raw input, before sanitisation: see _run_pipeline.
        if len(text) > self._MAX_INPUT_CHARS:
            raise InputError(
                f"Input text too large ({len(text)} chars). "
                f"Maximum supported: {self._MAX_INPUT_CHARS} chars."
            )
        text = self._sanitize_input(text)
        if not text or not text.strip():
            return {}
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
        # Size guard on the raw input, before sanitisation: see _run_pipeline.
        if len(text) > self._MAX_INPUT_CHARS:
            raise InputError(
                f"Input text too large ({len(text)} chars). "
                f"Maximum supported: {self._MAX_INPUT_CHARS} chars."
            )
        text = self._sanitize_input(text)
        if not text or not text.strip():
            return []
        return self._structure_parser.parse_structure(text)

    def chunk_iter(
        self,
        text: str,
        document_id: Optional[str] = None,
        *,
        raw_offsets: bool = False,
    ) -> Iterator[LegalChunk]:
        """Yield chunks from a legal document one at a time.

        This is a convenience wrapper around :meth:`chunk` — it runs the
        full pipeline first, then yields results.  It does **not** provide
        true streaming (cross-reference resolution and context enrichment
        are multi-chunk operations).

        Args:
            text: Full legal document as a plain-text string.
            document_id: Override ``document_id`` for this call.
            raw_offsets: As for :meth:`chunk` — populate
                ``raw_char_start``/``raw_char_end`` on every chunk.

        Yields:
            :class:`~lexichunk.models.LegalChunk` objects in document order.
        """
        yield from self.chunk(
            text, document_id=document_id, raw_offsets=raw_offsets
        )

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
        A generator that *raises* partway through is covered by the same
        "errors do not halt the batch" guarantee: the documents it already
        yielded are chunked normally and the failure is recorded as one
        :class:`~lexichunk.models.BatchError` at the index it stopped on.

        Args:
            texts: An iterable of documents to chunk.  **Not** a bare
                ``str``/``bytes``/``bytearray`` — those raise
                :class:`~lexichunk.exceptions.InputError` (a bare string
                is itself an iterable of one-character strings, which
                would otherwise silently chunk it one character at a
                time). Pass ``chunk_batch([text])`` for a single document.
                A ``dict`` (or any ``Mapping``) is rejected for the same
                reason: iterating one yields its *keys*, so
                ``chunk_batch({"doc1": text1})`` would chunk the string
                ``"doc1"`` and never look at the document. Pass
                ``mapping.values()``, or ``mapping.items()`` to use the
                keys as document ids.
            workers: Number of parallel worker **processes**. ``None``
                (the default) picks ``min(cpu_count, len(texts))``. When
                *workers* is 1, or the batch has 2 or fewer documents,
                processing is serial (no subprocess overhead) regardless
                of *workers*. On Windows, *workers* is capped at 61 (the
                ``WaitForMultipleObjects`` handle limit underlying
                :class:`~concurrent.futures.ProcessPoolExecutor`) rather
                than raising; the cap is logged at ``INFO`` when it
                actually reduces the count.

        Returns:
            :class:`~lexichunk.models.BatchResult` containing per-document
            chunk lists and any errors.

        Raises:
            InputError: If *texts* is a ``str``/``bytes``/``bytearray``, a
                ``Mapping``, or is not iterable at all.
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
        if isinstance(texts, Mapping):
            # Iterating a Mapping yields its *keys*, so
            # chunk_batch({"doc1": text1, "doc2": text2}) — an inviting call —
            # silently chunked the two short key strings and never touched the
            # documents in the values, returning a normal-looking BatchResult
            # with errors=[]. Which half the caller meant is genuinely
            # ambiguous, so reject it rather than guess.
            raise InputError(
                f"chunk_batch() expects a sequence of documents, got "
                f"{type(texts).__name__}. Iterating a mapping yields its keys; "
                f"pass chunk_batch(mapping.values()), or "
                f"chunk_batch(mapping.items()) for (text, doc_id) pairs."
            )
        if not isinstance(texts, Iterable):
            raise InputError(
                f"chunk_batch() expects an iterable of documents, got "
                f"{type(texts).__name__}."
            )
        # Materialise generators exactly once, element by element rather than
        # with list(), so a generator that raises partway through does not
        # discard everything it already yielded. The documented contract is
        # that a failure is reported per index in BatchResult.errors and does
        # not halt the batch; before this, a raising generator propagated its
        # exception straight out of chunk_batch(), unlike every other kind of
        # per-document failure.
        items: list[Any] = []
        iteration_error: Exception | None = None
        try:
            for item in texts:
                items.append(item)
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            logger.warning(
                "chunk_batch() input iterable raised after %d item(s): %s",
                len(items), exc,
            )
            iteration_error = exc

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
            return BatchResult(
                results=[],
                errors=(
                    [] if iteration_error is None
                    else [_iteration_error(items, iteration_error)]
                ),
            )

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
            if self._classification_hook is not None:
                _require_picklable_hook(self._classification_hook)
            result = self._chunk_batch_parallel(pairs, effective_workers, skip_indices)
        else:
            result = self._chunk_batch_serial(pairs, skip_indices)

        # Merge early validation errors.
        result.errors.extend(early_errors)
        if iteration_error is not None:
            result.errors.append(_iteration_error(items, iteration_error))
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
            include_ancestor_headers=self._include_ancestor_headers,
            document_id=self._document_id,
            chars_per_token=self._chars_per_token,
            extra_abbreviations=self._extra_abbreviations,
            extra_clause_signals=self._extra_clause_signals,
            enable_definition_cache=self._enable_definition_cache,
            max_cache_size=self._max_cache_size,
            classification_hook=self._classification_hook,
            classification_hook_threshold=self._classification_hook_threshold,
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
    include_ancestor_headers: bool
    document_id: str | None
    chars_per_token: int
    extra_abbreviations: list[str] | None
    extra_clause_signals: dict[ClauseType, list[str]] | None
    enable_definition_cache: bool
    max_cache_size: int
    classification_hook: ClassificationHook | None = None
    classification_hook_threshold: float = 0.5

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
            include_ancestor_headers=self.include_ancestor_headers,
            enable_definition_cache=self.enable_definition_cache,
            extra_abbreviations=self.extra_abbreviations,
            extra_clause_signals=self.extra_clause_signals,
        )
        _validate_classification_hook(
            self.classification_hook, self.classification_hook_threshold
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
        include_ancestor_headers=config.include_ancestor_headers,
        document_id=config.document_id,
        chars_per_token=config.chars_per_token,
        extra_abbreviations=config.extra_abbreviations,
        extra_clause_signals=config.extra_clause_signals,
        enable_definition_cache=config.enable_definition_cache,
        max_cache_size=config.max_cache_size,
        classification_hook=config.classification_hook,
        classification_hook_threshold=config.classification_hook_threshold,
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
    include_ancestor_headers: object,
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
        include_ancestor_headers: Must be a ``bool``.
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
        ("include_ancestor_headers", include_ancestor_headers),
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


def _validate_classification_hook(
    hook: object, threshold: object
) -> ClassificationHook | None:
    """Validate the ``classification_hook`` pair and return the hook.

    Args:
        hook: ``None`` or a callable taking ``(chunk, result)``.
        threshold: A ``float``/``int`` in ``[0.0, 1.0]``.

    Returns:
        The hook, unchanged.

    Raises:
        ConfigurationError: If *hook* is not callable, or *threshold* is not
            a number in ``[0.0, 1.0]``.
    """
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ConfigurationError(
            f"classification_hook_threshold must be a float, got "
            f"{type(threshold).__name__}"
        )
    if not 0.0 <= float(threshold) <= 1.0:
        raise ConfigurationError(
            f"classification_hook_threshold ({threshold}) must be in [0.0, 1.0]"
        )
    if hook is None:
        return None
    if not callable(hook):
        raise ConfigurationError(
            f"classification_hook must be callable or None, got "
            f"{type(hook).__name__}"
        )
    return hook  # type: ignore[return-value]


def _require_picklable_hook(hook: ClassificationHook) -> None:
    """Fail fast when a hook cannot survive the trip to a worker process.

    ``chunk_batch(workers>1)`` runs each document in a child process, so the
    hook has to be pickled along with the rest of the configuration.  A
    lambda, a local closure, or a bound method of an unpicklable object all
    fail — and the default failure mode is a
    :class:`~concurrent.futures.process.BrokenProcessPool` raised from deep
    inside the pool, or worse, a per-document ``BatchError`` that reads like
    the *documents* were bad.  Checking up front turns that into one clear
    :class:`~lexichunk.exceptions.ConfigurationError` naming the actual fix.

    Args:
        hook: The configured classification hook.

    Raises:
        ConfigurationError: If the hook cannot be pickled.
    """
    try:
        pickle.dumps(hook)
    except Exception as exc:  # noqa: BLE001 - re-raised as ConfigurationError
        name = getattr(hook, "__qualname__", repr(hook))
        raise ConfigurationError(
            f"classification_hook {name!r} cannot be pickled "
            f"({type(exc).__name__}: {exc}), so it cannot be used with "
            f"chunk_batch(workers>1) — each document is processed in a child "
            f"process. Use a module-level function (or a picklable callable "
            f"class) instead of a lambda or a closure, or pass workers=1."
        ) from exc


def _iteration_error(items: list[Any], exc: Exception) -> BatchError:
    """Build the synthetic :class:`BatchError` for a raising input iterable.

    Args:
        items: The documents successfully drawn from the iterable before it
            raised; its length is the index the failure is reported at.
        exc: The exception the iterable raised.

    Returns:
        A :class:`BatchError` describing the iteration failure.
    """
    return BatchError(
        index=len(items),
        text_preview="<input iterable>",
        error=f"Input iterable raised after {len(items)} item(s): {exc}",
        error_type=type(exc).__qualname__,
    )


def _count_boundary_crossing_chunks(
    chunks: list[LegalChunk], root_units: list[ParsedClause]
) -> int:
    """Count chunks whose span straddles two root structural units.

    A *root unit* is a parsed clause with no parent — the synthetic
    preamble, each top-level clause, each Schedule.  Their
    ``[char_start, char_end)`` spans tile the document without overlap
    (a clause only closes when a same-or-more-senior header arrives), so a
    chunk overlapping two of them has merged across a boundary the
    hierarchy says is real.

    Args:
        chunks: The emitted chunks, in document order.
        root_units: The parsed clauses with ``parent_uid is None``, in
            document order.

    Returns:
        The number of offending chunks — expected to be ``0``.
    """
    if len(root_units) < 2:
        return 0
    starts = [unit.char_start for unit in root_units]
    crossing = 0
    for chunk in chunks:
        if chunk.char_end <= chunk.char_start:
            continue
        # Number of unit boundaries strictly inside the chunk's own span.
        first = bisect_right(starts, chunk.char_start)
        last = bisect_left(starts, chunk.char_end)
        if last > first:
            crossing += 1
    return crossing


def _container_key(chunk: LegalChunk) -> str:
    """Return the top-level container a chunk sits under.

    Args:
        chunk: The chunk whose enclosing container is wanted.

    Returns:
        The first segment of ``hierarchy_path`` (e.g. ``"Schedule 2"``), or
        the empty string when the chunk has no path.
    """
    return chunk.hierarchy_path.split(" > ")[0].strip()


def _extract_container_scoped_terms(
    extractor: DefinitionsExtractor,
    text: str,
    chunks: list[LegalChunk],
    defined_terms: dict[str, DefinedTerm],
) -> dict[str, dict[str, DefinedTerm]]:
    """Re-extract definitions separately inside each Schedule-like container.

    A term defined in the main body and then explicitly redefined for one
    schedule — ``For the purposes of this Schedule 2 only, "Services" means
    the managed hosting services ...`` — is routine drafting, and the
    schedule-local meaning is the one that governs text inside that schedule.
    A single flat term dictionary cannot express that, so every chunk inside
    Schedule 2 was handed the main-body definition: the wrong legal meaning,
    fed straight into ``defined_terms_context`` and the ``context_header``
    that a RAG pipeline embeds.

    Args:
        extractor: The extractor to reuse for the per-container passes.
        text: The full sanitised document text.
        chunks: The chunks produced for *text*.
        defined_terms: The document-wide term dictionary.

    Returns:
        A mapping from container identifier (the first segment of
        ``hierarchy_path``) to that container's own term dictionary.  Empty
        when the document has no schedule containers or no defined terms —
        in which case no extra extraction work is done at all.
    """
    if not defined_terms:
        return {}

    spans: dict[str, list[int]] = {}
    for chunk in chunks:
        if chunk.document_section is not DocumentSection.SCHEDULES:
            continue
        key = _container_key(chunk)
        if not key:
            continue
        span = spans.get(key)
        if span is None:
            spans[key] = [chunk.char_start, chunk.char_end]
        else:
            span[0] = min(span[0], chunk.char_start)
            span[1] = max(span[1], chunk.char_end)

    container_terms: dict[str, dict[str, DefinedTerm]] = {}
    for key, (start, end) in spans.items():
        local = extractor.extract_from_section(text[start:end], key)
        if local:
            container_terms[key] = local
    return container_terms


def _attach_defined_terms(
    chunks: list[LegalChunk],
    defined_terms: dict[str, DefinedTerm],
    *,
    container_terms: Optional[dict[str, dict[str, DefinedTerm]]] = None,
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

    **Scoping rule.** When a term is defined more than once, the definition
    attached to a chunk is the one from the nearest enclosing container — the
    schedule the chunk sits in, if that schedule defines the term itself —
    and otherwise the main-body one.  This is what makes
    ``For the purposes of this Schedule 2 only, "Services" means ...``
    govern the chunks inside Schedule 2 while leaving the rest of the
    agreement on the main-body meaning.

    Args:
        chunks: List of LegalChunk objects to enrich (mutated in-place).
        defined_terms: Dict of all defined terms in the document.
        container_terms: Optional mapping from container identifier to that
            container's own term dictionary, as built by
            :func:`_extract_container_scoped_terms`.  A term present there
            overrides the document-wide definition for chunks inside that
            container.
    """
    if not defined_terms:
        return
    container_terms = container_terms or {}

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
        local_terms = container_terms.get(_container_key(chunk), {})
        seen: set[str] = set()
        for match in candidate_pattern.finditer(content):
            pos = match.start()
            for term, term_pattern in by_first_char.get(content[pos], ()):
                if term in seen:
                    continue
                if not term_pattern.match(content, pos):
                    continue
                seen.add(term)
                # Nearest enclosing container wins over the main body.
                dt = local_terms.get(term) or defined_terms.get(term)
                if dt is None:
                    continue
                chunk.defined_terms_used.append(term)
                chunk.defined_terms_context[term] = dt.definition
