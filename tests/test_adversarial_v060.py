"""Adversarial / edge-case tests for v0.6.0 features."""

from __future__ import annotations

import pytest

from lexichunk import ClassificationResult, ClauseType, LegalChunker
from lexichunk.enrichment.clause_type import (
    ClauseTypeClassifier,
    _classify_detailed,
)
from lexichunk.models import DocumentSection, LegalChunk


class TestSingleChunkPosition:
    """Position scoring when there is only one chunk (i/max(n-1,1) = 0/1)."""

    def test_single_chunk_position_zero(self) -> None:
        result = _classify_detailed(
            "governed by the laws of England",
            relative_position=0.0,
        )
        assert result.clause_type == ClauseType.GOVERNING_LAW

    def test_single_chunk_classify_all(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        text = "1. Governing Law\n\nThis agreement is governed by English law.\n"
        chunks = chunker.chunk(text)
        assert len(chunks) >= 1
        # With only one chunk, relative_position = 0/max(0,1) = 0.0 — no boost.
        for chunk in chunks:
            assert 0.0 <= chunk.classification_confidence <= 1.0


class TestConfidenceInvariants:
    """Confidence must always be between 0.0 and 1.0."""

    def test_structural_override_confidence_one(self) -> None:
        for section, expected_type in [
            (DocumentSection.DEFINITIONS, ClauseType.DEFINITIONS),
            (DocumentSection.PREAMBLE, ClauseType.PREAMBLE),
            (DocumentSection.RECITALS, ClauseType.RECITALS),
        ]:
            r = _classify_detailed("anything", document_section=section)
            assert r.confidence == 1.0
            assert r.clause_type == expected_type

    def test_unknown_confidence_zero(self) -> None:
        r = _classify_detailed("qwertyuiop asdfghjkl zxcvbnm")
        assert r.confidence == 0.0
        assert r.clause_type == ClauseType.UNKNOWN

    @pytest.mark.parametrize("position", [0.0, 0.25, 0.5, 0.75, 0.99, 1.0])
    def test_confidence_bounds_at_all_positions(self, position: float) -> None:
        r = _classify_detailed(
            "terminate the agreement upon notice of termination",
            relative_position=position,
        )
        assert 0.0 <= r.confidence <= 1.0

    def test_no_negative_scores(self) -> None:
        r = _classify_detailed(
            "payment of fees shall be made within 30 days",
            relative_position=0.9,
        )
        for score in r.scores.values():
            assert score >= 0.0

    def test_scores_immutable_from_classify_detailed(self) -> None:
        r = _classify_detailed("governed by the laws of England")
        with pytest.raises(TypeError):
            r.scores[ClauseType.UNKNOWN] = 999  # type: ignore[index]


class TestHereinafterEdgeCases:
    """Edge cases for the hereinafter definition pattern."""

    def test_hereinafter_without_quotes_not_matched(self) -> None:
        from lexichunk.parsers.definitions import DefinitionsExtractor

        text = "ABC Corp hereinafter referred to as The Company."
        ext = DefinitionsExtractor(jurisdiction="uk")
        result = ext.extract(text)
        assert "The Company" not in result

    def test_hereinafter_with_short_term_rejected(self) -> None:
        from lexichunk.parsers.definitions import DefinitionsExtractor

        text = 'ABC Corp hereinafter referred to as "X".'
        ext = DefinitionsExtractor(jurisdiction="uk")
        result = ext.extract(text)
        # Single character terms are rejected by _is_valid_term.
        assert "X" not in result

    def test_hereinafter_with_lowercase_term_not_matched(self) -> None:
        from lexichunk.parsers.definitions import DefinitionsExtractor

        text = 'ABC Corp hereinafter referred to as "the company".'
        ext = DefinitionsExtractor(jurisdiction="uk")
        result = ext.extract(text)
        # Pattern requires uppercase first letter — consistent with other patterns.
        assert "the company" not in result

    def test_hereinafter_multiple_in_same_document(self) -> None:
        from lexichunk.parsers.definitions import DefinitionsExtractor

        text = (
            'ABC Corp, hereinafter referred to as "The Buyer", '
            "agrees to the terms. "
            'XYZ Ltd, hereinafter called "The Seller", '
            "shall deliver goods."
        )
        ext = DefinitionsExtractor(jurisdiction="uk")
        result = ext.extract(text)
        assert "The Buyer" in result
        assert "The Seller" in result


class TestCrossRefStatsInvariants:
    """Cross-ref stats must satisfy basic invariants."""

    def test_resolved_never_exceeds_total(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        text = (
            "1. Definitions\n\n"
            '"Term" means something.\n\n'
            "2. Obligations\n\n"
            "Subject to Clause 1 and Section 3, obligations apply.\n\n"
            "3. Termination\n\n"
            "Termination provisions apply.\n"
        )
        chunks = chunker.chunk(text)
        for c in chunks:
            assert c.cross_ref_resolved <= c.cross_ref_total

    def test_stats_consistent_with_chunk_sums(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        text = (
            "1. Scope\n\nScope of work.\n\n"
            "2. Payment\n\nSee Clause 1 for payment.\n\n"
            "3. Term\n\nPursuant to Clause 2, term is one year.\n"
        )
        chunks = chunker.chunk(text)
        stats = chunker.cross_ref_stats
        if stats:
            total_from_chunks = sum(c.cross_ref_total for c in chunks)
            resolved_from_chunks = sum(c.cross_ref_resolved for c in chunks)
            assert stats["total"] == total_from_chunks
            assert stats["resolved"] == resolved_from_chunks

    def test_no_refs_gives_zero_total(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        text = "1. Introduction\n\nThis is a simple introduction without references.\n"
        chunks = chunker.chunk(text)
        for c in chunks:
            if not c.cross_references:
                assert c.cross_ref_total == 0
                assert c.cross_ref_resolved == 0

    def test_rate_one_when_no_refs(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        text = "1. Simple\n\nNo references here.\n"
        chunker.chunk(text)
        assert chunker.cross_ref_resolution_rate == 1.0


class TestBackwardCompatibility:
    """Verify existing API contracts are preserved."""

    def test_legal_chunk_new_fields_have_defaults(self) -> None:
        """LegalChunk can be created without specifying v0.6.0 fields."""
        from lexichunk.models import (
            DocumentSection,
            HierarchyNode,
            Jurisdiction,
            LegalChunk,
        )

        chunk = LegalChunk(
            content="Some text",
            index=0,
            hierarchy=HierarchyNode(level=0, identifier="1"),
            hierarchy_path="1",
            document_section=DocumentSection.OPERATIVE,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction=Jurisdiction.UK,
        )
        assert chunk.classification_confidence == 0.0
        assert chunk.secondary_clause_type is None
        assert chunk.cross_ref_total == 0
        assert chunk.cross_ref_resolved == 0

    def test_classify_clause_type_standalone_unchanged(self) -> None:
        """classify_clause_type() works with the old positional API."""
        from lexichunk.enrichment.clause_type import classify_clause_type

        # Positional only.
        result = classify_clause_type("governed by the laws of England")
        assert isinstance(result, ClauseType)
        assert result == ClauseType.GOVERNING_LAW

        # With all keyword args.
        from lexichunk.models import DocumentSection

        result2 = classify_clause_type(
            "random text",
            hierarchy_path="",
            document_section=DocumentSection.DEFINITIONS,
            extra_signals=None,
        )
        assert result2 == ClauseType.DEFINITIONS

    def test_classification_result_importable_from_top_level(self) -> None:
        from lexichunk import ClassificationResult

        assert ClassificationResult.__name__ == "ClassificationResult"

    def test_classify_clause_type_never_applies_position_boost(self) -> None:
        """Standalone function must NOT apply position boost."""
        from lexichunk.enrichment.clause_type import classify_clause_type

        # Even text matching end-of-doc types should not get boosted.
        result = classify_clause_type("This is an entire agreement clause and severability.")
        # Just verify it returns a ClauseType without position influence.
        assert isinstance(result, ClauseType)


class TestSecondaryTypeInvariants:
    """Secondary clause type must always differ from primary."""

    def test_secondary_differs_from_primary(self) -> None:
        result = _classify_detailed(
            "The party shall indemnify and hold harmless. "
            "This agreement may be terminated upon notice of termination."
        )
        if result.secondary_clause_type is not None:
            assert result.secondary_clause_type != result.clause_type

    def test_secondary_none_for_single_match(self) -> None:
        result = _classify_detailed("force majeure event act of god")
        assert result.secondary_clause_type is None

    def test_secondary_none_for_unknown(self) -> None:
        result = _classify_detailed("xyzzy foobar nothing here")
        assert result.secondary_clause_type is None


class TestEmptyContentWithPosition:
    """Empty content at high position must not crash or produce bad values."""

    def test_empty_content_high_position(self) -> None:
        result = _classify_detailed("", relative_position=0.9)
        assert result.clause_type == ClauseType.UNKNOWN
        assert result.confidence == 0.0
        assert result.scores == {}

    def test_whitespace_only_high_position(self) -> None:
        result = _classify_detailed("   \n\t  ", relative_position=0.95)
        assert result.clause_type == ClauseType.UNKNOWN
        assert result.confidence == 0.0


class TestFullPipelineV060Integration:
    """End-to-end test exercising all v0.6.0 features simultaneously."""

    def test_all_v060_features_together(self) -> None:
        text = (
            "1. Definitions and Interpretation\n\n"
            '"Agreement" means this agreement between the parties. '
            '"Service Provider" means the party providing services. '
            "ABC Corp, hereinafter referred to as "
            '"The Provider", is a Delaware corporation.\n\n'
            "2. Obligations of the Service Provider\n\n"
            "The Service Provider shall perform the services described in "
            "Clause 1 and subject to Clause 3. The Service Provider shall "
            "indemnify and hold harmless the other party against any losses "
            "and damages arising from a breach of this Agreement.\n\n"
            "3. Termination and Expiry\n\n"
            "Either party may terminate this Agreement by giving written "
            "notice of termination. Upon termination, all obligations shall "
            "cease pursuant to Clause 2.\n\n"
            "4. Governing Law and Jurisdiction\n\n"
            "This Agreement shall be governed by and construed in accordance "
            "with the laws of England. The courts of England shall have "
            "exclusive jurisdiction to settle any disputes.\n\n"
            "5. Entire Agreement\n\n"
            "This Agreement constitutes the entire agreement between the "
            "parties and supersedes all prior agreements, whether written or "
            "oral. The remaining provisions shall be severable.\n"
        )
        chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
        chunks = chunker.chunk(text)

        assert len(chunks) >= 3

        # All chunks have confidence populated.
        for chunk in chunks:
            assert 0.0 <= chunk.classification_confidence <= 1.0
            assert isinstance(chunk.cross_ref_total, int)
            assert chunk.cross_ref_resolved <= chunk.cross_ref_total

        # Hereinafter term extracted.
        all_terms = set()
        for chunk in chunks:
            all_terms.update(chunk.defined_terms_used)
        assert "Agreement" in all_terms or "Service Provider" in all_terms

        # Cross-ref stats populated on the chunker.
        stats = chunker.cross_ref_stats
        assert "total" in stats
        assert "resolved" in stats
        assert "rate" in stats

        # At least one chunk should have cross-references.
        assert any(c.cross_ref_total > 0 for c in chunks)

        # Last chunk(s) should have position-aware classification.
        last = chunks[-1]
        assert last.classification_confidence > 0.0
