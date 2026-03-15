"""LangChain integration — LegalTextSplitter.

Install extras:
    pip install lexichunk[langchain]
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..chunker import LegalChunker
from ..models import Jurisdiction

if TYPE_CHECKING:
    from langchain_core.documents import Document as _LCDocument

    from ..models import LegalChunk

# ---------------------------------------------------------------------------
# Optional dependency probe
# ---------------------------------------------------------------------------

_LANGCHAIN_AVAILABLE = False
_Document: Any = None

try:
    from langchain_core.documents import Document as _Document  # type: ignore[assignment,no-redef]

    _LANGCHAIN_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class LegalTextSplitter:
    """LangChain-compatible text splitter for legal documents.

    Wraps :class:`~lexichunk.chunker.LegalChunker` and returns
    ``langchain_core.documents.Document`` objects with rich legal metadata
    attached to each document's ``metadata`` dict.

    This class does **not** inherit from ``TextSplitter`` in order to avoid a
    hard dependency on LangChain at import time.  It is fully duck-type
    compatible: any LangChain chain or retriever that accepts a list of
    ``Document`` objects will work with the output of :meth:`split_text` and
    :meth:`create_documents`.

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
        ImportError: If ``langchain-core`` is not installed when the class
            is instantiated.

    Example::

        from lexichunk.integrations.langchain import LegalTextSplitter

        splitter = LegalTextSplitter(jurisdiction="uk")
        docs = splitter.split_text(contract_text)
        for doc in docs:
            print(doc.metadata["clause_type"], doc.metadata["hierarchy_path"])
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
        if not _LANGCHAIN_AVAILABLE:
            raise ImportError(
                "LegalTextSplitter requires 'langchain-core'. "
                "Install it with: pip install lexichunk[langchain]"
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

    def split_text(self, text: str) -> list[_LCDocument]:
        """Split a legal document into a list of LangChain ``Document`` objects.

        Runs the full :class:`~lexichunk.chunker.LegalChunker` pipeline and
        converts each :class:`~lexichunk.models.LegalChunk` into a
        ``langchain_core.documents.Document`` with a structured ``metadata``
        dict.

        Args:
            text: Full legal document as a plain-text string.

        Returns:
            List of ``langchain_core.documents.Document`` objects in document
            order.  Each document's ``metadata`` contains the following keys:

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
        """
        chunks = self._chunker.chunk(text)
        return [_chunk_to_document(chunk) for chunk in chunks]

    def create_documents(self, texts: list[str]) -> list[_LCDocument]:
        """Split multiple legal documents and return a flat list of ``Document`` objects.

        Convenience wrapper that calls :meth:`split_text` for every text in
        *texts* and concatenates the results.

        Args:
            texts: List of legal document strings to split.

        Returns:
            Flat list of ``langchain_core.documents.Document`` objects from all
            input texts, in the order they were processed.
        """
        documents: list[_LCDocument] = []
        for text in texts:
            documents.extend(self.split_text(text))
        return documents


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


from ..utils import build_metadata as _build_metadata


def _chunk_to_document(chunk: LegalChunk) -> _LCDocument:
    """Convert a :class:`~lexichunk.models.LegalChunk` to a LangChain ``Document``.

    Args:
        chunk: A :class:`~lexichunk.models.LegalChunk` instance.

    Returns:
        A ``langchain_core.documents.Document`` with ``page_content`` set to
        the chunk's text and ``metadata`` populated with legal metadata.
    """
    return _Document(  # type: ignore[misc,no-any-return]
        page_content=chunk.content,
        metadata=_build_metadata(chunk),
    )
