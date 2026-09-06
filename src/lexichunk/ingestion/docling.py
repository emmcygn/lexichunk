"""Docling → lexichunk.

`Docling <https://github.com/docling-project/docling>`_ is very good at the
job lexichunk deliberately does not do: turning a PDF, DOCX or HTML file into
a structured document — finding the headings, the reading order, the tables,
and the page furniture.  lexichunk is good at the job Docling does not do:
knowing that ``5.2`` is a subsection of ``5``, that ``SCHEDULE 1`` is a
container, that ``"Services"`` was defined in clause 1 and used in clause 7,
and that a chunk must never straddle two top-level clauses.

**After Docling, not instead of Docling.**  This adapter is the join:

.. code-block:: python

    from docling.document_converter import DocumentConverter
    from lexichunk import LegalChunker
    from lexichunk.ingestion import from_docling

    result = DocumentConverter().convert("msa.pdf")
    sections = from_docling(result.document, jurisdiction="uk")
    chunks = LegalChunker(jurisdiction="uk").chunk_documents(sections)

``docling-core`` is an optional dependency (``pip install lexichunk[docling]``).
This module imports without it; :func:`from_docling` raises a helpful
``ImportError`` if it is actually needed and missing.
"""

from __future__ import annotations

from typing import Any, Optional

from ..exceptions import InputError
from ..models import Jurisdiction, Section
from ._common import SectionAccumulator

__all__ = ["from_docling"]

_INSTALL_HINT = (
    "from_docling() needs docling-core, which lexichunk does not depend on. "
    "Install it with: pip install 'lexichunk[docling]' (or pip install "
    "docling-core). You do not need the full `docling` package unless you "
    "are also converting PDFs."
)

# Labels whose text is body content belonging to the current section.
_BODY_LABELS = frozenset({"text", "paragraph", "caption", "formula", "code"})

# Labels that are page furniture: Docling has already identified them as
# running headers, footers and page numbers, which is exactly the noise a
# text-only pipeline has to guess at.  Dropped unless asked for.
_FURNITURE_LABELS = frozenset({"page_header", "page_footer", "footnote"})

# Bullet glyphs that carry no ordering information, so are not worth keeping
# in the text.  A real enumerator ("(a)", "1.") is kept, because lexichunk's
# own sub-clause detection and cascading splitter both read it.
_PLAIN_BULLETS = frozenset({"-", "*", "•", "·", "‣", "◦", "–", "—"})

#: Level given to a :class:`TitleItem` — above every heading, since a
#: document title encloses the whole agreement.
TITLE_LEVEL = -3


def _load_document(source: Any) -> Any:
    """Return a ``DoclingDocument``, parsing JSON if that is what we were given.

    Args:
        source: A ``DoclingDocument``, or its JSON form as ``str``/``bytes``,
            or the equivalent ``dict``.

    Returns:
        A ``DoclingDocument``.

    Raises:
        ImportError: If ``docling-core`` is not installed.
        InputError: If *source* cannot be read as a document.
    """
    try:
        from docling_core.types.doc import DoclingDocument
    except ImportError as exc:  # pragma: no cover - exercised by a stub test
        raise ImportError(_INSTALL_HINT) from exc

    if isinstance(source, DoclingDocument):
        return source
    try:
        if isinstance(source, (str, bytes, bytearray)):
            return DoclingDocument.model_validate_json(source)
        if isinstance(source, dict):
            return DoclingDocument.model_validate(source)
    except Exception as exc:  # noqa: BLE001 - re-raised as InputError
        raise InputError(
            f"from_docling() could not read the given JSON as a "
            f"DoclingDocument: {type(exc).__name__}: {exc}"
        ) from exc
    raise InputError(
        f"from_docling() expects a DoclingDocument, or its JSON as str/bytes, "
        f"or the equivalent dict; got {type(source).__name__}."
    )


def _label_of(item: Any) -> str:
    """Return an item's label as a plain lower-case string."""
    label = getattr(item, "label", None)
    return str(getattr(label, "value", label) or "").lower()


def _list_item_text(item: Any) -> str:
    """Render a list item, keeping a real enumerator and dropping bullets."""
    text = (getattr(item, "text", "") or "").strip()
    marker = (getattr(item, "marker", None) or "").strip()
    if not marker or marker in _PLAIN_BULLETS:
        return text
    if text.startswith(marker):
        return text
    return f"{marker} {text}"


def _table_text(item: Any) -> str:
    """Render a table row-wise as ``cell | cell | cell`` lines.

    Row-wise, not markdown-pipe-table: a row of a fee schedule or a data
    processing annex is a *sentence's worth* of meaning ("Hosting | GBP
    5,000 | Monthly"), and keeping each row on its own line lets the
    cascading splitter break an over-sized table between rows rather than
    mid-row.  ``TableItem`` has no ``.text``, so this reads ``data.grid``,
    which resolves spans and needs no pandas.

    Args:
        item: A ``TableItem``.

    Returns:
        The table's text, with any caption on the first line.
    """
    lines: list[str] = []
    for caption in getattr(item, "captions", ()) or ():
        text = (getattr(caption, "text", None) or "").strip()
        if text:
            lines.append(text)

    data = getattr(item, "data", None)
    grid = getattr(data, "grid", None) or []
    for row in grid:
        cells = [(getattr(cell, "text", "") or "").strip() for cell in row]
        # Collapse the duplicate text a spanning cell leaves in every column
        # it covers, so "Fees | Fees | Fees" reads as "Fees".
        collapsed: list[str] = []
        for cell in cells:
            if not collapsed or collapsed[-1] != cell:
                collapsed.append(cell)
        rendered = " | ".join(collapsed).strip(" |")
        if rendered:
            lines.append(rendered)
    return "\n".join(lines)


def from_docling(
    doc: Any,
    *,
    jurisdiction: Jurisdiction | str = "uk",
    include_title: bool = True,
    include_tables: bool = True,
    include_furniture: bool = False,
    document_title_level: int = TITLE_LEVEL,
) -> list[Section]:
    """Convert a ``DoclingDocument`` into :class:`~lexichunk.models.Section` records.

    Section headers open a section; the text, list and table items that
    follow become its body, until the next header.  Anything before the
    first header becomes a preamble section, exactly as lexichunk's own
    parser would treat leading text.

    **Levels come from the numbering when there is any.**  Docling reports a
    heading's *depth*; it has no opinion about whether ``SCHEDULE 2`` is a
    container or ``5.2`` is a subsection of ``5``.  Where a heading starts
    with legal numbering, the jurisdiction's own ``detect_level`` supplies
    the level and identifier and the remainder becomes the title; where it
    does not (a bare ``CONFIDENTIALITY``), Docling's depth is used, mapped so
    that depth 1 is a top-level clause.

    Args:
        doc: A ``DoclingDocument``, or its JSON form as ``str``/``bytes``, or
            the equivalent ``dict``.  JSON is validated with
            ``DoclingDocument.model_validate_json``.
        jurisdiction: Whose numbering rules to apply to heading text.  Use
            the same value you will pass to
            :class:`~lexichunk.chunker.LegalChunker`.
        include_title: Emit the document's ``TitleItem`` as a root section
            enclosing everything, so ``hierarchy_path`` reads
            ``Master Services Agreement > 5 — Payment``.
        include_tables: Export table content into the enclosing section's
            body, row-wise.  Turn off if your retrieval layer handles
            tables separately.
        include_furniture: Include page headers, footers and footnotes.
            Off by default: Docling has already identified them as
            furniture, and dropping them here is one of the main reasons to
            run Docling first rather than chunking extracted text.
        document_title_level: Level for the title section.  Anything below
            the lowest heading level works; the default of ``-3`` sits above
            Exhibit (``-2``) and Schedule (``-1``).

    Returns:
        Sections in document order, ready for
        :meth:`~lexichunk.chunker.LegalChunker.chunk_documents`.

    Raises:
        ImportError: If ``docling-core`` is not installed.
        InputError: If *doc* cannot be read as a ``DoclingDocument``.
    """
    document = _load_document(doc)

    try:
        from docling_core.types.doc import ContentLayer
    except ImportError as exc:  # pragma: no cover - _load_document got there first
        raise ImportError(_INSTALL_HINT) from exc

    layers: Optional[set[Any]] = None
    if include_furniture:
        layers = {ContentLayer.BODY, ContentLayer.FURNITURE}

    accumulator = SectionAccumulator(jurisdiction)
    for item, _depth in document.iterate_items(included_content_layers=layers):
        label = _label_of(item)

        if label == "title":
            if include_title:
                accumulator.start_section(
                    (getattr(item, "text", "") or "").strip(),
                    document_title_level,
                )
            continue

        if label == "section_header":
            heading_depth = getattr(item, "level", 1) or 1
            # Docling counts headings from 1; lexichunk counts top-level
            # clauses from 0.
            accumulator.start_section(
                (getattr(item, "text", "") or "").strip(),
                int(heading_depth) - 1,
            )
            continue

        if label in _FURNITURE_LABELS:
            if include_furniture:
                accumulator.add_text((getattr(item, "text", "") or "").strip())
            continue

        if label == "table":
            if include_tables:
                accumulator.add_text(_table_text(item))
            continue

        if label == "list_item":
            accumulator.add_text(_list_item_text(item))
            continue

        if label in _BODY_LABELS:
            accumulator.add_text((getattr(item, "text", "") or "").strip())

    return accumulator.result()
