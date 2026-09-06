"""Letter-named attachments: ``Exhibit A``, ``Exhibit B``.

US agreements name their attachments by letter and refer to them constantly —
"attached hereto as Exhibit A", "in the form set out in Exhibit B".  The
structure parser has always recognised ``EXHIBIT A`` as a container heading,
but the US cross-reference pattern only accepted digits or Roman numerals as
an identifier, so those references were invisible: the document contained an
Exhibit A chunk that nothing could ever resolve to.

It was also inconsistent in a way that is hard to notice.  ``Exhibit C``
*did* resolve, because ``C`` is a Roman numeral; ``Exhibit A``, ``B`` and
``D`` did not.  A corpus check on exhibit coverage would have looked
partially healthy.
"""

from __future__ import annotations

import pytest

from lexichunk import LegalChunker
from lexichunk.parsers.references import ReferenceDetector

_AGREEMENT = """\
ARTICLE II
SERVICES

Section 2.01 Statement of Work

The Provider shall perform the services described in Exhibit A and shall
deliver the items listed in Exhibit B in accordance with the schedule stated
in Exhibit A.

EXHIBIT A
STATEMENT OF WORK

The Provider shall host and support the platform for the duration of the Term.

EXHIBIT B
SERVICE LEVELS

Availability shall be no less than 99.9 percent measured monthly.
"""


@pytest.mark.parametrize(
    "text,expected",
    [
        ("attached hereto as Exhibit A", ("Exhibit A", "A", "exhibit")),
        ("in the form of Exhibit B hereto", ("Exhibit B", "B", "exhibit")),
        ("set out in Exhibit D", ("Exhibit D", "D", "exhibit")),
        ("Exhibit A.", ("Exhibit A", "A", "exhibit")),
        ("see Exhibit A, which governs", ("Exhibit A", "A", "exhibit")),
        ("as set out in Schedule C", ("Schedule C", "C", "schedule")),
    ],
)
def test_letter_named_attachments_are_detected(
    text: str, expected: tuple[str, str, str]
) -> None:
    references = ReferenceDetector("us").detect(text)
    assert [
        (r.raw_text, r.target_identifier, r.target_kind) for r in references
    ] == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "the Schedule Terms apply to this engagement",
        "Exhibit Alpha is not a reference",
        "each Section Head shall report quarterly",
        "the Article Nine provisions",
    ],
)
def test_a_capitalised_word_is_not_a_letter_reference(text: str) -> None:
    """The letter must stand alone: `Schedule Terms` is not schedule `T`."""
    assert ReferenceDetector("us").detect(text) == []


def test_roman_numeral_articles_still_win_the_alternation() -> None:
    """`Article IV` must stay `IV`, not collapse to the single letter `I`."""
    references = ReferenceDetector("us").detect("under Article IV of this Agreement")
    assert [(r.raw_text, r.target_identifier) for r in references] == [
        ("Article IV", "IV")
    ]


def test_numbered_references_are_unaffected() -> None:
    references = ReferenceDetector("us").detect(
        "pursuant to Section 3.02 and not otherwise"
    )
    assert [(r.raw_text, r.target_identifier) for r in references] == [
        ("Section 3.02", "3.02")
    ]


def test_exhibit_references_resolve_to_the_exhibit_chunk() -> None:
    chunks = LegalChunker(jurisdiction="us", min_chunk_size=0).chunk(_AGREEMENT)
    by_identifier = {c.hierarchy.identifier: c for c in chunks}
    exhibit_a = by_identifier["EXHIBIT A"]
    exhibit_b = by_identifier["EXHIBIT B"]

    body = by_identifier["Section 2.01"]
    targets = {
        r.raw_text: r.target_chunk_index
        for r in body.cross_references
        if r.target_kind == "exhibit"
    }
    assert targets == {"Exhibit A": exhibit_a.index, "Exhibit B": exhibit_b.index}
    assert body.cross_ref_resolved == body.cross_ref_total


def test_an_exhibit_reference_does_not_resolve_to_a_numbered_clause() -> None:
    """Container kinds stay strict: `Exhibit A` may not land on clause `A`."""
    text = (
        "Section 1.01 Scope\n\n"
        "The obligations set out in Exhibit A apply to the whole engagement.\n"
    )
    chunks = LegalChunker(jurisdiction="us", min_chunk_size=0).chunk(text)
    for chunk in chunks:
        for reference in chunk.cross_references:
            if reference.target_kind == "exhibit":
                assert reference.target_chunk_index is None
