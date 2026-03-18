"""Adversarial tests for v0.8.0 — EU jurisdiction, ReDoS guards, coverage.

Written as a SEPARATE PASS after implementation (L014).
"""

from __future__ import annotations

import re

from lexichunk import Jurisdiction, LegalChunker
from lexichunk.jurisdiction import (
    _JURISDICTION_REGISTRY,
    get_detect_level,
    get_patterns,
)
from lexichunk.jurisdiction.eu import EU_PATTERNS, EUPatterns
from lexichunk.jurisdiction.eu import detect_level as eu_detect
from lexichunk.models import ClauseType, JurisdictionPatterns

# ===========================================================================
# EU DETECT_LEVEL EDGE CASES
# ===========================================================================


class TestEUDetectLevelEdgeCases:
    def test_indented_article(self) -> None:
        """Indented articles should still be detected (lstrip is applied)."""
        result = eu_detect("    Article 5")
        assert result == (0, "Article 5")

    def test_article_zero(self) -> None:
        """Article 0 is unusual but should be detected."""
        result = eu_detect("Article 0")
        assert result == (0, "Article 0")

    def test_chapter_lowercase_not_detected(self) -> None:
        """'chapter' lowercase should NOT be a header."""
        assert eu_detect("chapter I is about scope.") is None

    def test_section_lowercase_not_detected(self) -> None:
        """'section 1' lowercase should NOT be a header."""
        assert eu_detect("section 1 describes the rules.") is None

    def test_annex_lowercase_not_detected(self) -> None:
        """'annex' lowercase should NOT be a header."""
        assert eu_detect("annex I is referenced.") is None

    def test_article_text_no_number(self) -> None:
        """'Article' without a number should NOT match."""
        assert eu_detect("Article about data protection") is None

    def test_paragraph_number_only(self) -> None:
        """'42.' at line start followed by non-whitespace = paragraph."""
        result = eu_detect("42. The processor shall")
        assert result == (2, "42")

    def test_paragraph_no_space_after_dot(self) -> None:
        """'1.Word' should NOT match (no space after dot)."""
        assert eu_detect("1.Word without space") is None

    def test_allcaps_single_word(self) -> None:
        """Single ALL-CAPS word >=2 chars should be detected."""
        result = eu_detect("PRINCIPLES")
        assert result == (0, "PRINCIPLES")

    def test_allcaps_excluded_keywords(self) -> None:
        """ALL-CAPS keywords in the exclusion list should NOT match."""
        assert eu_detect("ARTICLE") is None  # len < 2? No, len=7 but starts with ARTICLE
        # Actually ARTICLE starts with 'ARTICLE' so it's excluded
        result = eu_detect("ARTICLE")
        assert result is None

    def test_allcaps_with_numbers_no_match(self) -> None:
        """ALL-CAPS text with numbers should NOT match fullmatch."""
        assert eu_detect("ARTICLE 5") is not None  # This matches article pattern
        assert eu_detect("ABC123") is None  # Has digits, won't match [A-Z \t]+ fullmatch


# ===========================================================================
# EU PATTERNS PROTOCOL INVARIANTS
# ===========================================================================


class TestEUPatternsProtocol:
    def test_all_protocol_attributes_exist(self) -> None:
        """Verify all six JurisdictionPatterns attributes are present."""
        p = EUPatterns()
        assert hasattr(p, "cross_ref")
        assert hasattr(p, "definition")
        assert hasattr(p, "definition_curly")
        assert hasattr(p, "definitions_headers")
        assert hasattr(p, "boilerplate_headers")
        assert hasattr(p, "signature_markers")

    def test_isinstance_check(self) -> None:
        assert isinstance(EUPatterns(), JurisdictionPatterns)

    def test_cross_ref_is_compiled_pattern(self) -> None:
        assert isinstance(EU_PATTERNS.cross_ref, re.Pattern)

    def test_definition_is_compiled_pattern(self) -> None:
        assert isinstance(EU_PATTERNS.definition, re.Pattern)


# ===========================================================================
# REGISTRY INTEGRITY — EU IS BUILT-IN
# ===========================================================================


class TestEURegistryIntegrity:
    def test_eu_in_registry(self) -> None:
        assert "eu" in _JURISDICTION_REGISTRY

    def test_eu_patterns_from_enum(self) -> None:
        patterns = get_patterns(Jurisdiction.EU)
        assert patterns is EU_PATTERNS

    def test_eu_detect_level_from_enum(self) -> None:
        fn = get_detect_level(Jurisdiction.EU)
        assert fn is eu_detect

    def test_eu_enum_value(self) -> None:
        assert Jurisdiction.EU.value == "eu"

    def test_eu_string_resolves_to_enum(self) -> None:
        """LegalChunker('eu') should resolve to Jurisdiction.EU enum."""
        chunker = LegalChunker(jurisdiction="eu")
        assert chunker._jurisdiction == Jurisdiction.EU


# ===========================================================================
# EU PIPELINE — EDGE CASES
# ===========================================================================


class TestEUPipelineEdgeCases:
    def test_empty_input(self) -> None:
        chunker = LegalChunker(jurisdiction="eu")
        assert chunker.chunk("") == []

    def test_whitespace_only(self) -> None:
        chunker = LegalChunker(jurisdiction="eu")
        assert chunker.chunk("   \n\n  ") == []

    def test_no_structure_fallback(self) -> None:
        """Plain text with no EU headers should trigger fallback chunker."""
        chunker = LegalChunker(jurisdiction="eu")
        text = "This is plain text without any structural headers. " * 50
        chunks = chunker.chunk(text)
        assert len(chunks) > 0

    def test_single_article(self) -> None:
        text = "Article 1\nThis Regulation applies to all data.\n"
        chunker = LegalChunker(jurisdiction="eu")
        chunks = chunker.chunk(text)
        assert len(chunks) == 1
        assert "Article 1" in chunks[0].hierarchy.identifier

    def test_mixed_case_not_confused(self) -> None:
        """'ARTICLE 1' and 'Article 2' should both be detected as articles."""
        text = (
            "ARTICLE 1\n"
            "This Regulation lays down rules relating to the protection of natural "
            "persons with regard to the processing of personal data and rules relating "
            "to the free movement of personal data within the Union.\n\n"
            "Article 2\n"
            "This Regulation applies to the processing of personal data wholly or "
            "partly by automated means and to the processing other than by automated "
            "means of personal data which form part of a filing system.\n"
        )
        chunker = LegalChunker(jurisdiction="eu", min_chunk_size=0)
        chunks = chunker.chunk(text)
        identifiers = [c.hierarchy.identifier for c in chunks]
        assert "Article 1" in identifiers
        assert "Article 2" in identifiers

    def test_eu_definitions_extraction(self) -> None:
        """EU definitions use single quotes — verify extraction."""
        text = (
            "Article 4\nDefinitions\n\n"
            "'Controller' means the natural or legal person.\n"
            "'Processor' means a natural or legal person which processes.\n"
        )
        chunker = LegalChunker(jurisdiction="eu")
        terms = chunker.get_defined_terms(text)
        assert "Controller" in terms
        assert "Processor" in terms

    def test_eu_data_protection_classification(self) -> None:
        """GDPR-like text should be classified as DATA_PROTECTION."""
        text = (
            "Article 6\nLawfulness of processing\n\n"
            "1. Processing of personal data shall be lawful only if the data subject "
            "has given consent to the processing of his or her personal data. "
            "The data controller shall be able to demonstrate that the data subject "
            "has consented to the processing.\n"
        )
        chunker = LegalChunker(jurisdiction="eu")
        chunks = chunker.chunk(text)
        types = {c.clause_type for c in chunks}
        assert ClauseType.DATA_PROTECTION in types

    def test_chunk_iter_eu(self) -> None:
        text = "Article 1\nFirst rule.\n\nArticle 2\nSecond rule.\n"
        chunker = LegalChunker(jurisdiction="eu")
        chunks_list = list(chunker.chunk_iter(text))
        assert len(chunks_list) == len(chunker.chunk(text))

    def test_batch_parallel_eu(self) -> None:
        """EU is a built-in Jurisdiction enum, so parallel batch should work."""
        text = "Article 1\nFirst rule.\n\nArticle 2\nSecond rule.\n"
        chunker = LegalChunker(jurisdiction="eu")
        result = chunker.chunk_batch([text] * 5, workers=2)
        assert result.success_count == 5
        assert result.error_count == 0


# ===========================================================================
# CROSS-REFERENCE PATTERNS — EU-SPECIFIC
# ===========================================================================


class TestEUCrossRefEdgeCases:
    def test_article_with_paragraph_subpoint(self) -> None:
        """'Article 6(1)(a)' should capture the full identifier."""
        m = EU_PATTERNS.cross_ref.search("pursuant to Article 6(1)(a)")
        assert m is not None
        assert m.group(1) == "6(1)(a)"

    def test_plural_articles(self) -> None:
        m = EU_PATTERNS.cross_ref.search("Articles 5 and 6")
        assert m is not None

    def test_annex_singular_and_plural(self) -> None:
        """Both 'Annex' and 'Annexes' should match."""
        m1 = EU_PATTERNS.cross_ref.search("see Annex I")
        m2 = EU_PATTERNS.cross_ref.search("Annexes I and II")
        assert m1 is not None
        assert m2 is not None

    def test_recital_reference(self) -> None:
        m = EU_PATTERNS.cross_ref.search("as stated in Recital 26")
        assert m is not None
        assert m.group(1) == "26"


# ===========================================================================
# VERSION & CLASSIFIER — BETA STATUS
# ===========================================================================


class TestVersionBeta:
    def test_version_is_beta(self) -> None:
        import lexichunk
        assert lexichunk.__version__ == "0.8.0b1"

    def test_jurisdiction_enum_has_eu(self) -> None:
        assert hasattr(Jurisdiction, "EU")
        assert Jurisdiction.EU.value == "eu"
