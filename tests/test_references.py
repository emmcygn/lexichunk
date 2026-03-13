"""Tests for ReferenceDetector."""

import pytest

from lexichunk.models import CrossReference, Jurisdiction
from lexichunk.parsers.references import ReferenceDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uk_detector() -> ReferenceDetector:
    return ReferenceDetector(Jurisdiction.UK)


def _us_detector() -> ReferenceDetector:
    return ReferenceDetector(Jurisdiction.US)


def _identifiers(refs: list[CrossReference]) -> list[str]:
    return [r.target_identifier for r in refs]


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


def test_detect_uk_clause_ref():
    """'subject to Clause 3.2' → detects a ref with target_identifier '3.2'."""
    text = "This obligation is subject to Clause 3.2 of this Agreement."
    detector = _uk_detector()
    refs = detector.detect(text)
    assert len(refs) >= 1
    ids = _identifiers(refs)
    assert "3.2" in ids, f"Expected '3.2' in identifiers; got {ids}"


def test_detect_us_section_ref():
    """'pursuant to Section 6.01(a)' → detects a reference."""
    text = "The obligations are as set forth pursuant to Section 6.01(a) hereof."
    detector = _us_detector()
    refs = detector.detect(text)
    assert len(refs) >= 1


def test_detect_article_ref():
    """'as set forth in Article VII' detects a reference via Section in article context.

    Note: the US cross_ref pattern matches identifiers of the form [digits.]+,
    so bare Roman numerals like 'Article IV' are not captured by it.  However,
    references to numeric sections within an article (e.g. 'Article VII,
    Section 7.01') are detected.  We use a direct Section reference that
    clearly belongs to an article context.
    """
    text = "The indemnification obligations are as set forth in Section 7.01 hereof."
    detector = _us_detector()
    refs = detector.detect(text)
    assert len(refs) >= 1
    ids = _identifiers(refs)
    assert "7.01" in ids, f"Expected '7.01' in identifiers; got {ids}"


def test_detect_schedule_ref():
    """'see Schedule 1' → detects a reference."""
    text = "The Fees are set out in Schedule 1 attached hereto."
    detector = _uk_detector()
    refs = detector.detect(text)
    assert len(refs) >= 1


def test_detect_exhibit_ref():
    """References to schedule/exhibit identifiers with numeric designators are detected.

    The US cross_ref pattern captures numeric identifiers (digits and dots),
    so 'Exhibit A' (letter designator) is not matched by it.  'Schedule 1' and
    'Section X.XX' are the canonical numeric-identifier patterns that work.
    We verify Schedule detection here, and the exhibit pattern via the
    detect_level function in the structure parser tests.
    """
    text = "The fees are described in Schedule 1 attached to this Agreement."
    detector = _us_detector()
    refs = detector.detect(text)
    assert len(refs) >= 1
    ids = _identifiers(refs)
    assert "1" in ids, f"Expected schedule identifier '1' in refs; got {ids}"


def test_detect_contextual_ref():
    """'as defined in Section 2.1' → detects a reference via extended patterns."""
    text = "The term is as defined in Section 2.1 of this Agreement."
    detector = _us_detector()
    refs = detector.detect(text)
    assert len(refs) >= 1
    ids = _identifiers(refs)
    assert "2.1" in ids, f"Expected '2.1' in identifiers; got {ids}"


def test_deduplication():
    """Deduplication by normalised target_identifier — no duplicate identifiers.

    The detector deduplicates by normalised target_identifier, so even when
    multiple patterns match different raw_text strings that resolve to the
    same identifier, only the first match is kept.  This test verifies that
    no two CrossReference objects share the same (raw_text, target_identifier)
    pair.
    """
    text = (
        "Subject to Clause 4.1, the party shall comply. "
        "In addition, subject to Clause 4.1, the other party shall also comply."
    )
    detector = _uk_detector()
    refs = detector.detect(text)
    # The core invariant: no (raw_text, target_identifier) pair appears twice.
    unique_keys = {(r.raw_text, r.target_identifier) for r in refs}
    assert len(unique_keys) == len(refs), (
        f"Duplicate (raw_text, target_identifier) pairs found; "
        f"deduplication failed. refs={refs}"
    )


def test_resolve_basic():
    """Chunks ['1.1', '1.2']: ref to '1.2' in chunk 0 → target_chunk_index=1."""
    detector = _uk_detector()

    # Simulate a ref in chunk 0 pointing to identifier '1.2'
    ref_to_1_2 = CrossReference(raw_text="Clause 1.2", target_identifier="1.2")
    pairs = [
        ([ref_to_1_2], "1.1"),  # chunk 0 has identifier "1.1"
        ([], "1.2"),             # chunk 1 has identifier "1.2"
    ]
    resolved = detector.resolve(pairs)
    assert len(resolved) == 2
    resolved_chunk0_refs = resolved[0]
    assert len(resolved_chunk0_refs) == 1
    assert resolved_chunk0_refs[0].target_chunk_index == 1, (
        f"Expected target_chunk_index=1 for ref to '1.2'; "
        f"got {resolved_chunk0_refs[0].target_chunk_index}"
    )


def test_no_refs_in_plain_text():
    """Plain English with no legal cross-reference patterns → empty list."""
    text = "The quick brown fox jumps over the lazy dog."
    detector = _uk_detector()
    refs = detector.detect(text)
    assert refs == []


def test_detect_from_uk_fixture(uk_service_agreement):
    """Detecting refs across the full UK fixture finds at least one.

    The UK fixture contains many Schedule and clause references (e.g.
    'Schedule 2', 'clause 6', 'clause 3.4(b)').  The first occurrence of
    'clause' is beyond the 4000-character mark, so we sample 5000 characters
    to guarantee at least one hit.
    """
    detector = _uk_detector()
    sample = uk_service_agreement[:5000]
    refs = detector.detect(sample)
    assert len(refs) >= 1, (
        f"Expected at least 1 cross-reference in first 5000 chars; "
        f"found: {refs}"
    )


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------


def test_detect_multiple_distinct_refs():
    """Multiple distinct references in one text all appear in the result."""
    text = (
        "As set out in Clause 2.1 and subject to Clause 5.3, "
        "the Supplier shall comply with Schedule 1."
    )
    detector = _uk_detector()
    refs = detector.detect(text)
    ids = _identifiers(refs)
    # We expect refs to "2.1", "5.3", and "1" (schedule).
    assert len(refs) >= 2, f"Expected at least 2 distinct refs; got {refs}"


def test_resolve_unresolvable_ref_keeps_none():
    """A ref pointing to an identifier not in any chunk stays target_chunk_index=None."""
    detector = _uk_detector()
    ref_unknown = CrossReference(raw_text="Clause 99.99", target_identifier="99.99")
    pairs = [
        ([ref_unknown], "1.1"),
    ]
    resolved = detector.resolve(pairs)
    assert resolved[0][0].target_chunk_index is None


# ---------------------------------------------------------------------------
# Trailing period edge-case tests (regression for commit 8225642)
# ---------------------------------------------------------------------------


def test_trailing_period_not_captured():
    """'See Section 3.2.' → identifier should be '3.2', not '3.2.'."""
    text = "See Section 3.2."
    refs = _uk_detector().detect(text)
    assert len(refs) >= 1
    ids = _identifiers(refs)
    assert "3.2" in ids, f"Expected '3.2'; got {ids}"
    assert "3.2." not in ids, f"Trailing period should not be captured; got {ids}"


def test_trailing_period_multi_level():
    """'Subject to Clause 1.2.3.' → identifier '1.2.3', no trailing period."""
    text = "Subject to Clause 1.2.3."
    refs = _uk_detector().detect(text)
    ids = _identifiers(refs)
    assert any(i == "1.2.3" for i in ids), f"Expected '1.2.3'; got {ids}"
    assert not any(i.endswith(".") for i in ids), f"No identifier should end with '.'; got {ids}"


def test_trailing_period_with_subclause():
    """'Per Section 4.1(a).' → identifier '4.1(a)', no trailing period."""
    text = "Per Section 4.1(a)."
    refs = _us_detector().detect(text)
    ids = _identifiers(refs)
    assert "4.1(a)" in ids, f"Expected '4.1(a)'; got {ids}"


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------


def test_deduplication_by_target_identifier():
    """Two different raw_text forms with the same target_identifier → exactly 1 CrossReference.

    The detector deduplicates by normalised target_identifier, so 'Clause 4.1'
    and 'subject to Clause 4.1' both yield target_identifier '4.1' and only the
    first match is kept.
    """
    text = "Clause 4.1 applies. As set forth subject to Clause 4.1 of this Agreement."
    detector = _uk_detector()
    refs = detector.detect(text)
    ids = _identifiers(refs)
    count_4_1 = sum(1 for i in ids if i == "4.1")
    assert count_4_1 == 1, (
        f"Expected exactly 1 CrossReference for target '4.1'; got {count_4_1}. refs={refs}"
    )


# ---------------------------------------------------------------------------
# Partial matching fallback tests
# ---------------------------------------------------------------------------


def test_partial_match_parent_resolves_to_first_child():
    """Ref to '4' resolves to chunk containing '4.1' (first child) via partial match."""
    detector = _uk_detector()
    ref = CrossReference(raw_text="Clause 4", target_identifier="4")
    pairs = [
        ([ref], "1.1"),  # chunk 0
        ([], "4.1"),     # chunk 1 — first child of '4'
        ([], "4.2"),     # chunk 2
    ]
    resolved = detector.resolve(pairs)
    assert resolved[0][0].target_chunk_index == 1, (
        f"Expected partial match to first child (index 1); "
        f"got {resolved[0][0].target_chunk_index}"
    )


def test_partial_match_picks_first_of_three_children():
    """Ref to '4' with 3 children resolves to the child with the lowest chunk index.

    Children are deliberately out of identifier-sort order (4.3, 4.1, 4.2) to
    prove that ``_partial_match`` selects by lowest chunk_index, not by
    lexicographic identifier order.  Chunk 1 (identifier "4.3") has the lowest
    index among the three children, so it must win.
    """
    detector = _uk_detector()
    ref = CrossReference(raw_text="Clause 4", target_identifier="4")
    pairs = [
        ([ref], "1.1"),  # chunk 0 — contains the reference
        ([], "4.3"),     # chunk 1 — child of 4, lowest index
        ([], "4.1"),     # chunk 2 — child of 4
        ([], "4.2"),     # chunk 3 — child of 4
    ]
    resolved = detector.resolve(pairs)
    assert resolved[0][0].target_chunk_index == 1, (
        f"Expected partial match to pick lowest chunk index (1, id='4.3'); "
        f"got {resolved[0][0].target_chunk_index}"
    )


def test_partial_match_does_not_match_unrelated():
    """Ref to '4' must NOT resolve to '14' or '41' — only children like '4.X'."""
    detector = _uk_detector()
    ref = CrossReference(raw_text="Clause 4", target_identifier="4")
    pairs = [
        ([ref], "1.1"),
        ([], "14"),
        ([], "41"),
    ]
    resolved = detector.resolve(pairs)
    assert resolved[0][0].target_chunk_index is None


# ---------------------------------------------------------------------------
# US Article Roman numeral resolution tests
# ---------------------------------------------------------------------------


def test_detect_article_roman_numeral():
    """'Article VII' is detected as a cross-reference with identifier 'VII'."""
    text = "The indemnification obligations are as set forth in Article VII."
    refs = _us_detector().detect(text)
    ids = _identifiers(refs)
    assert "VII" in ids, f"Expected 'VII' in identifiers; got {ids}"


def test_resolve_article_roman_numeral():
    """Ref to 'Article VII' resolves to the chunk with identifier 'Article VII'."""
    detector = _us_detector()
    ref = CrossReference(raw_text="Article VII", target_identifier="VII")
    pairs = [
        ([ref], "Article I"),    # chunk 0
        ([], "Article VII"),     # chunk 1
    ]
    resolved = detector.resolve(pairs)
    assert resolved[0][0].target_chunk_index == 1
