"""Tests for the chunk_iter() generator API."""

from __future__ import annotations

import types

from lexichunk import LegalChunker

_UK_DOC = """\
1. Definitions

1.1 In this Agreement, the following terms shall have the meanings set out below:

    "Service" means the software development services described in Schedule 1.

2. Obligations

2.1 The Supplier shall provide the Service in accordance with this Agreement.
"""


class TestChunkIter:
    """Verify chunk_iter() behaves as a generator wrapper over chunk()."""

    def test_returns_iterator(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        result = chunker.chunk_iter(_UK_DOC)
        assert isinstance(result, types.GeneratorType)

    def test_matches_chunk_output(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunks = chunker.chunk(_UK_DOC)
        iter_chunks = list(chunker.chunk_iter(_UK_DOC))

        assert len(iter_chunks) == len(chunks)
        for a, b in zip(chunks, iter_chunks):
            assert a.content == b.content

    def test_empty_text(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        result = list(chunker.chunk_iter(""))
        assert result == []

    def test_with_document_id(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunks = list(chunker.chunk_iter(_UK_DOC, document_id="doc-123"))
        assert all(c.document_id == "doc-123" for c in chunks)
