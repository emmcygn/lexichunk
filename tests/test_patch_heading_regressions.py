from __future__ import annotations

import pytest

from lexichunk.models import Jurisdiction
from lexichunk.parsers.structure import StructureParser


def _identifiers_and_parents(text: str, jurisdiction: Jurisdiction) -> list[tuple[str, str | None]]:
    clauses = StructureParser(jurisdiction).parse(text)
    return [(clause.identifier, clause.parent_identifier) for clause in clauses]


@pytest.mark.parametrize(
    "body_line",
    [
        'The product is called the "Service."',
        "The product is called the “Service.”",
        "The product is called the Service (including support.)",
        "The product is called the «Service.»",
        "The product is called the ‹Service.›",
    ],
    ids=[
        "straight-quotes",
        "curly-quotes",
        "parentheses",
        "double-angle-quotes",
        "single-angle-quotes",
    ],
)
def test_uk_heading_after_punctuation_inside_closing_delimiter_is_a_new_root(
    body_line: str,
) -> None:
    text = f"1. Definitions\n{body_line}\n2. Term\nThe term begins today.\n"

    assert _identifiers_and_parents(text, Jurisdiction.UK) == [
        ("1", None),
        ("2", None),
    ]


@pytest.mark.parametrize(
    "body_line",
    [
        'The product is called the "Service"',
        "The product is called the “Service”",
        "The product is called the Service (including support)",
        "The product is called the «Service»",
        "The product is called the ‹Service›",
    ],
    ids=[
        "straight-quotes",
        "curly-quotes",
        "parentheses",
        "double-angle-quotes",
        "single-angle-quotes",
    ],
)
def test_closing_delimiter_without_sentence_punctuation_does_not_open_a_block(
    body_line: str,
) -> None:
    text = f"1. Definitions\n{body_line}\n2. Term\nThe term begins today.\n"

    assert _identifiers_and_parents(text, Jurisdiction.UK) == [("1", None)]


def test_us_numbered_list_under_section_is_not_promoted_to_clause_roots() -> None:
    text = (
        "SECTION 1.01 ORDER FORM\n"
        "The Order Form shall include:\n"
        "1. Customer Name\n"
        "2. Service Address\n"
        "SECTION 1.02 TERM\n"
        "The Term begins today.\n"
    )

    assert _identifiers_and_parents(text, Jurisdiction.US) == [
        ("Section 1.01", None),
        ("Section 1.02", None),
    ]


def test_us_bare_decimal_headings_remain_clause_roots() -> None:
    text = (
        "1. Definitions\n"
        "The product is called the Service.\n"
        "2. Term\n"
        "The term begins today.\n"
    )

    assert _identifiers_and_parents(text, Jurisdiction.US) == [
        ("1", None),
        ("2", None),
    ]


def test_us_pdf_wrapped_decimal_continuation_remains_body_text() -> None:
    text = (
        "Section 11.3 Modifications. Strata may modify these Terms from time to time by\n"
        "posting revised Terms on its website. If Customer objects to any modification,\n"
        "Customer's sole remedy is to terminate its subscription in accordance with Section\n"
        "7.2. Continued use of the Platform after the effective date of any modification\n"
        "constitutes acceptance of the modified Terms.\n"
    )

    assert _identifiers_and_parents(text, Jurisdiction.US) == [
        ("Section 11.3", None),
    ]


def test_us_blank_line_ends_explicit_section_form_list_context() -> None:
    text = (
        "SECTION 1.02 TERM\n"
        "Body.\n"
        "\n"
        "\n"
        "2. Service Levels\n"
        "The service levels apply.\n"
        "3. Charges\n"
        "The charges apply.\n"
    )

    assert _identifiers_and_parents(text, Jurisdiction.US) == [
        ("Section 1.02", None),
        ("2", None),
        ("3", None),
    ]


def test_us_lowercase_numbered_form_list_keeps_following_section_root() -> None:
    text = (
        "SECTION 1.01 ORDER FORM\n"
        "The form includes:\n"
        "1. customer name\n"
        "2. service address\n"
        "SECTION 1.02 TERM\n"
        "Body.\n"
    )

    assert _identifiers_and_parents(text, Jurisdiction.US) == [
        ("Section 1.01", None),
        ("Section 1.02", None),
    ]


def test_us_section_heading_colon_introduces_numbered_form_list() -> None:
    text = (
        "SECTION 1.01 REQUIRED INFORMATION:\n"
        "1. Customer Name\n"
        "2. Service Address\n"
        "SECTION 1.02 TERM\n"
        "Body.\n"
    )

    assert _identifiers_and_parents(text, Jurisdiction.US) == [
        ("Section 1.01", None),
        ("Section 1.02", None),
    ]


def test_us_heading_context_work_is_linear_in_candidate_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section_count = 200
    inspected_context_entries = 0
    original = StructureParser._inside_marked_us_section

    def counted_inside_marked_us_section(
        parser: StructureParser,
        context: dict[int, tuple[int, str]] | list[tuple[int, str]] | None,
    ) -> bool:
        nonlocal inspected_context_entries
        inspected_context_entries += len(context) if context is not None else 0
        return original(parser, context)

    monkeypatch.setattr(
        StructureParser,
        "_inside_marked_us_section",
        counted_inside_marked_us_section,
    )
    text = "".join(
        f"SECTION 1.{section_number:03d} HEADING\nBody.\n"
        for section_number in range(1, section_count + 1)
    )

    clauses = StructureParser(Jurisdiction.US).parse(text)

    assert len(clauses) == section_count
    assert inspected_context_entries <= section_count * 2
