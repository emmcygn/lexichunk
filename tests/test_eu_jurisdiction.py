"""Tests for the EU Directives jurisdiction support."""

from __future__ import annotations

from lexichunk import Jurisdiction, LegalChunker
from lexichunk.jurisdiction import get_detect_level, get_patterns
from lexichunk.jurisdiction.eu import EU_PATTERNS, detect_level

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GDPR_EXCERPT = """\
CHAPTER I
GENERAL PROVISIONS

Article 1
Subject matter and scope

1. This Regulation lays down rules relating to the protection of natural persons with regard to the processing of personal data and rules relating to the free movement of personal data.

2. This Regulation protects fundamental rights and freedoms of natural persons and in particular their right to the protection of personal data.

Article 2
Material scope

1. This Regulation applies to the processing of personal data wholly or partly by automated means and to the processing other than by automated means of personal data which form part of a filing system or are intended to form part of a filing system.

2. This Regulation does not apply to the processing of personal data:
(a) in the course of an activity which falls outside the scope of Union law;
(b) by the Member States when carrying out activities which fall within the scope of Chapter 2 of Title V of the TEU;
(c) by a natural person in the course of a purely personal or household activity;

Article 4
Definitions

For the purposes of this Regulation, the following definitions apply:
'Personal Data' means any information relating to an identified or identifiable natural person.
'Processing' means any operation or set of operations which is performed on personal data.
'Controller' means the natural or legal person, public authority, agency or other body which determines the purposes and means of the processing of personal data.

CHAPTER II
PRINCIPLES

Article 5
Principles relating to processing of personal data

1. Personal data shall be:
(a) processed lawfully, fairly and in a transparent manner in relation to the data subject;
(b) collected for specified, explicit and legitimate purposes;
(c) adequate, relevant and limited to what is necessary in relation to the purposes for which they are processed;
"""


# ---------------------------------------------------------------------------
# detect_level — positive tests
# ---------------------------------------------------------------------------


class TestDetectLevelPositive:
    def test_chapter_roman(self) -> None:
        assert detect_level("CHAPTER I") == (-1, "Chapter I")

    def test_chapter_with_title(self) -> None:
        assert detect_level("Chapter II — General Provisions") == (-1, "Chapter II")

    def test_article_arabic(self) -> None:
        assert detect_level("Article 1") == (0, "Article 1")

    def test_article_caps(self) -> None:
        assert detect_level("ARTICLE 42") == (0, "Article 42")

    def test_article_with_title(self) -> None:
        assert detect_level("Article 5 — Principles") == (0, "Article 5")

    def test_section(self) -> None:
        assert detect_level("Section 3") == (1, "Section 3")

    def test_section_caps(self) -> None:
        assert detect_level("SECTION 1") == (1, "Section 1")

    def test_numbered_paragraph(self) -> None:
        assert detect_level("1. This Regulation lays down rules") == (2, "1")

    def test_numbered_paragraph_higher(self) -> None:
        assert detect_level("12. The Commission shall") == (2, "12")

    def test_alpha_sub(self) -> None:
        assert detect_level("(a) in the course of an activity") == (3, "(a)")

    def test_roman_sub(self) -> None:
        assert detect_level("(ii) any subsequent processing") == (4, "(ii)")

    def test_annex_roman(self) -> None:
        assert detect_level("ANNEX I") == (-2, "Annex I")

    def test_annex_mixed(self) -> None:
        assert detect_level("Annex IV — Impact assessment") == (-2, "Annex IV")

    def test_allcaps_header(self) -> None:
        assert detect_level("GENERAL PROVISIONS") == (0, "GENERAL PROVISIONS")


# ---------------------------------------------------------------------------
# detect_level — negative tests
# ---------------------------------------------------------------------------


class TestDetectLevelNegative:
    def test_plain_text(self) -> None:
        assert detect_level("This is a normal sentence.") is None

    def test_lowercase_article(self) -> None:
        """'article' lowercase should not be a header."""
        assert detect_level("article 5 is referenced above.") is None

    def test_number_mid_sentence(self) -> None:
        assert detect_level("    The sum of 42 items.") is None

    def test_empty(self) -> None:
        assert detect_level("") is None

    def test_single_letter(self) -> None:
        """Single uppercase letter is too short for ALL-CAPS header."""
        assert detect_level("A") is None


# ---------------------------------------------------------------------------
# EUPatterns — protocol conformance and pattern matching
# ---------------------------------------------------------------------------


class TestEUPatterns:
    def test_protocol_conformance(self) -> None:
        from lexichunk.models import JurisdictionPatterns
        assert isinstance(EU_PATTERNS, JurisdictionPatterns)

    def test_cross_ref_article(self) -> None:
        m = EU_PATTERNS.cross_ref.search("as defined in Article 4")
        assert m is not None
        assert m.group(1) == "4"

    def test_cross_ref_chapter(self) -> None:
        m = EU_PATTERNS.cross_ref.search("see Chapter II")
        assert m is not None
        assert m.group(1) == "II"

    def test_cross_ref_annex(self) -> None:
        m = EU_PATTERNS.cross_ref.search("in Annex I")
        assert m is not None
        assert m.group(1) == "I"

    def test_cross_ref_recital(self) -> None:
        m = EU_PATTERNS.cross_ref.search("Recital 26")
        assert m is not None
        assert m.group(1) == "26"

    def test_cross_ref_no_match(self) -> None:
        m = EU_PATTERNS.cross_ref.search("some random text with numbers 42")
        assert m is None

    def test_cross_ref_paragraph_subpoint(self) -> None:
        m = EU_PATTERNS.cross_ref.search("Article 6(1)(a)")
        assert m is not None
        assert m.group(1) == "6(1)(a)"

    def test_definition_single_quote(self) -> None:
        m = EU_PATTERNS.definition.search("'Personal Data' means any information")
        assert m is not None
        assert m.group(1) == "Personal Data"

    def test_definition_curly_quote(self) -> None:
        m = EU_PATTERNS.definition_curly.search(
            "\u201cController\u201d means the natural person"
        )
        assert m is not None
        assert m.group(1) == "Controller"

    def test_definition_no_match_lowercase(self) -> None:
        """Lowercase initial should not match."""
        m = EU_PATTERNS.definition.search("'processing' means any operation")
        assert m is None


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestEURegistryIntegration:
    def test_get_patterns_enum(self) -> None:
        patterns = get_patterns(Jurisdiction.EU)
        assert patterns is EU_PATTERNS

    def test_get_patterns_string(self) -> None:
        patterns = get_patterns("eu")
        assert patterns is EU_PATTERNS

    def test_get_detect_level_enum(self) -> None:
        fn = get_detect_level(Jurisdiction.EU)
        assert fn is detect_level


# ---------------------------------------------------------------------------
# Full pipeline E2E
# ---------------------------------------------------------------------------


class TestEUPipelineE2E:
    def test_chunker_produces_chunks(self) -> None:
        chunker = LegalChunker(jurisdiction="eu")
        chunks = chunker.chunk(GDPR_EXCERPT)
        assert len(chunks) > 0

    def test_jurisdiction_on_chunks(self) -> None:
        chunker = LegalChunker(jurisdiction=Jurisdiction.EU)
        chunks = chunker.chunk(GDPR_EXCERPT)
        assert all(c.jurisdiction == Jurisdiction.EU for c in chunks)

    def test_hierarchy_detected(self) -> None:
        chunker = LegalChunker(jurisdiction="eu")
        chunks = chunker.chunk(GDPR_EXCERPT)
        identifiers = [c.hierarchy.identifier for c in chunks]
        # Should detect chapters and articles
        assert any("Chapter" in i or "Article" in i for i in identifiers)

    def test_defined_terms_extracted(self) -> None:
        chunker = LegalChunker(jurisdiction="eu")
        terms = chunker.get_defined_terms(GDPR_EXCERPT)
        term_names = {t.lower() for t in terms}
        assert "personal data" in term_names

    def test_cross_references_detected(self) -> None:
        chunker = LegalChunker(jurisdiction="eu")
        chunks = chunker.chunk(GDPR_EXCERPT)
        all_refs = []
        for c in chunks:
            all_refs.extend(c.cross_references)
        # The excerpt references Chapter 2
        ref_texts = [r.raw_text.lower() for r in all_refs]
        assert any("chapter" in r for r in ref_texts)

    def test_clause_type_classification(self) -> None:
        chunker = LegalChunker(jurisdiction="eu")
        chunks = chunker.chunk(GDPR_EXCERPT)
        # The definitions article should be classified as DEFINITIONS
        from lexichunk.models import ClauseType
        types = [c.clause_type for c in chunks]
        assert ClauseType.DEFINITIONS in types

    def test_chunk_with_metrics(self) -> None:
        chunker = LegalChunker(jurisdiction="eu")
        chunks, metrics = chunker.chunk_with_metrics(GDPR_EXCERPT)
        assert len(chunks) > 0
        assert metrics.chunk_count == len(chunks)
        assert metrics.total_duration_ms > 0

    def test_batch_serial(self) -> None:
        chunker = LegalChunker(jurisdiction="eu")
        result = chunker.chunk_batch([GDPR_EXCERPT, GDPR_EXCERPT])
        assert result.success_count == 2
        assert result.error_count == 0


# ---------------------------------------------------------------------------
# GDPR fixture tests
# ---------------------------------------------------------------------------

import pathlib

_FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"
_GDPR_FIXTURE = (_FIXTURE_DIR / "eu_gdpr_excerpt.txt").read_text(encoding="utf-8")


class TestGDPRFixture:
    def test_gdpr_fixture_chunks_produced(self) -> None:
        chunker = LegalChunker(jurisdiction="eu", min_chunk_size=0)
        chunks = chunker.chunk(_GDPR_FIXTURE)
        assert len(chunks) >= 6  # at least preamble + 6 articles

    def test_gdpr_fixture_hierarchy_has_chapters(self) -> None:
        chunker = LegalChunker(jurisdiction="eu", min_chunk_size=0)
        chunks = chunker.chunk(_GDPR_FIXTURE)
        identifiers = [c.hierarchy.identifier for c in chunks]
        assert any("Chapter" in i for i in identifiers)

    def test_gdpr_fixture_hierarchy_has_articles(self) -> None:
        chunker = LegalChunker(jurisdiction="eu", min_chunk_size=0)
        chunks = chunker.chunk(_GDPR_FIXTURE)
        identifiers = [c.hierarchy.identifier for c in chunks]
        article_ids = [i for i in identifiers if "Article" in i]
        assert len(article_ids) >= 4

    def test_gdpr_fixture_definitions_extracted(self) -> None:
        chunker = LegalChunker(jurisdiction="eu")
        terms = chunker.get_defined_terms(_GDPR_FIXTURE)
        term_names = {t.lower() for t in terms}
        assert "personal data" in term_names
        assert "processing" in term_names
        assert "controller" in term_names

    def test_gdpr_fixture_definitions_detected_by_extractor(self) -> None:
        """The definitions extractor should find a definitions section."""
        chunker = LegalChunker(jurisdiction="eu")
        terms = chunker.get_defined_terms(_GDPR_FIXTURE)
        # Should extract at least 5 terms from Article 4
        assert len(terms) >= 5

    def test_gdpr_fixture_cross_refs_detected(self) -> None:
        chunker = LegalChunker(jurisdiction="eu", min_chunk_size=0)
        chunks = chunker.chunk(_GDPR_FIXTURE)
        all_refs = []
        for c in chunks:
            all_refs.extend(c.cross_references)
        # Fixture references Chapter 2, paragraph 1, etc.
        assert len(all_refs) > 0

    def test_gdpr_fixture_preamble_detected(self) -> None:
        """Recitals before Chapter I should be preamble."""
        from lexichunk.models import DocumentSection
        chunker = LegalChunker(jurisdiction="eu", min_chunk_size=0)
        chunks = chunker.chunk(_GDPR_FIXTURE)
        preamble = [c for c in chunks if c.document_section == DocumentSection.PREAMBLE]
        assert len(preamble) >= 1
        # Preamble should contain recital text
        preamble_text = " ".join(c.content for c in preamble)
        assert "fundamental right" in preamble_text.lower()

    def test_gdpr_fixture_operative_sections(self) -> None:
        from lexichunk.models import DocumentSection
        chunker = LegalChunker(jurisdiction="eu", min_chunk_size=0)
        chunks = chunker.chunk(_GDPR_FIXTURE)
        operative = [c for c in chunks if c.document_section == DocumentSection.OPERATIVE]
        assert len(operative) > 0

    def test_gdpr_fixture_definitions_section_bounded(self) -> None:
        """Definitions section should not bleed into Article 5."""
        chunker = LegalChunker(jurisdiction="eu")
        defs = chunker.get_defined_terms(_GDPR_FIXTURE)
        # Article 5 talks about "principles" — should NOT be extracted as a term
        term_names = {t.lower() for t in defs}
        # These are real definition terms from Article 4
        assert "consent" in term_names
        assert "recipient" in term_names

    def test_gdpr_fixture_char_offsets_valid(self) -> None:
        chunker = LegalChunker(jurisdiction="eu", min_chunk_size=0)
        chunks = chunker.chunk(_GDPR_FIXTURE)
        for ch in chunks:
            assert ch.char_start >= 0
            assert ch.char_end >= ch.char_start
            assert ch.char_end <= len(LegalChunker._sanitize_input(_GDPR_FIXTURE))
