"""Tests for DefinitionsExtractor."""

import pytest

from lexichunk.models import DefinedTerm, Jurisdiction
from lexichunk.parsers.definitions import DefinitionsExtractor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_extractor(jurisdiction: Jurisdiction = Jurisdiction.UK) -> DefinitionsExtractor:
    return DefinitionsExtractor(jurisdiction)


# ---------------------------------------------------------------------------
# Basic pattern tests
# ---------------------------------------------------------------------------


def test_extract_straight_quotes():
    """Straight-quoted term with 'means' keyword is extracted."""
    text = '"Services" means the services to be provided by the Supplier.'
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Services" in result
    dt = result["Services"]
    assert isinstance(dt, DefinedTerm)
    assert dt.term == "Services"


def test_extract_curly_quotes():
    """Curly-quoted term with 'means' keyword is extracted."""
    text = "\u201cServices\u201d means the services to be provided by the Supplier."
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Services" in result


def test_extract_shall_mean():
    """'shall mean' trigger phrase extracts the term."""
    text = '"Affiliate" shall mean any entity that directly or indirectly controls the party.'
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Affiliate" in result


def test_extract_has_the_meaning():
    """'has the meaning' trigger phrase extracts the term."""
    text = '"Agreement" has the meaning ascribed to it in the preamble hereof.'
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Agreement" in result


def test_skip_short_term():
    """Single-character terms (len < 2) are not extracted."""
    text = '"A" means something here that is defined.'
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "A" not in result


def test_skip_common_word_the():
    """The stop-word 'The' is not extracted even when quoted and followed by means."""
    text = '"The" means the definite article used in legal writing.'
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "The" not in result


def test_extract_from_uk_fixture(uk_service_agreement):
    """UK fixture should yield at least 5 defined terms.

    The uk_service_agreement.txt defines: Affiliate, Authorised Users,
    Business Day, Commencement Date, Confidential Information,
    Data Protection Legislation, Fees, Intellectual Property Rights,
    Services, Service Levels, Term.
    """
    extractor = _make_extractor(Jurisdiction.UK)
    result = extractor.extract(uk_service_agreement)
    assert len(result) >= 5, (
        f"Expected at least 5 defined terms; got {len(result)}: {list(result.keys())}"
    )


def test_extract_from_us_fixture(us_msa):
    """US fixture should yield at least 5 defined terms.

    The us_msa.txt defines: Affiliate, Authorized User, Confidential
    Information, Documentation, Intellectual Property Rights, Order Form,
    Provider Technology, Services, Statement of Work / SOW, Term.
    """
    extractor = _make_extractor(Jurisdiction.US)
    result = extractor.extract(us_msa)
    assert len(result) >= 5, (
        f"Expected at least 5 defined terms; got {len(result)}: {list(result.keys())}"
    )


def test_defined_term_has_source_clause(uk_service_agreement):
    """Every extracted DefinedTerm must carry a non-empty source_clause."""
    extractor = _make_extractor(Jurisdiction.UK)
    result = extractor.extract(uk_service_agreement)
    assert len(result) > 0
    for term, dt in result.items():
        assert dt.source_clause, (
            f"Term '{term}' has an empty source_clause"
        )


def test_defined_term_has_definition(uk_service_agreement):
    """Every extracted DefinedTerm must carry a non-empty definition string."""
    extractor = _make_extractor(Jurisdiction.UK)
    result = extractor.extract(uk_service_agreement)
    assert len(result) > 0
    for term, dt in result.items():
        assert dt.definition.strip(), (
            f"Term '{term}' has an empty definition"
        )


def test_no_definitions_returns_empty():
    """Text with no definition patterns should return an empty dict."""
    text = "The quick brown fox jumps over the lazy dog. No definitions here."
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert result == {}


# ---------------------------------------------------------------------------
# Cross-jurisdiction extraction
# ---------------------------------------------------------------------------


def test_affiliate_defined_in_uk_fixture(uk_service_agreement):
    """'Affiliate' should be among the extracted terms from the UK fixture."""
    extractor = _make_extractor(Jurisdiction.UK)
    result = extractor.extract(uk_service_agreement)
    assert "Affiliate" in result


def test_affiliate_defined_in_us_fixture(us_msa):
    """'Affiliate' should be among the extracted terms from the US fixture."""
    extractor = _make_extractor(Jurisdiction.US)
    result = extractor.extract(us_msa)
    assert "Affiliate" in result


def test_services_defined_in_uk_fixture(uk_service_agreement):
    """'Services' should be among the extracted terms from the UK fixture."""
    extractor = _make_extractor(Jurisdiction.UK)
    result = extractor.extract(uk_service_agreement)
    assert "Services" in result


def test_confidential_information_defined_in_uk_fixture(uk_service_agreement):
    """'Confidential Information' should be extracted from the UK fixture."""
    extractor = _make_extractor(Jurisdiction.UK)
    result = extractor.extract(uk_service_agreement)
    assert "Confidential Information" in result


def test_fees_defined_in_uk_fixture(uk_service_agreement):
    """'Fees' should be extracted from the UK fixture."""
    extractor = _make_extractor(Jurisdiction.UK)
    result = extractor.extract(uk_service_agreement)
    assert "Fees" in result
