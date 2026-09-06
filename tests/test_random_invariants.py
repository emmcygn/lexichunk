"""Property-based invariants over randomly generated legal-looking documents.

``tests/test_invariants.py`` pins the same properties against five hand-written
fixtures plus three synthetic cases.  That catches regressions on documents we
already thought of.  This module generates documents we did not: random
numbering depths, random clause lengths, ALL-CAPS headings, schedules,
sub-clause runs, cross-references pointing at clauses that may or may not
exist, and body text that is *shaped* like a heading.

The size grid is deliberate.  ``max_chunk_size`` 64/128/512 crossed with
``min_chunk_size`` 0/16/64 is where the interesting interactions live: a small
cap forces the cascading splitter to run on clauses that would normally pass
through whole, and a large minimum forces merging to attempt exactly the
hierarchy crossings it must refuse.  Each property runs across all nine
pairs and reports which one failed.

Generation is deterministic:
``tests/conftest.py`` registers and loads a Hypothesis profile with
``derandomize=True`` and the example database off, so a given commit draws
the same documents on every machine and every run.  A property test that
draws different examples each time is one whose failures cannot be
reproduced and whose passes mean less than they look like they do.
"""

from __future__ import annotations

import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from lexichunk import LegalChunker

MAX_SIZES = (64, 128, 512)
MIN_SIZES = (0, 16, 64)

_SENTENCES = [
    "The Supplier shall provide the Services with reasonable skill and care.",
    "Each party shall keep confidential all information disclosed to it.",
    "The Customer shall pay each invoice within thirty days of receipt.",
    "Neither party excludes liability for death or personal injury.",
    "This clause survives termination of this agreement for any reason.",
    "The parties shall negotiate in good faith to resolve any dispute.",
    "Notices must be given in writing and delivered to the registered office.",
    "No variation of this agreement is effective unless made in writing.",
    "Nothing in this agreement creates a partnership between the parties.",
    "Time is of the essence in respect of the obligations in this clause.",
]

_CROSS_REFERENCES = [
    "as set out in clause 1.1",
    "subject to clause 2",
    "in accordance with Schedule 1",
    "described in clause 3.2",
    "pursuant to paragraph 4",
    "as referred to in clause 99.9",
]

_TITLES = [
    "Definitions",
    "Confidentiality",
    "Payment Terms",
    "Termination",
    "Governing Law",
    "Limitation of Liability",
    "Data Protection",
    "Intellectual Property",
]

# Lines that look like headings but are body text, to make the plausibility
# gate work for its living.
_DECOYS = [
    "3 Business Days after receipt of a valid invoice.",
    "2. GBP 5,000 per month for hosting services.",
    "1. Definitions .......................... 4",
    "CONFIDENTIAL",
    "Page 3 of 12",
]


@st.composite
def legal_documents(draw: st.DrawFn) -> str:
    """Generate a plausible-looking legal document.

    Shapes drawn from: preamble text, top-level numbered clauses with titles,
    subsections, alpha sub-clauses, ALL-CAPS headings, schedules, and decoy
    lines that look like headings but are not.
    """
    parts: list[str] = []

    if draw(st.booleans()):
        parts.append(
            "This agreement is made between the parties on 1 March 2024.\n"
        )

    clause_count = draw(st.integers(min_value=1, max_value=8))
    for number in range(1, clause_count + 1):
        title = draw(st.sampled_from(_TITLES))
        parts.append(f"\n{number}. {title}\n")
        for sentence in draw(
            st.lists(st.sampled_from(_SENTENCES), min_size=0, max_size=6)
        ):
            parts.append(sentence + "\n")
        for reference in draw(
            st.lists(st.sampled_from(_CROSS_REFERENCES), max_size=2)
        ):
            parts.append(f"The Supplier shall act {reference}.\n")
        for decoy in draw(st.lists(st.sampled_from(_DECOYS), max_size=2)):
            parts.append(decoy + "\n")

        for sub in range(1, draw(st.integers(min_value=0, max_value=3)) + 1):
            parts.append(f"\n{number}.{sub} {draw(st.sampled_from(_TITLES))}\n")
            for sentence in draw(
                st.lists(st.sampled_from(_SENTENCES), min_size=0, max_size=4)
            ):
                parts.append(sentence + "\n")
            for letter in "abc"[: draw(st.integers(min_value=0, max_value=3))]:
                parts.append(f"({letter}) {draw(st.sampled_from(_SENTENCES))}\n")

    if draw(st.booleans()):
        parts.append("\nSchedule 1 — Services Description\n")
        for sentence in draw(
            st.lists(st.sampled_from(_SENTENCES), min_size=1, max_size=5)
        ):
            parts.append(sentence + "\n")

    return "".join(parts)


def _chunkers() -> list[tuple[int, int]]:
    """The size grid every property is checked across."""
    return [
        (maximum, minimum)
        for maximum in MAX_SIZES
        for minimum in MIN_SIZES
        if minimum <= maximum
    ]


_SETTINGS = settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


# ---------------------------------------------------------------------------
# 1. Tiling and non-overlap
# ---------------------------------------------------------------------------


@_SETTINGS
@given(legal_documents())
def test_spans_are_ordered_and_never_overlap(text: str) -> None:
    for maximum, minimum in _chunkers():
        chunker = LegalChunker(
            jurisdiction="uk", max_chunk_size=maximum, min_chunk_size=minimum
        )
        chunks = chunker.chunk(text)
        previous_end = 0
        for chunk in chunks:
            assert chunk.char_start <= chunk.char_end
            assert chunk.char_start >= previous_end, (
                f"[{maximum}/{minimum}] chunk {chunk.index} overlaps its "
                f"predecessor"
            )
            previous_end = chunk.char_end


@_SETTINGS
@given(legal_documents())
def test_chunk_bodies_are_exact_slices(text: str) -> None:
    """`content` always ends with the literal sanitised span it claims."""
    sanitised = LegalChunker.sanitize(text)
    for maximum, minimum in _chunkers():
        chunker = LegalChunker(
            jurisdiction="uk", max_chunk_size=maximum, min_chunk_size=minimum
        )
        for chunk in chunker.chunk(text):
            span = sanitised[chunk.char_start : chunk.char_end]
            assert span in chunk.content, (
                f"[{maximum}/{minimum}] chunk {chunk.index}: span not found "
                f"in content"
            )


# ---------------------------------------------------------------------------
# 2. The size cap
# ---------------------------------------------------------------------------


@_SETTINGS
@given(legal_documents())
def test_max_chunk_size_is_a_hard_cap(text: str) -> None:
    for maximum, minimum in _chunkers():
        chunker = LegalChunker(
            jurisdiction="uk", max_chunk_size=maximum, min_chunk_size=minimum
        )
        for chunk in chunker.chunk(text):
            assert chunk.token_count <= maximum, (
                f"[{maximum}/{minimum}] chunk {chunk.index}: "
                f"token_count={chunk.token_count}"
            )


# ---------------------------------------------------------------------------
# 3. No empty chunks, no internal split markers leaking out
# ---------------------------------------------------------------------------

_INTERNAL_MARKER = re.compile(r"__part|#p\d")


@_SETTINGS
@given(legal_documents())
def test_no_empty_chunks_and_no_internal_markers(text: str) -> None:
    for maximum, minimum in _chunkers():
        chunker = LegalChunker(
            jurisdiction="uk", max_chunk_size=maximum, min_chunk_size=minimum
        )
        for chunk in chunker.chunk(text):
            assert chunk.content.strip()
            for field in (
                chunk.hierarchy.identifier,
                chunk.hierarchy_path,
                chunk.original_header,
                chunk.context_header,
                chunk.content,
            ):
                assert not _INTERNAL_MARKER.search(field), (
                    f"[{maximum}/{minimum}] chunk {chunk.index} leaked an "
                    f"internal split marker: {field!r}"
                )


# ---------------------------------------------------------------------------
# 4. Determinism
# ---------------------------------------------------------------------------


@_SETTINGS
@given(legal_documents())
def test_deterministic_across_instances(text: str) -> None:
    for maximum, minimum in _chunkers():
        first = LegalChunker(
            jurisdiction="uk", max_chunk_size=maximum, min_chunk_size=minimum
        )
        second = LegalChunker(
            jurisdiction="uk", max_chunk_size=maximum, min_chunk_size=minimum
        )
        once = [c.to_dict() for c in first.chunk(text)]
        again = [c.to_dict() for c in first.chunk(text)]
        fresh = [c.to_dict() for c in second.chunk(text)]
        assert once == again, f"[{maximum}/{minimum}] repeated call diverged"
        assert once == fresh, f"[{maximum}/{minimum}] fresh instance diverged"


# ---------------------------------------------------------------------------
# 5. Serialisation round-trip
# ---------------------------------------------------------------------------


@_SETTINGS
@given(legal_documents())
def test_to_dict_from_dict_round_trip(text: str) -> None:
    from lexichunk.models import LegalChunk

    for maximum, minimum in _chunkers():
        chunker = LegalChunker(
            jurisdiction="uk", max_chunk_size=maximum, min_chunk_size=minimum
        )
        for chunk in chunker.chunk(text):
            payload = chunk.to_dict()
            assert LegalChunk.from_dict(payload).to_dict() == payload


# ---------------------------------------------------------------------------
# 6. Cross-reference consistency
# ---------------------------------------------------------------------------


@_SETTINGS
@given(legal_documents())
def test_resolved_targets_are_in_range(text: str) -> None:
    for maximum, minimum in _chunkers():
        chunker = LegalChunker(
            jurisdiction="uk", max_chunk_size=maximum, min_chunk_size=minimum
        )
        chunks = chunker.chunk(text)
        for chunk in chunks:
            assert chunk.cross_ref_resolved <= chunk.cross_ref_total
            for reference in chunk.cross_references:
                if reference.target_chunk_index is not None:
                    assert 0 <= reference.target_chunk_index < len(chunks)


# ---------------------------------------------------------------------------
# 7. No over-merge across a top-level clause boundary
# ---------------------------------------------------------------------------


@_SETTINGS
@given(legal_documents())
def test_no_chunk_spans_two_top_level_clauses(text: str) -> None:
    for maximum, minimum in _chunkers():
        chunker = LegalChunker(
            jurisdiction="uk", max_chunk_size=maximum, min_chunk_size=minimum
        )
        _, metrics = chunker.chunk_with_metrics(text)
        assert metrics.chunks_spanning_multiple_top_level_clauses == 0, (
            f"[{maximum}/{minimum}] a chunk merged across a top-level boundary"
        )


# ---------------------------------------------------------------------------
# 8. chunk_documents agrees with chunk on the same structure
# ---------------------------------------------------------------------------


@_SETTINGS
@given(legal_documents())
def test_chunk_documents_reproduces_chunk(text: str) -> None:
    from lexichunk.parsers.structure import StructureParser

    sanitised = LegalChunker.sanitize(text)
    for maximum, minimum in _chunkers():
        chunker = LegalChunker(
            jurisdiction="uk", max_chunk_size=maximum, min_chunk_size=minimum
        )
        direct = chunker.chunk(sanitised)
        clauses = StructureParser("uk").parse(sanitised)
        if not clauses:
            continue
        via_documents = chunker.chunk_documents(clauses)
        assert [c.to_dict() for c in direct] == [
            c.to_dict() for c in via_documents
        ], f"[{maximum}/{minimum}] chunk_documents diverged from chunk"


# ---------------------------------------------------------------------------
# 9. The profile itself
# ---------------------------------------------------------------------------


def test_generation_is_deterministic() -> None:
    """Guard the guard.

    Everything above is only worth running if it draws the same documents
    every time. If the profile in ``tests/conftest.py`` stops being loaded —
    renamed, or shadowed by a `hypothesis` section in a config file — these
    tests keep passing while quietly becoming a lottery, so the property
    that makes them meaningful is asserted directly.
    """
    from hypothesis import settings

    assert settings.default.derandomize is True
    assert settings.default.database is None
