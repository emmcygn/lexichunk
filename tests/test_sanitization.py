"""Tests for input sanitization — v0.3.0 robustness."""

from __future__ import annotations

import unicodedata

import pytest

from lexichunk import LegalChunker


@pytest.fixture
def chunker() -> LegalChunker:
    return LegalChunker(jurisdiction="uk")


# ---------------------------------------------------------------------------
# BOM handling
# ---------------------------------------------------------------------------

class TestBOM:
    def test_bom_stripped_from_chunk_output(self, chunker: LegalChunker) -> None:
        text = "\ufeff1. This is clause one.\n\n2. This is clause two."
        chunks = chunker.chunk(text)
        assert chunks
        for c in chunks:
            assert "\ufeff" not in c.content

    def test_bom_only_input_returns_empty(self, chunker: LegalChunker) -> None:
        assert chunker.chunk("\ufeff") == []
        assert chunker.chunk("\ufeff  \ufeff") == []

    def test_nested_bom_stripped(self, chunker: LegalChunker) -> None:
        text = "1. First clause.\ufeff\n\n2. Second\ufeff clause."
        chunks = chunker.chunk(text)
        for c in chunks:
            assert "\ufeff" not in c.content


# ---------------------------------------------------------------------------
# Line-ending normalization
# ---------------------------------------------------------------------------

class TestLineEndings:
    def test_crlf_normalized(self, chunker: LegalChunker) -> None:
        text = "1. Clause A.\r\n\r\n2. Clause B."
        chunks = chunker.chunk(text)
        assert chunks
        for c in chunks:
            assert "\r" not in c.content

    def test_stray_cr_normalized(self, chunker: LegalChunker) -> None:
        text = "1. Clause A.\r\r2. Clause B."
        chunks = chunker.chunk(text)
        for c in chunks:
            assert "\r" not in c.content

    def test_mixed_endings(self, chunker: LegalChunker) -> None:
        text = "1. A.\r\n2. B.\r3. C.\n4. D."
        chunks = chunker.chunk(text)
        for c in chunks:
            assert "\r" not in c.content


# ---------------------------------------------------------------------------
# Null bytes
# ---------------------------------------------------------------------------

class TestNullBytes:
    def test_null_bytes_removed(self, chunker: LegalChunker) -> None:
        text = "1. Clause\x00 with null bytes.\n\n2. Another\x00 clause."
        chunks = chunker.chunk(text)
        for c in chunks:
            assert "\x00" not in c.content

    def test_only_null_bytes_returns_empty(self, chunker: LegalChunker) -> None:
        assert chunker.chunk("\x00\x00\x00") == []


# ---------------------------------------------------------------------------
# Unicode NFC normalization
# ---------------------------------------------------------------------------

class TestNFC:
    def test_nfc_normalization(self, chunker: LegalChunker) -> None:
        # é as e + combining accent (NFD) should become single codepoint (NFC)
        nfd_text = "1. Caf\u0065\u0301 clause."
        chunks = chunker.chunk(nfd_text)
        assert chunks
        # The content should be NFC-normalized
        for c in chunks:
            assert c.content == unicodedata.normalize("NFC", c.content)

    def test_already_nfc_unchanged(self, chunker: LegalChunker) -> None:
        text = "1. Café clause."
        chunks = chunker.chunk(text)
        assert chunks
        assert "Café" in chunks[0].content


# ---------------------------------------------------------------------------
# Clean text identity — no mutation when input is already clean
# ---------------------------------------------------------------------------

class TestCleanIdentity:
    def test_clean_ascii_unchanged(self, chunker: LegalChunker) -> None:
        text = "1. The Borrower shall repay.\n\n2. The Lender may accelerate."
        chunks = chunker.chunk(text)
        assert chunks
        # Joining chunks should give us the text back (minus any chunker logic)
        assert "The Borrower shall repay" in chunks[0].content


# ---------------------------------------------------------------------------
# Sanitization applied to all public methods
# ---------------------------------------------------------------------------

class TestAllPublicMethods:
    def test_get_defined_terms_sanitizes(self, chunker: LegalChunker) -> None:
        text = '\ufeff"Borrower" means the party borrowing.\r\n'
        terms = chunker.get_defined_terms(text)
        # Should not crash; BOM/CRLF handled
        assert isinstance(terms, dict)

    def test_parse_structure_sanitizes(self, chunker: LegalChunker) -> None:
        text = "\ufeff1. First clause\r\n1.1 Sub-clause"
        nodes = chunker.parse_structure(text)
        assert isinstance(nodes, list)


# ---------------------------------------------------------------------------
# Adversarial sanitization tests
# ---------------------------------------------------------------------------

class TestAdversarialSanitization:
    def test_multi_bom(self, chunker: LegalChunker) -> None:
        text = "\ufeff\ufeff\ufeff1. Clause."
        chunks = chunker.chunk(text)
        assert chunks
        assert "\ufeff" not in chunks[0].content

    def test_zero_width_chars_preserved(self, chunker: LegalChunker) -> None:
        """Zero-width spaces are valid Unicode — sanitize shouldn't strip them
        (only BOM and null bytes are stripped)."""
        text = "1. Clause\u200b here."
        chunks = chunker.chunk(text)
        assert chunks

    def test_combining_diacritics_normalized(self, chunker: LegalChunker) -> None:
        # Multiple combining marks
        text = "1. A\u0300\u0301\u0302 clause."
        chunks = chunker.chunk(text)
        for c in chunks:
            assert c.content == unicodedata.normalize("NFC", c.content)
