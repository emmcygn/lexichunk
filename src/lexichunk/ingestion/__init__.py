"""Adapters from document-conversion tools into lexichunk's ``Section`` model.

**After Docling, not instead of Docling.**  lexichunk deliberately does not
parse PDFs, DOCX or HTML — that is a hard, separate problem that Docling,
``unstructured`` and a dozen internal converters already solve well.  What
those tools do *not* do is legal structure: that ``5.2`` is a subsection of
``5``, that ``SCHEDULE 1`` is a container, that ``"Services"`` was defined in
clause 1 and used in clause 7, that a chunk must never straddle two top-level
clauses.  That is lexichunk's half.

These adapters are the join.  Each turns one converter's output into
:class:`~lexichunk.models.Section` records for
:meth:`~lexichunk.chunker.LegalChunker.chunk_documents`, which runs the whole
pipeline *except* heading detection — because the converter already did that,
from the document's own layout, better than anything line-based can recover
from flattened text.

.. code-block:: python

    from docling.document_converter import DocumentConverter
    from lexichunk import LegalChunker
    from lexichunk.ingestion import from_docling

    result = DocumentConverter().convert("msa.pdf")
    chunks = LegalChunker(jurisdiction="uk").chunk_documents(
        from_docling(result.document, jurisdiction="uk")
    )

Nothing here is imported eagerly and lexichunk still has zero mandatory
dependencies: importing this package never imports ``docling_core`` or
``unstructured``.  :func:`from_docling` raises a helpful ``ImportError`` if
``docling-core`` is genuinely needed and missing (``pip install
'lexichunk[docling]'``); :func:`from_unstructured` is duck-typed and imports
nothing at all.
"""

from __future__ import annotations

from ._common import refine_heading
from .docling import from_docling
from .markdown import from_markdown
from .unstructured import from_unstructured

__all__ = [
    "from_docling",
    "from_markdown",
    "from_unstructured",
    "refine_heading",
]
