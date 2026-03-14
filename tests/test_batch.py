"""Tests for chunk_batch() — serial and parallel paths."""

from __future__ import annotations

import pytest

from lexichunk import (
    BatchResult,
    ConfigurationError,
    LegalChunker,
)

_UK_DOC = """\
1. Definitions

1.1 In this Agreement, the following terms shall have the meanings set out below:

    "Service" means the software development services described in Schedule 1.

2. Obligations

2.1 The Supplier shall provide the Service in accordance with this Agreement.
"""

_US_DOC = """\
ARTICLE I
DEFINITIONS

Section 1.01. Definitions.
The following terms shall have the meanings set forth below:

"Agreement" means this Master Services Agreement.

ARTICLE II
SERVICES

Section 2.01. Scope of Services.
The Provider shall furnish the Services described in Exhibit A.
"""


# -----------------------------------------------------------------------
# Serial batch tests
# -----------------------------------------------------------------------


class TestBatchSerialSingleDoc:
    def test_single_document(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        result = chunker.chunk_batch([_UK_DOC], workers=1)
        assert isinstance(result, BatchResult)
        assert len(result.results) == 1
        assert result.total_chunks > 0
        assert result.success_count == 1
        assert result.error_count == 0


class TestBatchSerialMultipleDocs:
    def test_two_documents(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        result = chunker.chunk_batch([_UK_DOC, _UK_DOC], workers=1)
        assert len(result.results) == 2
        assert result.success_count == 2


class TestBatchSerialTupleInput:
    def test_tuple_with_doc_id(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        result = chunker.chunk_batch([(_UK_DOC, "doc-1")], workers=1)
        assert result.success_count == 1
        assert all(c.document_id == "doc-1" for c in result.results[0])


class TestBatchSerialMixedInput:
    def test_mixed_str_and_tuple(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        result = chunker.chunk_batch([_UK_DOC, (_UK_DOC, "doc-2")], workers=1)
        assert result.success_count == 2
        # First doc has no doc_id override.
        # Second doc has doc_id.
        assert all(c.document_id == "doc-2" for c in result.results[1])


class TestBatchSerialErrorCollection:
    def test_bad_doc_collected_as_error(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        # Exceed max input chars by using a huge text.
        huge = "x" * (LegalChunker._MAX_INPUT_CHARS + 1)
        result = chunker.chunk_batch([_UK_DOC, huge], workers=1)
        assert result.success_count == 1
        assert result.error_count == 1
        assert result.errors[0].index == 1
        assert result.errors[0].text_preview == huge[:100]
        assert "too large" in result.errors[0].error
        # Successful doc still has results.
        assert len(result.results[0]) > 0
        # Failed doc gets empty list.
        assert result.results[1] == []


class TestBatchSerialEmptyList:
    def test_empty_input(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        result = chunker.chunk_batch([])
        assert result.results == []
        assert result.errors == []
        assert result.total_chunks == 0


class TestBatchResultProperties:
    def test_properties(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        result = chunker.chunk_batch([_UK_DOC, _UK_DOC], workers=1)
        assert result.total_chunks == sum(len(r) for r in result.results)
        assert result.success_count == 2
        assert result.error_count == 0


class TestBatchInvalidWorkers:
    def test_workers_zero_raises(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        with pytest.raises(ConfigurationError, match="workers"):
            chunker.chunk_batch([_UK_DOC], workers=0)


# -----------------------------------------------------------------------
# Parallel batch tests
# -----------------------------------------------------------------------


class TestBatchParallelMatchesSerial:
    def test_parallel_same_as_serial(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        serial = chunker.chunk_batch([_UK_DOC, _UK_DOC, _UK_DOC], workers=1)
        parallel = chunker.chunk_batch([_UK_DOC, _UK_DOC, _UK_DOC], workers=2)

        assert serial.success_count == parallel.success_count
        assert serial.total_chunks == parallel.total_chunks
        for s_chunks, p_chunks in zip(serial.results, parallel.results):
            assert len(s_chunks) == len(p_chunks)
            for sc, pc in zip(s_chunks, p_chunks):
                assert sc.content == pc.content


class TestBatchParallelErrorCollection:
    def test_parallel_error_collected(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        huge = "x" * (LegalChunker._MAX_INPUT_CHARS + 1)
        result = chunker.chunk_batch(
            [_UK_DOC, huge, _UK_DOC, _UK_DOC], workers=2
        )
        assert result.success_count == 3
        assert result.error_count == 1
        assert result.errors[0].index == 1


class TestBatchParallelCustomJurisdictionBlocked:
    def test_custom_jurisdiction_with_workers_raises(self) -> None:
        from lexichunk.jurisdiction import register_jurisdiction
        from lexichunk.jurisdiction.uk import UKPatterns, detect_level

        register_jurisdiction("test_custom", UKPatterns(), detect_level)
        chunker = LegalChunker(jurisdiction="test_custom")
        with pytest.raises(ConfigurationError, match="Custom jurisdiction"):
            chunker.chunk_batch(
                [_UK_DOC, _UK_DOC, _UK_DOC], workers=2
            )


class TestBatchSerialFallbackForSmallBatch:
    """Even with workers>1, batches of ≤2 docs use serial path."""

    def test_small_batch_serial(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        # 2 docs with workers=4 should still work (serial fallback).
        result = chunker.chunk_batch([_UK_DOC, _UK_DOC], workers=4)
        assert result.success_count == 2
