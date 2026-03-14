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
    """

    total_duration_ms: float
    stage_metrics: tuple[StageMetric, ...]
    chunk_count: int
    defined_term_count: int
    cross_ref_total: int
    cross_ref_resolved: int
    input_chars: int
    fallback_used: bool
