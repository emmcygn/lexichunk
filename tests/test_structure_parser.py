"""Tests for StructureParser and jurisdiction detect_level functions."""

from pathlib import Path

import pytest

from lexichunk.jurisdiction.uk import detect_level as uk_detect_level
from lexichunk.jurisdiction.us import detect_level as us_detect_level
from lexichunk.jurisdiction.us import roman_to_int
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


def test_us_all_caps_header_detected():
    """'REPRESENTATIONS AND WARRANTIES' → detected as a level-0 clause header."""
    result = us_detect_level("REPRESENTATIONS AND WARRANTIES")
    assert result is not None
    level, identifier = result
    assert level == 0
    assert identifier == "REPRESENTATIONS AND WARRANTIES"


def test_us_mixed_case_not_caps_header():
    """'Representations and Warranties' → not an ALL-CAPS header.

    Mixed-case text should not match the ALL-CAPS pattern; it returns
    None (handled by existing patterns only if it matches ARTICLE/Section/etc.).
    """
    result = us_detect_level("Representations and Warranties")
    assert result is None


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


# ---------------------------------------------------------------------------
# roman_to_int tests
# ---------------------------------------------------------------------------


def test_roman_to_int_valid():
    """Standard Roman numerals convert correctly."""
    assert roman_to_int("I") == 1
    assert roman_to_int("IV") == 4
    assert roman_to_int("VII") == 7
    assert roman_to_int("IX") == 9
    assert roman_to_int("XL") == 40
    assert roman_to_int("XCIX") == 99


def test_roman_to_int_case_insensitive():
    """Lowercase input is accepted."""
    assert roman_to_int("vii") == 7
    assert roman_to_int("xlii") == 42


def test_roman_to_int_invalid_char_raises():
    """Non-Roman characters raise ValueError."""
    with pytest.raises(ValueError, match="Invalid Roman numeral character"):
        roman_to_int("ABCD")


def test_roman_to_int_empty_raises():
    """Empty string raises ValueError."""
    with pytest.raises(ValueError, match="Empty string"):
        roman_to_int("")


def test_roman_to_int_mixed_invalid_raises():
    """String mixing valid and invalid chars raises ValueError."""
    with pytest.raises(ValueError, match="Invalid Roman numeral character"):
        roman_to_int("XIV2")


# ---------------------------------------------------------------------------
# ParsedClause.uid / parent_uid — stable identifiers (Phase 0, mechanical)
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

_UID_FIXTURE_CASES = [
    ("uk_service_agreement.txt", Jurisdiction.UK, "contract"),
    ("uk_terms_conditions.txt", Jurisdiction.UK, "terms_conditions"),
    ("us_msa.txt", Jurisdiction.US, "contract"),
    ("us_terms_of_service.txt", Jurisdiction.US, "terms_conditions"),
    ("eu_gdpr_excerpt.txt", Jurisdiction.EU, "contract"),
]


def _assert_uids_unique_and_parents_earlier(clauses: list[ParsedClause]) -> None:
    uids = [c.uid for c in clauses]
    assert len(uids) == len(set(uids)), f"duplicate uids found: {uids}"

    uid_order: dict[str, int] = {c.uid: i for i, c in enumerate(clauses)}
    for clause in clauses:
        if clause.parent_uid is not None:
            assert clause.parent_uid in uid_order, (
                f"clause uid={clause.uid} has parent_uid={clause.parent_uid} "
                f"which does not exist"
            )
            assert int(clause.parent_uid) < int(clause.uid), (
                f"clause uid={clause.uid} parent_uid={clause.parent_uid} "
                f"is not numerically earlier"
            )


@pytest.mark.parametrize("filename,jurisdiction,doc_type", _UID_FIXTURE_CASES)
def test_uids_unique_and_parent_earlier_on_fixtures(filename, jurisdiction, doc_type):
    text = (_FIXTURES_DIR / filename).read_text(encoding="utf-8")
    clauses = StructureParser(jurisdiction, doc_type=doc_type).parse(text)
    assert clauses, f"expected at least one clause for {filename}"
    _assert_uids_unique_and_parents_earlier(clauses)


def test_uids_unique_and_parent_earlier_on_synthetic_doc():
    text = (
        "1. Confidentiality\n"
        "1.1 Scope\n"
        "This clause applies broadly.\n"
        "2. Termination\n"
        "3. Governing Law\n"
    )
    clauses = StructureParser(Jurisdiction.UK, doc_type="contract").parse(text)
    _assert_uids_unique_and_parents_earlier(clauses)


def test_uid_is_monotonic_counter_string():
    """uid values are '0', '1', '2', ... assigned in creation (opening) order."""
    text = (
        "1. Confidentiality\n"
        "1.1 Scope\n"
        "Text.\n"
        "2. Termination\n"
    )
    clauses = StructureParser(Jurisdiction.UK, doc_type="contract").parse(text)
    uids = sorted(int(c.uid) for c in clauses)
    assert uids == list(range(len(clauses)))


def test_top_level_clause_parent_uid_is_none():
    text = "1. Confidentiality\nSome text.\n2. Termination\nMore text.\n"
    clauses = StructureParser(Jurisdiction.UK, doc_type="contract").parse(text)
    top_level = [c for c in clauses if c.parent_identifier is None]
    assert top_level, "expected at least one top-level clause"
    for clause in top_level:
        assert clause.parent_uid is None


def test_parsed_clause_uid_defaults_when_not_specified():
    """Construction sites that don't pass uid/parent_uid still work (defaults)."""
    clause = ParsedClause(
        identifier="(a)",
        title=None,
        content="text",
        level=1,
        parent_identifier="1",
        document_section=DocumentSection.OPERATIVE,
        char_start=0,
        char_end=4,
    )
    assert clause.uid == ""
    assert clause.parent_uid is None
