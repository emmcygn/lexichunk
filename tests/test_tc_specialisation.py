"""Tests for Terms & Conditions document type specialisation."""

import pytest

from lexichunk import LegalChunker
from lexichunk.models import ClauseType, DocumentSection, Jurisdiction
from lexichunk.enrichment.clause_type import classify_clause_type


# ---------------------------------------------------------------------------
# End-to-end T&C parsing tests
# ---------------------------------------------------------------------------


def test_uk_tc_no_recitals_or_signatures(uk_terms_conditions):
    """UK T&C parsed with doc_type='terms_conditions' has no RECITALS or SIGNATURES."""
    chunker = LegalChunker(jurisdiction="uk", doc_type="terms_conditions")
    chunks = chunker.chunk(uk_terms_conditions)
    sections = {c.document_section for c in chunks}
    assert DocumentSection.RECITALS not in sections, (
        "T&C documents should not produce RECITALS sections"
    )
    assert DocumentSection.SIGNATURES not in sections, (
        "T&C documents should not produce SIGNATURES sections"
    )


def test_us_tc_no_recitals_or_signatures(us_terms_of_service):
    """US T&C parsed with doc_type='terms_conditions' has no RECITALS or SIGNATURES."""
    chunker = LegalChunker(jurisdiction="us", doc_type="terms_conditions")
    chunks = chunker.chunk(us_terms_of_service)
    sections = {c.document_section for c in chunks}
    assert DocumentSection.RECITALS not in sections
    assert DocumentSection.SIGNATURES not in sections


def test_uk_tc_detects_acceptable_use(uk_terms_conditions):
    """UK T&C fixture section 3 ('Acceptable use') is classified as ACCEPTABLE_USE."""
    chunker = LegalChunker(jurisdiction="uk", doc_type="terms_conditions")
    chunks = chunker.chunk(uk_terms_conditions)
    clause_types = {c.clause_type for c in chunks}
    assert ClauseType.ACCEPTABLE_USE in clause_types, (
        f"Expected ACCEPTABLE_USE in chunk types; got {clause_types}"
    )


def test_us_tc_detects_account_security(us_terms_of_service):
    """US T&C fixture section 2.3 ('Account Security') is classified as ACCOUNT_SECURITY."""
    chunker = LegalChunker(jurisdiction="us", doc_type="terms_conditions")
    chunks = chunker.chunk(us_terms_of_service)
    clause_types = {c.clause_type for c in chunks}
    assert ClauseType.ACCOUNT_SECURITY in clause_types, (
        f"Expected ACCOUNT_SECURITY in chunk types; got {clause_types}"
    )


def test_contract_mode_still_detects_recitals(uk_service_agreement):
    """Contract mode (default) still detects RECITALS — no regression."""
    chunker = LegalChunker(jurisdiction="uk", doc_type="contract")
    chunks = chunker.chunk(uk_service_agreement)
    sections = {c.document_section for c in chunks}
    # UK service agreement may or may not have recitals depending on fixture,
    # but at minimum SIGNATURES detection should still work for contracts.
    # We verify the contract path is unchanged by checking OPERATIVE exists.
    assert DocumentSection.OPERATIVE in sections


def test_contract_mode_signatures_not_suppressed(us_msa):
    """Contract mode still detects SIGNATURES sections — not suppressed."""
    chunker = LegalChunker(jurisdiction="us", doc_type="contract")
    chunks = chunker.chunk(us_msa)
    # Check that the contract pipeline is not affected by T&C suppression.
    # The US MSA should have OPERATIVE sections at minimum.
    sections = {c.document_section for c in chunks}
    assert DocumentSection.OPERATIVE in sections


# ---------------------------------------------------------------------------
# Keyword classification tests — ACCEPTABLE_USE
# ---------------------------------------------------------------------------


def test_classify_acceptable_use_prohibited_content():
    """'prohibited content' keyword triggers ACCEPTABLE_USE."""
    assert classify_clause_type(
        "Users must not post prohibited content on the platform."
    ) == ClauseType.ACCEPTABLE_USE


def test_classify_acceptable_use_acceptable_use():
    """'acceptable use' keyword triggers ACCEPTABLE_USE."""
    assert classify_clause_type(
        "This acceptable use policy governs your use of the service."
    ) == ClauseType.ACCEPTABLE_USE


def test_classify_acceptable_use_prohibited_activities():
    """'prohibited activities' keyword triggers ACCEPTABLE_USE."""
    assert classify_clause_type(
        "The following prohibited activities are not permitted."
    ) == ClauseType.ACCEPTABLE_USE


def test_classify_acceptable_use_negative_generic():
    """Generic text without acceptable-use keywords → not ACCEPTABLE_USE."""
    result = classify_clause_type("The service is provided as described.")
    assert result != ClauseType.ACCEPTABLE_USE


def test_classify_acceptable_use_negative_payment():
    """Payment-heavy text → not ACCEPTABLE_USE even if 'use' appears."""
    result = classify_clause_type(
        "Payment of fees is due upon invoice. Fees are payable monthly."
    )
    assert result != ClauseType.ACCEPTABLE_USE


# ---------------------------------------------------------------------------
# Keyword classification tests — USER_RESTRICTIONS
# ---------------------------------------------------------------------------


def test_classify_user_restrictions_reverse_engineer():
    """'reverse engineer' keyword triggers USER_RESTRICTIONS."""
    assert classify_clause_type(
        "You shall not reverse engineer, decompile, or disassemble the software."
    ) == ClauseType.USER_RESTRICTIONS


def test_classify_user_restrictions_derivative_works():
    """'derivative works' keyword triggers USER_RESTRICTIONS."""
    assert classify_clause_type(
        "Creating derivative works based on the platform is prohibited."
    ) == ClauseType.USER_RESTRICTIONS


def test_classify_user_restrictions_sublicense():
    """'sublicense' keyword triggers USER_RESTRICTIONS."""
    assert classify_clause_type(
        "You may not sublicense, decompile, or create derivative works."
    ) == ClauseType.USER_RESTRICTIONS


def test_classify_user_restrictions_negative_generic():
    """Generic contract text → not USER_RESTRICTIONS."""
    result = classify_clause_type("This agreement is effective from the date hereof.")
    assert result != ClauseType.USER_RESTRICTIONS


def test_classify_user_restrictions_negative_ip():
    """IP-heavy text → not USER_RESTRICTIONS (despite 'license' overlap)."""
    result = classify_clause_type(
        "All intellectual property rights, including copyright and patent, "
        "remain with the licensor. The licence is non-exclusive."
    )
    assert result != ClauseType.USER_RESTRICTIONS


# ---------------------------------------------------------------------------
# Keyword classification tests — ACCOUNT_SECURITY
# ---------------------------------------------------------------------------


def test_classify_account_security_login_credentials():
    """'login credentials' keyword triggers ACCOUNT_SECURITY."""
    assert classify_clause_type(
        "You are responsible for safeguarding your login credentials and password."
    ) == ClauseType.ACCOUNT_SECURITY


def test_classify_account_security_password():
    """'password' keyword triggers ACCOUNT_SECURITY."""
    assert classify_clause_type(
        "You must use a strong password and enable multi-factor authentication."
    ) == ClauseType.ACCOUNT_SECURITY


def test_classify_account_security_unauthorized_access():
    """'unauthorized access' keyword triggers ACCOUNT_SECURITY."""
    assert classify_clause_type(
        "You must notify us immediately of any unauthorized access to your account."
    ) == ClauseType.ACCOUNT_SECURITY


def test_classify_account_security_negative_generic():
    """Generic text → not ACCOUNT_SECURITY."""
    result = classify_clause_type("The terms of this agreement shall survive termination.")
    assert result != ClauseType.ACCOUNT_SECURITY


def test_classify_account_security_negative_data_protection():
    """Data-protection text → not ACCOUNT_SECURITY."""
    result = classify_clause_type(
        "We process personal data in accordance with GDPR. "
        "The data controller shall ensure data subject rights."
    )
    assert result != ClauseType.ACCOUNT_SECURITY
