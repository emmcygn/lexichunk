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

    def chunk(self, *args, **kwargs) -> list[LegalChunk]: ...


__all__ = ["ChunkingStrategy"]
