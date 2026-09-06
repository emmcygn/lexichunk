"""Ingestion adapters: Docling, ``unstructured``, and markdown.

The Docling tests build ``DoclingDocument`` objects programmatically — no
PDF, no ML models, no ``docling`` package — so they exercise the real
docling-core API without any of its heavyweight surroundings.  The
``unstructured`` tests use stand-in objects on purpose: the adapter is
duck-typed and imports nothing, which is exactly the property worth pinning.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from lexichunk import LegalChunker
from lexichunk.exceptions import InputError
from lexichunk.ingestion import (
    from_docling,
    from_markdown,
    from_unstructured,
    refine_heading,
)
from lexichunk.models import DocumentSection, Section

docling_types = pytest.importorskip("docling_core.types.doc")


# ---------------------------------------------------------------------------
# Import safety
# ---------------------------------------------------------------------------


def test_the_package_imports_without_touching_optional_dependencies() -> None:
    """Importing lexichunk.ingestion must not pull in a converter."""
    for module in list(sys.modules):
        if module.startswith(("lexichunk.ingestion", "docling_core")):
            sys.modules.pop(module, None)
    importlib.import_module("lexichunk.ingestion")
    assert not any(m.startswith("docling_core") for m in sys.modules)
    assert not any(m.startswith("unstructured") for m in sys.modules)


def test_from_docling_raises_a_helpful_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With docling-core absent, the error names the fix."""
    import builtins

    real_import = builtins.__import__

    def _blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("docling_core"):
            raise ImportError("No module named 'docling_core'")
        return real_import(name, *args, **kwargs)

    for module in list(sys.modules):
        if module.startswith("docling_core"):
            monkeypatch.delitem(sys.modules, module, raising=False)
    monkeypatch.setattr(builtins, "__import__", _blocked)

    with pytest.raises(ImportError, match=r"lexichunk\[docling\]"):
        from_docling(object())


# ---------------------------------------------------------------------------
# refine_heading
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "heading,jurisdiction,fallback,expected",
    [
        ("5.2 Payment Terms", "uk", 0, ("5.2", "Payment Terms", 1)),
        ("1. Definitions", "uk", 3, ("1", "Definitions", 0)),
        ("SCHEDULE 1 - FEES", "uk", 0, ("SCHEDULE 1", "FEES", -1)),
        # A heading that is nothing but numbering is still a real detection.
        ("Schedule 2", "uk", 0, ("Schedule 2", None, -1)),
        ("Article IV — Indemnification", "us", 2, ("Article IV", "Indemnification", 0)),
        ("Section 3.01 Notices", "us", 0, ("Section 3.01", "Notices", 1)),
        ("Exhibit A", "us", 0, ("Exhibit A", None, -2)),
        # No numbering: the converter's own depth is kept.
        ("CONFIDENTIALITY", "uk", 1, ("CONFIDENTIALITY", None, 1)),
        # The US ALL-CAPS fallback is ignored: it carries no numbering.
        ("CONFIDENTIALITY", "us", 2, ("CONFIDENTIALITY", None, 2)),
        ("Governing Law", "uk", 2, ("Governing Law", None, 2)),
        ("", "uk", 0, ("", None, 0)),
    ],
)
def test_refine_heading(
    heading: str,
    jurisdiction: str,
    fallback: int,
    expected: tuple[str, Optional[str], int],
) -> None:
    assert refine_heading(heading, jurisdiction, fallback) == expected


def test_numbering_overrides_the_converters_depth() -> None:
    """A converter that flattens a schedule and a clause is corrected."""
    _, _, clause_level = refine_heading("5. Payment", "uk", 0)
    _, _, schedule_level = refine_heading("Schedule 2", "uk", 0)
    assert schedule_level < clause_level


# ---------------------------------------------------------------------------
# Docling
# ---------------------------------------------------------------------------


def _build_docling_document() -> Any:
    """A small agreement with a title, headings, a table, a list and furniture."""
    from docling_core.types.doc import ContentLayer, DocItemLabel, DoclingDocument
    from docling_core.types.doc.document import TableCell, TableData

    doc = DoclingDocument(name="project-atlas-msa")
    doc.add_title(text="Master Services Agreement")
    doc.add_text(
        label=DocItemLabel.PAGE_HEADER,
        text="CONFIDENTIAL - Project Atlas Services Agreement",
        content_layer=ContentLayer.FURNITURE,
    )
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="This agreement is made on 1 March 2024 between the parties.",
    )
    doc.add_heading(text="1. Definitions", level=1)
    doc.add_text(
        label=DocItemLabel.TEXT,
        text='In this agreement "Services" means the services described in '
        "Schedule 1.",
    )
    doc.add_heading(text="1.1 Interpretation", level=2)
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="Headings are for convenience only and do not affect construction.",
    )
    doc.add_heading(text="2. Payment", level=1)
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="The Customer shall pay each invoice within thirty days, as set "
        "out in clause 1.1.",
    )
    doc.add_heading(text="SCHEDULE 1 - FEES", level=1)
    doc.add_table(
        data=TableData(
            num_rows=3,
            num_cols=2,
            table_cells=[
                TableCell(
                    text="Service",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                    column_header=True,
                ),
                TableCell(
                    text="Fee",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                    column_header=True,
                ),
                TableCell(
                    text="Hosting",
                    start_row_offset_idx=1,
                    end_row_offset_idx=2,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                ),
                TableCell(
                    text="GBP 5,000 per month",
                    start_row_offset_idx=1,
                    end_row_offset_idx=2,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                ),
                TableCell(
                    text="Support",
                    start_row_offset_idx=2,
                    end_row_offset_idx=3,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                ),
                TableCell(
                    text="GBP 1,200 per month",
                    start_row_offset_idx=2,
                    end_row_offset_idx=3,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                ),
            ],
        )
    )
    group = doc.add_list_group()
    doc.add_list_item(
        text="The Supplier shall provide hosting.", marker="(a)", parent=group
    )
    doc.add_list_item(
        text="The Supplier shall provide support.", marker="(b)", parent=group
    )
    return doc


@pytest.fixture(scope="module")
def docling_document() -> Any:
    return _build_docling_document()


def test_docling_sections_in_document_order(docling_document: Any) -> None:
    sections = from_docling(docling_document, jurisdiction="uk")
    assert [s.identifier for s in sections] == [
        "Master Services Agreement",
        "1",
        "1.1",
        "2",
        "SCHEDULE 1",
    ]


def test_docling_levels_come_from_the_numbering(docling_document: Any) -> None:
    """Both "1. Definitions" and "SCHEDULE 1" are Docling heading level 1."""
    sections = {s.identifier: s for s in from_docling(docling_document)}
    assert sections["1"].level == 0
    assert sections["1.1"].level == 1
    # The numbering says a schedule is a container, not a top-level clause,
    # even though Docling reported the same heading depth for both.
    assert sections["SCHEDULE 1"].level == -1


def test_docling_titles_are_split_off_the_identifier(docling_document: Any) -> None:
    sections = {s.identifier: s for s in from_docling(docling_document)}
    assert sections["1"].title == "Definitions"
    assert sections["1.1"].title == "Interpretation"
    assert sections["SCHEDULE 1"].title == "FEES"


def test_docling_title_item_encloses_the_document(docling_document: Any) -> None:
    sections = from_docling(docling_document)
    assert sections[0].identifier == "Master Services Agreement"
    assert sections[0].level == -3
    assert sections[0].level < min(s.level for s in sections[1:])


def test_docling_title_can_be_dropped(docling_document: Any) -> None:
    sections = from_docling(docling_document, include_title=False)
    assert sections[0].identifier == "preamble"
    assert sections[0].level == -99
    assert "1 March 2024" in sections[0].text


def test_docling_furniture_is_dropped_by_default(docling_document: Any) -> None:
    sections = from_docling(docling_document)
    assert not any("CONFIDENTIAL" in s.text for s in sections)


def test_docling_furniture_can_be_kept(docling_document: Any) -> None:
    sections = from_docling(docling_document, include_furniture=True)
    assert any("CONFIDENTIAL" in s.text for s in sections)


def test_docling_tables_are_exported_row_wise(docling_document: Any) -> None:
    schedule = next(
        s for s in from_docling(docling_document) if s.identifier == "SCHEDULE 1"
    )
    lines = schedule.text.splitlines()
    assert "Service | Fee" in lines
    assert "Hosting | GBP 5,000 per month" in lines
    assert "Support | GBP 1,200 per month" in lines


def test_docling_tables_can_be_dropped(docling_document: Any) -> None:
    schedule = next(
        s
        for s in from_docling(docling_document, include_tables=False)
        if s.identifier == "SCHEDULE 1"
    )
    assert "GBP 5,000" not in schedule.text
    assert "The Supplier shall provide hosting." in schedule.text


def test_docling_list_markers_are_preserved(docling_document: Any) -> None:
    schedule = next(
        s for s in from_docling(docling_document) if s.identifier == "SCHEDULE 1"
    )
    assert "(a) The Supplier shall provide hosting." in schedule.text
    assert "(b) The Supplier shall provide support." in schedule.text


def test_docling_json_round_trips(docling_document: Any) -> None:
    from_object = from_docling(docling_document)
    from_json = from_docling(docling_document.model_dump_json())
    assert [s.to_dict() for s in from_object] == [s.to_dict() for s in from_json]


def test_docling_accepts_a_dict(docling_document: Any) -> None:
    payload = docling_document.model_dump(mode="json")
    assert [s.identifier for s in from_docling(payload)] == [
        s.identifier for s in from_docling(docling_document)
    ]


def test_docling_rejects_unusable_input() -> None:
    with pytest.raises(InputError, match="expects a DoclingDocument"):
        from_docling(42)


def test_docling_rejects_malformed_json() -> None:
    with pytest.raises(InputError, match="could not read the given JSON"):
        from_docling('{"not": "a document"}')


def test_docling_end_to_end_through_chunk_documents(docling_document: Any) -> None:
    sections = from_docling(docling_document, jurisdiction="uk")
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    chunks, metrics = chunker.chunk_documents(sections, return_metrics=True)
    assert chunks
    assert metrics.chunks_spanning_multiple_top_level_clauses == 0
    paths = [c.hierarchy_path for c in chunks]
    assert any("1.1" in path for path in paths)
    # The schedule is classified as such because the numbering said so.
    assert any(c.document_section is DocumentSection.SCHEDULES for c in chunks)
    # Cross-references still resolve across externally-parsed sections.
    assert any(
        ref.target_chunk_index is not None
        for c in chunks
        for ref in c.cross_references
    )
    # And defined terms still attach.
    assert any("Services" in c.defined_terms_used for c in chunks)


def test_docling_empty_document_yields_no_sections() -> None:
    from docling_core.types.doc import DoclingDocument

    assert from_docling(DoclingDocument(name="empty")) == []


# ---------------------------------------------------------------------------
# unstructured (stand-in objects — nothing is installed or imported)
# ---------------------------------------------------------------------------


@dataclass
class _Metadata:
    category_depth: Optional[int] = None


@dataclass
class _Element:
    category: str
    text: str
    metadata: _Metadata = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = _Metadata()


_ELEMENTS = [
    _Element("Header", "CONFIDENTIAL - Project Atlas"),
    _Element("Title", "MASTER SERVICES AGREEMENT", _Metadata(category_depth=0)),
    _Element("NarrativeText", "This agreement is made on 1 March 2024."),
    _Element("Title", "1. Definitions", _Metadata(category_depth=0)),
    _Element(
        "NarrativeText",
        'In this agreement "Services" means the services described in Schedule 1.',
    ),
    _Element("Title", "1.1 Interpretation", _Metadata(category_depth=1)),
    _Element("NarrativeText", "Headings are for convenience only."),
    _Element("Title", "Schedule 1", _Metadata(category_depth=0)),
    _Element("ListItem", "(a) Hosting services."),
    _Element("ListItem", "(b) Support services."),
    _Element("Table", "Service Fee\nHosting GBP 5,000"),
    _Element("PageNumber", "Page 3 of 42"),
    _Element("Footer", "Page 3 of 42"),
]


def test_unstructured_sections_and_levels() -> None:
    sections = from_unstructured(_ELEMENTS, jurisdiction="uk")
    assert [s.identifier for s in sections] == [
        "MASTER SERVICES AGREEMENT",
        "1",
        "1.1",
        "Schedule 1",
    ]
    levels = {s.identifier: s.level for s in sections}
    assert levels["MASTER SERVICES AGREEMENT"] == 0
    assert levels["1"] == 0
    assert levels["1.1"] == 1
    assert levels["Schedule 1"] == -1


def test_unstructured_furniture_is_dropped_by_default() -> None:
    body = " ".join(s.text for s in from_unstructured(_ELEMENTS))
    assert "CONFIDENTIAL" not in body
    assert "Page 3 of 42" not in body


def test_unstructured_furniture_can_be_kept() -> None:
    body = " ".join(s.text for s in from_unstructured(_ELEMENTS, include_furniture=True))
    assert "Page 3 of 42" in body


def test_unstructured_lists_and_tables_land_in_the_section() -> None:
    schedule = next(
        s for s in from_unstructured(_ELEMENTS) if s.identifier == "Schedule 1"
    )
    assert "(a) Hosting services." in schedule.text
    assert "Hosting GBP 5,000" in schedule.text


def test_unstructured_missing_category_depth_defaults_to_top_level() -> None:
    elements = [_Element("Title", "CONFIDENTIALITY"), _Element("NarrativeText", "Body.")]
    sections = from_unstructured(elements)
    assert sections[0].level == 0


def test_unstructured_falls_back_to_the_class_name() -> None:
    class NarrativeText:
        text = "Some body text with no category attribute at all."
        metadata = _Metadata()

    sections = from_unstructured([NarrativeText()])
    assert sections[0].identifier == "preamble"
    assert "no category attribute" in sections[0].text


def test_unstructured_unknown_categories_are_kept_not_dropped() -> None:
    elements = [
        _Element("Title", "1. Definitions"),
        _Element("SomethingNew", "Text a future version invented."),
    ]
    sections = from_unstructured(elements)
    assert "future version invented" in sections[0].text


def test_unstructured_rejects_a_bare_string() -> None:
    with pytest.raises(InputError, match="iterable of partition elements"):
        from_unstructured("1. Definitions")  # type: ignore[arg-type]


def test_unstructured_rejects_a_non_iterable() -> None:
    with pytest.raises(InputError, match="iterable of partition elements"):
        from_unstructured(42)  # type: ignore[arg-type]


def test_unstructured_end_to_end() -> None:
    chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk_documents(
        from_unstructured(_ELEMENTS, jurisdiction="uk")
    )
    assert chunks
    assert any(c.document_section is DocumentSection.SCHEDULES for c in chunks)


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------

_MARKDOWN = """\
# Master Services Agreement

This agreement is made between the parties on 1 March 2024.

## 1. Definitions

In this agreement "Services" means the services described in Schedule 1.

### 1.1 Interpretation

Headings are for convenience only.

## 2. Payment

The Customer shall pay each invoice within thirty days, per clause 1.1.

## Schedule 1 - Services Description

The Supplier shall provide managed hosting.
"""


def test_markdown_sections_and_levels() -> None:
    sections = from_markdown(_MARKDOWN, jurisdiction="uk")
    assert [s.identifier for s in sections] == [
        "Master Services Agreement",
        "1",
        "1.1",
        "2",
        "Schedule 1",
    ]
    levels = {s.identifier: s.level for s in sections}
    assert levels["1"] == 0
    assert levels["1.1"] == 1
    assert levels["Schedule 1"] == -1


def test_markdown_records_source_offsets() -> None:
    for section in from_markdown(_MARKDOWN):
        assert section.char_start is not None
        assert section.char_end is not None
        assert _MARKDOWN[section.char_start : section.char_end].strip()


def test_markdown_source_offsets_reach_the_chunks() -> None:
    chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk_documents(
        from_markdown(_MARKDOWN)
    )
    for chunk in chunks:
        assert chunk.raw_char_start >= 0
        assert _MARKDOWN[chunk.raw_char_start : chunk.raw_char_end].strip()


def test_markdown_leading_text_becomes_a_preamble() -> None:
    sections = from_markdown("Some framing text.\n\n# 1. Definitions\n\nBody.\n")
    assert sections[0].identifier == "preamble"
    assert sections[0].level == -99
    assert sections[0].text == "Some framing text."


def test_markdown_preamble_gets_no_synthesised_heading() -> None:
    """A preamble label must never appear in the reconstructed text."""
    chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk_documents(
        from_markdown("Some framing text.\n\n# 1. Definitions\n\nBody text here.\n")
    )
    assert "preamble" not in "".join(c.content for c in chunks)


def test_markdown_paragraphs_are_preserved() -> None:
    sections = from_markdown("# 1. Services\n\nFirst para.\n\nSecond para.\n")
    assert sections[0].text == "First para.\n\nSecond para."


def test_markdown_ignores_hashes_inside_a_fenced_block() -> None:
    text = (
        "# 1. Definitions\n\n"
        "```python\n"
        "# this is a comment, not a heading\n"
        "x = 1\n"
        "```\n\n"
        "Body text follows the block.\n"
    )
    sections = from_markdown(text)
    assert len(sections) == 1
    assert "not a heading" in sections[0].text


def test_markdown_handles_tilde_fences() -> None:
    text = "# 1. Definitions\n\n~~~\n# not a heading\n~~~\n\nBody.\n"
    assert len(from_markdown(text)) == 1


def test_markdown_closing_hashes_are_stripped() -> None:
    sections = from_markdown("## 2. Payment ##\n\nBody text.\n")
    assert sections[0].identifier == "2"
    assert sections[0].title == "Payment"


def test_markdown_empty_input_yields_nothing() -> None:
    assert from_markdown("") == []
    assert from_markdown("   \n\n  \n") == []


def test_markdown_heading_only_document_still_produces_sections() -> None:
    sections = from_markdown("# 1. Definitions\n## 1.1 Interpretation\n")
    assert [s.identifier for s in sections] == ["1", "1.1"]
    assert all(s.text == "" for s in sections)


def test_markdown_rejects_non_str() -> None:
    with pytest.raises(InputError, match="expects a str"):
        from_markdown(b"# heading")  # type: ignore[arg-type]


def test_markdown_end_to_end_matches_the_structure_we_expect() -> None:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    chunks, metrics = chunker.chunk_documents(
        from_markdown(_MARKDOWN, jurisdiction="uk"), return_metrics=True
    )
    assert metrics.chunks_spanning_multiple_top_level_clauses == 0
    by_path = {c.hierarchy_path: c for c in chunks}
    assert "1 — Definitions > 1.1 — Interpretation" in by_path
    assert any(
        c.document_section is DocumentSection.SCHEDULES for c in chunks
    )
    assert any(
        ref.target_identifier == "1.1"
        for c in chunks
        for ref in c.cross_references
    )


def test_adapters_all_return_sections() -> None:
    for produced in (
        from_markdown(_MARKDOWN),
        from_unstructured(_ELEMENTS),
        from_docling(_build_docling_document()),
    ):
        assert produced
        assert all(isinstance(section, Section) for section in produced)
