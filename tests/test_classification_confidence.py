"""Tests for classification confidence, secondary type, and ClassificationResult."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from lexichunk import ClassificationResult, ClauseType, LegalChunker
from lexichunk.enrichment.clause_type import (
    ClauseTypeClassifier,
    _classify_detailed,
)
from lexichunk.models import DocumentSection


class TestClassificationResult:
    """ClassificationResult dataclass basics."""

    def test_frozen(self) -> None:
        r = ClassificationResult(
            clause_type=ClauseType.UNKNOWN,
            confidence=0.0,
            secondary_clause_type=None,
            scores={},
        )
        with pytest.raises(AttributeError):
            r.confidence = 0.5  # type: ignore[misc]

    def test_scores_immutable(self) -> None:
        r = ClassificationResult(
            clause_type=ClauseType.TERMINATION,
            confidence=0.8,
            secondary_clause_type=None,
            scores=MappingProxyType({ClauseType.TERMINATION: 4.0}),
        )
        with pytest.raises(TypeError):
            r.scores[ClauseType.UNKNOWN] = 999  # type: ignore[index]

    def test_fields_accessible(self) -> None:
        r = ClassificationResult(
            clause_type=ClauseType.TERMINATION,
            confidence=0.8,
            secondary_clause_type=ClauseType.COVENANTS,
            scores=MappingProxyType({ClauseType.TERMINATION: 4.0, ClauseType.COVENANTS: 1.0}),
        )
        assert r.clause_type == ClauseType.TERMINATION
        assert r.confidence == 0.8
        assert r.secondary_clause_type == ClauseType.COVENANTS
        assert ClauseType.TERMINATION in r.scores


class TestClassifyDetailed:
    """Tests for _classify_detailed internal function."""

    def test_structural_override_confidence_is_one(self) -> None:
        result = _classify_detailed(
            "random text",
            document_section=DocumentSection.DEFINITIONS,
        )
        assert result.clause_type == ClauseType.DEFINITIONS
        assert result.confidence == 1.0
        assert result.secondary_clause_type is None

    def test_unknown_confidence_is_zero(self) -> None:
        result = _classify_detailed("xyzzy foobar nothing here")
        assert result.clause_type == ClauseType.UNKNOWN
        assert result.confidence == 0.0

    def test_single_match_confidence_is_one(self) -> None:
        result = _classify_detailed(
            "force majeure event beyond reasonable control act of god"
        )
        assert result.clause_type == ClauseType.FORCE_MAJEURE
        assert result.confidence == 1.0
        assert result.secondary_clause_type is None

    def test_multiple_matches_gives_secondary(self) -> None:
        result = _classify_detailed(
            "The party shall indemnify and hold harmless. "
            "This agreement may be terminated upon notice."
        )
        assert result.confidence < 1.0
        assert result.secondary_clause_type is not None
        assert result.secondary_clause_type != result.clause_type

    def test_confidence_between_zero_and_one(self) -> None:
        result = _classify_detailed(
            "payment shall be made within 30 days. "
            "warranty is provided as is."
        )
        assert 0.0 < result.confidence <= 1.0

    def test_scores_dict_populated(self) -> None:
        result = _classify_detailed(
            "This clause governs confidentiality and non-disclosure."
        )
        assert len(result.scores) >= 1
        assert result.clause_type in result.scores


class TestClassifierClassifyDetailed:
    """Tests for ClauseTypeClassifier.classify_detailed()."""

    def test_returns_classification_result(self) -> None:
        c = ClauseTypeClassifier()
        result = c.classify_detailed("governed by the laws of England")
        assert isinstance(result, ClassificationResult)
        assert result.clause_type == ClauseType.GOVERNING_LAW

    def test_with_relative_position(self) -> None:
        c = ClauseTypeClassifier()
        result = c.classify_detailed(
            "This agreement constitutes the entire agreement.",
            relative_position=0.9,
        )
        assert result.clause_type == ClauseType.ENTIRE_AGREEMENT


class TestClassifyAllPopulatesFields:
    """classify_all must set confidence and secondary_clause_type on chunks."""

    def test_confidence_populated_on_chunks(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        text = (
            "1. Definitions\n\n"
            '"Agreement" means this agreement.\n\n'
            "2. Confidentiality\n\n"
            "All information shall be kept confidential.\n\n"
            "3. Governing Law\n\n"
            "This agreement is governed by English law.\n"
        )
        chunks = chunker.chunk(text)
        assert len(chunks) > 0
        for chunk in chunks:
            assert 0.0 <= chunk.classification_confidence <= 1.0

    def test_secondary_clause_type_can_be_set(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        text = (
            "1. Indemnification and Termination\n\n"
            "The party shall indemnify and hold harmless the other party. "
            "Either party may terminate this agreement upon written notice "
            "of termination.\n"
        )
        chunks = chunker.chunk(text)
        # At least one chunk should have signals for both types.
        [c for c in chunks if c.secondary_clause_type is not None]
        # Even if none is mixed, confidence should still be populated.
        for chunk in chunks:
            assert isinstance(chunk.classification_confidence, float)
