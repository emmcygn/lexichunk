"""Chunking strategies: clause-aware and fallback."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import LegalChunk


@runtime_checkable
class ChunkingStrategy(Protocol):
    """Protocol that all chunking strategies satisfy.

    This is a structural (duck-typed) interface — concrete chunkers do
    not need to explicitly inherit from it.
    """

    def chunk(self, *args: object, **kwargs: object) -> list[LegalChunk]:
        """Produce chunks from the strategy's input.

        The signature is intentionally loose: each concrete strategy takes
        the input it needs — :class:`~lexichunk.strategies.fallback.FallbackChunker`
        takes the document text, while
        :class:`~lexichunk.strategies.clause_aware.ClauseAwareChunker` takes
        the parsed clauses and the text.

        Returns:
            List of :class:`~lexichunk.models.LegalChunk` objects in
            document order.
        """
        ...


__all__ = ["ChunkingStrategy"]
