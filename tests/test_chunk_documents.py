"""``LegalChunker.chunk_documents()`` — chunking pre-parsed structure.

The strongest test here is the equivalence one: feeding
``StructureParser.parse(text)`` straight back through ``chunk_documents()``
must reproduce ``chunk(text)`` byte-for-byte on every fixture.  If that holds,
the reconstruction preserves every offset invariant the pipeline relies on,
and a caller writing an adapter is building against the same contract.
"""

from __future__ import annotations

import pytest

from lexichunk import LegalChunker
from lexichunk.exceptions import InputError
from lexichunk.models import DocumentSection, Section
from lexichunk.parsers.structure import ParsedClause, StructureParser

from ._snapshot_support import FIXTURE_CONFIGS, load_fixture, make_chunker

# ---------------------------------------------------------------------------
# Equivalence with the native path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
def test_parsed_clauses_reproduce_chunk_exactly(
    fixture_name: str, jurisdiction: str, doc_type: str
) -> None:
    text = LegalChunker.sanitize(load_fixture(fixture_name))
    chunker = make_chunker(jurisdiction, doc_type)
    direct = chunker.chunk(text)
    clauses = StructureParser(jurisdiction, doc_type=doc_type).parse(text)
    via_documents = chunker.chunk_documents(clauses)
    assert [c.to_dict() for c in direct] == [c.to_dict() for c in via_documents]


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
def test_metrics_flag_matches_chunk_with_metrics(
    fixture_name: str, jurisdiction: str, doc_type: str
) -> None:
    text = LegalChunker.sanitize(load_fixture(fixture_name))
    chunker = make_chunker(jurisdiction, doc_type)
    _, native = chunker.chunk_with_metrics(text)
    clauses = StructureParser(jurisdiction, doc_type=doc_type).parse(text)
    chunks, metrics = chunker.chunk_documents(clauses, return_metrics=True)
    assert metrics.chunk_count == native.chunk_count == len(chunks)
    assert metrics.clause_count == native.clause_count
    assert metrics.top_level_clause_count == native.top_level_clause_count
    assert metrics.chunks_spanning_multiple_top_level_clauses == 0
    # No heading detection ran, so nothing could have been rejected.
    assert metrics.heading_candidates_rejected == 0


# ---------------------------------------------------------------------------
# The Section path
# ---------------------------------------------------------------------------

_SECTIONS = [
    Section(
        identifier="1",
        title="Definitions",
        text='In this agreement "Services" means the services described in '
        "Schedule 1.",
        level=0,
    ),
    Section(
        identifier="1.1",
        title="Interpretation",
        text="Headings are for convenience only and do not affect construction.",
        level=1,
    ),
    Section(
        identifier="2",
        title="Payment Terms",
        text="The Customer shall pay each invoice within thirty days of receipt, "
        "as further described in clause 1.1.",
        level=0,
    ),
    Section(
        identifier="Schedule 1",
        title="Services Description",
        text="The Supplier shall provide managed hosting and support services.",
        level=-1,
    ),
]


def _chunk_sections(**kwargs: object) -> list:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0, **kwargs)  # type: ignore[arg-type]
    return chunker.chunk_documents(_SECTIONS)


def test_sections_produce_one_chunk_each_when_nothing_merges() -> None:
    chunks = _chunk_sections()
    identifiers = [c.hierarchy.identifier for c in chunks]
    assert identifiers == ["1", "1.1", "2", "Schedule 1"]


def test_hierarchy_is_inferred_from_levels() -> None:
    chunks = _chunk_sections()
    by_identifier = {c.hierarchy.identifier: c for c in chunks}
    assert by_identifier["1.1"].hierarchy.parent == "1"
    assert by_identifier["1"].hierarchy.parent is None
    assert by_identifier["1.1"].hierarchy_path.startswith("1 — Definitions > 1.1")


def test_document_sections_are_classified_like_a_parsed_document() -> None:
    chunks = _chunk_sections()
    by_identifier = {c.hierarchy.identifier: c for c in chunks}
    assert by_identifier["1"].document_section is DocumentSection.DEFINITIONS
    # Inherited: a clause under a Definitions heading is part of them.
    assert by_identifier["1.1"].document_section is DocumentSection.DEFINITIONS
    assert by_identifier["2"].document_section is DocumentSection.OPERATIVE
    assert by_identifier["Schedule 1"].document_section is DocumentSection.SCHEDULES


def test_bodies_are_exact_slices_and_tile_without_overlap() -> None:
    """The invariant every downstream guarantee rests on."""
    chunks = _chunk_sections()
    previous_end = 0
    for chunk in chunks:
        assert chunk.char_start >= previous_end
        previous_end = chunk.char_end
        assert chunk.content.strip()


def test_defined_terms_and_cross_references_still_work() -> None:
    chunks = _chunk_sections()
    assert any("Services" in c.defined_terms_used for c in chunks)
    references = [ref for c in chunks for ref in c.cross_references]
    assert any(ref.target_identifier == "1.1" for ref in references)
    assert any(ref.target_chunk_index is not None for ref in references)


def test_explicit_parent_identifier_wins_over_levels() -> None:
    sections = [
        Section(identifier="A", title="Alpha", text="First body text.", level=0),
        Section(identifier="B", title="Beta", text="Second body text.", level=0),
        Section(
            identifier="C",
            title="Gamma",
            text="Third body text.",
            level=0,
            parent_identifier="A",
        ),
    ]
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    chunks = chunker.chunk_documents(sections)
    gamma = next(c for c in chunks if c.hierarchy.identifier == "C")
    assert gamma.hierarchy.parent == "A"
    assert gamma.hierarchy_path.startswith("A — Alpha > C")


def test_a_section_without_an_identifier_uses_its_title() -> None:
    sections = [
        Section(
            identifier="",
            title="CONFIDENTIALITY",
            text="Each party shall keep the other's information confidential.",
            level=0,
        )
    ]
    chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk_documents(
        sections
    )
    assert chunks[0].hierarchy.identifier == "CONFIDENTIALITY"


def test_a_section_with_empty_body_still_produces_structure() -> None:
    sections = [
        Section(identifier="Article I", title="Definitions", text="", level=0),
        Section(
            identifier="1.01",
            title=None,
            text="Defined terms have the meanings given in this Article.",
            level=1,
        ),
    ]
    chunks = LegalChunker(jurisdiction="us", min_chunk_size=0).chunk_documents(
        sections
    )
    assert chunks
    assert "Article I" in chunks[0].hierarchy_path


def test_document_id_is_applied() -> None:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    chunks = chunker.chunk_documents(_SECTIONS, document_id="msa-2024-001")
    assert all(c.document_id == "msa-2024-001" for c in chunks)


def test_document_id_falls_back_to_the_constructor() -> None:
    chunker = LegalChunker(
        jurisdiction="uk", min_chunk_size=0, document_id="from-init"
    )
    chunks = chunker.chunk_documents(_SECTIONS)
    assert all(c.document_id == "from-init" for c in chunks)


def test_sizing_is_enforced_the_same_way() -> None:
    long_body = "The Supplier shall provide the Services with due care. " * 200
    sections = [Section(identifier="1", title="Services", text=long_body, level=0)]
    chunker = LegalChunker(jurisdiction="uk", max_chunk_size=64, min_chunk_size=0)
    chunks = chunker.chunk_documents(sections)
    assert len(chunks) > 1
    assert all(c.token_count <= 64 for c in chunks)


def test_classification_hook_applies_on_this_path_too() -> None:
    from lexichunk.models import ClauseType

    def to_services(chunk: object, result: object) -> ClauseType:
        return ClauseType.SERVICES

    chunker = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=to_services,  # type: ignore[arg-type]
        classification_hook_threshold=1.0,
    )
    chunks = chunker.chunk_documents(_SECTIONS)
    assert any(c.classification_source == "hook" for c in chunks)


# ---------------------------------------------------------------------------
# Source offsets
# ---------------------------------------------------------------------------

_SOURCE = (
    "1. Definitions\n"
    "In this agreement terms have their given meanings.\n"
    "2. Payment\n"
    "Invoices are payable within thirty days of receipt by the Customer.\n"
)
_BODY_ONE = _SOURCE.index("In this")
_BODY_TWO = _SOURCE.index("Invoices")

_SOURCED_SECTIONS = [
    Section(
        identifier="1",
        title="Definitions",
        text="In this agreement terms have their given meanings.",
        level=0,
        char_start=_BODY_ONE,
        char_end=_BODY_ONE + len("In this agreement terms have their given meanings."),
    ),
    Section(
        identifier="2",
        title="Payment",
        text="Invoices are payable within thirty days of receipt by the Customer.",
        level=0,
        char_start=_BODY_TWO,
        char_end=_BODY_TWO
        + len("Invoices are payable within thirty days of receipt by the Customer."),
    ),
]


def test_source_offsets_are_populated_when_every_section_has_them() -> None:
    chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk_documents(
        _SOURCED_SECTIONS
    )
    assert len(chunks) == 2
    for chunk in chunks:
        assert chunk.raw_char_start >= 0
        assert chunk.raw_char_end > chunk.raw_char_start
        # The mapped source span covers the section's own body text.
        assert _SOURCE[chunk.raw_char_start : chunk.raw_char_end].strip()


def test_source_offsets_point_at_the_right_section() -> None:
    chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk_documents(
        _SOURCED_SECTIONS
    )
    first, second = chunks
    assert _SOURCE[first.raw_char_start : first.raw_char_end].startswith("In this")
    assert _SOURCE[second.raw_char_start : second.raw_char_end].startswith("Invoices")


def test_source_offsets_stay_unset_when_any_section_lacks_them() -> None:
    sections = list(_SOURCED_SECTIONS)
    sections[1] = Section(
        identifier="2",
        title="Payment",
        text="Invoices are payable within thirty days.",
        level=0,
    )
    chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk_documents(
        sections
    )
    assert all(c.raw_char_start == -1 and c.raw_char_end == -1 for c in chunks)


def test_source_offsets_are_unset_for_the_parsed_clause_path() -> None:
    text = "1. Definitions\nTerms have their given meanings in this agreement.\n"
    clauses = StructureParser("uk").parse(text)
    chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk_documents(
        clauses
    )
    assert all(c.raw_char_start == -1 for c in chunks)


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------


def test_section_text_is_sanitised_before_assembly() -> None:
    sections = [
        Section(
            identifier="1",
            title="Definitions",
            text="﻿CRLF\r\nand nulls\x00 are removed before assembly.",
            level=0,
        )
    ]
    chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk_documents(
        sections
    )
    body = "".join(c.content for c in chunks)
    assert "\r" not in body
    assert "\x00" not in body
    assert "﻿" not in body


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_a_string_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    with pytest.raises(InputError, match="sequence of Section"):
        chunker.chunk_documents("1. Definitions")  # type: ignore[arg-type]


def test_an_empty_sequence_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    with pytest.raises(InputError, match="at least one section"):
        chunker.chunk_documents([])


def test_a_non_sequence_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    with pytest.raises(InputError, match="sequence of Section"):
        chunker.chunk_documents(42)  # type: ignore[arg-type]


def test_a_generator_of_sections_is_accepted() -> None:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    chunks = chunker.chunk_documents(section for section in _SECTIONS)  # type: ignore[arg-type]
    assert len(chunks) == len(_SECTIONS)


def test_mixing_record_types_is_rejected() -> None:
    clauses = StructureParser("uk").parse("1. Definitions\nSome body text here.\n")
    chunker = LegalChunker(jurisdiction="uk")
    with pytest.raises(InputError, match="must be a ParsedClause"):
        chunker.chunk_documents([clauses[0], _SECTIONS[0]])  # type: ignore[list-item]


def test_a_bare_dict_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    with pytest.raises(InputError, match="must be a Section"):
        chunker.chunk_documents([{"identifier": "1"}])  # type: ignore[list-item]


def test_a_section_with_a_non_string_body_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    bad = Section(identifier="1", title=None, text=None, level=0)  # type: ignore[arg-type]
    with pytest.raises(InputError, match=r"sections\[0\].text must be a str"):
        chunker.chunk_documents([bad])


def test_a_section_with_a_non_int_level_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    bad = Section(identifier="1", title=None, text="x", level="0")  # type: ignore[arg-type]
    with pytest.raises(InputError, match=r"sections\[0\].level must be an int"):
        chunker.chunk_documents([bad])


def test_a_section_with_no_name_at_all_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    bad = Section(identifier="", title=None, text="Body text.", level=0)
    with pytest.raises(InputError, match="neither an identifier nor a title"):
        chunker.chunk_documents([bad])


def test_a_reversed_source_span_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    bad = Section(
        identifier="1", title=None, text="x", level=0, char_start=10, char_end=2
    )
    with pytest.raises(InputError, match="char_end .* must be >= char_start"):
        chunker.chunk_documents([bad])


def test_a_negative_source_offset_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    bad = Section(identifier="1", title=None, text="x", level=0, char_start=-1)
    with pytest.raises(InputError, match="non-negative int"):
        chunker.chunk_documents([bad])


def test_an_unknown_parent_identifier_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    bad = [
        Section(
            identifier="1",
            title=None,
            text="Body.",
            level=0,
            parent_identifier="nowhere",
        )
    ]
    with pytest.raises(InputError, match="does not match any earlier section"):
        chunker.chunk_documents(bad)


def test_a_bad_document_id_is_rejected() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    with pytest.raises(InputError, match="document_id must be a string"):
        chunker.chunk_documents(_SECTIONS, document_id=7)  # type: ignore[arg-type]


def test_an_oversized_reconstruction_is_rejected() -> None:
    class _Tiny(LegalChunker):
        _MAX_INPUT_CHARS = 100

    chunker = _Tiny(jurisdiction="uk")
    sections = [Section(identifier="1", title=None, text="x" * 500, level=0)]
    with pytest.raises(InputError, match="Reconstructed document too large"):
        chunker.chunk_documents(sections)


# ---------------------------------------------------------------------------
# Section itself
# ---------------------------------------------------------------------------


def test_section_to_dict_round_trips_through_json() -> None:
    import json

    payload = _SECTIONS[0].to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert set(payload) == {
        "identifier",
        "title",
        "text",
        "level",
        "parent_identifier",
        "char_start",
        "char_end",
    }


def test_hand_built_parsed_clauses_without_uids_are_nested_by_level() -> None:
    clauses = [
        ParsedClause(
            identifier="1",
            title="Definitions",
            content="1 Definitions\nTerms have their given meanings.\n\n",
            level=0,
            parent_identifier=None,
            document_section=DocumentSection.DEFINITIONS,
            char_start=0,
            char_end=0,
        ),
        ParsedClause(
            identifier="1.1",
            title="Interpretation",
            content="1.1 Interpretation\nHeadings do not affect construction.\n",
            level=1,
            parent_identifier=None,
            document_section=DocumentSection.OPERATIVE,
            char_start=0,
            char_end=0,
        ),
    ]
    chunks = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk_documents(
        clauses
    )
    child = next(c for c in chunks if c.hierarchy.identifier == "1.1")
    assert child.hierarchy.parent == "1"
