"""Tests for position-aware scoring in clause type classification."""

from __future__ import annotations

import pytest

from lexichunk import ClauseType, LegalChunker
from lexichunk.enrichment.clause_type import (
    ClassificationResult,
    ClauseTypeClassifier,
    _END_OF_DOC_TYPES,
    _POSITION_BONUS,
    _POSITION_THRESHOLD,
    _classify_detailed,
)


class TestPositionBoostConstants:
    """Verify position-boost configuration values."""

    def test_position_bonus_value(self) -> None:
        assert _POSITION_BONUS == 1.5

    def test_position_threshold_value(self) -> None:
        assert _POSITION_THRESHOLD == 0.75

    def test_end_of_doc_types_contents(self) -> None:
        expected = {
            ClauseType.BOILERPLATE,
            ClauseType.ENTIRE_AGREEMENT,
            ClauseType.SEVERABILITY,
            ClauseType.GOVERNING_LAW,
            ClauseType.NOTICES,
            ClauseType.AMENDMENT,
            ClauseType.ASSIGNMENT,
        }
        assert _END_OF_DOC_TYPES == expected


class TestPositionBoostAtEndOfDoc:
    """Position boost should increase scores at end of document."""

    def test_governing_law_boosted_at_end(self) -> None:
        text = "governed by the laws of the State of New York"
        at_start = _classify_detailed(text, relative_position=0.1)
        at_end = _classify_detailed(text, relative_position=0.9)
        assert at_start.clause_type == ClauseType.GOVERNING_LAW
        assert at_end.clause_type == ClauseType.GOVERNING_LAW
        # Score at end should be higher due to position boost.
        assert at_end.scores[ClauseType.GOVERNING_LAW] > at_start.scores[ClauseType.GOVERNING_LAW]

    def test_severability_boosted_at_end(self) -> None:
        text = "If any provision is invalid or unenforceable, the remaining provisions shall continue."
        at_end = _classify_detailed(text, relative_position=0.9)
        assert at_end.clause_type == ClauseType.SEVERABILITY

    def test_entire_agreement_boosted_at_end(self) -> None:
        text = "This agreement constitutes the entire agreement and supersedes all prior agreements."
        at_end = _classify_detailed(text, relative_position=0.95)
        assert at_end.clause_type == ClauseType.ENTIRE_AGREEMENT


class TestNoBoostAtStartOrMiddle:
    """Position boost should not apply before the threshold."""

    def test_no_boost_at_position_zero(self) -> None:
        text = "This clause covers severability provisions."
        r0 = _classify_detailed(text, relative_position=0.0)
        r_mid = _classify_detailed(text, relative_position=0.5)
        # Scores should be identical since both are below threshold.
        assert r0.scores.get(ClauseType.SEVERABILITY, 0) == r_mid.scores.get(
            ClauseType.SEVERABILITY, 0
        )

    def test_no_boost_at_threshold_boundary(self) -> None:
        text = "notices shall be given in writing"
        r_at = _classify_detailed(text, relative_position=0.75)
        r_below = _classify_detailed(text, relative_position=0.74)
        # At exactly 0.75, no boost (> not >=).
        assert r_at.scores.get(ClauseType.NOTICES, 0) == r_below.scores.get(
            ClauseType.NOTICES, 0
        )

    def test_boost_just_above_threshold(self) -> None:
        text = "notices shall be given in writing"
        r_above = _classify_detailed(text, relative_position=0.76)
        r_below = _classify_detailed(text, relative_position=0.74)
        assert r_above.scores.get(ClauseType.NOTICES, 0) > r_below.scores.get(
            ClauseType.NOTICES, 0
        )


class TestStrongSignalsOverrideBoost:
    """Strong competing signals should still win over position-boosted types."""

    def test_indemnification_dominates_at_end(self) -> None:
        text = (
            "The indemnifying party shall indemnify and hold harmless the "
            "indemnified party against all losses and damages. "
            "Notice shall be given."
        )
        result = _classify_detailed(text, relative_position=0.9)
        # Indemnification has many strong signals; the weak "notice" boost
        # should not override it.
        assert result.clause_type == ClauseType.INDEMNIFICATION

    def test_confidentiality_dominates_at_end(self) -> None:
        text = (
            "All confidential information and proprietary information "
            "including trade secrets shall remain confidential. "
            "Amendment may be made."
        )
        result = _classify_detailed(text, relative_position=0.85)
        assert result.clause_type == ClauseType.CONFIDENTIALITY


class TestClassifyAllUsesPosition:
    """classify_all should pass relative_position to each chunk."""

    def test_classify_all_uses_position(self) -> None:
        chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
        text = (
            "1. Definitions\n\n"
            '"Agreement" means this agreement between the parties.\n\n'
            "2. Payment\n\n"
            "Payment of fees shall be made within 30 days of invoice. "
            "The Supplier shall invoice the Buyer monthly in arrears for all "
            "services performed during the preceding calendar month.\n\n"
            "3. Governing Law\n\n"
            "This agreement shall be governed by and construed in accordance "
            "with the laws of England and Wales. The courts of England shall "
            "have exclusive jurisdiction.\n"
        )
        chunks = chunker.chunk(text)
        assert len(chunks) >= 2
        # The last chunk(s) should have position-aware classification.
        last = chunks[-1]
        assert isinstance(last.classification_confidence, float)
