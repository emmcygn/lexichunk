"""Context header generator for the Contextual Retrieval pattern.

Generates structured context headers that describe each ``LegalChunk``'s
location and type within a legal document.  Prepending these headers to
chunk content before embedding significantly improves retrieval quality by
giving the embedding model the broader document context that a human reader
would infer from the surrounding text.

Typical usage::

    from lexichunk.enrichment.context import ContextEnricher, build_embedded_text

    enricher = ContextEnricher()
    chunks = enricher.enrich_all(chunks)
    texts = [build_embedded_text(c) for c in chunks]
"""

from __future__ import annotations

from typing import Optional

from ..models import ClauseType, LegalChunk


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _format_clause_type(clause_type: ClauseType) -> str:
    """Format a ClauseType value for display in the context header.

    Converts the enum value (e.g. ``"limitation_of_liability"``) to
    title-cased words (e.g. ``"Limitation Of Liability"``).

    Args:
        clause_type: The ClauseType enum member to format.

    Returns:
        Human-readable, title-cased string representation of the clause type.
    """
    return clause_type.value.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_context_header(chunk: LegalChunk) -> str:
    """Generate a context header string for a LegalChunk.

    Follows the Contextual Retrieval pattern: a short, structured prefix
    that describes the chunk's location and type in the document.  This
    header is stored in ``chunk.context_header`` and can be prepended to
    ``chunk.content`` before embedding.

    Format::

        [Document: <doc_id>] [Section: <hierarchy_path>] [Type: <clause_type>] [Jurisdiction: <jurisdiction>]

    The ``[Document: ...]`` segment is omitted when ``chunk.document_id`` is
    ``None``.

    Args:
        chunk: A LegalChunk with ``hierarchy_path``, ``clause_type``,
               ``jurisdiction``, and optionally ``document_id`` populated.

    Returns:
        The context header string.

    Example:
        ``"[Document: NDA-2024] [Section: Article IV — Confidentiality] [Type: Confidentiality] [Jurisdiction: US]"``
    """
    segments: list[str] = []

    if chunk.document_id is not None:
        segments.append(f"[Document: {chunk.document_id}]")

    segments.append(f"[Section: {chunk.hierarchy_path}]")
    segments.append(f"[Type: {_format_clause_type(chunk.clause_type)}]")
    segments.append(f"[Jurisdiction: {chunk.jurisdiction.value.upper()}]")

    return " ".join(segments)


def build_embedded_text(chunk: LegalChunk) -> str:
    """Return the text to embed: context_header prepended to content.

    If ``context_header`` is empty, returns ``content`` unchanged so that
    un-enriched chunks can still be embedded without modification.

    Args:
        chunk: A LegalChunk whose ``context_header`` should already be
               populated via :func:`generate_context_header` or
               :class:`ContextEnricher`.

    Returns:
        The full text to pass to an embedding model.  When
        ``context_header`` is non-empty this is::

            <context_header>

            <content>
    """
    if chunk.context_header:
        return f"{chunk.context_header}\n\n{chunk.content}"
    return chunk.content


class ContextEnricher:
    """Enriches LegalChunk objects with context headers.

    Stateless class that wraps :func:`generate_context_header` for batch
    use.  All methods mutate chunks in-place *and* return them so they can
    be used in both imperative and functional styles.

    Example::

        enricher = ContextEnricher()

        # Single chunk
        enricher.enrich(chunk)

        # Batch
        enricher.enrich_all(chunks)
    """

    def enrich(self, chunk: LegalChunk) -> LegalChunk:
        """Set ``context_header`` on a single chunk and return it.

        Args:
            chunk: LegalChunk to enrich (mutated in-place).

        Returns:
            The same chunk with ``context_header`` populated.
        """
        chunk.context_header = generate_context_header(chunk)
        return chunk

    def enrich_all(self, chunks: list[LegalChunk]) -> list[LegalChunk]:
        """Set ``context_header`` on every chunk in a list.

        Args:
            chunks: List of LegalChunk objects (mutated in-place).

        Returns:
            The same list with ``context_header`` populated on every chunk.
        """
        for chunk in chunks:
            self.enrich(chunk)
        return chunks
