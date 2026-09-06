"""Polish-pass regression tests (G6).

One focused class per behaviour introduced by the polish pass:

* merged sub-clause identifiers reach cross-reference resolution;
* split parts of an oversized clause keep the original identifier;
* descendants of a Schedule/Exhibit container are ``SCHEDULES``;
* an untitled ``Article``/``Chapter`` heading adopts the next line as title;
* a heading-only group is absorbed by its first child;
* commercial clause types (services, insurance, audit, non-solicitation).
"""

from __future__ import annotations

import pathlib

import pytest

from lexichunk import LegalChunker
from lexichunk.models import ClauseType, DocumentSection
from lexichunk.parsers.structure import ParsedClause
from lexichunk.strategies.clause_aware import ClauseAwareChunker

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def uk_chunks() -> list:
    return LegalChunker(jurisdiction="uk", doc_type="contract").chunk(
        _fixture("uk_service_agreement")
    )


@pytest.fixture(scope="module")
def us_chunks() -> list:
    return LegalChunker(jurisdiction="us", doc_type="contract").chunk(
        _fixture("us_msa")
    )


@pytest.fixture(scope="module")
def eu_chunks() -> list:
    return LegalChunker(jurisdiction="eu", doc_type="contract").chunk(
        _fixture("eu_gdpr_excerpt")
    )


def _ref(chunks: list, chunk_index: int, identifier: str):
    """Return the cross-reference to *identifier* raised by *chunk_index*."""
    for ref in chunks[chunk_index].cross_references:
        if ref.target_identifier == identifier:
            return ref
    raise AssertionError(
        f"chunk {chunk_index} has no reference to {identifier!r}: "
        f"{[r.target_identifier for r in chunks[chunk_index].cross_references]}"
    )


def _is_own_heading_line(
    line: str, identifier: str, title: str | None
) -> bool:
    """Whether *line* is nothing but this chunk's own heading."""
    stripped = line.strip()
    folded_title = (title or "").strip().casefold()
    if not stripped.casefold().startswith(identifier.casefold()):
        return bool(folded_title) and stripped.casefold() == folded_title
    remainder = stripped[len(identifier):].strip(" .:\t-–—")
    return not remainder or remainder.casefold() == folded_title


def _find(chunks: list, identifier: str) -> int:
    for chunk in chunks:
        if chunk.hierarchy.identifier == identifier:
            return chunk.index
    raise AssertionError(f"no chunk with identifier {identifier!r}")


# ---------------------------------------------------------------------------
# 1. Merged identifiers reach resolution
# ---------------------------------------------------------------------------


class TestMergedIdentifiersResolve:
    def test_absorbed_sub_clause_resolves_to_its_container_chunk(
        self, uk_chunks: list
    ) -> None:
        """``clause 2.7`` was merged into the 2.6 chunk; it must resolve there."""
        source = next(
            c for c in uk_chunks
            if any(r.target_identifier == "2.7" for r in c.cross_references)
        )
        ref = _ref(uk_chunks, source.index, "2.7")
        assert ref.target_chunk_index is not None
        target = uk_chunks[ref.target_chunk_index]
        assert "2.7" in target.content

    def test_pinpoint_into_absorbed_sub_clause_resolves(
        self, uk_chunks: list
    ) -> None:
        """``clause 3.4(b)`` resolves to the chunk that absorbed ``3.4``."""
        source = next(
            c for c in uk_chunks
            if any(r.target_identifier == "3.4(b)" for r in c.cross_references)
        )
        ref = _ref(uk_chunks, source.index, "3.4(b)")
        assert ref.target_chunk_index is not None
        assert "3.4" in uk_chunks[ref.target_chunk_index].content

    def test_a_chunk_is_never_ambiguous_with_itself(self) -> None:
        """A merged chunk registers its own identifier only once.

        Regression: the absorbed-identifier list starts with the dominant
        clause's own identifier, so a naive registration listed the same chunk
        twice and every merged chunk became "ambiguous" with itself.
        """
        text = (
            "1. Services\n\n"
            "1.1 The Supplier shall provide the Services.\n\n"
            "2. Payment\n\n"
            "Fees are payable under clause 1 within 30 days of invoice.\n"
        )
        chunks = LegalChunker(jurisdiction="uk").chunk(text)
        ref = _ref(chunks, _find(chunks, "2"), "1")
        assert ref.target_chunk_index is not None
        assert chunks[ref.target_chunk_index].hierarchy_path.startswith(
            "1 — Services"
        )


# ---------------------------------------------------------------------------
# 2. Split parts keep the clause identifier
# ---------------------------------------------------------------------------


class TestSplitPartsKeepTheIdentifier:
    SPLIT_TEXT = (
        "1. Definitions and interpretation\n\n"
        "1.1 In this Agreement, the following terms have the meanings set "
        "out below. "
        + " ".join(
            f'"Term {i}" means the {i}th defined concept used in this '
            f"Agreement and nowhere else."
            for i in range(60)
        )
        + "\n"
    )

    def _split_chunks(self) -> list:
        return LegalChunker(
            jurisdiction="uk", max_chunk_size=120, min_chunk_size=0
        ).chunk(self.SPLIT_TEXT)

    def test_no_part_suffix_anywhere(self, uk_chunks: list) -> None:
        for chunk in [*uk_chunks, *self._split_chunks()]:
            assert "__part" not in chunk.hierarchy.identifier
            assert "__part" not in chunk.hierarchy_path
            assert "__part" not in chunk.original_header
            assert "__part" not in chunk.context_header

    def test_every_part_reads_as_the_original_clause(self) -> None:
        chunks = self._split_chunks()
        parts = [c for c in chunks if c.hierarchy.identifier == "1.1"]
        assert len(parts) > 1, "expected clause 1.1 to be split"
        paths = {c.hierarchy_path for c in parts}
        assert len(paths) == 1, paths
        assert paths.pop().startswith(
            "1 — Definitions and interpretation > 1.1"
        )

    def test_reference_resolves_to_the_first_part(self) -> None:
        text = (
            self.SPLIT_TEXT
            + "\n2. Interpretation\n\n"
            "Defined terms have the meanings given in clause 1.1.\n"
        )
        chunks = LegalChunker(
            jurisdiction="uk", max_chunk_size=120, min_chunk_size=0
        ).chunk(text)
        parts = [
            c.index for c in chunks if c.hierarchy.identifier == "1.1"
        ]
        assert len(parts) > 1
        source = next(
            c for c in chunks
            if any(r.target_identifier == "1.1" for r in c.cross_references)
            and c.hierarchy.identifier != "1.1"
        )
        ref = _ref(chunks, source.index, "1.1")
        assert ref.target_chunk_index == min(parts)


# ---------------------------------------------------------------------------
# 3. Container descendants inherit the container's document section
# ---------------------------------------------------------------------------


class TestContainerSectionInheritance:
    def test_schedule_descendants_are_schedules(self, uk_chunks: list) -> None:
        inside = [
            c for c in uk_chunks
            if c.hierarchy_path.upper().startswith("SCHEDULE ")
        ]
        assert inside, "no chunks inside a Schedule"
        assert all(
            c.document_section is DocumentSection.SCHEDULES for c in inside
        ), [(c.index, c.document_section.value) for c in inside]

    def test_main_body_is_not_dragged_into_schedules(
        self, uk_chunks: list
    ) -> None:
        outside = [
            c for c in uk_chunks
            if not c.hierarchy_path.upper().startswith("SCHEDULE ")
        ]
        assert all(
            c.document_section is not DocumentSection.SCHEDULES
            for c in outside
        )

    def test_eu_chapter_descendants_stay_operative(
        self, eu_chunks: list
    ) -> None:
        """EU maps Chapter to OPERATIVE, so nothing inherits SCHEDULES."""
        assert all(
            c.document_section is not DocumentSection.SCHEDULES
            for c in eu_chunks
        )

    def test_main_body_reference_prefers_the_main_body_clause(
        self, uk_chunks: list
    ) -> None:
        """``clause 3`` from clause 6.4 must not stay stuck on the Schedules.

        Both Schedules also have a paragraph 3; the section split is what
        breaks the tie.
        """
        source = next(
            c for c in uk_chunks
            if c.hierarchy_path.startswith("6 — Term and termination > 6.4")
        )
        ref = _ref(uk_chunks, source.index, "3")
        assert ref.target_chunk_index is not None
        target = uk_chunks[ref.target_chunk_index]
        assert target.hierarchy_path.startswith("3 — Fees and payment")
        assert target.document_section is DocumentSection.OPERATIVE


# ---------------------------------------------------------------------------
# 4. Two-line container headings
# ---------------------------------------------------------------------------


class TestAdoptedHeadingTitles:
    def test_us_article_adopts_the_next_line(self, us_chunks: list) -> None:
        paths = {c.hierarchy_path.split(" > ")[0] for c in us_chunks}
        assert "Article I — Definitions" in paths
        assert "Article VII — Indemnification" in paths

    def test_allcaps_title_is_recased(self) -> None:
        text = "ARTICLE I\nDEFINITIONS AND INTERPRETATION\n\nThe following terms apply.\n"
        chunks = LegalChunker(jurisdiction="us", min_chunk_size=0).chunk(text)
        assert chunks[0].hierarchy.title == "Definitions and Interpretation"

    def test_mixed_case_title_is_kept_verbatim(self) -> None:
        text = "Article 1\nSubject matter and scope\n\nThis Regulation applies.\n"
        chunks = LegalChunker(jurisdiction="eu", min_chunk_size=0).chunk(text)
        assert chunks[0].hierarchy.title == "Subject matter and scope"

    def test_the_adopted_line_stays_in_the_body(self) -> None:
        text = "ARTICLE I\nDEFINITIONS\n\nThe following terms apply here.\n"
        chunks = LegalChunker(jurisdiction="us", min_chunk_size=0).chunk(text)
        assert chunks[0].char_start == 0
        assert "DEFINITIONS" in chunks[0].content
        assert text[chunks[0].char_start:chunks[0].char_end] in chunks[0].content

    @pytest.mark.parametrize(
        "second_line",
        [
            "The Provider shall deliver the services described in the "
            "statement of work agreed between the parties.",
            "This Article sets out the definitions used throughout.",
            "Definitions:",
        ],
    )
    def test_prose_is_not_adopted_as_a_title(self, second_line: str) -> None:
        text = f"ARTICLE I\n{second_line}\n\nMore body text follows here.\n"
        chunks = LegalChunker(jurisdiction="us", min_chunk_size=0).chunk(text)
        assert chunks[0].hierarchy.title is None

    def test_a_real_heading_below_is_not_adopted(self) -> None:
        text = (
            "ARTICLE I\n"
            "Section 1.01  Definitions. The following terms apply here.\n"
        )
        chunks = LegalChunker(jurisdiction="us", min_chunk_size=0).chunk(text)
        article = next(
            c for c in chunks if c.hierarchy_path.startswith("Article I")
        )
        assert article.hierarchy_path.split(" > ")[0] == "Article I"


# ---------------------------------------------------------------------------
# 5. Heading-only chunks
# ---------------------------------------------------------------------------


class TestHeadingOnlyAbsorption:
    def test_no_chunk_is_only_its_own_heading(
        self, uk_chunks: list, us_chunks: list, eu_chunks: list
    ) -> None:
        for chunks in (uk_chunks, us_chunks, eu_chunks):
            for chunk in chunks:
                body = chunk.content[
                    len(chunk.content) - (chunk.char_end - chunk.char_start):
                ]
                lines = [ln for ln in body.splitlines() if ln.strip()]
                assert any(
                    not _is_own_heading_line(
                        line,
                        chunk.hierarchy.identifier,
                        chunk.hierarchy.title,
                    )
                    for line in lines
                ), f"chunk {chunk.index} is heading-only: {body!r}"

    @pytest.mark.parametrize(
        "path",
        [
            "SCHEDULE 1 — SERVICES DESCRIPTION",
            "SCHEDULE 2 — FEES AND PAYMENT TERMS",
            "Article I — Definitions",
            "Chapter I — General Provisions",
            "Chapter II — Principles",
        ],
    )
    def test_container_heading_is_not_a_chunk_of_its_own(
        self, uk_chunks: list, us_chunks: list, eu_chunks: list, path: str
    ) -> None:
        every = [*uk_chunks, *us_chunks, *eu_chunks]
        assert any(c.hierarchy_path.startswith(path) for c in every), (
            f"{path!r} disappeared from the document entirely"
        )
        assert not any(c.hierarchy_path == path for c in every), (
            f"{path!r} is still a chunk that holds nothing but its heading"
        )

    def test_schedule_heading_is_absorbed_by_its_first_child(
        self, uk_chunks: list
    ) -> None:
        chunk = next(
            c for c in uk_chunks
            if c.hierarchy_path.startswith("SCHEDULE 1")
        )
        assert chunk.hierarchy_path == (
            "SCHEDULE 1 — SERVICES DESCRIPTION > 1 — Overview of Services > "
            "1.1 — The Supplier shall provide the following categories of "
            "services to the Client during"
        )
        assert chunk.content.startswith("SCHEDULE 1 — SERVICES DESCRIPTION")
        # The absorbed ancestor headers are in the body, never prepended twice.
        assert chunk.content.count("SCHEDULE 1 — SERVICES DESCRIPTION") == 1
        assert chunk.content.count("1.   Overview of Services") == 1

    def test_absorbed_heading_still_resolves(self, uk_chunks: list) -> None:
        """``Schedule 1`` resolves to the chunk that swallowed the heading."""
        source = next(
            c for c in uk_chunks
            if any(
                r.target_kind == "schedule" and r.target_identifier == "1"
                for r in c.cross_references
            )
        )
        ref = next(
            r for r in source.cross_references
            if r.target_kind == "schedule" and r.target_identifier == "1"
        )
        assert ref.target_chunk_index is not None
        target = uk_chunks[ref.target_chunk_index]
        assert target.hierarchy_path.startswith("SCHEDULE 1")

    def test_article_heading_is_labelled_by_its_only_child(
        self, us_chunks: list
    ) -> None:
        chunk = us_chunks[2]
        assert chunk.hierarchy_path.startswith(
            "Article I — Definitions > Section 1.01 — "
        )
        assert chunk.content.startswith("ARTICLE I")

    def test_a_parent_with_several_children_keeps_its_own_label(
        self, uk_chunks: list
    ) -> None:
        """``3`` holding ``3.1``–``3.4`` is described by ``3``, not by ``3.1``."""
        chunk = next(
            c for c in uk_chunks if c.hierarchy_path == "3 — Fees and payment"
        )
        assert "3.1" in chunk.content and "3.4" in chunk.content

    @staticmethod
    def _schedule_pair(child_text: str) -> tuple[ParsedClause, ParsedClause]:
        heading = ParsedClause(
            identifier="SCHEDULE 1",
            title="Services",
            content="SCHEDULE 1 — Services\n\n",
            level=-1,
            parent_identifier=None,
            document_section=DocumentSection.SCHEDULES,
            char_start=0,
            char_end=23,
            uid="0",
            parent_uid=None,
        )
        child = ParsedClause(
            identifier="1.1",
            title=None,
            content=child_text,
            level=1,
            parent_identifier="SCHEDULE 1",
            document_section=DocumentSection.SCHEDULES,
            char_start=23,
            char_end=23 + len(child_text),
            uid="1",
            parent_uid="0",
        )
        return heading, child

    def test_heading_stays_when_the_child_will_not_fit(self) -> None:
        """A fold that would break ``max_chunk_size`` is refused."""
        chunker = ClauseAwareChunker(jurisdiction="uk", max_chunk_size=40)
        heading, child = self._schedule_pair("1.1 " + "word " * 60)
        groups = chunker._absorb_heading_only(
            [[heading], [child]], {c.uid: c for c in (heading, child)}
        )
        assert [[c.identifier for c in g] for g in groups] == [
            ["SCHEDULE 1"],
            ["1.1"],
        ]

    def test_heading_is_folded_when_the_child_fits(self) -> None:
        chunker = ClauseAwareChunker(jurisdiction="uk", max_chunk_size=512)
        heading, child = self._schedule_pair(
            "1.1 The Supplier shall provide the Services.\n"
        )
        groups = chunker._absorb_heading_only(
            [[heading], [child]], {c.uid: c for c in (heading, child)}
        )
        assert [[c.identifier for c in g] for g in groups] == [
            ["SCHEDULE 1", "1.1"]
        ]


# ---------------------------------------------------------------------------
# 6. Commercial clause types
# ---------------------------------------------------------------------------


class TestCommercialClauseTypes:
    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (
                "The Supplier shall perform the Services in accordance with "
                "each statement of work and shall meet the service levels "
                "for all deliverables.",
                ClauseType.SERVICES,
            ),
            (
                "The Supplier shall maintain professional indemnity insurance "
                "and public liability insurance with a reputable insurer.",
                ClauseType.INSURANCE,
            ),
            (
                "The Client shall have the right to audit and inspect the "
                "records and books and records of the Supplier.",
                ClauseType.AUDIT,
            ),
            (
                "Neither party shall solicit or induce any employee of the "
                "other party, nor entice away any such employee.",
                ClauseType.NON_SOLICITATION,
            ),
        ],
    )
    def test_new_types_are_classified(
        self, body: str, expected: ClauseType
    ) -> None:
        text = f"1. Obligations\n\n{body}\n"
        chunks = LegalChunker(jurisdiction="uk", min_chunk_size=1).chunk(text)
        assert chunks[0].clause_type is expected

    def test_uk_services_clause_and_its_children_are_services(
        self, uk_chunks: list
    ) -> None:
        """Clause 2 and the (a)–(e) list under 2.5 used to be UNKNOWN."""
        heading = next(
            c for c in uk_chunks if c.hierarchy_path == "2 — Services"
        )
        assert heading.clause_type is ClauseType.SERVICES
        children = next(
            c for c in uk_chunks
            if c.hierarchy_path.startswith("2 — Services > 2.5")
        )
        assert children.clause_type is ClauseType.SERVICES
        assert "(a)" in children.content

    def test_secondary_type_semantics_unchanged(self) -> None:
        """A second-place type is still reported as ``secondary_clause_type``."""
        text = (
            "1. Services and insurance\n\n"
            "The Supplier shall perform the Services and provide the "
            "deliverables under each statement of work, and shall maintain "
            "professional indemnity insurance with a reputable insurer.\n"
        )
        chunks = LegalChunker(jurisdiction="uk", min_chunk_size=1).chunk(text)
        chunk = chunks[0]
        assert chunk.secondary_clause_type is not None
        assert chunk.secondary_clause_type is not chunk.clause_type
