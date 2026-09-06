"""Pipeline metrics for observability."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageMetric:
    """Timing and output count for a single pipeline stage.

    Args:
        name: Machine-readable stage name (e.g. ``"structure_parsing"``).
        duration_ms: Wall-clock milliseconds spent in this stage.
        item_count: Number of items produced by this stage (chunks, terms,
            references, etc.).
    """

    name: str
    duration_ms: float
    item_count: int


@dataclass(frozen=True)
class PipelineMetrics:
    """Aggregate metrics from a single ``chunk_with_metrics()`` call.

    All timing values are wall-clock milliseconds measured with
    :func:`time.perf_counter`.

    Args:
        total_duration_ms: End-to-end pipeline duration in milliseconds.
        stage_metrics: Per-stage timing and counts, in pipeline order.
            Stored as a :class:`tuple` (immutable) — not a list.
        chunk_count: Total chunks produced.
        defined_term_count: Number of defined terms extracted (0 if
            definitions are disabled).
        cross_ref_total: Total cross-references detected across all chunks.
        cross_ref_resolved: Number of cross-references successfully resolved
            to a target chunk index.
        input_chars: Character count of the sanitised input text.
        fallback_used: ``True`` if the fallback (sentence-level) chunker
            was used instead of the clause-aware chunker.
        clause_count: Number of ``ParsedClause`` objects Stage 1 produced,
            including the synthetic preamble clause when the document has
            leading text.  ``0`` when the structure parser was bypassed.
        top_level_clause_count: Number of *root* structural units — parsed
            clauses with no parent.  For a UK contract that is the preamble
            plus each numbered top-level clause plus each Schedule; for a US
            one, each ``ARTICLE``.  This is the denominator to compare
            ``chunk_count`` against when judging whether chunking respected
            the document's own outline.
        chunks_spanning_multiple_top_level_clauses: Number of chunks whose
            ``[char_start, char_end)`` span overlaps more than one root
            structural unit.  **This is 0 by design**: the clause-aware
            chunker never merges two container-level groups, so a chunk
            cannot straddle two top-level clauses.  A non-zero value means
            a merge crossed a boundary it should not have — an over-merge
            that puts two unrelated clauses behind one embedding.
        chunks_with_multiple_clauses: Number of chunks that gathered more
            than one *distinct* clause identifier — a parent folded in with
            its sub-clauses, or a run of merged siblings.  Informational,
            not a defect: sub-clause grouping is how ``min_chunk_size`` is
            honoured without crossing hierarchy.  The pieces of one
            over-sized clause split across several chunks are **not**
            counted, since they carry a single identifier between them.
        chunks_below_min: Number of chunks whose ``token_count`` is below
            ``min_chunk_size``.  Expected to be non-zero on documents with
            short, structurally isolated clauses (``min_chunk_size`` is a
            preference; hierarchy wins), so read it as a distribution
            signal rather than an error count.
        heading_candidates_rejected: Number of lines the jurisdiction's
            ``detect_level`` proposed as headings that the structure
            parser's plausibility gate then rejected — table-of-contents
            entries, running headers, wrapped ALL-CAPS paragraphs, numbered
            list items inside a fees clause.  A sudden jump against a
            comparable document usually means the extraction layer changed,
            not the contract.
    """

    total_duration_ms: float
    stage_metrics: tuple[StageMetric, ...]
    chunk_count: int
    defined_term_count: int
    cross_ref_total: int
    cross_ref_resolved: int
    input_chars: int
    fallback_used: bool
    clause_count: int = 0
    top_level_clause_count: int = 0
    chunks_spanning_multiple_top_level_clauses: int = 0
    chunks_with_multiple_clauses: int = 0
    chunks_below_min: int = 0
    heading_candidates_rejected: int = 0
