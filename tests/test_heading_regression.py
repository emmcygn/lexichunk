"""Heading recognition: the shapes that must be found, and the ones that must not.

Two layers are pinned separately, because they fail differently.

``detect_level`` is a stateless per-line regex match. It decides whether a
line is *shaped* like a heading, and it is deliberately permissive.
:class:`~lexichunk.parsers.structure.StructureParser` then applies a
reject-only plausibility gate that can see the surrounding lines. A shape
that only a neighbour can disqualify — a wrapped sentence whose second line
happens to start with a number — belongs in the second table, not the first.

The US bare-decimal entries here exist because of a CUAD evaluation over 150
real SEC exhibit filings: ``jurisdiction="us"`` recovered five or more
top-level clauses in 14% of contracts against 31% for ``jurisdiction="uk"``
on the *same* US documents, purely because ``us`` demanded a literal
``Section``/``ARTICLE`` marker. Anyone following the obvious advice ("it's a
US contract, pass ``us``") silently got fixed-size splitting.
"""

from __future__ import annotations

import pytest

from lexichunk import LegalChunker
from lexichunk.jurisdiction import get_detect_level

# ---------------------------------------------------------------------------
# Layer 1 — per-line shape (no surrounding context)
# ---------------------------------------------------------------------------

# (jurisdiction, line, expected level or None, expected identifier or None)
HEADING_CASES: list[tuple[str, str, int | None, str | None]] = [
    # -- US: bare-decimal, the dominant US commercial style -----------------
    ("us", "1. Definitions.", 0, "1"),
    ("us", "1.  Definitions", 0, "1"),
    ("us", "2) Appointment", 0, "2"),
    ("us", "1.1 Affiliate means any entity under common control.", 1, "1.1"),
    ("us", "1.1. Scope", 1, "1.1"),
    ("us", "1.1.1 Sub-subsection text follows here.", 2, "1.1.1"),
    ("us", '1. "Affiliate" means any controlled entity;', 0, "1"),
    ("us", "3.   Fees (Exhibit A)", 0, "3"),
    # -- US: the keyword styles that already worked -------------------------
    ("us", "ARTICLE I", 0, "Article I"),
    ("us", "Article IV", 0, "Article IV"),
    ("us", "Section 1.01", 1, "Section 1.01"),
    ("us", "SECTION 7", 0, "Section 7"),
    ("us", "EXHIBIT A", -2, "EXHIBIT A"),
    ("us", "Schedule 2", -1, "Schedule 2"),
    ("us", "(a) The Board shall appoint the designee.", 3, "(a)"),
    ("us", "REPRESENTATIONS AND WARRANTIES", 0, "REPRESENTATIONS AND WARRANTIES"),
    # -- US: shapes that must NOT be headings even in isolation -------------
    # ";" rather than whitespace after the number: a wrapped sentence
    # ("... pursuant to Section\n4.5; (c) all outstanding fees ...").
    ("us", "4.5; (c) all outstanding Subscription Fees for the term", None, None),
    ("us", "1.2.3.4.5 is not a clause number", None, None),
    ("us", "2024 was a difficult year for the parties.", None, None),
    ("us", "The parties agree as follows.", None, None),
    # -- UK: the same bare-decimal shapes, unchanged by this work -----------
    ("uk", "1. Definitions", 0, "1"),
    ("uk", "1.1 Interpretation", 1, "1.1"),
    ("uk", "1.1.1 Further detail", 2, "1.1.1"),
    ("uk", "Clause 7", 0, "Clause 7"),
    ("uk", "Schedule 1", -1, "Schedule 1"),
    # ``(i)`` is level 3 (alpha) here, not 4 (Roman): this layer is a bare
    # per-line match, and the alpha-vs-Roman choice is made later by
    # ``_collect_headers``, which knows whether ``(h)`` preceded it.
    ("uk", "(i) the first limb", 3, "(i)"),
    ("uk", "4.5; (c) all outstanding fees for the term", None, None),
    # -- EU ------------------------------------------------------------------
    ("eu", "Article 5", 0, "Article 5"),
    ("eu", "CHAPTER II", -1, "Chapter II"),
    ("eu", "Annex I", -2, "Annex I"),
]


@pytest.mark.parametrize(
    "jurisdiction,line,level,identifier",
    HEADING_CASES,
    ids=[f"{j}:{line[:32]}" for j, line, _, _ in HEADING_CASES],
)
def test_detect_level_shape(
    jurisdiction: str, line: str, level: int | None, identifier: str | None
) -> None:
    result = get_detect_level(jurisdiction)(line)
    if level is None:
        assert result is None, f"{line!r} was read as a heading: {result}"
    else:
        assert result == (level, identifier)


def test_us_and_uk_agree_on_bare_decimal_shapes() -> None:
    """The two profiles must not disagree about plain numbering.

    Divergence here is exactly what the CUAD evaluation found and what made
    the jurisdiction named for the corpus the worse choice for it.
    """
    for line in (
        "1. Definitions",
        "1.1 Interpretation",
        "1.1.1 Further detail",
        "12. Governing Law",
    ):
        assert get_detect_level("us")(line) == get_detect_level("uk")(line), line


# ---------------------------------------------------------------------------
# Layer 2 — the plausibility gate, which needs the neighbouring lines
# ---------------------------------------------------------------------------

_WRAPPED_CONTINUATION = """\
Section 11.3 Modifications. Strata may modify these Terms from time to time by
posting revised Terms on its website. If Customer objects to any modification,
Customer's sole remedy is to terminate its subscription in accordance with Section
7.2. Continued use of the Platform after the effective date of any modification
constitutes acceptance of the modified Terms.
"""

_STACKED_SUBCLAUSES = """\
1. Definitions

1.1 In this Agreement the following terms have the meanings given below.

2. Appointment

2.1 The Supplier is appointed on the terms set out in this Agreement.
"""


def test_a_wrapped_sentence_is_not_a_clause() -> None:
    """`7.2.` at the head of a wrapped line continues a sentence.

    Believing it costs a real clause body: everything below the false
    heading is re-parented under a clause that does not exist.
    """
    nodes = LegalChunker(jurisdiction="us").parse_structure(_WRAPPED_CONTINUATION)
    assert [n.identifier for n in nodes if n.identifier == "7.2"] == []


def test_subclauses_stacked_under_an_unpunctuated_heading_survive() -> None:
    """`1.1` directly under `1. Definitions` (no full stop) is still a clause.

    The gate's "previous line was itself a heading" alternative is what keeps
    this; without it the rule that rejects wrapped sentences would also
    reject every sub-clause in this extremely common layout.
    """
    nodes = LegalChunker(jurisdiction="us").parse_structure(_STACKED_SUBCLAUSES)
    identifiers = [n.identifier for n in nodes]
    for expected in ("1", "1.1", "2", "2.1"):
        assert expected in identifiers, f"{expected} missing from {identifiers}"


@pytest.mark.parametrize(
    "line",
    [
        "3 Business Days after receipt of a valid invoice.",
        "2. GBP 5,000 per month for hosting services.",
        "1. Definitions .......................... 4",
    ],
)
def test_body_text_shaped_like_a_heading_is_still_rejected(line: str) -> None:
    """The pre-existing prose guards must survive the new numeric patterns."""
    document = f"PRELIMINARY MATTERS\n\nThe parties agree as follows.\n\n{line}\n"
    nodes = LegalChunker(jurisdiction="us").parse_structure(document)
    assert [n for n in nodes if n.identifier in {"3", "2", "1"}] == []


# ---------------------------------------------------------------------------
# The CUAD reproducer itself
# ---------------------------------------------------------------------------

_CUAD_REPRODUCER = """\
DISTRIBUTION AGREEMENT

1. Definitions.
1.1 "Affiliate" means any entity under common control with a party.

2. Appointment.
2.1 Supplier appoints Distributor as its exclusive distributor.

3. Confidentiality.
3.1 Each party shall keep confidential all Confidential Information.

4. Indemnification.
4.1 Distributor shall indemnify and hold harmless Supplier.

5. Governing Law.
5.1 This Agreement is governed by the laws of the State of Delaware.
"""


@pytest.mark.parametrize("jurisdiction", ["us", "uk"])
def test_bare_decimal_contract_recovers_five_top_level_clauses(
    jurisdiction: str,
) -> None:
    """Issue 1 from the CUAD evaluation.

    Before the fix this gave ``us`` zero top-level nodes and a single chunk
    for the whole contract — structure-aware chunking silently degraded to
    fixed-size splitting.
    """
    chunker = LegalChunker(jurisdiction=jurisdiction, max_chunk_size=512)
    nodes = chunker.parse_structure(_CUAD_REPRODUCER)
    top_level = [n for n in nodes if n.level == 0]
    assert len(top_level) >= 5, [n.identifier for n in nodes]
    assert len(chunker.chunk(_CUAD_REPRODUCER)) > 1
