"""Tests for extra_clause_signals on ClauseTypeClassifier and LegalChunker."""

from __future__ import annotations

from lexichunk import ClauseType, LegalChunker
from lexichunk.enrichment.clause_type import (
    ClauseTypeClassifier,
    classify_clause_type,
)

# ---------------------------------------------------------------------------
# classify_clause_type with extra_signals
# ---------------------------------------------------------------------------


class TestClassifyWithExtraSignals:
    def test_extra_signal_triggers_classification(self) -> None:
        """A unique keyword in extras should trigger the expected clause type."""
        result = classify_clause_type(
            "The zorgblatt fee is payable on demand.",
            extra_signals={ClauseType.PAYMENT: ["zorgblatt"]},
        )
        assert result == ClauseType.PAYMENT

    def test_existing_signals_still_work(self) -> None:
        """Built-in signals must still work when extras are present."""
        result = classify_clause_type(
            "The Supplier shall indemnify the Buyer.",
            extra_signals={ClauseType.PAYMENT: ["zorgblatt"]},
        )
        assert result == ClauseType.INDEMNIFICATION

    def test_multiple_clause_types_with_extras(self) -> None:
        """Multiple clause types can have extras simultaneously."""
        extras = {
            ClauseType.PAYMENT: ["subscription charge"],
            ClauseType.CONFIDENTIALITY: ["secret sauce"],
        }
        result = classify_clause_type(
            "The subscription charge for the secret sauce is $100.",
            extra_signals=extras,
        )
        # Both match; PAYMENT has more built-in signals in the text too
        assert result in (ClauseType.PAYMENT, ClauseType.CONFIDENTIALITY)

    def test_none_extras_behaves_as_default(self) -> None:
        result_with_none = classify_clause_type(
            "This agreement is governed by English law.",
            extra_signals=None,
        )
        result_without = classify_clause_type(
            "This agreement is governed by English law.",
        )
        assert result_with_none == result_without

    def test_empty_dict_extras_behaves_as_default(self) -> None:
        result_with_empty = classify_clause_type(
            "This agreement is governed by English law.",
            extra_signals={},
        )
        result_without = classify_clause_type(
            "This agreement is governed by English law.",
        )
        assert result_with_empty == result_without


# ---------------------------------------------------------------------------
# ClauseTypeClassifier with extra_signals
# ---------------------------------------------------------------------------


class TestClassifierWithExtraSignals:
    def test_classifier_uses_extra_signals(self) -> None:
        classifier = ClauseTypeClassifier(
            extra_signals={ClauseType.PAYMENT: ["zorgblatt"]},
        )
        result = classifier.classify("The zorgblatt fee is due.")
        assert result == ClauseType.PAYMENT

    def test_classifier_default_no_extras(self) -> None:
        classifier = ClauseTypeClassifier()
        result = classifier.classify("The Supplier shall indemnify the Buyer.")
        assert result == ClauseType.INDEMNIFICATION


# ---------------------------------------------------------------------------
# LegalChunker integration
# ---------------------------------------------------------------------------


class TestLegalChunkerExtraSignals:
    def test_chunker_with_extra_signals(self) -> None:
        """Extra signals passed to LegalChunker flow through to classification."""
        text = (
            "1. Zorgblatt Provisions\n"
            "The zorgblatt fee is payable on the first day of each month.\n"
        )
        chunker = LegalChunker(
            jurisdiction="uk",
            extra_clause_signals={ClauseType.PAYMENT: ["zorgblatt"]},
        )
        chunks = chunker.chunk(text)
        assert len(chunks) > 0
        assert chunks[0].clause_type == ClauseType.PAYMENT
