"""ReDoS security audit — verify regex patterns resist catastrophic backtracking.

Tests pathological inputs against all compiled regex patterns in the library
to ensure none exhibit exponential backtracking behaviour.  Each test imposes
a 2-second wall-clock budget; genuine ReDoS vulnerabilities would cause these
to hang for minutes or hours.
"""

from __future__ import annotations

import re
import time

from lexichunk import LegalChunker
from lexichunk.jurisdiction.eu import EU_PATTERNS
from lexichunk.jurisdiction.eu import detect_level as eu_detect
from lexichunk.jurisdiction.uk import UK_PATTERNS
from lexichunk.jurisdiction.uk import detect_level as uk_detect
from lexichunk.jurisdiction.us import US_PATTERNS
from lexichunk.jurisdiction.us import detect_level as us_detect
from lexichunk.parsers.references import _CONJUNCTIVE_TAIL, EXTENDED_PATTERNS

# Maximum wall-clock seconds for any single regex operation.
_TIMEOUT_BUDGET = 2.0


def _assert_no_hang(pattern: re.Pattern[str], text: str) -> None:
    """Assert that running pattern on text completes within the budget."""
    t0 = time.perf_counter()
    # Use findall to force full scan, not just first match.
    pattern.findall(text)
    elapsed = time.perf_counter() - t0
    assert elapsed < _TIMEOUT_BUDGET, (
        f"Pattern {pattern.pattern!r} took {elapsed:.1f}s on {len(text)}-char input "
        f"(budget: {_TIMEOUT_BUDGET}s) — possible ReDoS"
    )


# ---------------------------------------------------------------------------
# Pathological input generators
# ---------------------------------------------------------------------------

# Repeated dot-separated numbers (stresses numeric quantifiers like \d+(\.\d+)*)
_DOTTED_NUMBERS = "1.2.3.4.5.6.7.8.9.10." * 500

# Nested parentheses (stresses paren-matching groups)
_NESTED_PARENS = "(a)" * 2000

# Long whitespace-padded header-like text (stresses ^ anchored multi-line patterns)
_LONG_LINES = ("Article " + "X" * 200 + "\n") * 200

# Repeated near-misses for definition patterns (quoted strings without "means")
_NEAR_MISS_DEFS = ('"SomeTerm" and ' * 1000)

# Cross-reference-like text with many sections
_MANY_REFS = "Section " + ", Section ".join(str(i) for i in range(1000))

# Long text with no structure (worst case for structure detection)
_UNSTRUCTURED = "The quick brown fox jumps over the lazy dog. " * 2000

# Repeated alpha sub-clauses
_MANY_ALPHA = "\n".join(f"({chr(97 + (i % 26))}) item {i}" for i in range(2000))


# ---------------------------------------------------------------------------
# UK pattern audit
# ---------------------------------------------------------------------------


class TestUKPatternsReDoS:
    def test_subsection_3_dotted(self) -> None:
        _assert_no_hang(UK_PATTERNS.subsection_3, _DOTTED_NUMBERS)

    def test_subsection_2_dotted(self) -> None:
        _assert_no_hang(UK_PATTERNS.subsection_2, _DOTTED_NUMBERS)

    def test_top_level_long_lines(self) -> None:
        _assert_no_hang(UK_PATTERNS.top_level, _LONG_LINES)

    def test_cross_ref_many_refs(self) -> None:
        _assert_no_hang(UK_PATTERNS.cross_ref, _MANY_REFS)

    def test_definition_near_miss(self) -> None:
        _assert_no_hang(UK_PATTERNS.definition, _NEAR_MISS_DEFS)

    def test_detect_level_unstructured(self) -> None:
        t0 = time.perf_counter()
        for line in _UNSTRUCTURED.split("\n"):
            uk_detect(line)
        elapsed = time.perf_counter() - t0
        assert elapsed < _TIMEOUT_BUDGET


# ---------------------------------------------------------------------------
# US pattern audit
# ---------------------------------------------------------------------------


class TestUSPatternsReDoS:
    def test_article_long_lines(self) -> None:
        _assert_no_hang(US_PATTERNS.article, _LONG_LINES)

    def test_section_dotted(self) -> None:
        _assert_no_hang(US_PATTERNS.section, _DOTTED_NUMBERS)

    def test_cross_ref_many_refs(self) -> None:
        _assert_no_hang(US_PATTERNS.cross_ref, _MANY_REFS)

    def test_definition_near_miss(self) -> None:
        _assert_no_hang(US_PATTERNS.definition, _NEAR_MISS_DEFS)

    def test_detect_level_unstructured(self) -> None:
        t0 = time.perf_counter()
        for line in _UNSTRUCTURED.split("\n"):
            us_detect(line)
        elapsed = time.perf_counter() - t0
        assert elapsed < _TIMEOUT_BUDGET

    def test_allcaps_header_long_line(self) -> None:
        """ALL-CAPS detection uses fullmatch — test with very long input."""
        long_caps = "A" * 10_000
        t0 = time.perf_counter()
        us_detect(long_caps)
        assert time.perf_counter() - t0 < _TIMEOUT_BUDGET


# ---------------------------------------------------------------------------
# EU pattern audit
# ---------------------------------------------------------------------------


class TestEUPatternsReDoS:
    def test_chapter_long_lines(self) -> None:
        _assert_no_hang(EU_PATTERNS.chapter, _LONG_LINES)

    def test_article_long_lines(self) -> None:
        _assert_no_hang(EU_PATTERNS.article, _LONG_LINES)

    def test_cross_ref_many_refs(self) -> None:
        _assert_no_hang(EU_PATTERNS.cross_ref, _MANY_REFS)

    def test_definition_near_miss(self) -> None:
        _assert_no_hang(EU_PATTERNS.definition, _NEAR_MISS_DEFS)

    def test_detect_level_unstructured(self) -> None:
        t0 = time.perf_counter()
        for line in _UNSTRUCTURED.split("\n"):
            eu_detect(line)
        elapsed = time.perf_counter() - t0
        assert elapsed < _TIMEOUT_BUDGET


# ---------------------------------------------------------------------------
# Extended reference patterns audit
# ---------------------------------------------------------------------------


class TestExtendedPatternsReDoS:
    def test_extended_pattern_0_many_refs(self) -> None:
        _assert_no_hang(EXTENDED_PATTERNS[0], _MANY_REFS)

    def test_extended_pattern_1_many_refs(self) -> None:
        _assert_no_hang(EXTENDED_PATTERNS[1], _MANY_REFS)

    def test_conjunctive_tail_dotted(self) -> None:
        _assert_no_hang(_CONJUNCTIVE_TAIL, _DOTTED_NUMBERS)

    def test_conjunctive_tail_many_refs(self) -> None:
        _assert_no_hang(_CONJUNCTIVE_TAIL, _MANY_REFS)


# ---------------------------------------------------------------------------
# Definition patterns audit (module-level compiled patterns)
# ---------------------------------------------------------------------------


class TestDefinitionPatternsReDoS:
    def test_single_quote_near_miss(self) -> None:
        from lexichunk.parsers.definitions import _DEFINITION_SINGLE
        _assert_no_hang(_DEFINITION_SINGLE, _NEAR_MISS_DEFS)

    def test_hereinafter_long_text(self) -> None:
        from lexichunk.parsers.definitions import _DEFINITION_HEREINAFTER
        text = "hereinafter referred to as " * 1000
        _assert_no_hang(_DEFINITION_HEREINAFTER, text)

    def test_inline_paren_nested(self) -> None:
        from lexichunk.parsers.definitions import _INLINE_PAREN_GROUP
        _assert_no_hang(_INLINE_PAREN_GROUP, _NESTED_PARENS)

    def test_parenthetical_backref_many(self) -> None:
        from lexichunk.parsers.definitions import _PARENTHETICAL_BACKREF
        text = "the Borrower (as defined in " * 1000
        _assert_no_hang(_PARENTHETICAL_BACKREF, text)


# ---------------------------------------------------------------------------
# Full pipeline timeout guard
# ---------------------------------------------------------------------------


class TestPipelineTimeout:
    def test_large_unstructured_input(self) -> None:
        """Full pipeline on 100KB of unstructured text should complete in time."""
        chunker = LegalChunker(jurisdiction="uk")
        text = "The quick brown fox jumps over the lazy dog. " * 2500  # ~112KB
        t0 = time.perf_counter()
        chunks = chunker.chunk(text)
        elapsed = time.perf_counter() - t0
        assert elapsed < 10.0, f"Pipeline took {elapsed:.1f}s on ~100KB input"
        assert len(chunks) > 0

    def test_many_clause_headers(self) -> None:
        """Document with 1000 clause headers should not cause quadratic blowup."""
        lines = [f"{i}. Clause number {i} text here.\n" for i in range(1, 1001)]
        text = "".join(lines)
        chunker = LegalChunker(jurisdiction="uk")
        t0 = time.perf_counter()
        chunks = chunker.chunk(text)
        elapsed = time.perf_counter() - t0
        assert elapsed < 15.0, f"Pipeline took {elapsed:.1f}s on 1000-clause doc"
        assert len(chunks) > 0

    def test_eu_large_directive(self) -> None:
        """EU pipeline on a large directive-style document."""
        lines = []
        for i in range(1, 101):
            lines.append(f"Article {i}\n")
            lines.append(f"1. This article establishes rules for item {i}.\n")
            lines.append("2. Member States shall ensure compliance with paragraph 1.\n")
            lines.append("(a) by implementing appropriate measures;\n")
            lines.append("(b) by designating competent authorities.\n\n")
        text = "".join(lines)
        chunker = LegalChunker(jurisdiction="eu")
        t0 = time.perf_counter()
        chunks = chunker.chunk(text)
        elapsed = time.perf_counter() - t0
        assert elapsed < 10.0, f"EU pipeline took {elapsed:.1f}s on 100-article doc"
        assert len(chunks) > 0
