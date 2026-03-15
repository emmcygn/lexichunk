"""LlamaIndex integration — LegalNodeParser.

Install extras:
    pip install lexichunk[llama-index]
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..chunker import LegalChunker
from ..models import Jurisdiction

if TYPE_CHECKING:
    from llama_index.core.schema import Document as _LIDocument
    from llama_index.core.schema import TextNode as _LITextNode

    from ..models import LegalChunk

# ---------------------------------------------------------------------------
# Optional dependency probe
# ---------------------------------------------------------------------------

_LLAMA_INDEX_AVAILABLE = False
_TextNode: Any = None
_LlamaDocument: Any = None

try:
    from llama_index.core.schema import (
        Document as _LlamaDocument,  # type: ignore[assignment,no-redef]  # noqa: F401
    )
    from llama_index.core.schema import TextNode as _TextNode  # type: ignore[assignment,no-redef]

    _LLAMA_INDEX_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class LegalNodeParser:
    """LlamaIndex-compatible node parser for legal documents.

    Wraps :class:`~lexichunk.chunker.LegalChunker` and returns
    ``llama_index.core.schema.TextNode`` objects with rich legal metadata
    attached to each node's ``metadata`` dict.

    This class does **not** inherit from ``NodeParser`` in order to avoid a
    hard dependency on LlamaIndex at import time.  It is duck-type compatible
    with the LlamaIndex node-parser protocol: any pipeline that accepts a list
    of ``TextNode`` objects will work with the output of
    :meth:`get_nodes_from_documents` and :meth:`get_nodes_from_text`.

    Args:
        jurisdiction: Legal jurisdiction — ``"uk"`` or ``"us"`` (or a
            :class:`~lexichunk.models.Jurisdiction` enum value).
        doc_type: Document type hint.  ``"contract"`` or
            ``"terms_conditions"``.  Currently informational.
        max_chunk_size: Maximum chunk size in approximate tokens
            (1 token ≈ 4 characters).  Defaults to ``512``.
        min_chunk_size: Minimum chunk size in approximate tokens.  Clauses
            smaller than this are merged with their neighbour.  Defaults to
            ``64``.
        include_definitions: When ``True``, attach relevant defined-term
            definitions to each chunk.  Defaults to ``True``.
        include_context_header: When ``True``, populate the
            ``context_header`` field on every chunk.  Defaults to ``True``.

    Raises:
        ImportError: If ``llama-index-core`` is not installed when the class
            is instantiated.

    Example::

        from lexichunk.integrations.llama_index import LegalNodeParser

        parser = LegalNodeParser(jurisdiction="uk")
        nodes = parser.get_nodes_from_text(contract_text)
        for node in nodes:
            print(node.metadata["clause_type"], node.metadata["hierarchy_path"])
    """

    def __init__(
        self,
        jurisdiction: str | Jurisdiction = "uk",
        doc_type: str = "contract",
        max_chunk_size: int = 512,
        min_chunk_size: int = 64,
        include_definitions: bool = True,
        include_context_header: bool = True,
    ) -> None:
        if not _LLAMA_INDEX_AVAILABLE:
            raise ImportError(
                "LegalNodeParser requires 'llama-index-core'. "
                "Install it with: pip install lexichunk[llama-index]"
            )

        self._chunker = LegalChunker(
            jurisdiction=jurisdiction,
            doc_type=doc_type,
            max_chunk_size=max_chunk_size,
            min_chunk_size=min_chunk_size,
            include_definitions=include_definitions,
            include_context_header=include_context_header,
        )

    # ------------------------------------------------------------------
    # Primary public API
    # ------------------------------------------------------------------

    def get_nodes_from_documents(self, documents: list[_LIDocument]) -> list[_LITextNode]:
        """Parse a list of LlamaIndex ``Document`` objects into ``TextNode`` objects.

        Accepts any object that exposes either a ``.text`` attribute or a
        ``.get_content()`` method (the standard LlamaIndex ``Document``
        interface).  Runs the full :class:`~lexichunk.chunker.LegalChunker`
        pipeline for each document and converts every
        :class:`~lexichunk.models.LegalChunk` into a ``TextNode`` with a
        structured ``metadata`` dict.

        Args:
            documents: List of LlamaIndex ``Document`` (or compatible) objects
                to parse.

        Returns:
            Flat list of ``llama_index.core.schema.TextNode`` objects in
            document order.  Each node's ``metadata`` contains the following
            keys:

            - ``clause_type`` (str): Clause type enum value.
            - ``jurisdiction`` (str): Jurisdiction enum value.
            - ``document_section`` (str): Document section enum value.
            - ``hierarchy_path`` (str): Dot-separated clause hierarchy path.
            - ``hierarchy_identifier`` (str): Clause identifier (e.g. ``"1.2"``).
            - ``hierarchy_level`` (int): Depth in the clause hierarchy.
            - ``cross_references`` (list[dict]): Detected cross-references.
            - ``defined_terms_used`` (list[str]): Defined terms appearing in
              the chunk.
            - ``context_header`` (str): Contextual Retrieval header.
            - ``char_start`` (int): Start character offset in the source text.
            - ``char_end`` (int): End character offset in the source text.
            - ``chunk_index`` (int): Zero-based position among all chunks.
            - ``document_id`` (str | None): Document identifier, if set.

        Raises:
            AttributeError: If a document in *documents* exposes neither a
                ``.text`` attribute nor a ``.get_content()`` method.
        """
        nodes: list[_LITextNode] = []
        for document in documents:
            text = _extract_text(document)
            nodes.extend(self._nodes_from_text(text))
        return nodes

    def get_nodes_from_text(self, text: str) -> list[_LITextNode]:
        """Parse a plain-text legal document into a list of ``TextNode`` objects.

        Convenience method that does not require wrapping the input in a
        LlamaIndex ``Document``.

        Args:
            text: Full legal document as a plain-text string.

        Returns:
            List of ``llama_index.core.schema.TextNode`` objects in document
            order with legal metadata populated.
        """
        return self._nodes_from_text(text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _nodes_from_text(self, text: str) -> list[_LITextNode]:
        """Run the chunker and convert results to ``TextNode`` objects.

        Args:
            text: Full legal document as a plain-text string.

        Returns:
            List of ``llama_index.core.schema.TextNode`` instances.
        """
        chunks = self._chunker.chunk(text)
        return [_chunk_to_text_node(chunk) for chunk in chunks]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _extract_text(document: _LIDocument) -> str:
    """Extract the raw text from a LlamaIndex-compatible document object.

    Attempts ``.text`` first (direct attribute access), then falls back to
    calling ``.get_content()`` (the LlamaIndex ``BaseNode`` interface).

    Args:
        document: A LlamaIndex ``Document`` or any object with a ``.text``
            attribute or ``.get_content()`` method.

    Returns:
        The document's text content as a plain string.

    Raises:
        AttributeError: If *document* exposes neither ``.text`` nor
            ``.get_content()``.
    """
    if hasattr(document, "text"):
        return document.text  # type: ignore[no-any-return]
    if hasattr(document, "get_content"):
        return document.get_content()  # type: ignore[no-any-return]
    raise AttributeError(
        f"Document of type {type(document).__name__!r} has neither a '.text' "
        "attribute nor a '.get_content()' method."
    )


from ..utils import build_metadata as _build_metadata


def _chunk_to_text_node(chunk: LegalChunk) -> _LITextNode:
    """Convert a :class:`~lexichunk.models.LegalChunk` to a LlamaIndex ``TextNode``.

    Args:
        chunk: A :class:`~lexichunk.models.LegalChunk` instance.

    Returns:
        A ``llama_index.core.schema.TextNode`` with ``text`` set to the
        chunk's content and ``metadata`` populated with legal metadata.
    """
    return _TextNode(  # type: ignore[misc,no-any-return]
        text=chunk.content,
        metadata=_build_metadata(chunk),
    )
