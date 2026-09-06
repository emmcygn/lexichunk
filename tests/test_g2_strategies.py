"""Work package G2 — chunk merge / split / offset correctness.

Covers the defects catalogued as D3 (identifier-collision clause map), D4/D22
(positional merging and metadata taken from ``group[0]``), D5 (oversized clause
never split for want of sentence punctuation), D12/D13 (``content`` and offsets
describing two different strings, parent spans swallowing descendants) and D24
(cross-reference detection running on prepended ancestor headers), plus the
fallback chunker's under-run / over-run gaps.

Inputs are the repro documents from the engineering synthesis review.
"""

from __future__ import annotations

import logging

import pytest

from lexichunk import LegalChunker
from lexichunk.models import Jurisdiction, LegalChunk
from lexichunk.parsers.structure import StructureParser
from lexichunk.strategies.clause_aware import ClauseAwareChunker
from lexichunk.strategies.fallback import FallbackChunker

# ---------------------------------------------------------------------------
# Repro documents
# ---------------------------------------------------------------------------

# D3: a real "1. Definitions / 1.1" at the top and a "SCHEDULE 1 / 1 Services
# Description / 1.1" at the bottom — identical identifiers in two sections.
COLLIDING_IDENTIFIERS = (
    "1. Definitions\n"
    "1.1 In this Agreement, the following terms apply throughout the document.\n"
    "\n"
    "SCHEDULE 1\n"
    "1 Services Description\n"
    "1.1 The Supplier shall provide the services described in this Schedule.\n"
)

# D4: three independent top-level clauses, one with a sub-clause.  With
# min_chunk_size above every clause's size, positional merging used to fuse all
# of them into a single chunk labelled "1 — Confidentiality".
THREE_TOP_LEVEL_CLAUSES = (
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

# D5: ~5 KB of clause text whose only internal separators are semicolons —
# not one '.', '!' or '?'.
SEMICOLON_ONLY_CLAUSE = "1. Definitions\n" + (
    "the first term; the second term; the third term; the fourth term; "
    "the fifth term; "
) * 100

# D5, harder: a single unpunctuated run with no semicolons either.
UNPUNCTUATED_CLAUSE = "1. Definitions\n" + ("word " * 4000)


def _chunk(text: str, **kwargs: object) -> list[LegalChunk]:
    params: dict[str, object] = {"jurisdiction": "uk"}
    params.update(kwargs)
    return LegalChunker(**params).chunk(text)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. uid-keyed clause map (D3)
# ---------------------------------------------------------------------------


class TestUidKeyedClauseMap:
    def test_colliding_identifier_does_not_leak_foreign_headers(self) -> None:
        """A Schedule's "1"/"1.1" must not re-parent the Definitions "1.1"."""
        chunks = _chunk(COLLIDING_IDENTIFIERS, min_chunk_size=0)
        definitions = [
            c
            for c in chunks
            if c.hierarchy.identifier == "1.1" and c.char_start < 100
        ]
        assert definitions, "expected a chunk for the Definitions sub-clause 1.1"
        top = definitions[0]
        assert "SCHEDULE" not in top.content.upper(), (
            "another section's header was prepended into content: "
            f"{top.content!r}"
        )
        assert not top.hierarchy_path.upper().startswith("SCHEDULE"), (
            f"hierarchy_path escaped into the Schedule: {top.hierarchy_path!r}"
        )
        assert top.hierarchy_path.startswith("1 — Definitions"), top.hierarchy_path

    def test_schedule_subclause_keeps_its_own_ancestry(self) -> None:
        """The Schedule's own 1.1 still resolves through the Schedule."""
        chunks = _chunk(COLLIDING_IDENTIFIERS, min_chunk_size=0)
        schedule = [
            c
            for c in chunks
            if c.hierarchy.identifier == "1.1" and c.char_start > 100
        ]
        assert schedule, "expected a chunk for the Schedule sub-clause 1.1"
        assert schedule[0].hierarchy_path.startswith("SCHEDULE 1")

    def test_clause_map_is_keyed_on_uid(self) -> None:
        """Every parsed clause survives the map — no last-write-wins loss."""
        clauses = StructureParser(Jurisdiction.UK).parse(COLLIDING_IDENTIFIERS)
        assert len({c.uid for c in clauses}) == len(clauses)
        # ...whereas the identifiers genuinely collide.
        assert len({c.identifier for c in clauses}) < len(clauses)


# ---------------------------------------------------------------------------
# 2. Hierarchy-aware merge (D4, D22)
# ---------------------------------------------------------------------------


class TestHierarchyAwareMerge:
    def test_top_level_clauses_are_never_fused(self) -> None:
        chunks = _chunk(THREE_TOP_LEVEL_CLAUSES, max_chunk_size=512, min_chunk_size=64)
        assert len(chunks) >= 3, [c.hierarchy.identifier for c in chunks]

        confidentiality = [
            c for c in chunks if c.hierarchy.identifier == "1"
        ]
        assert confidentiality, "clause 1 chunk missing"
        assert "Termination" not in confidentiality[0].content, (
            "clause 2 Termination was swallowed by the Confidentiality chunk"
        )
        assert "Governing Law" not in confidentiality[0].content

    def test_every_top_level_clause_is_represented(self) -> None:
        chunks = _chunk(THREE_TOP_LEVEL_CLAUSES, max_chunk_size=512, min_chunk_size=64)
        identifiers = {c.hierarchy.identifier for c in chunks}
        assert {"1", "2", "3"} <= identifiers, identifiers

    def test_short_chunks_are_emitted_rather_than_mislabelled(self) -> None:
        """min_chunk_size is a preference; hierarchy is a fact."""
        chunks = _chunk(THREE_TOP_LEVEL_CLAUSES, max_chunk_size=512, min_chunk_size=64)
        assert any(c.token_count < 64 for c in chunks), (
            "expected at least one honest short chunk"
        )

    def test_child_merges_into_its_own_parent(self) -> None:
        """Case (b): 1.1 folds into 1, and 1 stays the dominant clause."""
        chunks = _chunk(THREE_TOP_LEVEL_CLAUSES, max_chunk_size=512, min_chunk_size=64)
        parent = [c for c in chunks if c.hierarchy.identifier == "1"][0]
        assert "1.1 Scope" in parent.content
        assert parent.hierarchy.level == 0
        assert parent.original_header == "1 Confidentiality"

    def test_last_merged_identifiers_exposes_absorbed_children(self) -> None:
        clauses = StructureParser(Jurisdiction.UK).parse(THREE_TOP_LEVEL_CLAUSES)
        chunker = ClauseAwareChunker(
            jurisdiction=Jurisdiction.UK, max_chunk_size=512, min_chunk_size=64
        )
        chunks = chunker.chunk(clauses, THREE_TOP_LEVEL_CLAUSES)
        merged = chunker.last_merged_identifiers
        assert merged, "expected at least one merged chunk to be recorded"
        for index, identifiers in merged.items():
            assert 0 <= index < len(chunks)
            # The dominant clause's own identifier leads the list.
            assert identifiers[0] == chunks[index].hierarchy.identifier
            assert len(identifiers) > 1
        # 4.1-style children stay discoverable for cross-reference resolution.
        assert any("1.1" in ids for ids in merged.values()), merged

    def test_last_merged_identifiers_is_reset_per_call(self) -> None:
        chunker = ClauseAwareChunker(
            jurisdiction=Jurisdiction.UK, max_chunk_size=512, min_chunk_size=64
        )
        clauses = StructureParser(Jurisdiction.UK).parse(THREE_TOP_LEVEL_CLAUSES)
        chunker.chunk(clauses, THREE_TOP_LEVEL_CLAUSES)
        first = dict(chunker.last_merged_identifiers)
        chunker.chunk(clauses, THREE_TOP_LEVEL_CLAUSES)
        assert chunker.last_merged_identifiers == first
        # A document with nothing to merge clears the mapping.
        chunker.chunk(
            StructureParser(Jurisdiction.UK).parse(THREE_TOP_LEVEL_CLAUSES),
            THREE_TOP_LEVEL_CLAUSES,
        )
        assert isinstance(chunker.last_merged_identifiers, dict)

    def test_merged_group_never_exceeds_max(self) -> None:
        chunks = _chunk(THREE_TOP_LEVEL_CLAUSES, max_chunk_size=30, min_chunk_size=25)
        for chunk in chunks:
            assert chunk.token_count <= 30, (
                f"chunk {chunk.index} token_count={chunk.token_count}"
            )


# ---------------------------------------------------------------------------
# 3. Hard size cap with the cascading splitter (D5)
# ---------------------------------------------------------------------------


class TestHardSizeCap:
    def test_semicolon_only_clause_is_split(self) -> None:
        chunks = _chunk(SEMICOLON_ONLY_CLAUSE, max_chunk_size=512, min_chunk_size=64)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.token_count <= 512, (
                f"chunk {chunk.index} token_count={chunk.token_count} > 512"
            )

    def test_unpunctuated_clause_is_split_by_word_window(self) -> None:
        chunks = _chunk(UNPUNCTUATED_CLAUSE, max_chunk_size=100, min_chunk_size=0)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.token_count <= 100

    def test_split_pieces_tile_the_clause_without_gaps(self) -> None:
        chunks = _chunk(SEMICOLON_ONLY_CLAUSE, max_chunk_size=512, min_chunk_size=0)
        parts = [c for c in chunks if "__part" in c.hierarchy.identifier]
        assert len(parts) > 1
        for a, b in zip(parts, parts[1:]):
            assert a.char_end == b.char_start, (
                f"gap/overlap between {a.hierarchy.identifier} and "
                f"{b.hierarchy.identifier}"
            )

    def test_indivisible_run_is_emitted_with_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        text = "1. Definitions\n" + ("x" * 3000)
        with caplog.at_level(logging.WARNING, logger="lexichunk.strategies.clause_aware"):
            chunks = _chunk(text, max_chunk_size=100, min_chunk_size=0)
        assert chunks
        assert any(
            "Indivisible text run" in record.getMessage()
            for record in caplog.records
        ), [record.getMessage() for record in caplog.records]

    def test_extra_abbreviations_apply_on_the_clause_aware_path(self) -> None:
        """``extra_abbreviations`` used to be wired only into the fallback."""
        body = " ".join(
            f"The parties agree on point {i} per Blah. Corp and its affiliates."
            for i in range(120)
        )
        text = "1. Definitions\n" + body
        without = _chunk(text, max_chunk_size=60, min_chunk_size=0)
        with_extra = _chunk(
            text,
            max_chunk_size=60,
            min_chunk_size=0,
            extra_abbreviations=["Blah"],
        )
        assert [c.content for c in without] != [c.content for c in with_extra], (
            "extra_abbreviations had no effect on the clause-aware path"
        )

    def test_hard_cap_holds_with_a_long_ancestor_header(self) -> None:
        """The prepended header counts against the budget, not on top of it."""
        text = (
            "1. A Very Long Top Level Heading That Will Be Prepended To Every "
            "Descendant Chunk Of This Section Indeed\n"
            "1.1 Scope\n"
            + " ".join(f"Sentence {i} of the sub-clause." for i in range(200))
            + "\n"
        )
        chunks = _chunk(text, max_chunk_size=60, min_chunk_size=0)
        for chunk in chunks:
            assert chunk.token_count <= 60, (
                f"chunk {chunk.index} token_count={chunk.token_count} > 60"
            )


# ---------------------------------------------------------------------------
# 4. Fallback chunker under-run / over-run
# ---------------------------------------------------------------------------


class TestFallbackWindows:
    def test_no_window_below_min_when_a_merge_is_possible(self) -> None:
        text = " ".join(f"Short sentence {i} here." for i in range(60))
        chunker = FallbackChunker(
            jurisdiction=Jurisdiction.UK, max_chunk_size=40, min_chunk_size=20
        )
        chunks = chunker.chunk(text)
        assert len(chunks) > 1
        for chunk in chunks[:-1]:
            assert chunk.token_count >= 20, (
                f"window {chunk.index} token_count={chunk.token_count} < min"
            )

    def test_merged_windows_respect_max(self) -> None:
        text = " ".join(f"Short sentence {i} here." for i in range(60))
        chunker = FallbackChunker(
            jurisdiction=Jurisdiction.UK, max_chunk_size=40, min_chunk_size=39
        )
        for chunk in chunker.chunk(text):
            assert chunk.token_count <= 40, (
                f"window {chunk.index} token_count={chunk.token_count} > max"
            )

    def test_fallback_content_is_an_exact_slice(self) -> None:
        text = " ".join(f"Short sentence {i} here." for i in range(60))
        chunker = FallbackChunker(
            jurisdiction=Jurisdiction.UK, max_chunk_size=40, min_chunk_size=20
        )
        for chunk in chunker.chunk(text):
            assert chunk.content == text[chunk.char_start:chunk.char_end], (
                f"window {chunk.index} content is a reconstruction, not a slice"
            )


# ---------------------------------------------------------------------------
# 5. Offsets as the single truth (D12, D13)
# ---------------------------------------------------------------------------


_OFFSET_DOCS = {
    "colliding": COLLIDING_IDENTIFIERS,
    "three_clauses": THREE_TOP_LEVEL_CLAUSES,
    "semicolon": SEMICOLON_ONLY_CLAUSE,
}


class TestOffsetsAreTheTruth:
    @pytest.mark.parametrize("name", sorted(_OFFSET_DOCS))
    def test_content_ends_with_the_exact_span(self, name: str) -> None:
        text = _OFFSET_DOCS[name]
        chunks = _chunk(text, min_chunk_size=0)
        sanitised = LegalChunker._sanitize_input(text)
        for chunk in chunks:
            span = sanitised[chunk.char_start:chunk.char_end]
            assert chunk.content.endswith(span), (
                f"[{name}] chunk {chunk.index}: content is not "
                f"headers + exact span"
            )

    @pytest.mark.parametrize("name", sorted(_OFFSET_DOCS))
    def test_spans_are_monotonic_and_non_overlapping(self, name: str) -> None:
        chunks = _chunk(_OFFSET_DOCS[name], min_chunk_size=0)
        for a, b in zip(chunks, chunks[1:]):
            assert a.char_end <= b.char_start, (
                f"[{name}] chunk {a.index} (end={a.char_end}) overlaps "
                f"chunk {b.index} (start={b.char_start})"
            )

    def test_parent_span_stops_before_its_children(self) -> None:
        """A parent-only chunk must not claim its descendants' text (D13)."""
        text = (
            "1. Services\n"
            "The Supplier shall provide the Services described below in "
            "accordance with this Agreement.\n"
            "\n"
            "1.1 Standard\n"
            "The Services shall be provided with reasonable care and skill "
            "at all times during the term.\n"
            "\n"
            "1.2 Personnel\n"
            "The Supplier shall use suitably qualified personnel to perform "
            "the Services under this Agreement.\n"
        )
        chunks = _chunk(text, min_chunk_size=0)
        parent = [c for c in chunks if c.hierarchy.identifier == "1"][0]
        child = [c for c in chunks if c.hierarchy.identifier == "1.1"][0]
        assert parent.char_end <= child.char_start
        assert "1.1 Standard" not in parent.content

    def test_no_reconstructed_separators(self) -> None:
        """Merged bodies keep the source's own blank lines, not extra ones."""
        text = (
            "1. Interpretation\n"
            "(a) first item of the list\n"
            "(b) second item of the list\n"
            "(c) third item of the list\n"
        )
        sanitised = LegalChunker._sanitize_input(text)
        for chunk in _chunk(text, min_chunk_size=64):
            body = sanitised[chunk.char_start:chunk.char_end]
            assert chunk.content.endswith(body)
            assert "\n\n\n" not in chunk.content


# ---------------------------------------------------------------------------
# 6. Cross-reference detection on the raw body (D24)
# ---------------------------------------------------------------------------


class TestDetectionOnRawBody:
    def test_reference_in_an_ancestor_header_is_not_inherited(self) -> None:
        text = (
            "1. Services as set out in Schedule 2\n"
            "1.1 Standard\n"
            "The Services shall be provided with reasonable care and skill "
            "at all times during the term of this agreement.\n"
            "\n"
            "1.2 Personnel\n"
            "The Supplier shall use suitably qualified personnel to perform "
            "the Services throughout the term of this agreement.\n"
        )
        chunks = _chunk(text, min_chunk_size=0)
        child = [c for c in chunks if c.hierarchy.identifier == "1.1"][0]
        assert "Schedule 2" in child.content, (
            "precondition: the ancestor header is prepended into content"
        )
        assert all(
            "Schedule 2" not in ref.raw_text for ref in child.cross_references
        ), (
            "a reference living in the prepended ancestor header was "
            f"attributed to the child chunk: {child.cross_references}"
        )

    def test_reference_in_the_body_is_still_detected(self) -> None:
        text = (
            "1. Services\n"
            "1.1 Standard\n"
            "The Services shall be provided in accordance with Schedule 2 "
            "and with reasonable care and skill at all times.\n"
        )
        chunks = _chunk(text, min_chunk_size=0)
        child = [c for c in chunks if c.hierarchy.identifier == "1.1"][0]
        assert any("Schedule 2" in ref.raw_text for ref in child.cross_references), (
            child.cross_references
        )
