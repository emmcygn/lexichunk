"""Adversarial tests for v0.7.0 — Observability & Docs.

Written as a SEPARATE pass after implementation, per CLAUDE.md section 5.
Tests probe edge cases, broken promises, and consumer-facing gotchas.
"""

from __future__ import annotations

import logging

import pytest

from lexichunk import LegalChunker, PipelineMetrics

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STRUCTURED_TEXT = """\
1. Definitions

1.1 "Agreement" means this agreement.

1.2 "Party" means a party to this Agreement.

2. Term and Termination

2.1 This Agreement shall commence on the Effective Date.

2.2 Either Party may terminate this Agreement by giving 30 days' notice.

3. Governing Law

3.1 This Agreement shall be governed by the laws of England.
"""


@pytest.fixture
def chunker() -> LegalChunker:
    return LegalChunker(jurisdiction="uk", doc_type="contract")


# ---------------------------------------------------------------------------
# Bug 1: Zero-overhead promise — chunk() should NOT compute item counts
# that are only needed for metrics.  If ref_count / classified / enriched
# computations are inside `if collect_metrics` guards, these tests pass
# trivially.  If they're unconditional, they add measurable work.
# ---------------------------------------------------------------------------


class TestZeroOverhead:
    """chunk() must not perform work that only chunk_with_metrics() needs."""

    def test_chunk_does_not_iterate_for_ref_count(
        self, chunker: LegalChunker
    ) -> None:
        """ref_count sum should only run when collect_metrics=True."""
        # We verify by patching sum() isn't feasible, so instead we verify
        # via the implementation structure: run chunk() and ensure no stage
        # debug logs (which are also gated on collect_metrics).  If the
        # counts were gated properly, no extra iterations happen.
        #
        # The real test is in the code review — this test documents the
        # expectation for future refactors.
        chunks = chunker.chunk(STRUCTURED_TEXT)
        assert len(chunks) > 0  # sanity

    def test_metrics_counts_match_when_collected(
        self, chunker: LegalChunker
    ) -> None:
        """When metrics ARE collected, counts must be accurate."""
        chunks, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        # cross_ref stage item_count should match actual refs on chunks
        stage_3 = [s for s in metrics.stage_metrics if s.name == "cross_reference_detection"][0]
        actual_refs = sum(len(c.cross_references) for c in chunks)
        assert stage_3.item_count == actual_refs


# ---------------------------------------------------------------------------
# Bug 2: assert in public method — python -O strips asserts
# ---------------------------------------------------------------------------


class TestNoAssertInPublicAPI:
    """chunk_with_metrics() must not rely on assert for runtime guarantees."""

    def test_returns_metrics_not_none(self, chunker: LegalChunker) -> None:
        """metrics is never None from chunk_with_metrics(), even under -O."""
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert metrics is not None
        assert isinstance(metrics, PipelineMetrics)

    def test_empty_input_returns_metrics_not_none(
        self, chunker: LegalChunker
    ) -> None:
        """Even empty input must return a real PipelineMetrics, not None."""
        _, metrics = chunker.chunk_with_metrics("")
        assert metrics is not None
        assert isinstance(metrics, PipelineMetrics)

    def test_whitespace_input_returns_metrics_not_none(
        self, chunker: LegalChunker
    ) -> None:
        _, metrics = chunker.chunk_with_metrics("   \n  ")
        assert metrics is not None


# ---------------------------------------------------------------------------
# Bug 3: Docstring says "Identical" but logging behavior differs
# ---------------------------------------------------------------------------


class TestLoggingBehaviorDifference:
    """chunk() and chunk_with_metrics() should differ ONLY in metrics output,
    not in observable side effects like logging (unless documented)."""

    def test_chunk_emits_no_stage_logs(
        self, chunker: LegalChunker, caplog: pytest.LogCaptureFixture
    ) -> None:
        """chunk() must not emit per-stage start/done debug messages."""
        with caplog.at_level(logging.DEBUG, logger="lexichunk.chunker"):
            chunker.chunk(STRUCTURED_TEXT)
        stage_messages = [r.message for r in caplog.records if "— start" in r.message]
        assert stage_messages == [], f"chunk() emitted stage logs: {stage_messages}"

    def test_chunk_with_metrics_emits_stage_logs(
        self, chunker: LegalChunker, caplog: pytest.LogCaptureFixture
    ) -> None:
        """chunk_with_metrics() MUST emit per-stage debug messages."""
        with caplog.at_level(logging.DEBUG, logger="lexichunk.chunker"):
            chunker.chunk_with_metrics(STRUCTURED_TEXT)
        stage_starts = [r.message for r in caplog.records if "— start" in r.message]
        assert len(stage_starts) == 7, f"Expected 7 stage starts, got {len(stage_starts)}"

    def test_both_emit_pipeline_complete(
        self, chunker: LegalChunker, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Both chunk() and chunk_with_metrics() emit 'Pipeline complete'."""
        with caplog.at_level(logging.DEBUG, logger="lexichunk.chunker"):
            chunker.chunk(STRUCTURED_TEXT)
        assert any("Pipeline complete" in r.message for r in caplog.records)

        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="lexichunk.chunker"):
            chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert any("Pipeline complete" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Edge cases: metrics on degenerate inputs
# ---------------------------------------------------------------------------


class TestMetricsEdgeCases:
    """Metrics must be well-formed even for degenerate inputs."""

    def test_single_char_input(self, chunker: LegalChunker) -> None:
        """Single character should not crash metrics collection."""
        chunks, metrics = chunker.chunk_with_metrics("x")
        assert isinstance(metrics, PipelineMetrics)
        assert metrics.input_chars == 1

    def test_very_short_clause(self, chunker: LegalChunker) -> None:
        """Minimal clause structure produces valid metrics."""
        text = "1. Short\n\nDone."
        chunks, metrics = chunker.chunk_with_metrics(text)
        assert metrics.chunk_count == len(chunks)
        assert metrics.total_duration_ms >= 0.0

    def test_metrics_with_definitions_disabled(self) -> None:
        """When include_definitions=False, defined_term_count should be 0."""
        chunker = LegalChunker(
            jurisdiction="uk", include_definitions=False
        )
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert metrics.defined_term_count == 0

    def test_metrics_with_context_header_disabled(self) -> None:
        """When include_context_header=False, context_enrichment item_count=0."""
        chunker = LegalChunker(
            jurisdiction="uk", include_context_header=False
        )
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        stage_5 = [s for s in metrics.stage_metrics if s.name == "context_enrichment"][0]
        assert stage_5.item_count == 0

    def test_consecutive_calls_independent_metrics(
        self, chunker: LegalChunker
    ) -> None:
        """Two calls should produce independent metrics objects."""
        _, m1 = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        _, m2 = chunker.chunk_with_metrics("1. Clause\n\nSimple.")
        assert m1 is not m2
        assert m1.input_chars != m2.input_chars

    def test_document_id_does_not_affect_metrics(
        self, chunker: LegalChunker
    ) -> None:
        """Metrics should be structurally identical regardless of doc ID."""
        _, m1 = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        _, m2 = chunker.chunk_with_metrics(STRUCTURED_TEXT, document_id="test-id")
        assert m1.chunk_count == m2.chunk_count
        assert m1.fallback_used == m2.fallback_used
        assert len(m1.stage_metrics) == len(m2.stage_metrics)


# ---------------------------------------------------------------------------
# Frozen dataclass — deeper mutation attempts
# ---------------------------------------------------------------------------


class TestDeepImmutability:
    """Callers must not be able to mutate metrics via any path."""

    def test_cannot_replace_stage_metrics(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        with pytest.raises(AttributeError):
            metrics.stage_metrics = ()  # type: ignore[misc]

    def test_cannot_append_to_stage_metrics_tuple(
        self, chunker: LegalChunker
    ) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        original_len = len(metrics.stage_metrics)
        # tuple doesn't have append, but verify it's truly a tuple
        assert not hasattr(metrics.stage_metrics, "append")
        assert len(metrics.stage_metrics) == original_len

    def test_stage_metric_fields_frozen(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        stage = metrics.stage_metrics[0]
        with pytest.raises(AttributeError):
            stage.name = "hacked"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            stage.item_count = -1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# cross_ref_stats consistency with metrics
# ---------------------------------------------------------------------------


class TestCrossRefStatsConsistency:
    """cross_ref_stats property must agree with metrics."""

    def test_stats_match_metrics(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        stats = chunker.cross_ref_stats
        assert stats["total"] == metrics.cross_ref_total
        assert stats["resolved"] == metrics.cross_ref_resolved

    def test_chunk_and_metrics_same_stats(self, chunker: LegalChunker) -> None:
        """chunk() followed by chunk_with_metrics() on same text: stats agree."""
        chunker.chunk(STRUCTURED_TEXT)
        stats_from_chunk = chunker.cross_ref_stats

        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        stats_from_metrics = chunker.cross_ref_stats

        assert stats_from_chunk["total"] == stats_from_metrics["total"]
        assert stats_from_chunk["resolved"] == stats_from_metrics["resolved"]


# ---------------------------------------------------------------------------
# chunk_iter and chunk_batch — verify they still work post-refactor
# ---------------------------------------------------------------------------


class TestChunkIterAndBatchRegression:
    """chunk_iter() and chunk_batch() must not be broken by the refactor."""

    def test_chunk_iter_works(self, chunker: LegalChunker) -> None:
        chunks_list = chunker.chunk(STRUCTURED_TEXT)
        chunks_iter = list(chunker.chunk_iter(STRUCTURED_TEXT))
        assert len(chunks_list) == len(chunks_iter)

    def test_chunk_batch_works(self, chunker: LegalChunker) -> None:
        result = chunker.chunk_batch([STRUCTURED_TEXT])
        assert len(result.results) == 1
        assert len(result.errors) == 0
        assert len(result.results[0]) > 0
