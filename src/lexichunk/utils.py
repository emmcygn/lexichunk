"""Shared utility functions used across the lexichunk package."""

from __future__ import annotations

from typing import Any

from .models import LegalChunk


def approx_tokens(text: str, chars_per_token: int = 4) -> int:
    """Approximate token count using a configurable character-to-token ratio.

    Args:
        text: The string whose token count is to be estimated.
        chars_per_token: Number of characters per token.  Defaults to 4.

    Returns:
        An integer token estimate, always at least 1.
    """
    return max(1, len(text) // chars_per_token)


def build_metadata(chunk: LegalChunk) -> dict[str, Any]:
    """Build a metadata dict from a LegalChunk for integration frameworks.

    Used by both the LangChain and LlamaIndex integration modules.

    Args:
        chunk: A LegalChunk instance.

    Returns:
        Dictionary of metadata ready to attach to a framework document node.
    """
    return {
        "clause_type": chunk.clause_type.value,
        "jurisdiction": chunk.jurisdiction.value,
        "document_section": chunk.document_section.value,
        "hierarchy_path": chunk.hierarchy_path,
        "hierarchy_identifier": chunk.hierarchy.identifier,
        "hierarchy_level": chunk.hierarchy.level,
        "cross_references": [
            {
                "raw_text": ref.raw_text,
                "target_identifier": ref.target_identifier,
                "target_chunk_index": ref.target_chunk_index,
            }
            for ref in chunk.cross_references
        ],
        "defined_terms_used": chunk.defined_terms_used,
        "context_header": chunk.context_header,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "chunk_index": chunk.index,
        "document_id": chunk.document_id,
    }
