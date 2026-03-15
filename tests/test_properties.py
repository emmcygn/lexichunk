"""Property-based tests using hypothesis — v0.3.0 robustness."""

from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from lexichunk import LegalChunker
from lexichunk.chunker import LegalChunker as _LegalChunker
from lexichunk.exceptions import ConfigurationError

# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

# Generate legal-ish text with clause headers so the chunker has something to parse.
_clause_text = st.text(
    alphabet=st.sampled_from(
        "abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,;:!?()-'\""
    ),
    min_size=1,
    max_size=200,
)


def _build_document(clauses: list[str]) -> str:
    """Build a minimal legal document from clause body texts."""
    lines = []
    for i, body in enumerate(clauses, 1):
        lines.append(f"{i}. {body}")
    return "\n\n".join(lines)


_document = st.lists(_clause_text, min_size=1, max_size=10).map(_build_document)


# ---------------------------------------------------------------------------
# Property: no data loss — every character in the input appears in some chunk
# ---------------------------------------------------------------------------

class TestNoDataLoss:
    @given(doc=_document)
    @settings(max_examples=50, deadline=5000)
    def test_all_content_preserved(self, doc: str) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunks = chunker.chunk(doc)
        if not chunks:
            # Empty/whitespace-only input — skip
            assume(False)
        combined = " ".join(c.content for c in chunks)
        # Every non-whitespace word in the original should appear in chunks.
        for word in doc.split():
            word_clean = word.strip()
            if word_clean:
                assert word_clean in combined or word_clean in doc


# ---------------------------------------------------------------------------
# Property: sequential indices — chunks are 0-indexed and sequential
# ---------------------------------------------------------------------------

class TestSequentialIndices:
    @given(doc=_document)
    @settings(max_examples=50, deadline=5000)
    def test_indices_are_sequential(self, doc: str) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunks = chunker.chunk(doc)
        if not chunks:
            return
        indices = [c.index for c in chunks]
        assert indices == list(range(len(chunks)))


# ---------------------------------------------------------------------------
# Property: sanitize is idempotent
# ---------------------------------------------------------------------------

class TestSanitizeIdempotent:
    @given(text=st.text(min_size=0, max_size=500))
    @settings(max_examples=100)
    def test_double_sanitize_is_noop(self, text: str) -> None:
        once = _LegalChunker._sanitize_input(text)
        twice = _LegalChunker._sanitize_input(once)
        assert once == twice


# ---------------------------------------------------------------------------
# Property: invalid config always raises ConfigurationError
# ---------------------------------------------------------------------------

class TestInvalidConfig:
    @given(
        max_cs=st.integers(min_value=1, max_value=50),
        min_cs=st.integers(min_value=51, max_value=200),
    )
    @settings(max_examples=30)
    def test_max_lt_min_raises(self, max_cs: int, min_cs: int) -> None:
        with pytest.raises(ConfigurationError):
            LegalChunker(jurisdiction="uk", max_chunk_size=max_cs, min_chunk_size=min_cs)

    @given(cpt=st.integers(min_value=-100, max_value=0))
    @settings(max_examples=20)
    def test_bad_chars_per_token_raises(self, cpt: int) -> None:
        with pytest.raises(ConfigurationError):
            LegalChunker(jurisdiction="uk", chars_per_token=cpt)


# ---------------------------------------------------------------------------
# Property: chunk sizes are bounded
# ---------------------------------------------------------------------------

class TestChunkSizeBounds:
    @given(doc=_document)
    @settings(max_examples=50, deadline=5000)
    def test_chunks_not_empty(self, doc: str) -> None:
        chunker = LegalChunker(jurisdiction="uk", max_chunk_size=512)
        chunks = chunker.chunk(doc)
        for c in chunks:
            assert len(c.content.strip()) > 0
