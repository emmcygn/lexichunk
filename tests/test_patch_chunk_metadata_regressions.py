from __future__ import annotations

from collections.abc import Callable

import pytest

from lexichunk import LegalChunker
from lexichunk.enrichment.clause_type import ClassificationResult
from lexichunk.models import ClauseType, LegalChunk

_PREFIX_BUDGET_TEXT = (
    "1. Long Parent Heading\n"
    "1.1 Child\n"
    "abcdefghijklmnopqrst\n"
)
_CLASSIFICATION_TEXT = "Confidential information may be terminated."


def _chunk_prefix_budget_text(include_ancestor_headers: bool) -> list[LegalChunk]:
    return LegalChunker(
        jurisdiction="uk",
        max_chunk_size=35,
        min_chunk_size=0,
        chars_per_token=1,
        include_ancestor_headers=include_ancestor_headers,
        include_definitions=False,
        include_context_header=False,
    ).chunk(_PREFIX_BUDGET_TEXT)


def test_disabled_ancestor_prefix_does_not_fragment_a_child_within_budget() -> None:
    chunks = _chunk_prefix_budget_text(include_ancestor_headers=False)

    assert [chunk.content for chunk in chunks] == [
        "1. Long Parent Heading\n",
        "1.1 Child\nabcdefghijklmnopqrst\n",
    ]
    assert all(chunk.token_count <= 35 for chunk in chunks)
    assert all(
        chunk.content == _PREFIX_BUDGET_TEXT[chunk.char_start : chunk.char_end]
        for chunk in chunks
    )


def test_enabled_ancestor_prefix_still_counts_toward_the_hard_cap() -> None:
    chunks = _chunk_prefix_budget_text(include_ancestor_headers=True)

    assert len(chunks) == 3
    assert all(chunk.token_count <= 35 for chunk in chunks)
    assert chunks[0].content.endswith("1.1 Child\n")
    assert chunks[1].content.startswith("1 Long Parent Heading\n")
    assert chunks[2].content.startswith("1 Long Parent Heading\n")


Hook = Callable[[LegalChunk, ClassificationResult], ClauseType | None]


def _classify_with_hook(hook: Hook) -> LegalChunk:
    return LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        include_definitions=False,
        include_context_header=False,
        classification_hook=hook,
        classification_hook_threshold=0.5,
    ).chunk(_CLASSIFICATION_TEXT)[0]


def _return_keyword_runner_up(
    chunk: LegalChunk, result: ClassificationResult
) -> ClauseType | None:
    return result.secondary_clause_type


def _return_keyword_primary(
    chunk: LegalChunk, result: ClassificationResult
) -> ClauseType | None:
    return result.clause_type


def _return_services(
    chunk: LegalChunk, result: ClassificationResult
) -> ClauseType | None:
    return ClauseType.SERVICES


def _return_none(
    chunk: LegalChunk, result: ClassificationResult
) -> ClauseType | None:
    return None


@pytest.mark.parametrize(
    "hook,expected_primary,expected_secondary,expected_source",
    [
        (
            _return_keyword_runner_up,
            ClauseType.CONFIDENTIALITY,
            ClauseType.TERMINATION,
            "hook",
        ),
        (
            _return_keyword_primary,
            ClauseType.TERMINATION,
            ClauseType.CONFIDENTIALITY,
            "hook",
        ),
        (
            _return_services,
            ClauseType.SERVICES,
            ClauseType.TERMINATION,
            "hook",
        ),
        (
            _return_none,
            ClauseType.TERMINATION,
            ClauseType.CONFIDENTIALITY,
            "keyword",
        ),
    ],
)
def test_hook_outcomes_keep_distinct_ranked_clause_types(
    hook: Hook,
    expected_primary: ClauseType,
    expected_secondary: ClauseType,
    expected_source: str,
) -> None:
    chunk = _classify_with_hook(hook)

    assert chunk.clause_type is expected_primary
    assert chunk.secondary_clause_type is expected_secondary
    assert chunk.classification_source == expected_source
    assert chunk.classification_confidence == 0.125


def test_hook_can_use_the_only_keyword_type_as_its_secondary() -> None:
    text = "This agreement may be terminated."
    keyword_chunk = LegalChunker(min_chunk_size=0).chunk(text)[0]
    hook_chunk = LegalChunker(
        min_chunk_size=0,
        classification_hook=_return_services,
        classification_hook_threshold=1.0,
    ).chunk(text)[0]

    assert keyword_chunk.clause_type is ClauseType.TERMINATION
    assert keyword_chunk.secondary_clause_type is None
    assert hook_chunk.clause_type is ClauseType.SERVICES
    assert hook_chunk.secondary_clause_type is ClauseType.TERMINATION
    assert hook_chunk.classification_confidence == keyword_chunk.classification_confidence
