"""LlamaIndex integration — LegalNodeParser.

Install extras:
    python -m pip install -e ".[llama-index]"
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from ..chunker import LegalChunker
from ..models import Jurisdiction
from ..utils import build_metadata as _build_metadata

if TYPE_CHECKING:
    from llama_index.core.schema import BaseNode as _BaseNode
    from llama_index.core.schema import Document as _LIDocument
    from llama_index.core.schema import TextNode as _LITextNode

# ---------------------------------------------------------------------------
# Optional dependency probe
# ---------------------------------------------------------------------------

_LLAMA_INDEX_AVAILABLE = False
_LlamaDocument: Any = None
_NodeParserBase: Any = object
_build_nodes_from_splits: Any = None
_MetadataMode: Any = None
_TextNode: Any = None


def _fallback_private_attr(*_args: Any, **_kwargs: Any) -> Any:
    """No-op stand-in for pydantic's ``PrivateAttr`` when llama-index is absent."""
    return None


_PrivateAttr: Any = _fallback_private_attr

try:
    # Import order kept as-is (not collapsed to one multi-line import) so each
    # `# type: ignore` comment stays attached to its own `from` line — mypy
    # requires the ignore on that exact line, not on the aliased name inside
    # a parenthesised multi-import block.
    from llama_index.core.bridge.pydantic import PrivateAttr as _PrivateAttr  # type: ignore[assignment,no-redef]  # noqa: I001
    from llama_index.core.node_parser import NodeParser as _NodeParserBase  # type: ignore[assignment,no-redef]  # noqa: I001
    from llama_index.core.node_parser.node_utils import (  # type: ignore[assignment,no-redef]
        build_nodes_from_splits as _build_nodes_from_splits,
    )
    from llama_index.core.schema import Document as _LlamaDocument  # type: ignore[assignment,no-redef]  # noqa: F401,I001
    from llama_index.core.schema import MetadataMode as _MetadataMode  # type: ignore[assignment,no-redef]  # noqa: I001
    from llama_index.core.schema import TextNode as _TextNode  # type: ignore[assignment,no-redef]  # noqa: I001

    _LLAMA_INDEX_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Structural metadata keys — excluded from embedding/LLM text by default
# ---------------------------------------------------------------------------

_STRUCTURAL_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "char_start",
        "char_end",
        "chunk_index",
        "cross_references",
        "cross_ref_total",
        "cross_ref_resolved",
        "hierarchy_level",
        "token_count",
        "original_header",
        "classification_confidence",
        "secondary_clause_type",
        "document_id",
    }
)
# Deliberately KEPT in the embedding / LLM text — these are semantically useful:
#   clause_type, jurisdiction, document_section, hierarchy_path,
#   hierarchy_identifier, context_header, defined_terms_used



# A LlamaIndex ``Document`` that the caller did not give an id to gets one
# from ``default_factory=lambda: str(uuid.uuid4())`` — a fresh random value on
# every construction.  This matches the RFC 4122 version-4 shape, which is how
# an auto-generated id is told apart from a caller-chosen one.
_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _document_content(document: Any) -> str:
    """Return *document*'s raw text, tolerating a non-LlamaIndex object."""
    try:
        return str(document.get_content(metadata_mode=_MetadataMode.NONE))
    except Exception:
        return str(getattr(document, "text", "") or "")


def _stable_document_id(document: Any) -> str:
    """Return a document identifier that is the same on every run.

    The caller's own ``Document.id_`` is used when there is one.  When there
    is not, LlamaIndex has already filled the field with a fresh
    ``uuid.uuid4()``, and using that made the whole pipeline
    non-deterministic: chunking the same text twice without supplying an
    explicit ``document_id`` — the common call pattern, with nothing in the
    API signalling that the argument is needed for reproducibility —
    produced a different ``[Document: …]`` context header, different embed
    text and a different ``node_id`` every time, so re-ingesting an unchanged
    document duplicated every vector.

    In that case the identifier is derived from a hash of the document's own
    content instead, which is stable across runs and still distinguishes two
    genuinely different documents.

    Args:
        document: The parent node/document.

    Returns:
        A stable document identifier string.
    """
    raw = getattr(document, "id_", None) or None
    if isinstance(raw, str) and raw and _UUID4_RE.match(raw) is None:
        return raw
    digest = hashlib.sha256(
        _document_content(document).encode("utf-8", errors="surrogatepass")
    ).hexdigest()
    return f"lexichunk-{digest[:32]}"


def _deterministic_id_func(i: int, document: Any) -> str:
    """Deterministic node-id generator: hash of (doc id, doc content, split index).

    The base LlamaIndex ``default_id_func`` uses ``uuid.uuid4()``, so
    re-parsing identical input produces a brand-new, unrelated set of node
    ids on every run — which duplicates every vector on re-indexing an
    unchanged corpus. This function instead hashes the parent document's
    *stable* identifier (see :func:`_stable_document_id`) and content
    together with the split index, so parsing the same document twice yields
    the same ``node_id`` for the same split — including when the caller never
    supplied an identifier of their own.

    Args:
        i: Index of the split within *document*.
        document: The parent node/document being split (passed by
            ``build_nodes_from_splits``, not the split text itself).

    Returns:
        A stable, hex-encoded SHA-256 digest string.
    """
    doc_id = _stable_document_id(document)
    content = _document_content(document)
    digest_input = f"{doc_id}\x00{content}\x00{i}".encode("utf-8", errors="surrogatepass")
    return hashlib.sha256(digest_input).hexdigest()


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class LegalNodeParser(_NodeParserBase):  # type: ignore[misc,valid-type]
    """LlamaIndex ``NodeParser`` for legal documents.

    Wraps :class:`~lexichunk.chunker.LegalChunker` and returns
    ``llama_index.core.schema.TextNode`` objects with rich legal metadata
    attached to each node's ``metadata`` dict.

    Subclassing ``llama_index.core.node_parser.NodeParser`` (rather than
    duck-typing) means this parser gets, for free, from the base class:

    - ``NodeRelationship.SOURCE`` / ``ref_doc_id`` — provenance back to the
      parent ``Document``.
    - ``NodeRelationship.PREVIOUS`` / ``NEXT`` sibling relationships (when
      ``include_prev_next_rel`` is ``True``).
    - Parent ``Document.metadata`` merge into each node's metadata (when
      ``include_metadata`` is ``True``).
    - ``id_func``-based node id assignment.

    These are required for LlamaIndex features such as auto-merging
    retrievers, sentence-window expansion, and provenance tracing.

    Args:
        jurisdiction: Legal jurisdiction — ``"uk"`` or ``"us"`` (or a
            :class:`~lexichunk.models.Jurisdiction` enum value).
        doc_type: Document type hint — ``"contract"`` or
            ``"terms_conditions"``.  Affects document-section detection: with
            ``"terms_conditions"`` the signature-block heuristic is relaxed
            (recitals/signature keyword matching is skipped), which changes
            which chunks are classified as ``SIGNATURES`` and ``RECITALS``.
        max_chunk_size: Maximum chunk size in approximate tokens
            (1 token ≈ 4 characters).  Defaults to ``512``.
        min_chunk_size: Minimum chunk size in approximate tokens.  Clauses
            smaller than this are merged with an adjacent sibling where the
            hierarchy allows.  Defaults to
            ``64``.
        include_definitions: When ``True``, attach relevant defined-term
            definitions to each chunk.  Defaults to ``True``.
        include_context_header: When ``True``, populate the
            ``context_header`` field on every chunk.  Defaults to ``True``.
        document_id: Default document identifier passed to the chunker when
            a parsed ``Document`` has no usable ``id_``.
        include_defined_terms_context: When ``True``, also emit
            ``defined_terms_context`` in each node's metadata.  See
            :func:`~lexichunk.utils.build_metadata`.
        flatten_metadata: When ``True``, JSON-encode non-scalar metadata
            values to strings, for vector stores that only accept scalar
            metadata.
        excluded_embed_metadata_keys: Metadata keys to exclude from both the
            embedding and LLM text of every produced node, in addition to
            each source document's own exclusions. Defaults to a structural
            set (offsets, counts, cross-references, …) that would otherwise
            add ~40% noise to embedding text with no retrieval value;
            ``clause_type``, ``jurisdiction``, ``document_section``,
            ``hierarchy_path``, ``hierarchy_identifier``, ``context_header``
            and ``defined_terms_used`` are deliberately kept.

    Note:
        **Node ids and headers are deterministic.** A ``Document`` the caller
        did not give an ``id_`` to arrives carrying a fresh ``uuid.uuid4()``
        from LlamaIndex.  Using it would make ``node_id``, the
        ``[Document: …]`` context header and therefore the embed text differ
        on every run of the same input, duplicating every vector on
        re-ingestion.  When ``Document.id_`` has that auto-generated shape and
        no ``document_id`` was supplied, the identifier is derived from a hash
        of the document's own content instead.  A caller-chosen ``id_`` always
        wins.

        **Offsets cover the clause body only.** ``start_char_idx`` and
        ``end_char_idx`` are lexichunk's own ``char_start``/``char_end``: the
        span of the clause's own text in the *sanitised* document.  A node's
        ``.text`` may additionally begin with synthesized ancestor header
        lines added for retrieval context, and those are not covered by any
        offset — so ``sanitised[start_char_idx:end_char_idx]`` is a suffix of
        ``.text`` for such a node, not the whole of it, and ``.text`` is not
        guaranteed to be a literal substring of the source document.  This is
        the same contract :class:`~lexichunk.models.LegalChunk` documents for
        ``content`` versus ``char_start``/``char_end``.

    Raises:
        ImportError: If ``llama-index-core`` is not installed when the class
            is instantiated.

    Example::

        from llama_index.core.schema import Document
        from lexichunk.integrations.llama_index import LegalNodeParser

        parser = LegalNodeParser(jurisdiction="uk")
        nodes = parser.get_nodes_from_documents([Document(text=contract_text)])
        for node in nodes:
            print(node.metadata["clause_type"], node.metadata["hierarchy_path"])
    """

    _chunker: Any = _PrivateAttr()
    _document_id: Optional[str] = _PrivateAttr()
    _include_defined_terms_context: bool = _PrivateAttr()
    _flatten_metadata: bool = _PrivateAttr()
    _excluded_metadata_keys: frozenset[str] = _PrivateAttr()
    _offset_overrides: Dict[str, tuple[int, int]] = _PrivateAttr(default_factory=dict)

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
        excluded_embed_metadata_keys: Sequence[str] | None = None,
        include_metadata: bool = True,
        include_prev_next_rel: bool = True,
        id_func: Any = None,
    ) -> None:
        if not _LLAMA_INDEX_AVAILABLE:
            raise ImportError(
                "LegalNodeParser requires 'llama-index-core'. "
                'Install it from a source checkout with: python -m pip install -e ".[llama-index]"'
            )

        super().__init__(
            include_metadata=include_metadata,
            include_prev_next_rel=include_prev_next_rel,
            id_func=id_func or _deterministic_id_func,
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
        self._excluded_metadata_keys = (
            frozenset(excluded_embed_metadata_keys)
            if excluded_embed_metadata_keys is not None
            else _STRUCTURAL_METADATA_KEYS
        )
        self._offset_overrides = {}

    # ------------------------------------------------------------------
    # Convenience API
    # ------------------------------------------------------------------

    def get_nodes_from_text(self, text: str) -> List[_LITextNode]:
        """Parse a plain-text legal document into a list of ``TextNode`` objects.

        Convenience method that does not require wrapping the input in a
        LlamaIndex ``Document`` first.

        Args:
            text: Full legal document as a plain-text string.

        Returns:
            List of ``llama_index.core.schema.TextNode`` objects in document
            order with legal metadata populated.
        """
        kwargs: dict[str, Any] = {"text": text}
        if self._document_id:
            kwargs["doc_id"] = self._document_id
        document = _LlamaDocument(**kwargs)
        return self.get_nodes_from_documents([document])  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # NodeParser interface
    # ------------------------------------------------------------------

    def _parse_nodes(
        self,
        nodes: Sequence[_BaseNode],
        show_progress: bool = False,
        **kwargs: Any,
    ) -> List[_BaseNode]:
        """Chunk each input document and build ``TextNode`` objects.

        Uses ``build_nodes_from_splits`` so ``NodeRelationship.SOURCE``,
        ``ref_doc_id``, and (later, in ``_postprocess_parsed_nodes``) the
        parent-metadata merge and ``PREVIOUS``/``NEXT`` relationships are all
        produced by the base class.

        Args:
            nodes: Sequence of parent ``Document``/``BaseNode`` objects.
            show_progress: Unused; accepted for interface compatibility.
            **kwargs: Unused; accepted for interface compatibility.

        Returns:
            Flat list of ``TextNode`` objects across all input documents.
        """
        all_nodes: List[Any] = []
        for doc in nodes:
            text = doc.get_content(metadata_mode=_MetadataMode.NONE)
            # A caller-chosen Document.id_ wins; then this parser's own
            # document_id; then a content hash. The last step is what keeps
            # context_header, embed text and node ids identical across runs
            # when nobody supplied an identifier at all — LlamaIndex would
            # otherwise have filled Document.id_ with a fresh uuid4.
            raw_id = getattr(doc, "id_", None)
            explicit_id = (
                raw_id
                if isinstance(raw_id, str) and raw_id and _UUID4_RE.match(raw_id) is None
                else None
            )
            doc_id = explicit_id or self._document_id or _stable_document_id(doc)
            chunks = self._chunker.chunk(text, document_id=doc_id)
            if not chunks:
                continue

            splits = [chunk.content for chunk in chunks]
            built = _build_nodes_from_splits(splits, doc, ref_doc=doc, id_func=self.id_func)

            for node, chunk in zip(built, chunks):
                node.metadata.update(
                    _build_metadata(
                        chunk,
                        include_defined_terms_context=self._include_defined_terms_context,
                        flatten=self._flatten_metadata,
                    )
                )
                # Explicit offsets from the chunker. `_postprocess_parsed_nodes`
                # (called after this method returns) recomputes start/end char
                # idx via `parent_doc.text.find(node_content)`, which returns -1
                # whenever `chunk.content` isn't a verbatim substring of the raw
                # document text (true whenever ancestor headers are prepended,
                # or whitespace was normalised during sanitisation) — in that
                # case it leaves our values alone. When `find()` *does* succeed
                # it would silently overwrite these with raw-text offsets, which
                # can disagree with lexichunk's (sanitised-text) offsets — so we
                # stash the intended values and restore them, unconditionally,
                # in our `_postprocess_parsed_nodes` override below.
                node.start_char_idx = chunk.char_start
                node.end_char_idx = chunk.char_end
                self._offset_overrides[node.node_id] = (chunk.char_start, chunk.char_end)

                node.excluded_embed_metadata_keys = sorted(
                    set(node.excluded_embed_metadata_keys or []) | self._excluded_metadata_keys
                )
                node.excluded_llm_metadata_keys = sorted(
                    set(node.excluded_llm_metadata_keys or []) | self._excluded_metadata_keys
                )

            all_nodes.extend(built)
        return all_nodes

    def _postprocess_parsed_nodes(
        self, nodes: List[_BaseNode], parent_doc_map: Dict[str, _LIDocument]
    ) -> List[_BaseNode]:
        """Restore lexichunk's char offsets after the base class post-processes nodes.

        See the caveat in :meth:`_parse_nodes`: the base implementation may
        overwrite ``start_char_idx``/``end_char_idx`` when it manages to find
        the node's text verbatim in the parent document. This override pins
        lexichunk's own (sanitised-text) offsets back in place unconditionally.

        Args:
            nodes: Nodes produced by ``_parse_nodes``.
            parent_doc_map: Map of ``ref_doc_id`` to parent ``Document``.

        Returns:
            The same node list, with offsets restored.
        """
        nodes = super()._postprocess_parsed_nodes(nodes, parent_doc_map)
        for node in nodes:
            override = self._offset_overrides.pop(node.node_id, None)
            if override is not None and isinstance(node, _TextNode):
                node.start_char_idx, node.end_char_idx = override
        return nodes
