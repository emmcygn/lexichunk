"""Tests for PipelineMetrics and chunk_with_metrics()."""

from __future__ import annotations

import logging

import pytest

from lexichunk import LegalChunker, PipelineMetrics, StageMetric

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

UNSTRUCTURED_TEXT = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
    "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris. "
    "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum."
)


@pytest.fixture
def chunker() -> LegalChunker:
    return LegalChunker(jurisdiction="uk", doc_type="contract")


# ---------------------------------------------------------------------------
# chunk_with_metrics() returns correct shape
# ---------------------------------------------------------------------------


class TestChunkWithMetricsShape:
    """chunk_with_metrics() returns the expected (chunks, metrics) tuple."""

    def test_returns_tuple(self, chunker: LegalChunker) -> None:
        result = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_chunks_are_list(self, chunker: LegalChunker) -> None:
        chunks, _ = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert isinstance(chunks, list)
        assert len(chunks) > 0

    def test_metrics_type(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert isinstance(metrics, PipelineMetrics)

    def test_empty_input_returns_empty(self, chunker: LegalChunker) -> None:
        chunks, metrics = chunker.chunk_with_metrics("")
        assert chunks == []
        assert isinstance(metrics, PipelineMetrics)
        assert metrics.chunk_count == 0
        assert metrics.stage_metrics == ()

    def test_whitespace_input_returns_empty(self, chunker: LegalChunker) -> None:
        chunks, metrics = chunker.chunk_with_metrics("   \n\t  ")
        assert chunks == []
        assert metrics.chunk_count == 0


# ---------------------------------------------------------------------------
# Stage metrics
# ---------------------------------------------------------------------------


class TestStageMetrics:
    """Per-stage metrics are populated correctly."""

    def test_all_seven_stages_present(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert len(metrics.stage_metrics) == 7

    def test_stage_names(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        names = [s.name for s in metrics.stage_metrics]
        assert names == [
            "structure_parsing",
            "chunking",
            "cross_reference_detection",
            "clause_type_classification",
            "context_enrichment",
            "defined_terms",
            "cross_reference_resolution",
        ]

    def test_stage_durations_positive(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        for stage in metrics.stage_metrics:
            assert isinstance(stage.duration_ms, float)
            assert stage.duration_ms >= 0.0

    def test_stage_item_counts_non_negative(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        for stage in metrics.stage_metrics:
            assert isinstance(stage.item_count, int)
            assert stage.item_count >= 0

    def test_total_duration_gte_sum_of_stages(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        stage_sum = sum(s.duration_ms for s in metrics.stage_metrics)
        assert metrics.total_duration_ms >= stage_sum * 0.99  # allow tiny float error


# ---------------------------------------------------------------------------
# Aggregate counts match actual output
# ---------------------------------------------------------------------------


class TestMetricsCounts:
    """Aggregate counts in metrics match the actual chunks."""

    def test_chunk_count_matches(self, chunker: LegalChunker) -> None:
        chunks, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert metrics.chunk_count == len(chunks)

    def test_input_chars(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        # input_chars reflects sanitised text length
        assert metrics.input_chars > 0

    def test_cross_ref_counts(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert isinstance(metrics.cross_ref_total, int)
        assert isinstance(metrics.cross_ref_resolved, int)
        assert metrics.cross_ref_resolved <= metrics.cross_ref_total

    def test_defined_term_count(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert isinstance(metrics.defined_term_count, int)
        assert metrics.defined_term_count >= 0


# ---------------------------------------------------------------------------
# Fallback detection
# ---------------------------------------------------------------------------


class TestFallbackUsed:
    """fallback_used is True when no structure is detected."""

    def test_structured_text_no_fallback(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert metrics.fallback_used is False

    def test_preamble_only_no_fallback(self, chunker: LegalChunker) -> None:
        """Plain text still parses as preamble — not fallback."""
        _, metrics = chunker.chunk_with_metrics(UNSTRUCTURED_TEXT)
        # The structure parser wraps any text as "preamble", so fallback
        # is NOT triggered for non-empty text with built-in jurisdictions.
        assert metrics.fallback_used is False

    def test_fallback_used_with_empty_parse(self) -> None:
        """Force the fallback path via a custom jurisdiction that never matches."""
        from unittest.mock import patch

        chunker = LegalChunker(jurisdiction="uk")
        with patch.object(chunker._structure_parser, "parse", return_value=[]):
            _, metrics = chunker.chunk_with_metrics(UNSTRUCTURED_TEXT)
        assert metrics.fallback_used is True


# ---------------------------------------------------------------------------
# Frozen dataclass mutation tests
# ---------------------------------------------------------------------------


class TestFrozenDataclasses:
    """PipelineMetrics and StageMetric are frozen — mutations raise TypeError."""

    def test_pipeline_metrics_frozen(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        with pytest.raises(AttributeError):
            metrics.chunk_count = 999  # type: ignore[misc]

    def test_stage_metric_frozen(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        stage = metrics.stage_metrics[0]
        with pytest.raises(AttributeError):
            stage.duration_ms = 999.0  # type: ignore[misc]

    def test_stage_metrics_tuple_immutable(self, chunker: LegalChunker) -> None:
        _, metrics = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert isinstance(metrics.stage_metrics, tuple)


# ---------------------------------------------------------------------------
# chunk() regression — behaviour unchanged
# ---------------------------------------------------------------------------


class TestChunkRegression:
    """chunk() still works identically after the _run_pipeline() refactor."""

    def test_chunk_returns_list(self, chunker: LegalChunker) -> None:
        result = chunker.chunk(STRUCTURED_TEXT)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_chunk_same_as_metrics(self, chunker: LegalChunker) -> None:
        """chunk() and chunk_with_metrics() produce identical chunks."""
        chunks_plain = chunker.chunk(STRUCTURED_TEXT)
        chunks_metr, _ = chunker.chunk_with_metrics(STRUCTURED_TEXT)
        assert len(chunks_plain) == len(chunks_metr)
        for a, b in zip(chunks_plain, chunks_metr):
            assert a.content == b.content
            assert a.clause_type == b.clause_type

    def test_chunk_empty_input(self, chunker: LegalChunker) -> None:
        assert chunker.chunk("") == []


# ---------------------------------------------------------------------------
# Structured logging at DEBUG level
# ---------------------------------------------------------------------------


class TestStructuredLogging:
    """Per-stage debug log messages appear when metrics are collected."""

    def test_debug_logs_emitted(
        self, chunker: LegalChunker, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="lexichunk.chunker"):
            chunker.chunk_with_metrics(STRUCTURED_TEXT)

        messages = [r.message for r in caplog.records]
        # Check for stage start/done messages
        assert any("structure_parsing — start" in m for m in messages)
        assert any("structure_parsing — done" in m for m in messages)
        assert any("chunking — start" in m for m in messages)
        assert any("cross_reference_detection — done" in m for m in messages)
        assert any("Pipeline complete" in m for m in messages)

    def test_chunk_no_stage_logs(
        self, chunker: LegalChunker, caplog: pytest.LogCaptureFixture
    ) -> None:
        """chunk() without metrics does not emit per-stage debug logs."""
        with caplog.at_level(logging.DEBUG, logger="lexichunk.chunker"):
            chunker.chunk(STRUCTURED_TEXT)

        messages = [r.message for r in caplog.records]
        assert not any("— start" in m for m in messages)


# ---------------------------------------------------------------------------
# document_id forwarding
# ---------------------------------------------------------------------------


class TestDocumentIdForwarding:
    """document_id is forwarded correctly through chunk_with_metrics()."""

    def test_document_id_in_chunks(self, chunker: LegalChunker) -> None:
        chunks, _ = chunker.chunk_with_metrics(STRUCTURED_TEXT, document_id="doc-42")
        for chunk in chunks:
            assert chunk.document_id == "doc-42"


# ---------------------------------------------------------------------------
# Imports from top-level
# ---------------------------------------------------------------------------


class TestImports:
    """PipelineMetrics and StageMetric are importable from lexichunk."""

    def test_import_pipeline_metrics(self) -> None:
        from lexichunk import PipelineMetrics as PM
        assert PM is PipelineMetrics

    def test_import_stage_metric(self) -> None:
        from lexichunk import StageMetric as SM
        assert SM is StageMetric
