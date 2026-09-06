"""Invariant suite — Phase 0 characterization.

Each invariant is its own test function so failures are individually
visible.  Parametrized over the five (fixture, config) pairs used by
``test_snapshots.py`` plus three synthetic inputs designed to probe edge
cases (CRLF + BOM, a semicolon-only oversized clause, a small multi-level
UK document).

Where an invariant currently FAILS for a specific case, that parameter is
marked ``xfail(strict=True, ...)`` with a one-line description of the known
bug.  This is intentional: Phase 0 freezes *current* behaviour (bugs
included) so later fixes are provable by a param flipping from xfail to
pass (which — because these are ``strict``— makes the suite fail loudly
until the mark is removed).  Do not weaken any assertion to make a case
pass; only add/remove xfail marks.
"""

from __future__ import annotations

from typing import Any

import pytest

from lexichunk import LegalChunker
from lexichunk.models import LegalChunk

from ._snapshot_support import FIXTURE_CONFIGS, load_fixture

DEFAULT_MAX_CHUNK_SIZE = 512
DEFAULT_MIN_CHUNK_SIZE = 64

# ---------------------------------------------------------------------------
# Synthetic inputs
# ---------------------------------------------------------------------------

# CRLF line endings + a leading UTF-8 BOM.
_CRLF_BOM_TEXT = (
    "﻿1. Confidentiality\r\n"
    "Each party shall keep confidential all information disclosed by the "
    "other party under this agreement.\r\n"
    "\r\n"
    "2. Termination\r\n"
    "Either party may terminate this agreement upon thirty days written "
    "notice to the other party.\r\n"
)

# A single ~5 KB clause with no sentence-terminating punctuation at all —
# only semicolons separate its (repeated) items.
_SEMICOLON_CLAUSE_TEXT = "1. Definitions\n" + (
    "the first term; the second term; the third term; the fourth term; "
    "the fifth term; "
) * 100

# A small 3-top-level-clause UK document with one nested sub-clause.
_SHORT_UK_TEXT = (
    "1. Confidentiality\n"
    "Each party shall keep confidential all information disclosed by the "
    "other party.\n"
    "\n"
    "1.1 Scope\n"
    "This clause applies to all confidential information disclosed under "
    "this agreement.\n"
    "\n"
    "2. Termination\n"
    "This agreement may be terminated by either party upon notice.\n"
    "\n"
    "3. Governing Law\n"
    "This agreement is governed by the laws of England and Wales.\n"
)

_SYNTHETIC_CASES: dict[str, tuple[str, str, str]] = {
    "crlf_bom": ("uk", "contract", _CRLF_BOM_TEXT),
    "semicolon_5kb_clause": ("uk", "contract", _SEMICOLON_CLAUSE_TEXT),
    "short_uk_three_clauses": ("uk", "contract", _SHORT_UK_TEXT),
}


def _all_cases() -> list[tuple[str, str, str, str]]:
    """Return (case_id, jurisdiction, doc_type, text) for every case."""
    cases: list[tuple[str, str, str, str]] = []
    for fixture_name, jurisdiction, doc_type in FIXTURE_CONFIGS:
        cases.append((fixture_name, jurisdiction, doc_type, load_fixture(fixture_name)))
    for case_id, (jurisdiction, doc_type, text) in _SYNTHETIC_CASES.items():
        cases.append((case_id, jurisdiction, doc_type, text))
    return cases


_ALL_CASES = _all_cases()


def _params(xfail_reasons: dict[str, str]) -> list[Any]:
    """Build a parametrize list, marking specific case ids as strict xfail."""
    params = []
    for case_id, jurisdiction, doc_type, text in _ALL_CASES:
        marks = []
        if case_id in xfail_reasons:
            marks.append(pytest.mark.xfail(strict=True, reason=xfail_reasons[case_id]))
        params.append(pytest.param(case_id, jurisdiction, doc_type, text, id=case_id, marks=marks))
    return params


def _chunk(jurisdiction: str, doc_type: str, text: str) -> tuple[LegalChunker, list[LegalChunk]]:
    chunker = LegalChunker(
        jurisdiction=jurisdiction,
        doc_type=doc_type,
        max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
        min_chunk_size=DEFAULT_MIN_CHUNK_SIZE,
    )
    return chunker, chunker.chunk(text)


# ---------------------------------------------------------------------------
# 1. No chunk has empty/whitespace-only content.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id,jurisdiction,doc_type,text", _params({}))
def test_no_empty_content(case_id: str, jurisdiction: str, doc_type: str, text: str) -> None:
    _, chunks = _chunk(jurisdiction, doc_type, text)
    for chunk in chunks:
        assert chunk.content is not None and chunk.content.strip(), (
            f"[{case_id}] chunk {chunk.index} has empty/whitespace-only content"
        )


# ---------------------------------------------------------------------------
# 2. char_start <= char_end, offsets non-decreasing by index, no overlap.
# ---------------------------------------------------------------------------

# FIXED (work package G2): a chunk's char_end is now the end of the clause's
# *own* text (ClauseAwareChunker._own_end) instead of ParsedClause.char_end,
# which spanned the whole descendant subtree.  Parent chunks no longer overlap
# their first child.
_OVERLAP_XFAIL: dict[str, str] = {}


@pytest.mark.parametrize("case_id,jurisdiction,doc_type,text", _params(_OVERLAP_XFAIL))
def test_offset_ordering_and_no_overlap(
    case_id: str, jurisdiction: str, doc_type: str, text: str
) -> None:
    _, chunks = _chunk(jurisdiction, doc_type, text)
    prev_start = -1
    for chunk in chunks:
        assert chunk.char_start <= chunk.char_end, (
            f"[{case_id}] chunk {chunk.index}: char_start={chunk.char_start} "
            f"> char_end={chunk.char_end}"
        )
        assert chunk.char_start >= prev_start, (
            f"[{case_id}] chunk {chunk.index}: char_start={chunk.char_start} "
            f"decreased from previous chunk's char_start={prev_start}"
        )
        prev_start = chunk.char_start
    for i in range(len(chunks) - 1):
        a, b = chunks[i], chunks[i + 1]
        assert a.char_end <= b.char_start, (
            f"[{case_id}] chunk {i} (char_end={a.char_end}) overlaps "
            f"chunk {i + 1} (char_start={b.char_start})"
        )


# ---------------------------------------------------------------------------
# 3. sanitised[char_start:char_end] is a substring of content ("content is a
#    superset" invariant).
# ---------------------------------------------------------------------------

# FIXED (work package G2): a chunk body is now the exact slice
# sanitised[char_start:char_end] rather than a '\n'.join reconstruction, in the
# merge, split and fallback paths alike.  `content` is that body with the
# ancestor headers prepended, so the span is reproduced byte-for-byte.
_SUPERSET_XFAIL: dict[str, str] = {}


@pytest.mark.parametrize("case_id,jurisdiction,doc_type,text", _params(_SUPERSET_XFAIL))
def test_content_is_superset_of_span(
    case_id: str, jurisdiction: str, doc_type: str, text: str
) -> None:
    sanitised = LegalChunker._sanitize_input(text)
    _, chunks = _chunk(jurisdiction, doc_type, text)
    for chunk in chunks:
        span = sanitised[chunk.char_start : chunk.char_end]
        assert span in chunk.content, (
            f"[{case_id}] chunk {chunk.index}: sanitised span not found in "
            f"content.\n  span[:80]={span[:80]!r}\n"
            f"  content[:80]={chunk.content[:80]!r}"
        )


# ---------------------------------------------------------------------------
# 4. token_count <= max_chunk_size for every chunk.
# ---------------------------------------------------------------------------

# FIXED (work package G2): max_chunk_size is now a hard cap.  Oversized clauses
# go through a cascading splitter (sentences → semicolons → enumerators →
# newlines → hard word window), merges re-check the combined size, and
# ClauseAwareChunker._enforce_max re-splits anything still over the limit after
# merging — counting the ancestor-header prefix against the budget.
_TOKEN_COUNT_XFAIL: dict[str, str] = {}


@pytest.mark.parametrize("case_id,jurisdiction,doc_type,text", _params(_TOKEN_COUNT_XFAIL))
def test_token_count_within_max(
    case_id: str, jurisdiction: str, doc_type: str, text: str
) -> None:
    _, chunks = _chunk(jurisdiction, doc_type, text)
    for chunk in chunks:
        assert chunk.token_count <= DEFAULT_MAX_CHUNK_SIZE, (
            f"[{case_id}] chunk {chunk.index}: token_count={chunk.token_count} "
            f"> max_chunk_size={DEFAULT_MAX_CHUNK_SIZE}"
        )


# ---------------------------------------------------------------------------
# 5. chunk(text) == list(chunk_iter(text)).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id,jurisdiction,doc_type,text", _params({}))
def test_chunk_equals_chunk_iter(
    case_id: str, jurisdiction: str, doc_type: str, text: str
) -> None:
    chunker = LegalChunker(
        jurisdiction=jurisdiction,
        doc_type=doc_type,
        max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
        min_chunk_size=DEFAULT_MIN_CHUNK_SIZE,
    )
    via_chunk = [c.to_dict() for c in chunker.chunk(text)]
    via_iter = [c.to_dict() for c in chunker.chunk_iter(text)]
    assert via_chunk == via_iter, f"[{case_id}] chunk() and chunk_iter() diverged"


# ---------------------------------------------------------------------------
# 6. Determinism: same instance twice, and a fresh instance, agree.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id,jurisdiction,doc_type,text", _params({}))
def test_deterministic_repeated_chunking(
    case_id: str, jurisdiction: str, doc_type: str, text: str
) -> None:
    chunker, first = _chunk(jurisdiction, doc_type, text)
    second = chunker.chunk(text)
    assert [c.to_dict() for c in first] == [c.to_dict() for c in second], (
        f"[{case_id}] repeated chunk() on the same instance diverged"
    )

    fresh = LegalChunker(
        jurisdiction=jurisdiction,
        doc_type=doc_type,
        max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
        min_chunk_size=DEFAULT_MIN_CHUNK_SIZE,
    )
    third = fresh.chunk(text)
    assert [c.to_dict() for c in first] == [c.to_dict() for c in third], (
        f"[{case_id}] chunk() on a fresh instance diverged from the original"
    )


# ---------------------------------------------------------------------------
# 7. chunk_batch(workers=1) matches sequential chunk() calls, in order.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id,jurisdiction,doc_type,text", _params({}))
def test_chunk_batch_matches_sequential(
    case_id: str, jurisdiction: str, doc_type: str, text: str
) -> None:
    chunker = LegalChunker(
        jurisdiction=jurisdiction,
        doc_type=doc_type,
        max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
        min_chunk_size=DEFAULT_MIN_CHUNK_SIZE,
    )
    texts = [text, text, text]
    batch = chunker.chunk_batch(texts, workers=1)
    expected = [chunker.chunk(t) for t in texts]

    assert len(batch.results) == len(expected), f"[{case_id}] batch result count mismatch"
    for i, (actual_chunks, expected_chunks) in enumerate(zip(batch.results, expected)):
        assert [c.to_dict() for c in actual_chunks] == [c.to_dict() for c in expected_chunks], (
            f"[{case_id}] batch result {i} diverged from sequential chunk()"
        )


# ---------------------------------------------------------------------------
# 8. cross_ref_resolved <= cross_ref_total; resolved target indices are valid.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id,jurisdiction,doc_type,text", _params({}))
def test_cross_ref_resolution_consistency(
    case_id: str, jurisdiction: str, doc_type: str, text: str
) -> None:
    _, chunks = _chunk(jurisdiction, doc_type, text)
    n = len(chunks)
    for chunk in chunks:
        assert chunk.cross_ref_resolved <= chunk.cross_ref_total, (
            f"[{case_id}] chunk {chunk.index}: cross_ref_resolved="
            f"{chunk.cross_ref_resolved} > cross_ref_total={chunk.cross_ref_total}"
        )
        for ref in chunk.cross_references:
            if ref.target_chunk_index is not None:
                assert 0 <= ref.target_chunk_index < n, (
                    f"[{case_id}] chunk {chunk.index}: cross-reference "
                    f"target_chunk_index={ref.target_chunk_index} is out of "
                    f"range for {n} chunks"
                )
