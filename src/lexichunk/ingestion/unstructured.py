""":mod:`unstructured` partition output → lexichunk.

``unstructured.partition.auto.partition()`` returns a flat list of elements,
each with a ``category`` (``"Title"``, ``"NarrativeText"``, ``"ListItem"``,
``"Table"`` …), the element's ``text``, and a ``metadata`` object that carries
``category_depth`` for headings.

.. code-block:: python

    from unstructured.partition.auto import partition
    from lexichunk import LegalChunker
    from lexichunk.ingestion import from_unstructured

    elements = partition("msa.pdf")
    sections = from_unstructured(elements, jurisdiction="us")
    chunks = LegalChunker(jurisdiction="us").chunk_documents(sections)

lexichunk does **not** depend on ``unstructured`` and does not import it.
:func:`from_unstructured` is duck-typed on the three attributes above, so it
works with any version — and with your own stand-in objects in a test, which
is how this adapter's own tests are written.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..exceptions import InputError
from ..models import Jurisdiction, Section
from ._common import SectionAccumulator

__all__ = ["from_unstructured"]

# Categories that open a new section.  "Header" is deliberately absent: in
# unstructured's vocabulary that is a *page* header, i.e. furniture.
_HEADING_CATEGORIES = frozenset({"title", "sectionheader", "heading"})

# Categories whose text belongs to the section currently open.
_BODY_CATEGORIES = frozenset(
    {
        "narrativetext",
        "text",
        "uncategorizedtext",
        "abstract",
        "formula",
        "codesnippet",
        "address",
        "emailaddress",
        "figurecaption",
        "caption",
    }
)

_LIST_CATEGORIES = frozenset({"listitem", "list_item"})
_TABLE_CATEGORIES = frozenset({"table"})

# Page furniture and layout artefacts, dropped by default.
_FURNITURE_CATEGORIES = frozenset(
    {"header", "footer", "pagebreak", "pagenumber", "image", "picture"}
)


def _category_of(element: Any) -> str:
    """Return an element's category, normalised for comparison."""
    category = getattr(element, "category", None)
    if category is None:
        category = type(element).__name__
    return str(category).replace(" ", "").replace("_", "").lower()


def _text_of(element: Any) -> str:
    """Return an element's text, tolerating ``None`` and non-``str`` values."""
    text = getattr(element, "text", None)
    if text is None:
        return ""
    return str(text).strip()


def _depth_of(element: Any, default: int) -> int:
    """Return a heading's depth from ``metadata.category_depth``.

    ``unstructured`` numbers heading depth from 0, so it maps straight onto
    lexichunk's levels (0 = top-level clause) with no shift.  Elements
    without the attribute — or with ``None``, which is common — fall back to
    *default*.
    """
    metadata = getattr(element, "metadata", None)
    depth = getattr(metadata, "category_depth", None)
    if isinstance(depth, bool) or not isinstance(depth, int):
        return default
    return depth


def from_unstructured(
    elements: Iterable[Any],
    *,
    jurisdiction: Jurisdiction | str = "uk",
    include_furniture: bool = False,
) -> list[Section]:
    """Convert ``unstructured`` partition output into :class:`~lexichunk.models.Section` records.

    ``Title`` elements open a section; ``NarrativeText``, ``ListItem`` and
    ``Table`` elements fill it, until the next ``Title``.  Anything before
    the first heading becomes a preamble section.

    As with :func:`~lexichunk.ingestion.from_docling`, a heading that
    *starts with* legal numbering takes its level and identifier from the
    jurisdiction's own rules — ``category_depth`` records how deep the
    layout looked, not that ``5.2`` sits under ``5``.  A heading without
    numbering keeps its ``category_depth`` (which ``unstructured`` numbers
    from 0, matching lexichunk's top-level clause).

    Args:
        elements: Any iterable of objects exposing ``category``, ``text``
            and ``metadata``.  Nothing is imported from ``unstructured``, so
            stand-in objects work identically.
        jurisdiction: Whose numbering rules to apply to heading text.
        include_furniture: Include ``Header``, ``Footer``, ``PageNumber``
            and ``PageBreak`` elements.  Off by default — a running header
            repeated on every page is noise that would otherwise land in
            whichever clause happened to span the page break.

    Returns:
        Sections in document order, ready for
        :meth:`~lexichunk.chunker.LegalChunker.chunk_documents`.

    Raises:
        InputError: If *elements* is a bare string or is not iterable.
    """
    if isinstance(elements, (str, bytes, bytearray)):
        raise InputError(
            f"from_unstructured() expects an iterable of partition elements, "
            f"got {type(elements).__name__}. Pass partition(...)'s return "
            f"value, not the document text."
        )
    if not isinstance(elements, Iterable):
        raise InputError(
            f"from_unstructured() expects an iterable of partition elements, "
            f"got {type(elements).__name__}."
        )

    accumulator = SectionAccumulator(jurisdiction)
    for element in elements:
        category = _category_of(element)
        text = _text_of(element)

        if category in _FURNITURE_CATEGORIES:
            if include_furniture and text:
                accumulator.add_text(text)
            continue

        if category in _HEADING_CATEGORIES:
            if text:
                accumulator.start_section(text, _depth_of(element, 0))
            continue

        if (
            category in _BODY_CATEGORIES
            or category in _LIST_CATEGORIES
            or category in _TABLE_CATEGORIES
        ):
            accumulator.add_text(text)
            continue

        # An unknown category is still text somebody extracted on purpose;
        # dropping it would silently lose content, which is worse than
        # putting a stray caption in the enclosing clause.
        accumulator.add_text(text)

    return accumulator.result()
