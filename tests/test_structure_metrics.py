"""Structure-quality fields on PipelineMetrics.

These are the numbers a legaltech engineer looks at to decide whether the
parser understood *this* contract, rather than whether the pipeline ran.
The load-bearing one is
``chunks_spanning_multiple_top_level_clauses``, which is 0 by design across
every fixture: the clause-aware chunker never merges two container-level
groups, so no chunk may straddle two top-level clauses.
"""

from __future__ import annotations

import pytest

from lexichunk import LegalChunker
from lexichunk.metrics import PipelineMetrics

from ._snapshot_support import FIXTURE_CONFIGS, load_fixture, make_chunker

_SHORT_UK = (
    "1. Definitions\n"
    "In this agreement the following terms have the meanings given below.\n"
    "\n"
    "1.1 Services\n"
    "The services described in Schedule 1.\n"
    "\n"
    "2. Termination\n"
    "Either party may terminate this agreement on thirty days notice.\n"
)


def _metrics(text: str, **kwargs: object) -> PipelineMetrics:
    chunker = LegalChunker(jurisdiction="uk", **kwargs)  # type: ignore[arg-type]
    _, metrics = chunker.chunk_with_metrics(text)
    return metrics


# ---------------------------------------------------------------------------
# The design invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
def test_no_chunk_spans_two_top_level_clauses(
    fixture_name: str, jurisdiction: str, doc_type: str
) -> None:
    chunker = make_chunker(jurisdiction, doc_type)
    _, metrics = chunker.chunk_with_metrics(load_fixture(fixture_name))
    assert metrics.chunks_spanning_multiple_top_level_clauses == 0, (
        f"{fixture_name}: a chunk merged across a top-level clause boundary"
    )


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
def test_no_over_merge_at_any_min_chunk_size(
    fixture_name: str, jurisdiction: str, doc_type: str
) -> None:
    """A large min_chunk_size pushes merging hard; hierarchy still wins."""
    text = load_fixture(fixture_name)
    for min_size in (0, 64, 256):
        chunker = LegalChunker(
            jurisdiction=jurisdiction,
            doc_type=doc_type,
            max_chunk_size=512,
            min_chunk_size=min_size,
        )
        _, metrics = chunker.chunk_with_metrics(text)
        assert metrics.chunks_spanning_multiple_top_level_clauses == 0, (
            f"{fixture_name} at min_chunk_size={min_size}: over-merge"
        )


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_clause_and_top_level_counts() -> None:
    metrics = _metrics(_SHORT_UK, min_chunk_size=0)
    # 1, 1.1, 2 — no preamble, the document opens on a heading.
    assert metrics.clause_count == 3
    # 1 and 2 are roots; 1.1 hangs off 1.
    assert metrics.top_level_clause_count == 2


def test_top_level_count_includes_the_preamble() -> None:
    metrics = _metrics("Some framing text.\n\n" + _SHORT_UK, min_chunk_size=0)
    assert metrics.clause_count == 4
    assert metrics.top_level_clause_count == 3


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
def test_counts_are_internally_consistent(
    fixture_name: str, jurisdiction: str, doc_type: str
) -> None:
    chunker = make_chunker(jurisdiction, doc_type)
    chunks, metrics = chunker.chunk_with_metrics(load_fixture(fixture_name))
    assert 0 < metrics.top_level_clause_count <= metrics.clause_count
    assert 0 <= metrics.chunks_with_multiple_clauses <= metrics.chunk_count
    assert 0 <= metrics.chunks_below_min <= metrics.chunk_count
    assert metrics.chunk_count == len(chunks)
    assert metrics.heading_candidates_rejected >= 0


def test_chunks_below_min_matches_the_chunks() -> None:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=64)
    chunks, metrics = chunker.chunk_with_metrics(_SHORT_UK)
    expected = sum(1 for c in chunks if c.token_count < 64)
    assert metrics.chunks_below_min == expected


def test_chunks_below_min_is_zero_when_there_is_no_minimum() -> None:
    metrics = _metrics(_SHORT_UK, min_chunk_size=0)
    assert metrics.chunks_below_min == 0


def test_chunks_with_multiple_clauses_counts_sub_clause_grouping() -> None:
    """A parent gathered with its short sub-clause is one grouped chunk."""
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=256)
    chunks, metrics = chunker.chunk_with_metrics(_SHORT_UK)
    assert metrics.chunks_with_multiple_clauses >= 1
    assert metrics.chunks_with_multiple_clauses <= len(chunks)


def test_split_pieces_of_one_clause_are_not_counted_as_grouped() -> None:
    """An over-sized clause split into pieces carries one identifier."""
    long_clause = "1. Services\n" + ("The supplier shall provide services. " * 400)
    chunker = LegalChunker(jurisdiction="uk", max_chunk_size=64, min_chunk_size=0)
    chunks, metrics = chunker.chunk_with_metrics(long_clause)
    assert len(chunks) > 3
    assert metrics.chunks_with_multiple_clauses == 0


# ---------------------------------------------------------------------------
# heading_candidates_rejected
# ---------------------------------------------------------------------------


def test_rejected_headings_counts_table_of_contents_lines() -> None:
    toc = (
        "TABLE OF CONTENTS\n"
        "1. Definitions ......................... 1\n"
        "2. Services ............................ 3\n"
        "3. Termination ......................... 7\n"
        "\n"
        "1. Definitions\n"
        "In this agreement the following terms apply throughout.\n"
    )
    metrics = _metrics(toc, min_chunk_size=0)
    assert metrics.heading_candidates_rejected >= 3


def test_rejected_headings_is_zero_for_a_clean_document() -> None:
    metrics = _metrics(_SHORT_UK, min_chunk_size=0)
    assert metrics.heading_candidates_rejected == 0


def test_rejected_headings_resets_between_calls() -> None:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    noisy = "1. Definitions ..................... 1\n\n1. Definitions\nText here.\n"
    _, first = chunker.chunk_with_metrics(noisy)
    _, second = chunker.chunk_with_metrics(_SHORT_UK)
    assert first.heading_candidates_rejected >= 1
    assert second.heading_candidates_rejected == 0


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


def test_empty_document_reports_zeroes() -> None:
    metrics = _metrics("   \n\n  ")
    assert metrics.clause_count == 0
    assert metrics.top_level_clause_count == 0
    assert metrics.chunks_spanning_multiple_top_level_clauses == 0
    assert metrics.chunks_with_multiple_clauses == 0
    assert metrics.chunks_below_min == 0
    assert metrics.heading_candidates_rejected == 0


def test_headerless_document_uses_the_fallback_and_still_reports() -> None:
    text = "This is running prose with no clause numbering at all. " * 20
    metrics = _metrics(text, min_chunk_size=0)
    assert metrics.fallback_used is True
    # The parser produced the single synthetic preamble clause.
    assert metrics.clause_count == 1
    assert metrics.top_level_clause_count == 1
    assert metrics.chunks_spanning_multiple_top_level_clauses == 0
    # merged_identifiers is not tracked on the fallback path.
    assert metrics.chunks_with_multiple_clauses == 0


def test_new_fields_default_to_zero_when_constructed_directly() -> None:
    metrics = PipelineMetrics(
        total_duration_ms=1.0,
        stage_metrics=(),
        chunk_count=0,
        defined_term_count=0,
        cross_ref_total=0,
        cross_ref_resolved=0,
        input_chars=0,
        fallback_used=False,
    )
    assert metrics.clause_count == 0
    assert metrics.top_level_clause_count == 0
    assert metrics.chunks_spanning_multiple_top_level_clauses == 0
    assert metrics.chunks_with_multiple_clauses == 0
    assert metrics.chunks_below_min == 0
    assert metrics.heading_candidates_rejected == 0


# ---------------------------------------------------------------------------
# chunks_unclassified — CUAD issue 6
# ---------------------------------------------------------------------------
#
# Two of 150 CUAD contracts produced chunks where *every* chunk came back
# ClauseType.UNKNOWN: both short and unusually formatted (one a Chinese-English
# photovoltaic cooperation agreement, one a bank outsourcing agreement that
# reduced to a single chunk). That is the classifier declining rather than
# misfiring, which is the right failure direction — but it means those
# documents carry no clause metadata at all, and nothing in the metrics said
# so. Detecting it should not require iterating the chunks yourself.


def test_an_entirely_unclassified_document_is_visible_in_the_metrics() -> None:
    text = (
        "50MWp Photovoltaic Cooperation. Party A and Party B hereby cooperate "
        "on the project in Ningxia. The total capacity is 50MWp."
    )
    chunks, metrics = LegalChunker(
        jurisdiction="us", min_chunk_size=0
    ).chunk_with_metrics(text)

    assert all(c.clause_type.value == "unknown" for c in chunks)
    assert metrics.chunks_unclassified == metrics.chunk_count
    # fallback_used is the companion signal: it says whether the structure
    # parser found anything to classify in the first place.
    assert metrics.fallback_used is True


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
def test_real_fixtures_are_mostly_classified(
    fixture_name: str, jurisdiction: str, doc_type: str
) -> None:
    """A few unclassified chunks are normal; all of them is the alarm."""
    chunks, metrics = make_chunker(jurisdiction, doc_type).chunk_with_metrics(
        load_fixture(fixture_name)
    )
    assert metrics.chunks_unclassified == sum(
        1 for c in chunks if c.clause_type.value == "unknown"
    )
    assert metrics.chunks_unclassified < metrics.chunk_count, (
        f"{fixture_name} carries no clause metadata at all"
    )
