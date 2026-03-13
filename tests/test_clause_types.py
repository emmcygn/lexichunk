"""Tests for classify_clause_type."""

import pytest

from lexichunk.enrichment.clause_type import classify_clause_type
from lexichunk.models import ClauseType, DocumentSection


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def classify(content: str, path: str = "", section=None) -> ClauseType:
    return classify_clause_type(content, hierarchy_path=path, document_section=section)


# ---------------------------------------------------------------------------
# DEFINITIONS
# ---------------------------------------------------------------------------


def test_definitions_means():
    assert classify('"Services" means the services to be provided.') == ClauseType.DEFINITIONS


def test_definitions_shall_mean():
    assert classify('"Affiliate" shall mean any entity that controls the party.') == ClauseType.DEFINITIONS


def test_definitions_has_the_meaning():
    assert classify('"Agreement" has the meaning set out in the preamble.') == ClauseType.DEFINITIONS


def test_not_definitions_payment():
    result = classify("The Client shall pay the invoice within thirty days.")
    assert result != ClauseType.DEFINITIONS


def test_not_definitions_termination():
    result = classify("Either party may terminate this agreement on 30 days notice.")
    assert result != ClauseType.DEFINITIONS


# ---------------------------------------------------------------------------
# INDEMNIFICATION
# ---------------------------------------------------------------------------


def test_indemnification_indemnify():
    assert classify("The Supplier shall indemnify and defend the Client.") == ClauseType.INDEMNIFICATION


def test_indemnification_hold_harmless():
    assert classify("The party shall hold harmless the other from any claims.") == ClauseType.INDEMNIFICATION


def test_indemnification_losses_and_damages():
    assert classify("The Indemnifying Party shall cover all losses and damages arising.") == ClauseType.INDEMNIFICATION


def test_not_indemnification_confidentiality():
    # Strong confidentiality signals should not be classified as indemnification.
    result = classify(
        "Each party shall keep confidential information strictly confidential "
        "and not disclose proprietary information to any third party."
    )
    assert result != ClauseType.INDEMNIFICATION


def test_not_indemnification_plain():
    result = classify("The Services shall be provided in a professional manner.")
    assert result != ClauseType.INDEMNIFICATION


# ---------------------------------------------------------------------------
# TERMINATION
# ---------------------------------------------------------------------------


def test_termination_terminate():
    assert classify("Either party may terminate this Agreement immediately.") == ClauseType.TERMINATION


def test_termination_termination_word():
    assert classify("Upon termination of this Agreement all licences shall cease.") == ClauseType.TERMINATION


def test_termination_notice_of_termination():
    assert classify("The Client shall give notice of termination in writing.") == ClauseType.TERMINATION


def test_not_termination_payment():
    result = classify("The Client shall pay the Fees within thirty days of receipt of invoice.")
    assert result != ClauseType.TERMINATION


def test_not_termination_empty():
    result = classify("")
    assert result != ClauseType.TERMINATION


# ---------------------------------------------------------------------------
# CONFIDENTIALITY
# ---------------------------------------------------------------------------


def test_confidentiality_confidential():
    """Confidentiality signals must outscore competing signals.

    'confidential' alone scores 1 point, but 'shall not' (COVENANTS) also
    scores 2 points.  Use multiple confidentiality signals to win clearly.
    """
    assert classify(
        "Each party shall keep confidential all Confidential Information "
        "and shall not disclose proprietary information to any third party."
    ) == ClauseType.CONFIDENTIALITY


def test_confidentiality_non_disclosure():
    """'non-disclosure' alone scores 3 points (3-word phrase) for confidentiality."""
    # 'non-disclosure' is a single signal string that contains a hyphen;
    # it is stored as one signal.  We need enough confidentiality signal
    # mass without inadvertently triggering stronger signals.
    assert classify(
        "The non-disclosure obligations of each party are set out herein. "
        "All Confidential Information is protected under this clause."
    ) == ClauseType.CONFIDENTIALITY


def test_confidentiality_proprietary_information():
    assert classify("The Receiving Party shall protect all proprietary information.") == ClauseType.CONFIDENTIALITY


def test_not_confidentiality_governing_law():
    result = classify("This Agreement shall be governed by the laws of England and Wales.")
    assert result != ClauseType.CONFIDENTIALITY


def test_not_confidentiality_plain():
    result = classify("The Supplier shall provide the Services as described herein.")
    assert result != ClauseType.CONFIDENTIALITY


# ---------------------------------------------------------------------------
# LIMITATION_OF_LIABILITY
# ---------------------------------------------------------------------------


def test_lol_shall_not_exceed():
    assert classify("Each party's liability shall not exceed the total fees paid.") == ClauseType.LIMITATION_OF_LIABILITY


def test_lol_in_no_event():
    assert classify("In no event shall either party be liable for indirect damages.") == ClauseType.LIMITATION_OF_LIABILITY


def test_lol_aggregate_liability():
    assert classify("The aggregate liability of the Supplier under this Agreement is capped.") == ClauseType.LIMITATION_OF_LIABILITY


def test_not_lol_indemnification():
    # Multi-word indemnification signals must outscore single LOL words.
    result = classify(
        "The Indemnifying Party shall defend, indemnify, and hold harmless "
        "the Indemnified Party against all Losses."
    )
    assert result != ClauseType.LIMITATION_OF_LIABILITY


def test_not_lol_termination():
    result = classify("Either party may terminate this Agreement upon thirty days notice.")
    assert result != ClauseType.LIMITATION_OF_LIABILITY


# ---------------------------------------------------------------------------
# GOVERNING_LAW
# ---------------------------------------------------------------------------


def test_governing_law_governed_by():
    assert classify("This Agreement shall be governed by the laws of England and Wales.") == ClauseType.GOVERNING_LAW


def test_governing_law_governing_law_phrase():
    assert classify("The governing law of this contract shall be the law of Delaware.") == ClauseType.GOVERNING_LAW


def test_governing_law_courts_of():
    assert classify("The parties submit to the exclusive jurisdiction of the courts of England.") == ClauseType.GOVERNING_LAW


def test_not_governing_law_payment():
    result = classify("Customer shall pay Provider the fees set forth in each Order Form.")
    assert result != ClauseType.GOVERNING_LAW


def test_not_governing_law_definitions():
    result = classify('"Affiliate" means any entity that directly controls the party.')
    assert result != ClauseType.GOVERNING_LAW


# ---------------------------------------------------------------------------
# DATA_PROTECTION
# ---------------------------------------------------------------------------


def test_data_protection_personal_data():
    assert classify("The Supplier shall process personal data in accordance with the law.") == ClauseType.DATA_PROTECTION


def test_data_protection_data_protection_phrase():
    assert classify("The parties shall comply with all applicable data protection legislation.") == ClauseType.DATA_PROTECTION


def test_data_protection_gdpr():
    assert classify("Processing must comply with the GDPR and applicable national law.") == ClauseType.DATA_PROTECTION


def test_not_data_protection_confidentiality():
    result = classify(
        "Each party shall keep confidential all information and trade secrets "
        "and shall not disclose proprietary information without prior written consent."
    )
    assert result != ClauseType.DATA_PROTECTION


def test_not_data_protection_payment():
    result = classify("Customer shall pay the invoice within thirty days of receipt.")
    assert result != ClauseType.DATA_PROTECTION


# ---------------------------------------------------------------------------
# Structural override tests
# ---------------------------------------------------------------------------


def test_document_section_override_definitions():
    """document_section=DEFINITIONS → ClauseType.DEFINITIONS regardless of content."""
    result = classify_clause_type(
        "The Supplier shall indemnify and hold harmless the Client.",
        document_section=DocumentSection.DEFINITIONS,
    )
    assert result == ClauseType.DEFINITIONS


def test_document_section_override_preamble():
    """document_section=PREAMBLE → ClauseType.PREAMBLE regardless of content."""
    result = classify_clause_type(
        "This Agreement shall be governed by the laws of England and Wales.",
        document_section=DocumentSection.PREAMBLE,
    )
    assert result == ClauseType.PREAMBLE


def test_unknown_for_empty():
    """An empty string with no signals returns UNKNOWN."""
    result = classify("")
    assert result == ClauseType.UNKNOWN


def test_unknown_for_no_signals():
    """Text with no matching signals returns UNKNOWN."""
    result = classify("Lorem ipsum dolor sit amet consectetur adipiscing elit.")
    assert result == ClauseType.UNKNOWN


# ---------------------------------------------------------------------------
# Hierarchy path bonus
# ---------------------------------------------------------------------------


def test_tie_breaking_uses_insertion_order():
    """When two ClauseTypes score equally, the one first in CLAUSE_SIGNALS wins.

    This matters because ``max(scores, key=...)`` breaks ties by returning
    the *first* key it encounters with the maximum value.  Since ``scores``
    is built by iterating ``CLAUSE_SIGNALS`` (a dict literal whose insertion
    order is guaranteed in Python 3.7+), the first clause type in
    ``CLAUSE_SIGNALS`` with the tied score wins.

    Here both INDEMNIFICATION and TERMINATION score exactly 1 (one single-word
    signal each: "indemnify" and "terminate").  INDEMNIFICATION appears before
    TERMINATION in ``CLAUSE_SIGNALS``, so it must be the winner.
    """
    from lexichunk.enrichment.clause_type import CLAUSE_SIGNALS, _score

    content = "The obligation to indemnify and to terminate applies here."
    content_lower = content.lower()

    # Sanity-check that the scores are genuinely tied.
    scores = _score(content_lower, "")
    assert scores[ClauseType.INDEMNIFICATION] == scores[ClauseType.TERMINATION], (
        f"Expected tied scores, got INDEMNIFICATION={scores[ClauseType.INDEMNIFICATION]} "
        f"vs TERMINATION={scores[ClauseType.TERMINATION]}"
    )

    # Verify INDEMNIFICATION appears before TERMINATION in CLAUSE_SIGNALS.
    signal_order = list(CLAUSE_SIGNALS.keys())
    assert signal_order.index(ClauseType.INDEMNIFICATION) < signal_order.index(
        ClauseType.TERMINATION
    ), "Test assumes INDEMNIFICATION precedes TERMINATION in CLAUSE_SIGNALS"

    # The classifier must pick the earlier one.
    result = classify(content)
    assert result == ClauseType.INDEMNIFICATION


def test_hierarchy_path_bonus():
    """Weak content signals + path containing 'indemnification' → INDEMNIFICATION.

    The path bonus is 3.0 points.  A single multi-word phrase like
    'hold harmless' would score 2 from content.  We use content with only
    single-word indemnification signals (e.g. 'losses') which by themselves
    would not be sufficient, but the path bonus pushes indemnification to the
    top.
    """
    # Content alone would classify as something generic; path overrides.
    result = classify_clause_type(
        "The party shall cover all losses incurred.",
        hierarchy_path="Article VII > Section 7.01 Indemnification",
    )
    assert result == ClauseType.INDEMNIFICATION


def test_hierarchy_path_bonus_confidentiality():
    """Path containing 'confidentiality' boosts CONFIDENTIALITY score."""
    result = classify_clause_type(
        "Each party shall treat the information with care.",
        hierarchy_path="Article IV Confidentiality",
    )
    assert result == ClauseType.CONFIDENTIALITY
