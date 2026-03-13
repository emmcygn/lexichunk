"""Tests for DefinitionsExtractor."""


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


# ---------------------------------------------------------------------------
# Single-quote definition tests
# ---------------------------------------------------------------------------


def test_single_quote_definition():
    """Straight single-quoted term with 'means' keyword is extracted."""
    text = "'Supplier' means the entity providing services."
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Supplier" in result
    dt = result["Supplier"]
    assert isinstance(dt, DefinedTerm)
    assert dt.term == "Supplier"


def test_single_quote_means():
    """Single-quoted multi-word term with 'means' keyword is extracted."""
    text = "'Confidential Information' means any information disclosed by either party."
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Confidential Information" in result
    dt = result["Confidential Information"]
    assert dt.term == "Confidential Information"


def test_mixed_quotes():
    """Document with both double-quoted and single-quoted definitions extracts both."""
    text = (
        '"Term One" means the first defined term.\n\n'
        "'Term Two' means the second defined term."
    )
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Term One" in result, f"Missing 'Term One'; got {list(result.keys())}"
    assert "Term Two" in result, f"Missing 'Term Two'; got {list(result.keys())}"


# ---------------------------------------------------------------------------
# Inline / parenthetical definition tests
# ---------------------------------------------------------------------------


def test_inline_parenthetical_definition():
    """Inline parenthetical: '(each a "Party")' extracts 'Party'."""
    text = 'The Buyer and the Seller (each a "Party" and together the "Parties") agree.'
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Party" in result, f"Missing 'Party'; got {list(result.keys())}"
    assert "Parties" in result, f"Missing 'Parties'; got {list(result.keys())}"


def test_inline_parenthetical_single_term():
    """Inline parenthetical with a single quoted term."""
    text = 'This agreement (the "Agreement") is entered into.'
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Agreement" in result, f"Missing 'Agreement'; got {list(result.keys())}"


def test_parenthetical_backref():
    """Parenthetical back-reference: 'the Borrower (as defined in Section 1.1)'."""
    text = "the Borrower (as defined in Section 1.1) shall pay the fees."
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Borrower" in result, f"Missing 'Borrower'; got {list(result.keys())}"


def test_shall_have_the_meaning():
    """'shall have the meaning' trigger phrase extracts the term."""
    text = '"Term" shall have the meaning set forth in Section 2.1.'
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Term" in result, f"Missing 'Term'; got {list(result.keys())}"


# ---------------------------------------------------------------------------
# Skip list tests
# ---------------------------------------------------------------------------


def test_skip_list_rejects_common_words():
    """Common false-positive words like 'Each', 'Any', 'Such' are rejected."""
    from lexichunk.parsers.definitions import _SKIP_TERMS

    reject_words = ["Each", "Any", "Such", "All", "No", "If", "Where", "When",
                     "Upon", "In", "For", "By", "At", "On", "To", "Of", "Or",
                     "And", "But", "Not", "It", "We", "You", "They", "Our",
                     "Your", "Its"]
    for word in reject_words:
        assert word in _SKIP_TERMS, f"'{word}' should be in _SKIP_TERMS"


def test_skip_list_rejects_each_in_extraction():
    """'Each' should not be extracted even when it appears in definition form."""
    text = '"Each" means every individual party to this agreement.'
    extractor = _make_extractor()
    result = extractor.extract(text)
    assert "Each" not in result
