"""Tests for StructureParser and jurisdiction detect_level functions."""

import pytest

from lexichunk.jurisdiction.uk import detect_level as uk_detect_level
from lexichunk.jurisdiction.us import detect_level as us_detect_level
from lexichunk.models import DocumentSection, Jurisdiction
from lexichunk.parsers.structure import ParsedClause, StructureParser


# ---------------------------------------------------------------------------
# UK detect_level tests
# ---------------------------------------------------------------------------


def test_uk_detect_level_top_clause():
    """'1. Definitions' → level 0, identifier '1'."""
    result = uk_detect_level("1. Definitions")
    assert result is not None
    level, identifier = result
    assert level == 0
    assert identifier == "1"


def test_uk_detect_level_subsection():
    """'1.1 Services' → level 1, identifier '1.1'."""
    result = uk_detect_level("1.1 Services")
    assert result is not None
    level, identifier = result
    assert level == 1
    assert identifier == "1.1"


def test_uk_detect_level_sub_subsection():
    """'1.1.1 Details' → level 2, identifier '1.1.1'."""
    result = uk_detect_level("1.1.1 Details")
    assert result is not None
    level, identifier = result
    assert level == 2
    assert identifier == "1.1.1"


def test_uk_detect_level_alpha():
    """'(a) ' followed by content → level 3, identifier '(a)'."""
    result = uk_detect_level("(a) the supplier shall provide")
    assert result is not None
    level, identifier = result
    assert level == 3
    assert identifier == "(a)"


def test_uk_detect_level_roman():
    """'(ii) ' or '(iv) ' followed by content → level 4.

    Note: '(i)' is a single lowercase letter so the alpha pattern fires
    first (level 3).  Multi-character Roman numerals like '(ii)' or '(iv)'
    are unambiguously Roman and therefore return level 4.
    """
    # (i) is ambiguous — single lowercase letter matches alpha first → level 3.
    result_i = uk_detect_level("(i) payment terms")
    assert result_i is not None
    assert result_i[0] == 3  # alpha pattern fires on single char 'i'

    # (ii) is unambiguously Roman → level 4.
    result_ii = uk_detect_level("(ii) first instalment")
    assert result_ii is not None
    level, identifier = result_ii
    assert level == 4
    assert identifier == "(ii)"

    # (iv) is also unambiguously Roman → level 4.
    result_iv = uk_detect_level("(iv) fourth instalment")
    assert result_iv is not None
    assert result_iv[0] == 4
    assert result_iv[1] == "(iv)"


def test_uk_detect_level_schedule():
    """'Schedule 1' → level -1."""
    result = uk_detect_level("Schedule 1")
    assert result is not None
    level, identifier = result
    assert level == -1
    assert "Schedule" in identifier
    assert "1" in identifier


def test_uk_detect_level_not_header():
    """Plain body text returns None."""
    result = uk_detect_level("This is body text with no clause marker.")
    assert result is None


def test_uk_detect_level_not_header_lowercase():
    """A numeric prefix followed by a lowercase word is not a top-level header.

    The UK top_level pattern requires the first character after the number to
    be uppercase (digit-dot-space-Uppercase).  So '1.1 this is not a header'
    still resolves as level 1 (subsection) because the subsection pattern
    only requires any non-space character, not an uppercase one.
    For a top-level candidate like '3. services' (lowercase s) the result
    is None because the top-level rule is not satisfied.
    """
    # "1.1 this" — subsection pattern fires on \S (any non-space)
    result = uk_detect_level("1.1 this is not a header")
    # The subsection pattern r'^(\d+\.\d+)\.?\s+\S' matches on 't'.
    assert result is not None
    level, identifier = result
    assert level == 1

    # "3. services" — top-level requires uppercase after the number; 's' is
    # lowercase so this should NOT match the top-level rule → returns None.
    result2 = uk_detect_level("3. services provided by the supplier")
    assert result2 is None


# ---------------------------------------------------------------------------
# US detect_level tests
# ---------------------------------------------------------------------------


def test_us_detect_level_article():
    """'ARTICLE I' → level 0, identifier contains 'Article I'."""
    result = us_detect_level("ARTICLE I")
    assert result is not None
    level, identifier = result
    assert level == 0
    assert "I" in identifier


def test_us_detect_level_section():
    """'Section 1.01' → level 1."""
    result = us_detect_level("Section 1.01")
    assert result is not None
    level, identifier = result
    assert level == 1
    assert "1.01" in identifier


def test_us_detect_level_exhibit():
    """'Exhibit A' → level -2."""
    result = us_detect_level("Exhibit A")
    assert result is not None
    level, identifier = result
    assert level == -2
    assert "Exhibit" in identifier or "exhibit" in identifier.lower()


# ---------------------------------------------------------------------------
# StructureParser — UK fixture
# ---------------------------------------------------------------------------


def test_structure_parser_uk_parses_clauses(uk_service_agreement):
    """Parsing the UK fixture returns a non-empty list of ParsedClause."""
    parser = StructureParser(Jurisdiction.UK)
    clauses = parser.parse(uk_service_agreement)
    assert isinstance(clauses, list)
    assert len(clauses) > 0
    for clause in clauses:
        assert isinstance(clause, ParsedClause)


def test_structure_parser_uk_has_definitions_section(uk_service_agreement):
    """The UK fixture contains a clause classified as DEFINITIONS.

    The UK service agreement has '1.   Definitions and interpretation' which
    should be mapped to DocumentSection.DEFINITIONS.
    """
    parser = StructureParser(Jurisdiction.UK)
    clauses = parser.parse(uk_service_agreement)
    definitions_clauses = [
        c for c in clauses if c.document_section == DocumentSection.DEFINITIONS
    ]
    assert len(definitions_clauses) > 0, (
        "Expected at least one clause with document_section == DEFINITIONS; "
        f"found sections: {[c.document_section for c in clauses[:10]]}"
    )


def test_structure_parser_uk_hierarchy_path(uk_service_agreement):
    """Subsection clauses (level 1) should have a parent_identifier set.

    The UK fixture has many x.y subsections under top-level clauses; each
    should record the top-level clause number as its parent.
    """
    parser = StructureParser(Jurisdiction.UK)
    clauses = parser.parse(uk_service_agreement)
    # Find any level-1 subsection clause.
    subsections = [c for c in clauses if c.level == 1]
    assert len(subsections) > 0, "Expected subsection-level clauses (level 1) in UK fixture"
    for sub in subsections:
        assert sub.parent_identifier is not None, (
            f"Subsection {sub.identifier!r} has no parent_identifier"
        )


def test_structure_parser_us_parses_articles(us_msa):
    """The US fixture must yield at least one level-0 (Article) clause."""
    parser = StructureParser(Jurisdiction.US)
    clauses = parser.parse(us_msa)
    articles = [c for c in clauses if c.level == 0]
    assert len(articles) > 0, (
        "Expected Article-level (level 0) clauses in US fixture; "
        f"found levels: {sorted({c.level for c in clauses})}"
    )


def test_structure_parser_empty_text():
    """Parsing an empty string returns an empty list."""
    parser = StructureParser(Jurisdiction.UK)
    result = parser.parse("")
    assert result == []


def test_structure_parser_no_headers():
    """Text with no clause markers returns a single preamble clause."""
    text = "Just plain text with no clause markers."
    parser = StructureParser(Jurisdiction.UK)
    result = parser.parse(text)
    assert len(result) == 1
    assert result[0].identifier == "preamble"
    assert result[0].document_section == DocumentSection.PREAMBLE
