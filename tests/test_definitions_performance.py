"""Definition-body extraction must stay linear in the document.

CUAD issue 4: worst-case chunking cost was ~500x the median — 20.6 s on a
291,873-character contract against a 0.042 s median across 150 contracts.
It was not length. Synthetic text scaled linearly and cheaply (722,000
characters of repeated well-formed clauses in 0.48 s, twice the size of the
worst real contract at 2% of the cost), so the driver was *content*.

It was ``_extract_definition_body``. For each definition it searched from
that definition to the end of the document, once per stop pattern, with
around fourteen patterns. Most documents use two or three definition forms,
so the other patterns matched nowhere and paid a full scan every time —
O(definitions x document length). A contract with a long definitions article
is exactly the shape that maximises both factors, which is why it looked
content-dependent.

The searches are now bounded by ``_STOP_SEARCH_SLACK``, which is sound
because only the earliest match start can lower the boundary. These tests
pin both halves of that claim: that it is still correct, and that it is no
longer quadratic.
"""

from __future__ import annotations

import time

import pytest

import lexichunk.parsers.definitions as definitions_module
from lexichunk import LegalChunker
from lexichunk.parsers.definitions import DefinitionsExtractor

from ._snapshot_support import FIXTURE_CONFIGS, load_fixture

# Measured on this input: 0.95s bounded, 18.75s with the searches unbounded
# again. 8s sits well clear of both — roughly 8x headroom for a slow shared
# runner, while still failing decisively if the quadratic behaviour returns.
# It is not there to police a few hundred milliseconds.
_TIME_BUDGET_SECONDS = 8.0

_DEFINITION_COUNT = 500
_BODY_CLAUSE_COUNT = 300


def _pathological_document() -> str:
    """A document with many defined terms *and* many clauses.

    Both factors of the old ``O(definitions x length)`` cost at once: a long
    definitions article, and enough body afterwards that every definition's
    stop-pattern search had a long way to run.
    """
    lines = ["MASTER SERVICES AGREEMENT", "", "ARTICLE I", "DEFINITIONS", ""]
    for i in range(_DEFINITION_COUNT):
        lines.append(
            f'"Defined Term {i:04d}" means the {i:04d}th category of services, '
            f"materials and deliverables described in the applicable statement "
            f"of work and accepted by the Customer in writing."
        )
        lines.append("")

    for i in range(_BODY_CLAUSE_COUNT):
        lines.append(f"Section {i + 2}.01 Obligation {i:04d}")
        lines.append("")
        lines.append(
            f"The Provider shall perform each Defined Term {i:04d} obligation "
            f"in accordance with the applicable service levels and shall "
            f"report on its performance monthly. The Customer shall pay the "
            f"corresponding fees within thirty (30) days of receipt of a "
            f"valid invoice."
        )
        lines.append("")

    return "\n".join(lines)


def test_a_definition_heavy_document_chunks_in_reasonable_time() -> None:
    text = _pathological_document()
    chunker = LegalChunker(jurisdiction="us", max_chunk_size=512)

    start = time.perf_counter()
    chunks, metrics = chunker.chunk_with_metrics(text)
    elapsed = time.perf_counter() - start

    # Guard the guard: if the document stopped being pathological, the timing
    # assertion below would pass for the wrong reason.
    assert len(text) > 150_000, len(text)
    assert metrics.defined_term_count >= 400, metrics.defined_term_count
    assert len(chunks) >= 200, len(chunks)

    assert elapsed < _TIME_BUDGET_SECONDS, (
        f"chunked {len(text):,} chars with {metrics.defined_term_count} "
        f"defined terms in {elapsed:.2f}s, over the {_TIME_BUDGET_SECONDS}s "
        f"budget — definition-body extraction may be quadratic again"
    )


def test_cost_grows_linearly_with_document_length() -> None:
    """Quadratic growth would show as a super-linear ratio here.

    Doubling a definition-heavy document quadrupled the old cost. The bound
    is loose (3x for a 2x input) so ordinary constant-factor noise on a
    shared runner does not fail the build, but 4x-and-up does.
    """
    single = _pathological_document()
    chunker = LegalChunker(jurisdiction="us", max_chunk_size=512)

    def timed(text: str) -> float:
        # A fresh chunker each time: the definition cache would otherwise
        # make the second measurement free and hide the growth entirely.
        fresh = LegalChunker(jurisdiction="us", max_chunk_size=512)
        start = time.perf_counter()
        fresh.chunk(text)
        return time.perf_counter() - start

    chunker.chunk(single[:100])  # warm any lazy module state
    one = timed(single)
    two = timed(single + "\n" + single)

    assert two < one * 3.0, (
        f"doubling the document multiplied the cost by {two / one:.1f}x "
        f"({one:.2f}s -> {two:.2f}s); expected roughly linear growth"
    )


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
def test_bounding_the_search_does_not_change_what_is_extracted(
    fixture_name: str,
    jurisdiction: str,
    doc_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The optimisation is an optimisation, not a behaviour change.

    Only the earliest stop-pattern match can lower the body boundary, so
    searching a bounded window must give the same answer as searching to the
    end of the document. Raising the slack to something larger than any
    document makes the searches effectively unbounded again.
    """
    text = load_fixture(fixture_name)

    def extracted() -> dict[str, str]:
        terms = DefinitionsExtractor(jurisdiction).extract(text)
        return {name: term.definition for name, term in terms.items()}

    bounded = extracted()
    monkeypatch.setattr(definitions_module, "_STOP_SEARCH_SLACK", 10_000_000)
    assert extracted() == bounded
