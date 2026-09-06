"""LangChain integration — LegalTextSplitter.

Install extras:
    pip install lexichunk[langchain]
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from ..chunker import LegalChunker
from ..models import Jurisdiction
from ..utils import build_metadata as _build_metadata

if TYPE_CHECKING:
    from langchain_core.documents import Document as _LCDocument

    from ..models import LegalChunk

# ---------------------------------------------------------------------------
# Optional dependency probe
# ---------------------------------------------------------------------------

_LANGCHAIN_AVAILABLE = False
_Document: Any = None
_BaseTransformer: Any = object

try:
    # Import order kept as-is (not collapsed to one multi-line import) so each
    # `# type: ignore` comment stays attached to its own `from` line — mypy
    # requires the ignore on that exact line, not on the aliased name inside
    # a parenthesised multi-import block.
    from langchain_core.documents import BaseDocumentTransformer as _BaseTransformer  # type: ignore[assignment,no-redef]  # noqa: I001
    from langchain_core.documents import Document as _Document  # type: ignore[assignment,no-redef]  # noqa: I001

    _LANGCHAIN_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class LegalTextSplitter(_BaseTransformer):  # type: ignore[misc,valid-type]
    """LangChain-compatible document transformer for legal documents.

    Wraps :class:`~lexichunk.chunker.LegalChunker` and returns
    ``langchain_core.documents.Document`` objects with rich legal metadata
    attached to each document's ``metadata`` dict.

    This class deliberately does **not** subclass
    ``langchain_text_splitters.TextSplitter``. It is an *adapter*, not a
    drop-in replacement: :meth:`split_text` returns ``Document`` objects
    carrying legal metadata, whereas ``TextSplitter.split_text()`` returns
    plain strings. It subclasses ``langchain_core.documents.
    BaseDocumentTransformer`` instead, so it can be used anywhere LangChain
    accepts a document transformer (including LCEL), without adding a
    dependency on the separate ``langchain-text-splitters`` distribution.

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
        document_id: Default document identifier used when one cannot be
            resolved from a ``Document`` passed to :meth:`split_documents`.
        include_defined_terms_context: When ``True``, also emit
            ``defined_terms_context`` in each document's metadata.  See
            :func:`~lexichunk.utils.build_metadata`.
        flatten_metadata: When ``True``, JSON-encode non-scalar metadata
            values (``cross_references``, ``defined_terms_used``, …) to
            strings, for vector stores that only accept scalar metadata.
        metadata_prefix: When set, every lexichunk-produced metadata key is
            namespaced with this prefix (e.g. ``"lexichunk_"``) so it cannot
            collide with a caller's own metadata schema.

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
        *,
        document_id: str | None = None,
        include_defined_terms_context: bool = False,
        flatten_metadata: bool = False,
        metadata_prefix: str | None = None,
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
        self._document_id = document_id
        self._include_defined_terms_context = include_defined_terms_context
        self._flatten_metadata = flatten_metadata
        self._metadata_prefix = metadata_prefix

    # ------------------------------------------------------------------
    # Primary public API
    # ------------------------------------------------------------------

    def split_text(self, text: str, *, document_id: str | None = None) -> list[_LCDocument]:
        """Split a legal document into a list of LangChain ``Document`` objects.

        Note:
            This deliberately differs from ``TextSplitter.split_text()``,
            which returns ``list[str]``.  This method returns ``Document``
            objects because lexichunk's value proposition is the structured
            legal metadata attached to each chunk.

        Runs the full :class:`~lexichunk.chunker.LegalChunker` pipeline and
        converts each :class:`~lexichunk.models.LegalChunk` into a
        ``langchain_core.documents.Document`` with a structured ``metadata``
        dict.

        Args:
            text: Full legal document as a plain-text string.
            document_id: Document identifier to attach to every resulting
                chunk's metadata.  Falls back to the constructor's
                ``document_id`` when omitted.

        Returns:
            List of ``langchain_core.documents.Document`` objects in document
            order.  See :func:`~lexichunk.utils.build_metadata` for the set
            of metadata keys populated on each document.
        """
        resolved_document_id = document_id if document_id is not None else self._document_id
        chunks = self._chunker.chunk(text, document_id=resolved_document_id)
        return [self._chunk_to_document(chunk, resolved_document_id) for chunk in chunks]

    def create_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> list[_LCDocument]:
        """Split multiple legal documents and return a flat list of ``Document`` objects.

        Convenience wrapper that calls :meth:`split_text` for every text in
        *texts* and concatenates the results, optionally merging in
        caller-supplied metadata per source text (lexichunk metadata keys
        win on collision).

        Args:
            texts: List of legal document strings to split.
            metadatas: Optional list of metadata dicts, one per entry in
                *texts*.  Merged into every chunk produced from the
                corresponding text.

        Returns:
            Flat list of ``langchain_core.documents.Document`` objects from all
            input texts, in the order they were processed.

        Raises:
            ValueError: If *metadatas* is provided and its length does not
                match the length of *texts*.
        """
        if metadatas is not None and len(metadatas) != len(texts):
            raise ValueError(
                f"metadatas must be the same length as texts: "
                f"got {len(metadatas)} metadatas for {len(texts)} texts."
            )

        documents: list[_LCDocument] = []
        for i, text in enumerate(texts):
            docs = self.split_text(text)
            if metadatas is not None:
                extra = metadatas[i]
                for doc in docs:
                    merged = copy.deepcopy(extra)
                    merged.update(doc.metadata)
                    doc.metadata = merged
            documents.extend(docs)
        return documents

    def split_documents(self, documents: Iterable[_LCDocument]) -> list[_LCDocument]:
        """Split LangChain ``Document`` objects, preserving caller metadata.

        This is the idiomatic LangChain entry point after a document loader.
        For each input document, a ``document_id`` is resolved (in order):

        1. ``Document.id``
        2. ``Document.metadata["document_id"]`` (if a ``str``)
        3. ``Document.metadata["source"]`` (if a ``str``)
        4. This splitter's constructor ``document_id``
        5. ``None``

        Each output document's metadata is a deep copy of the caller's
        input ``metadata`` dict, updated with the lexichunk-produced keys
        (lexichunk's keys win on any collision). When ``metadata_prefix`` is
        set, lexichunk's keys are namespaced with that prefix before the
        merge, so they cannot collide with caller keys at all. Output
        ``Document.id`` is set to ``f"{document_id}:{chunk.index}"`` when a
        ``document_id`` was resolved.

        Args:
            documents: Iterable of ``langchain_core.documents.Document``
                objects to split.

        Returns:
            Flat list of ``Document`` objects, in input-document order, each
            carrying the source document's metadata merged with lexichunk's.
        """
        output: list[_LCDocument] = []
        for document in documents:
            document_id = self._resolve_document_id(document)
            chunks = self._chunker.chunk(document.page_content, document_id=document_id)
            caller_metadata = document.metadata or {}
            for chunk in chunks:
                lexichunk_metadata = _build_metadata(
                    chunk,
                    include_defined_terms_context=self._include_defined_terms_context,
                    flatten=self._flatten_metadata,
                )
                if self._metadata_prefix:
                    lexichunk_metadata = {
                        f"{self._metadata_prefix}{key}": value for key, value in lexichunk_metadata.items()
                    }
                merged_metadata = copy.deepcopy(caller_metadata)
                merged_metadata.update(lexichunk_metadata)
                new_doc = _Document(page_content=chunk.content, metadata=merged_metadata)
                if document_id is not None:
                    new_doc.id = f"{document_id}:{chunk.index}"
                output.append(new_doc)
        return output

    def transform_documents(self, documents: Sequence[_LCDocument], **kwargs: Any) -> Sequence[_LCDocument]:
        """Transform documents — alias for :meth:`split_documents`.

        Implements the ``BaseDocumentTransformer`` interface so instances of
        this class can be used anywhere LangChain accepts a document
        transformer (e.g. LCEL pipelines).

        Args:
            documents: Sequence of ``Document`` objects to split.
            **kwargs: Ignored; accepted for interface compatibility.

        Returns:
            Flat list of split ``Document`` objects. See
            :meth:`split_documents`.
        """
        return self.split_documents(documents)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_document_id(self, document: _LCDocument) -> str | None:
        """Resolve the document_id for one input ``Document``.

        Args:
            document: The source ``Document``.

        Returns:
            The resolved document identifier, or ``None``.
        """
        doc_id = getattr(document, "id", None)
        if isinstance(doc_id, str) and doc_id:
            return doc_id
        metadata = document.metadata or {}
        candidate = metadata.get("document_id")
        if isinstance(candidate, str) and candidate:
            return candidate
        source = metadata.get("source")
        if isinstance(source, str) and source:
            return source
        return self._document_id

    def _chunk_to_document(self, chunk: LegalChunk, document_id: str | None) -> _LCDocument:
        """Convert a :class:`~lexichunk.models.LegalChunk` to a LangChain ``Document``.

        Args:
            chunk: A :class:`~lexichunk.models.LegalChunk` instance.
            document_id: Resolved document identifier, used to build the
                output ``Document.id`` when not ``None``.

        Returns:
            A ``langchain_core.documents.Document`` with ``page_content`` set to
            the chunk's text and ``metadata`` populated with legal metadata.
        """
        metadata = _build_metadata(
            chunk,
            include_defined_terms_context=self._include_defined_terms_context,
            flatten=self._flatten_metadata,
        )
        if self._metadata_prefix:
            metadata = {f"{self._metadata_prefix}{key}": value for key, value in metadata.items()}
        doc = _Document(page_content=chunk.content, metadata=metadata)
        if document_id is not None:
            doc.id = f"{document_id}:{chunk.index}"
        return doc  # type: ignore[no-any-return]
