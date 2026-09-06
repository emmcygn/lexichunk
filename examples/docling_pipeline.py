"""Docling -> lexichunk, end to end, with no models and no PDF.

The real pipeline is three lines::

    result = DocumentConverter().convert("msa.pdf")
    sections = from_docling(result.document, jurisdiction="uk")
    chunks = LegalChunker(jurisdiction="uk").chunk_documents(sections)

That first line needs the full ``docling`` package and a few hundred
megabytes of models, so this example builds the ``DoclingDocument`` by hand
instead — the same object ``convert()`` would have returned, assembled with
``docling-core`` alone.  Everything after that line is exactly what you would
run in production.

What the example is actually showing: Docling knows where the headings and
the running header are, because it read the PDF's layout.  It does not know
that ``SCHEDULE 1`` is a container rather than a top-level clause, that
``1.1`` nests under ``1``, that ``"Services"`` was defined in clause 1, or
that a chunk must not straddle two top-level clauses.  Handing Docling's
structure to ``chunk_documents()`` gets you both halves.

Requires ``pip install 'lexichunk[docling]'``.

Run::

    python examples/docling_pipeline.py
"""

from __future__ import annotations

import sys

from lexichunk import LegalChunker

try:
    from docling_core.types.doc import ContentLayer, DocItemLabel, DoclingDocument
    from docling_core.types.doc.document import TableCell, TableData
except ImportError:
    print(
        "This example needs docling-core:\n"
        "    pip install 'lexichunk[docling]'\n"
        "(the full `docling` package is only needed to convert real PDFs)."
    )
    sys.exit(0)

from lexichunk.ingestion import from_docling


def _cell(text: str, row: int, column: int, *, header: bool = False) -> TableCell:
    """Build a single-row, single-column table cell."""
    return TableCell(
        text=text,
        start_row_offset_idx=row,
        end_row_offset_idx=row + 1,
        start_col_offset_idx=column,
        end_col_offset_idx=column + 1,
        column_header=header,
    )


def build_document() -> DoclingDocument:
    """Assemble the document a PDF conversion would have produced.

    Deliberately includes the two things that make extracted legal text hard
    and that Docling gets right: a running page header (tagged as furniture,
    so it never lands in a clause) and a fee table (structured, so it can be
    exported row-wise instead of as a smear of numbers).
    """
    doc = DoclingDocument(name="project-atlas-msa")

    doc.add_title(text="Project Atlas Services Agreement")

    # Docling tags running headers and footers as furniture. In text
    # extracted from the same PDF, this line would appear every 45 lines,
    # in the middle of whichever clause spanned the page break.
    doc.add_text(
        label=DocItemLabel.PAGE_HEADER,
        text="CONFIDENTIAL - Project Atlas Services Agreement",
        content_layer=ContentLayer.FURNITURE,
    )
    doc.add_text(
        label=DocItemLabel.PAGE_FOOTER,
        text="Page 1 of 42",
        content_layer=ContentLayer.FURNITURE,
    )

    doc.add_text(
        label=DocItemLabel.TEXT,
        text="This Agreement is made on 1 March 2024 between Atlas Systems "
        "Limited and Northgate Holdings plc.",
    )

    doc.add_heading(text="1. Definitions and Interpretation", level=1)
    doc.add_text(
        label=DocItemLabel.TEXT,
        text='In this Agreement, "Services" means the managed hosting and '
        'support services described in Schedule 1, and "Charges" means the '
        "fees set out in that Schedule.",
    )

    doc.add_heading(text="1.1 Construction", level=2)
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="Headings are for convenience only and do not affect the "
        "construction of this Agreement.",
    )

    doc.add_heading(text="2. Charges and Payment", level=1)
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="The Customer shall pay the Charges within thirty days of receipt "
        "of a valid invoice, as further described in clause 1.1 and "
        "Schedule 1.",
    )

    doc.add_heading(text="3. Limitation of Liability", level=1)
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="Neither party excludes liability for death or personal injury "
        "caused by its negligence. Subject to that, the Supplier's total "
        "liability under this Agreement shall not exceed the Charges paid in "
        "the preceding twelve months.",
    )

    # Docling reports this at the same heading depth as "1." and "2.".
    # lexichunk's UK rules know a Schedule is a container, not clause 4.
    doc.add_heading(text="Schedule 1 - Charges", level=1)
    doc.add_table(
        data=TableData(
            num_rows=3,
            num_cols=3,
            table_cells=[
                _cell("Service", 0, 0, header=True),
                _cell("Charge", 0, 1, header=True),
                _cell("Frequency", 0, 2, header=True),
                _cell("Managed hosting", 1, 0),
                _cell("GBP 5,000", 1, 1),
                _cell("Monthly", 1, 2),
                _cell("Support desk", 2, 0),
                _cell("GBP 1,200", 2, 1),
                _cell("Monthly", 2, 2),
            ],
        )
    )
    listing = doc.add_list_group()
    doc.add_list_item(
        text="The Charges are exclusive of VAT.", marker="(a)", parent=listing
    )
    doc.add_list_item(
        text="The Charges may be reviewed annually.", marker="(b)", parent=listing
    )
    return doc


def main() -> None:
    """Convert, chunk, and show what each half of the pipeline contributed."""
    doc = build_document()

    # --- The one line you would replace with a real conversion -------------
    sections = from_docling(doc, jurisdiction="uk")

    print("Sections from Docling, after lexichunk refined the levels")
    print("-" * 78)
    for section in sections:
        title = f" - {section.title}" if section.title else ""
        print(f"  level {section.level:>3}  {section.identifier}{title}")

    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    chunks, metrics = chunker.chunk_documents(
        sections, document_id="project-atlas-msa", return_metrics=True
    )

    print()
    print("Chunks")
    print("-" * 78)
    for chunk in chunks:
        print(f"[{chunk.index}] {chunk.hierarchy_path}")
        print(f"     section={chunk.document_section}  type={chunk.clause_type}")
        if chunk.defined_terms_used:
            print(f"     terms: {', '.join(sorted(chunk.defined_terms_used))}")
        for reference in chunk.cross_references:
            target = (
                f"chunk {reference.target_chunk_index}"
                if reference.target_chunk_index is not None
                else "unresolved"
            )
            print(f"     ref: {reference.raw_text!r} -> {target}")

    print()
    print("What each half contributed")
    print("-" * 78)
    print(
        "  Docling      : reading order, heading boundaries, the fee table as\n"
        "                 rows, and the running header/footer marked as\n"
        "                 furniture (dropped, so 'CONFIDENTIAL - Project\n"
        "                 Atlas' never lands inside clause 2)."
    )
    print(
        "  lexichunk    : Schedule 1 recognised as a container rather than\n"
        "                 clause 4, 1.1 nested under 1, 'Services' and\n"
        "                 'Charges' extracted and attached where used, and\n"
        "                 cross-references resolved to chunk indices."
    )
    print()
    print(
        f"  {metrics.clause_count} sections -> {metrics.chunk_count} chunks; "
        f"{metrics.chunks_spanning_multiple_top_level_clauses} chunks span two "
        f"top-level clauses (must be 0)."
    )

    furniture = any("CONFIDENTIAL" in chunk.content for chunk in chunks)
    print(f"  Running header present in any chunk: {furniture}")


if __name__ == "__main__":
    main()
