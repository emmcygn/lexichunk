"""Tests for LegalChunk (and nested dataclass) to_dict()/from_dict()."""

from __future__ import annotations

import copy
import json

import pytest

from lexichunk import LegalChunker
from lexichunk.models import ClauseType, DocumentSection, Jurisdiction, LegalChunk

from ._snapshot_support import FIXTURE_CONFIGS, load_fixture, make_chunker

_ALL_CHUNK_FIELDS = {
    "content",
    "index",
    "hierarchy",
    "hierarchy_path",
    "document_section",
    "clause_type",
    "jurisdiction",
    "cross_references",
    "defined_terms_used",
    "defined_terms_context",
    "classification_confidence",
    "secondary_clause_type",
    "cross_ref_total",
    "cross_ref_resolved",
    "context_header",
    "document_id",
    "char_start",
    "char_end",
    "token_count",
    "original_header",
}


def _all_fixture_chunks() -> list[LegalChunk]:
    chunks: list[LegalChunk] = []
    for fixture_name, jurisdiction, doc_type in FIXTURE_CONFIGS:
        text = load_fixture(fixture_name)
        chunker = make_chunker(jurisdiction, doc_type)
        chunks.extend(chunker.chunk(text))
    return chunks


@pytest.fixture(scope="module")
def all_chunks() -> list[LegalChunk]:
    return _all_fixture_chunks()


# ---------------------------------------------------------------------------
# to_dict() shape
# ---------------------------------------------------------------------------


def test_to_dict_includes_every_field(all_chunks: list[LegalChunk]) -> None:
    for chunk in all_chunks:
        d = chunk.to_dict()
        assert set(d) == _ALL_CHUNK_FIELDS, (
            f"to_dict() keys {set(d)} != expected {_ALL_CHUNK_FIELDS}"
        )


def test_to_dict_is_json_dumpable(all_chunks: list[LegalChunk]) -> None:
    for chunk in all_chunks:
        # No custom encoder — must work with the stdlib default encoder.
        json.dumps(chunk.to_dict())


def test_to_dict_enum_fields_are_plain_strings(all_chunks: list[LegalChunk]) -> None:
    for chunk in all_chunks:
        d = chunk.to_dict()
        assert isinstance(d["document_section"], str)
        assert isinstance(d["clause_type"], str)
        assert d["document_section"] == chunk.document_section.value
        assert d["clause_type"] == chunk.clause_type.value
        if chunk.secondary_clause_type is not None:
            assert d["secondary_clause_type"] == chunk.secondary_clause_type.value
        else:
            assert d["secondary_clause_type"] is None


def test_to_dict_jurisdiction_is_string_value(all_chunks: list[LegalChunk]) -> None:
    for chunk in all_chunks:
        d = chunk.to_dict()
        assert isinstance(d["jurisdiction"], str)
        if isinstance(chunk.jurisdiction, Jurisdiction):
            assert d["jurisdiction"] == chunk.jurisdiction.value
        else:
            assert d["jurisdiction"] == chunk.jurisdiction


def test_to_dict_custom_jurisdiction_kept_as_string() -> None:
    from lexichunk.jurisdiction import _JURISDICTION_REGISTRY

    # Reuse an existing registered pattern set under a new custom name so we
    # don't need to hand-roll a JurisdictionPatterns implementation here.
    uk_patterns, uk_detect_level = _JURISDICTION_REGISTRY["uk"]
    from lexichunk.jurisdiction import register_jurisdiction

    register_jurisdiction("test-custom-jurisdiction", uk_patterns, uk_detect_level)
    try:
        chunker = LegalChunker(jurisdiction="test-custom-jurisdiction")
        chunks = chunker.chunk("1. Definitions\nThis clause defines terms.\n")
        assert chunks
        for chunk in chunks:
            d = chunk.to_dict()
            assert d["jurisdiction"] == "test-custom-jurisdiction"
    finally:
        del _JURISDICTION_REGISTRY["test-custom-jurisdiction"]


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_round_trip_every_fixture_chunk(all_chunks: list[LegalChunk]) -> None:
    for chunk in all_chunks:
        d = chunk.to_dict()
        restored = LegalChunk.from_dict(d)
        assert restored.to_dict() == d


def test_round_trip_through_json_string(all_chunks: list[LegalChunk]) -> None:
    for chunk in all_chunks:
        d = chunk.to_dict()
        s = json.dumps(d)
        restored = LegalChunk.from_dict(json.loads(s))
        assert restored.to_dict() == d


def test_from_dict_reconstructs_enums(all_chunks: list[LegalChunk]) -> None:
    for chunk in all_chunks:
        restored = LegalChunk.from_dict(chunk.to_dict())
        assert isinstance(restored.document_section, DocumentSection)
        assert isinstance(restored.clause_type, ClauseType)
        assert restored.document_section == chunk.document_section
        assert restored.clause_type == chunk.clause_type
        if chunk.secondary_clause_type is not None:
            assert isinstance(restored.secondary_clause_type, ClauseType)
            assert restored.secondary_clause_type == chunk.secondary_clause_type
        else:
            assert restored.secondary_clause_type is None


def test_from_dict_unknown_jurisdiction_kept_as_string() -> None:
    chunker = make_chunker("uk", "contract")
    text = load_fixture("uk_service_agreement")
    chunk = chunker.chunk(text)[0]
    d = chunk.to_dict()
    d["jurisdiction"] = "not-a-real-jurisdiction"
    restored = LegalChunk.from_dict(d)
    assert restored.jurisdiction == "not-a-real-jurisdiction"
    assert isinstance(restored.jurisdiction, str)
    assert not isinstance(restored.jurisdiction, Jurisdiction)


def test_from_dict_known_jurisdiction_reconstructs_enum(all_chunks: list[LegalChunk]) -> None:
    for chunk in all_chunks:
        if isinstance(chunk.jurisdiction, Jurisdiction):
            restored = LegalChunk.from_dict(chunk.to_dict())
            assert isinstance(restored.jurisdiction, Jurisdiction)
            assert restored.jurisdiction == chunk.jurisdiction


# ---------------------------------------------------------------------------
# Mutation isolation
# ---------------------------------------------------------------------------


def test_to_dict_mutation_does_not_affect_chunk(all_chunks: list[LegalChunk]) -> None:
    for chunk in all_chunks:
        before = copy.deepcopy(chunk.to_dict())
        d = chunk.to_dict()

        d["content"] = "MUTATED"
        d["hierarchy"]["identifier"] = "MUTATED"
        d["cross_references"].append({"raw_text": "x", "target_identifier": "x", "target_chunk_index": None})
        d["defined_terms_used"].append("MUTATED")
        d["defined_terms_context"]["MUTATED"] = "MUTATED"

        after = chunk.to_dict()
        assert after == before, "mutating a to_dict() result affected the chunk's own state"


def test_nested_to_dict_methods() -> None:
    from lexichunk.models import CrossReference, DefinedTerm, HierarchyNode

    node = HierarchyNode(level=1, identifier="1.1", title="Scope", parent="1")
    assert node.to_dict() == {
        "level": 1,
        "identifier": "1.1",
        "title": "Scope",
        "parent": "1",
    }

    ref = CrossReference(raw_text="Clause 3.2", target_identifier="3.2", target_chunk_index=4)
    assert ref.to_dict() == {
        "raw_text": "Clause 3.2",
        "target_identifier": "3.2",
        "target_chunk_index": 4,
        "target_kind": "clause",
    }

    term = DefinedTerm(term="Supplier", definition="means the party.", source_clause="1.1")
    assert term.to_dict() == {
        "term": "Supplier",
        "definition": "means the party.",
        "source_clause": "1.1",
    }

    # json.dumps should work with no custom encoder for all three.
    json.dumps(node.to_dict())
    json.dumps(ref.to_dict())
    json.dumps(term.to_dict())
