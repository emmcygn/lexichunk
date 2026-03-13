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


def test_contract_mode_still_detects_recitals():
    """Contract mode detects RECITALS — suppression only applies to T&C.

    Uses synthetic text since the real fixtures may not have recitals.
    """
    text = (
        "1. Background\n\n"
        "WHEREAS the Supplier has agreed to provide services.\n\n"
        "2. Services\n\n"
        "2.1 The Supplier shall provide the services described herein.\n"
    )
    chunker = LegalChunker(jurisdiction="uk", doc_type="contract")
    chunks = chunker.chunk(text)
    sections = {c.document_section for c in chunks}
    assert DocumentSection.RECITALS in sections, (
        "Contract mode must detect RECITALS — suppression should only apply to T&C"
    )


def test_contract_mode_signatures_not_suppressed():
    """Contract mode detects SIGNATURES — suppression only applies to T&C.

    Uses synthetic text with a "Signature Page" heading that the structure
    parser will detect as a clause header with signature keywords.
    """
    text = (
        "1. Services\n\n"
        "1.1 The Supplier shall provide the services described herein.\n\n"
        "2. Signature Page\n\n"
        "IN WITNESS WHEREOF the parties have executed this Agreement.\n"
    )
    chunker = LegalChunker(
        jurisdiction="uk", doc_type="contract", min_chunk_size=1
    )
    chunks = chunker.chunk(text)
    sections = {c.document_section for c in chunks}
    assert DocumentSection.SIGNATURES in sections, (
        f"Contract mode must detect SIGNATURES — suppression should only apply to T&C. "
        f"Got sections: {sections}"
    )


def test_tc_mode_suppresses_recitals_on_synthetic():
    """T&C mode suppresses RECITALS even when the text contains recital keywords."""
    text = (
        "1. Background\n\n"
        "WHEREAS the user has agreed to use the platform.\n\n"
        "2. Services\n\n"
        "2.1 The platform provides analytics services.\n"
    )
    chunker = LegalChunker(jurisdiction="uk", doc_type="terms_conditions")
    chunks = chunker.chunk(text)
    sections = {c.document_section for c in chunks}
    assert DocumentSection.RECITALS not in sections, (
        "T&C mode must suppress RECITALS detection"
    )


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
