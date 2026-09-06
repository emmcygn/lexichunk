"""Table-driven regression pin for the heading-plausibility gate.

The gate in :meth:`StructureParser._is_plausible_heading` is the single point
where clause detection can fail in both directions, and both failures are
silent:

* a **false negative** does not merely mis-level a clause — the clause body is
  absorbed into the previous clause, so there is no chunk, no
  ``hierarchy_path``, and no way to retrieve the provision by its title;
* a **false positive** injects a bogus top-level entry (a page number, a
  postal address, a line item) into the hierarchy, which then shows up in
  every ``context_header`` beneath it.

Both directions therefore need a fixed table that CI runs on every commit.
The lines below are the ones real documents actually broke on: the realistic
heading set and the numeric-prose set are taken verbatim from
``tests/test_g7_adversarial_fixes.py``, and the table-of-contents and
container cases from ``tests/test_g1_structure.py``. The suites there test the
gate's internals; this module is the flat, CI-facing table.
"""

from __future__ import annotations

import pytest

from lexichunk.models import Jurisdiction
from lexichunk.parsers.structure import StructureParser

# ---------------------------------------------------------------------------
# Must be detected: 25 realistic contract headings
# ---------------------------------------------------------------------------

# Sixteen titles that an adversarial pass showed being swallowed outright —
# each starts with, or contains, a word the gate used to treat as prose
# ("Business", "Hours", "Working", "Year", "Month", "Calendar", "Minute",
# "May") — plus nine ordinary headings kept as a control.
REALISTIC_HEADINGS: list[str] = [
    "Business Continuity",
    "Business Ethics and Anti-Bribery",
    "Days of Service",
    "Hours of Business",
    "Hours of Work",
    "Working Time Regulations",
    "Working Practices",
    "Working Capital Adjustment",
    "Year End Accounts",
    "Month-End Reporting",
    "Month End Reporting",
    "Calendar of Events",
    "Calendar Year Adjustment",
    "Minute Books",
    "May Not Be Assigned",
    "May Assign",
    "Definitions",
    "Confidentiality",
    "Governing Law",
    "Limitation of Liability",
    "Termination",
    "Notices",
    "Force Majeure",
    "Data Protection",
    "Intellectual Property",
]


def _numbered_document(title: str) -> str:
    """A three-clause UK contract whose middle clause is *title*."""
    return (
        "AGREEMENT\n\n"
        "1. Preliminary\n\n"
        "Some preliminary body text goes here for context.\n\n"
        f"2. {title}\n\n"
        "The body of this clause is here and continues for a sentence.\n\n"
        "3. Final\n\n"
        "Final body text.\n"
    )


def test_realistic_heading_table_is_the_expected_size() -> None:
    """Guard the table itself — a silent deletion would weaken the gate."""
    assert len(REALISTIC_HEADINGS) == 25
    assert len(set(REALISTIC_HEADINGS)) == 25


@pytest.mark.parametrize("title", REALISTIC_HEADINGS)
def test_realistic_heading_is_its_own_top_level_clause(title: str) -> None:
    clauses = StructureParser(Jurisdiction.UK).parse(_numbered_document(title))
    match = [c for c in clauses if c.title == title]
    assert len(match) == 1, f"{title!r} was not detected as a clause heading"
    assert match[0].level == 0
    assert match[0].identifier == "2"


def test_nine_word_allcaps_heading_survives() -> None:
    """A common US heading longer than the ALL-CAPS word budget used to be."""
    document = (
        "PRELIMINARY MATTERS\n\nSome body text here.\n\n"
        "REPRESENTATIONS AND WARRANTIES OF THE SELLER AND THE COMPANY\n\n"
        "The Seller represents and warrants as follows.\n"
    )
    clauses = StructureParser(Jurisdiction.US).parse(document)
    assert any(
        c.identifier == "REPRESENTATIONS AND WARRANTIES OF THE SELLER AND THE COMPANY"
        for c in clauses
    )


def test_long_but_short_worded_numbered_heading_survives() -> None:
    title = "Limitation of Liability and Exclusion of Consequential Loss"
    document = (
        "AGREEMENT\n\n1. Scope\n\nBody text.\n\n"
        f"2. {title}\n\nThe liability of each party is limited.\n"
    )
    clauses = StructureParser(Jurisdiction.UK).parse(document)
    assert title in [c.title for c in clauses]


# ---------------------------------------------------------------------------
# Must NOT be detected: heading-shaped lines that are really prose
# ---------------------------------------------------------------------------

_NUMERIC_PROSE_TEMPLATE = (
    "AGREEMENT\n\n1. Payment\n\n"
    "The Client shall pay each invoice within\n"
    "{line}\n\n2. Term\n\nOne year.\n"
)

_LIST_ITEM_TEMPLATE = (
    "AGREEMENT\n\n5. Fees\n\nThe fees payable are as follows.\n\n"
    "2. {line} per month for hosting services.\n\n"
    "6. Term\n\nOne year.\n"
)

_ADDRESS_TEMPLATE = (
    "AGREEMENT\n\n5. Notices\n\nAny notice shall be sent to:\n\n"
    "50 Broadway, London, {line}. VAT number: GB 312 4487 90.\n\n"
    "6. Governing Law\n\nEnglish law applies.\n"
)

# (label, template, line, identifiers that must be the only level-0 clauses)
FALSE_POSITIVE_CASES: list[tuple[str, str, str, list[str]]] = [
    # Dates and durations opening a wrapped sentence.
    ("duration-business-days", _NUMERIC_PROSE_TEMPLATE,
     "3 Business Days after receipt of an invoice.", ["1", "2"]),
    ("duration-working-days", _NUMERIC_PROSE_TEMPLATE,
     "5 Working Days from the date on which the invoice is received.", ["1", "2"]),
    ("duration-days", _NUMERIC_PROSE_TEMPLATE,
     "30 days after the date of the notice given under this clause.", ["1", "2"]),
    ("date-month-year", _NUMERIC_PROSE_TEMPLATE,
     "January 2024 is the Effective Date of this Agreement.", ["1", "2"]),
    # Currency amounts in a numbered price list.
    ("currency-gbp-code", _LIST_ITEM_TEMPLATE, "GBP 5,000", ["5", "6"]),
    ("currency-gbp-symbol", _LIST_ITEM_TEMPLATE, "£5,000", ["5", "6"]),
    ("currency-usd-symbol", _LIST_ITEM_TEMPLATE, "$5,000", ["5", "6"]),
    ("currency-usd-code", _LIST_ITEM_TEMPLATE, "USD 5,000", ["5", "6"]),
    ("currency-eur-symbol", _LIST_ITEM_TEMPLATE, "€5.000", ["5", "6"]),
    # Postal addresses in a notices clause.
    ("postcode-sw1h", _ADDRESS_TEMPLATE, "SW1H 0BD", ["5", "6"]),
    ("postcode-ec1a", _ADDRESS_TEMPLATE, "EC1A 1BB", ["5", "6"]),
    ("postcode-m1", _ADDRESS_TEMPLATE, "M1 1AE", ["5", "6"]),
    ("postcode-b33", _ADDRESS_TEMPLATE, "B33 8TH", ["5", "6"]),
]


@pytest.mark.parametrize(
    "case", FALSE_POSITIVE_CASES, ids=[c[0] for c in FALSE_POSITIVE_CASES]
)
def test_heading_shaped_prose_is_rejected(case: tuple[str, str, str, list[str]]) -> None:
    label, template, line, expected = case
    clauses = StructureParser(Jurisdiction.UK).parse(template.format(line=line))
    top_level = [c.identifier for c in clauses if c.level == 0]
    assert top_level == expected, f"{label}: {line!r} was promoted to a clause"


# ---------------------------------------------------------------------------
# Table-of-contents lines
# ---------------------------------------------------------------------------

TOC_CASES: list[tuple[str, str]] = [
    (
        "dot-leader",
        "1. Definitions .................................................. 3\n"
        "2. Services ...................................................... 5\n"
        "\n"
        "1.   Definitions\n"
        "The following terms apply.\n",
    ),
    (
        "wide-gutter",
        "1. Definitions        3\n\n1.   Definitions\nBody.\n",
    ),
]


@pytest.mark.parametrize("case", TOC_CASES, ids=[c[0] for c in TOC_CASES])
def test_table_of_contents_line_is_rejected(case: tuple[str, str]) -> None:
    label, text = case
    parser = StructureParser(Jurisdiction.UK)
    clauses = parser.parse(text)
    assert [c.identifier for c in clauses] == ["preamble", "1"], label
    assert parser.last_rejected_headings >= 1, label


# ---------------------------------------------------------------------------
# Container placement (Schedule / Exhibit / Annex)
# ---------------------------------------------------------------------------


def test_column_zero_schedule_is_a_container() -> None:
    parser = StructureParser(Jurisdiction.UK)
    clauses = parser.parse("SCHEDULE 2 - FEES\nSome schedule body text.\n")
    assert [c.identifier for c in clauses] == ["SCHEDULE 2"]
    assert parser.last_rejected_headings == 0


def test_wrapped_schedule_reference_is_not_a_container() -> None:
    """An indented `Schedule 2.` continuing a sentence is a reference."""
    text = (
        "3.   Fees and payment\n"
        "\n"
        "3.1  In consideration of the provision of the Services, the Client "
        "shall pay the Fees to\n"
        "     the Supplier in accordance with the payment terms set out in "
        "this clause 3 and in\n"
        "     Schedule 2.\n"
        "\n"
        "4.   Confidentiality\n"
        "Each party shall keep information confidential.\n"
    )
    parser = StructureParser(Jurisdiction.UK)
    clauses = parser.parse(text)
    assert "Schedule 2" not in [c.identifier for c in clauses]
    assert parser.last_rejected_headings >= 1
