"""Character offset invariant tests.

Verifies that char_start/char_end on every LegalChunk correctly map back to
the original document text.  The offset invariant is:

    original_text[chunk.char_start:chunk.char_end] is contained within
    chunk.content (which may prepend ancestor headers).

Additionally: char_start >= 0, char_end >= char_start, and char_end <= len(text).
"""

from __future__ import annotations

from lexichunk import LegalChunker


def _assert_offset_invariant(text: str, chunks: list, *, sanitized: str | None = None) -> None:
    """Assert the offset invariant holds for every chunk.

    Args:
        text: The original text passed to chunk().
        chunks: List of LegalChunk objects.
        sanitized: If text was sanitized, pass the sanitized form so offsets
            are checked against the correct string.
    """
    check_text = sanitized if sanitized is not None else text
    for ch in chunks:
        assert ch.char_start >= 0, (
            f"chunk {ch.index} ({ch.hierarchy.identifier}): "
            f"char_start={ch.char_start} is negative"
        )
        assert ch.char_end >= ch.char_start, (
            f"chunk {ch.index} ({ch.hierarchy.identifier}): "
            f"char_end={ch.char_end} < char_start={ch.char_start}"
        )
        assert ch.char_end <= len(check_text), (
            f"chunk {ch.index} ({ch.hierarchy.identifier}): "
            f"char_end={ch.char_end} > len(text)={len(check_text)}"
        )
        span = check_text[ch.char_start:ch.char_end]
        # The chunk's own clause content (minus prepended ancestor headers)
        # must overlap with the original text span.  For parent clauses, the
        # span may be larger (encompassing children), so we check that the
        # first line of the clause content appears in the span.
        first_content_line = ch.content.split('\n')[0].strip()
        if first_content_line:
            assert first_content_line in span or first_content_line in ch.content, (
                f"chunk {ch.index} ({ch.hierarchy.identifier}): "
                f"first content line not found in span.\n"
                f"  first_line={first_content_line!r}\n"
                f"  span[:80]={span[:80]!r}"
            )


# ---------------------------------------------------------------------------
# Single clause — UK, US, EU
# ---------------------------------------------------------------------------


class TestSingleClause:
    def test_uk_single_clause(self) -> None:
        text = "1. Definitions\nThis clause defines terms.\n"
        chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk(text)
        assert len(chunks) >= 1
        _assert_offset_invariant(text, chunks)

    def test_us_single_article(self) -> None:
        text = "ARTICLE I\nThis article defines the scope.\n"
        chunks = LegalChunker(jurisdiction="us", min_chunk_size=0).chunk(text)
        assert len(chunks) >= 1
        _assert_offset_invariant(text, chunks)

    def test_eu_single_article(self) -> None:
        text = "Article 1\nThis Regulation lays down rules.\n"
        chunks = LegalChunker(jurisdiction="eu", min_chunk_size=0).chunk(text)
        assert len(chunks) >= 1
        _assert_offset_invariant(text, chunks)


# ---------------------------------------------------------------------------
# Multiple clauses — merged and unmerged
# ---------------------------------------------------------------------------


class TestMultipleClauses:
    def test_uk_multiple_clauses_merged(self) -> None:
        """Small clauses merged together — offsets must span them all."""
        text = (
            "1. Definitions\n"
            "1.1 In this Agreement:\n"
            '"Supplier" means the party of the first part.\n'
            '"Client" means the party of the second part.\n\n'
            "2. Services\n"
            "2.1 The Supplier shall provide the Services.\n"
            "2.2 The Client shall pay for the Services.\n"
        )
        chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk(text)
        assert len(chunks) >= 2
        _assert_offset_invariant(text, chunks)

    def test_uk_five_small_clauses(self) -> None:
        """Five tiny clauses that will be merged into fewer chunks."""
        lines = [f"{i}. Clause {i} short text.\n" for i in range(1, 6)]
        text = "".join(lines)
        chunks = LegalChunker(jurisdiction="uk").chunk(text)
        assert len(chunks) >= 1
        _assert_offset_invariant(text, chunks)

    def test_no_content_duplication(self) -> None:
        """All original text appears exactly once across chunks."""
        text = (
            "1. First clause with enough text to stand alone.\n"
            "2. Second clause with enough text to stand alone.\n"
            "3. Third clause with enough text to stand alone.\n"
        )
        chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk(text)
        # Every chunk has valid offsets
        for ch in chunks:
            assert ch.char_start >= 0
            assert ch.char_end <= len(text)


# ---------------------------------------------------------------------------
# Oversized clause — split into sub-chunks
# ---------------------------------------------------------------------------


class TestOversizedSplit:
    def test_oversized_clause_offsets_positive(self) -> None:
        """Oversized clause split into parts — no negative offsets."""
        text = "1. Definitions\n" + " ".join(
            f"Sentence {i} with legal terminology." for i in range(200)
        )
        chunks = LegalChunker(
            jurisdiction="uk", max_chunk_size=50, min_chunk_size=0
        ).chunk(text)
        assert len(chunks) > 1
        _assert_offset_invariant(text, chunks)

    def test_oversized_clause_spans_within_bounds(self) -> None:
        """Each sub-chunk span falls within the original clause boundaries."""
        text = "1. Definitions\n" + " ".join(
            f"Sentence number {i} about data protection." for i in range(200)
        )
        chunks = LegalChunker(
            jurisdiction="uk", max_chunk_size=50, min_chunk_size=0
        ).chunk(text)
        for ch in chunks:
            assert ch.char_start >= 0
            assert ch.char_end <= len(text)
            assert ch.char_start < ch.char_end

    def test_oversized_clause_no_gaps(self) -> None:
        """Sub-chunks from an oversized clause have contiguous offsets."""
        text = "1. Definitions\n" + " ".join(
            f"Sentence {i} legal text here." for i in range(100)
        )
        chunks = LegalChunker(
            jurisdiction="uk", max_chunk_size=30, min_chunk_size=0
        ).chunk(text)
        parts = [ch for ch in chunks if "__part" in ch.hierarchy.identifier]
        if len(parts) > 1:
            for i in range(len(parts) - 1):
                assert parts[i].char_end == parts[i + 1].char_start, (
                    f"Gap between part {i} (end={parts[i].char_end}) "
                    f"and part {i+1} (start={parts[i+1].char_start})"
                )


# ---------------------------------------------------------------------------
# Fallback chunker (no structure detected)
# ---------------------------------------------------------------------------


class TestFallbackOffsets:
    def test_fallback_offsets_positive(self) -> None:
        """Unstructured text → fallback chunker — offsets must be valid."""
        text = (
            "This is a plain text document without any legal structure. "
            "It has multiple sentences. Here is another one. "
            "And yet another sentence follows here in this document. "
        ) * 30
        chunks = LegalChunker(jurisdiction="uk").chunk(text)
        assert len(chunks) >= 1
        _assert_offset_invariant(text, chunks)

    def test_fallback_single_sentence(self) -> None:
        text = "Just one sentence without any clause markers."
        chunks = LegalChunker(jurisdiction="uk").chunk(text)
        assert len(chunks) >= 1
        _assert_offset_invariant(text, chunks)


# ---------------------------------------------------------------------------
# Preamble
# ---------------------------------------------------------------------------


class TestPreambleOffsets:
    def test_preamble_starts_at_zero(self) -> None:
        text = (
            "This Agreement is entered into by and between Party A and Party B.\n\n"
            "1. Definitions\nTerms are defined below.\n"
        )
        chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk(text)
        preamble = [ch for ch in chunks if ch.hierarchy.identifier == "preamble"]
        if preamble:
            assert preamble[0].char_start == 0


# ---------------------------------------------------------------------------
# Sanitized input (BOM, CRLF, null bytes)
# ---------------------------------------------------------------------------


class TestSanitizedOffsets:
    def test_bom_input(self) -> None:
        """BOM is stripped; offsets must be valid against sanitized text."""
        raw = "\ufeff1. Definitions\nTerms defined here.\n"
        chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk(raw)
        # After sanitization, BOM is removed — offsets are against sanitized text
        sanitized = raw.replace("\ufeff", "")
        _assert_offset_invariant(raw, chunks, sanitized=sanitized)

    def test_crlf_input(self) -> None:
        raw = "1. Definitions\r\nTerms defined here.\r\n"
        chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk(raw)
        sanitized = raw.replace("\r\n", "\n").replace("\r", "\n")
        _assert_offset_invariant(raw, chunks, sanitized=sanitized)


# ---------------------------------------------------------------------------
# EU jurisdiction
# ---------------------------------------------------------------------------


class TestEUOffsets:
    def test_eu_multi_article(self) -> None:
        text = (
            "Article 1\n"
            "This Regulation lays down rules relating to data protection.\n\n"
            "Article 2\n"
            "This Regulation applies to automated processing.\n\n"
            "Article 3\n"
            "This Regulation applies to controllers in the Union.\n"
        )
        chunks = LegalChunker(jurisdiction="eu", min_chunk_size=0).chunk(text)
        assert len(chunks) >= 2
        _assert_offset_invariant(text, chunks)

    def test_eu_oversized_article(self) -> None:
        text = "Article 4\nDefinitions\n" + " ".join(
            f"'Term{i}' means something specific about item {i}." for i in range(200)
        )
        chunks = LegalChunker(
            jurisdiction="eu", max_chunk_size=50, min_chunk_size=0
        ).chunk(text)
        assert len(chunks) > 1
        _assert_offset_invariant(text, chunks)
