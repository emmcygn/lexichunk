"""Shared utility functions used across the lexichunk package."""

from __future__ import annotations

import json
from enum import Enum
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


def build_metadata(
    chunk: LegalChunk,
    *,
    include_defined_terms_context: bool = False,
    flatten: bool = False,
) -> dict[str, Any]:
    """Build a metadata dict from a LegalChunk for integration frameworks.

    Used by both the LangChain and LlamaIndex integration modules. Every
    value in the returned dict is guaranteed to be JSON-serialisable
    (``json.dumps`` safe) — enums are rendered as their ``.value`` string and
    nested dataclasses are converted via their own ``to_dict()``.

    Args:
        chunk: A LegalChunk instance.
        include_defined_terms_context: When ``True``, also emit
            ``defined_terms_context`` (a ``dict[str, str]`` of full
            definition text keyed by term). This is omitted by default
            because it re-inflates embedding/LLM text and several vector
            stores reject non-scalar metadata.
        flatten: When ``True``, JSON-encode every non-scalar value
            (``cross_references``, ``defined_terms_used``, and
            ``defined_terms_context`` when included) to a string, for vector
            stores that only accept scalar metadata values.

    Returns:
        Dictionary of metadata ready to attach to a framework document node.

    Note:
        ``cross_references`` (and ``defined_terms_context`` when included)
        are non-scalar (list/dict) values; some vector stores reject or
        silently drop non-scalar metadata. Pass ``flatten=True`` to
        JSON-encode them to strings, or apply your framework's
        complex-metadata filter.
    """
    metadata: dict[str, Any] = {
        "clause_type": chunk.clause_type.value,
        "jurisdiction": chunk.jurisdiction.value if isinstance(chunk.jurisdiction, Enum) else chunk.jurisdiction,
        "document_section": chunk.document_section.value,
        "hierarchy_path": chunk.hierarchy_path,
        "hierarchy_identifier": chunk.hierarchy.identifier,
        "hierarchy_level": chunk.hierarchy.level,
        "cross_references": [ref.to_dict() for ref in chunk.cross_references],
        "defined_terms_used": list(chunk.defined_terms_used),
        "context_header": chunk.context_header,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "chunk_index": chunk.index,
        "document_id": chunk.document_id,
        "classification_confidence": chunk.classification_confidence,
        "secondary_clause_type": (
            chunk.secondary_clause_type.value if chunk.secondary_clause_type is not None else None
        ),
        "cross_ref_total": chunk.cross_ref_total,
        "cross_ref_resolved": chunk.cross_ref_resolved,
        "token_count": chunk.token_count,
        "original_header": chunk.original_header,
    }

    if include_defined_terms_context:
        metadata["defined_terms_context"] = dict(chunk.defined_terms_context)

    if flatten:
        for key, value in list(metadata.items()):
            if isinstance(value, (list, dict)):
                metadata[key] = json.dumps(value)

    return metadata
