"""Work package G1 — structure parsing & jurisdiction detection.

One focused regression test per behaviour introduced by G1:

* the jurisdiction-agnostic heading-plausibility gate
  (:meth:`StructureParser._is_plausible_heading`);
* per-jurisdiction ``SECTION_ROLES``;
* alpha vs Roman disambiguation of ``(i)``/``(v)``/``(x)``/``(l)``/``(c)``;
* ``detect_level`` coverage additions (US bare ``Section N``, US
  ``Schedule 1.``, UK numbered definitions / ``Clause N`` / ``1)`` /
  ``Appendix``, EU ``Recital (n)``);
* title hygiene and ``SIGNATURES`` precision.

Repro inputs are taken verbatim from the engineering synthesis where the
document gives them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lexichunk import LegalChunker
from lexichunk.jurisdiction import register_jurisdiction
from lexichunk.jurisdiction.eu import SECTION_ROLES as EU_SECTION_ROLES
from lexichunk.jurisdiction.eu import detect_level as eu_detect_level
from lexichunk.jurisdiction.uk import SECTION_ROLES as UK_SECTION_ROLES
from lexichunk.jurisdiction.uk import detect_level as uk_detect_level
from lexichunk.jurisdiction.us import SECTION_ROLES as US_SECTION_ROLES
from lexichunk.jurisdiction.us import detect_level as us_detect_level
from lexichunk.models import DocumentSection, Jurisdiction
from lexichunk.parsers.structure import (
    MAX_TITLE_CHARS,
    StructureParser,
    _extract_title,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _parse(text: str, jurisdiction=Jurisdiction.UK, doc_type: str = "contract"):
    parser = StructureParser(jurisdiction, doc_type=doc_type)
    return parser, parser.parse(text)


def _identifiers(clauses) -> list[str]:
    return [c.identifier for c in clauses]


# ===========================================================================
# 1. Heading-plausibility gate
# ===========================================================================


class TestTocRejection:
    """Gate rule (a): dot-leader / right-aligned page number lines."""

    def test_dot_leader_toc_lines_are_not_clauses(self) -> None:
        text = (
            "1. Definitions .................................................. 3\n"
            "2. Services ...................................................... 5\n"
            "\n"
            "1.   Definitions\n"
            "The following terms apply.\n"
        )
        parser, clauses = _parse(text)
        # Only the real clause 1 survives (plus the synthetic preamble).
        assert _identifiers(clauses) == ["preamble", "1"]
        assert parser.last_rejected_headings == 2

    def test_wide_gutter_page_number_rejected(self) -> None:
        text = "1. Definitions        3\n\n1.   Definitions\nBody.\n"
        parser, clauses = _parse(text)
        assert _identifiers(clauses) == ["preamble", "1"]
        assert parser.last_rejected_headings == 1

    def test_toc_entry_does_not_leak_leader_dots_into_the_title(self) -> None:
        _, clauses = _parse(
            "1. Definitions ......... 3\n\n1.  Definitions\nBody text.\n"
        )
        titles = [c.title for c in clauses if c.identifier == "1"]
        assert titles == ["Definitions"]


class TestContainerGate:
    """Gate rule (b): Schedule / Exhibit / Annex / Chapter placement."""

    def test_wrapped_schedule_reference_is_not_a_container(self) -> None:
        """The `"     Schedule 2."` phantom from the shipped UK fixture."""
        text = (
            "3.   Fees and payment\n"
            "\n"
            "3.1  In consideration of the provision of the Services, the Client "
            "shall pay the Fees to\n"
            "     the Supplier in accordance with the payment terms set out in "
            "this clause 3 and in\n"
            "     Schedule 2.\n"
            "\n"
            "4.   Confidentiality\n"
            "Each party shall keep information confidential.\n"
        )
        parser, clauses = _parse(text)
        assert "Schedule 2" not in _identifiers(clauses)
        assert parser.last_rejected_headings == 1
        # Clause 4 stays top-level rather than being re-parented.
        clause_4 = next(c for c in clauses if c.identifier == "4")
        assert clause_4.parent_identifier is None

    def test_column_zero_schedule_is_accepted(self) -> None:
        text = "SCHEDULE 2 - FEES\nSome schedule body text.\n"
        parser, clauses = _parse(text)
        assert _identifiers(clauses) == ["SCHEDULE 2"]
        assert parser.last_rejected_headings == 0

    def test_blank_separated_indented_schedule_is_accepted(self) -> None:
        text = "1.  Services\nBody.\n\n     Schedule 3 - Service Levels\nBody.\n"
        _, clauses = _parse(text)
        assert "Schedule 3" in _identifiers(clauses)

    def test_uk_fixture_has_no_phantom_schedule_2(self) -> None:
        text = (FIXTURES_DIR / "uk_service_agreement.txt").read_text(encoding="utf-8")
        parser, clauses = _parse(text)
        schedule_2 = [c for c in clauses if c.identifier.lower() == "schedule 2"]
        # Exactly one Schedule 2 — the real, column-0 one.
        assert len(schedule_2) == 1
        assert schedule_2[0].identifier == "SCHEDULE 2"
        assert parser.last_rejected_headings > 0


class TestAllCapsGate:
    """Gate rule (c): the US/EU ALL-CAPS level-0 fallback."""

    def test_document_title_on_first_line_is_not_a_heading(self) -> None:
        text = "TERMS OF SERVICE\n\nSome introductory prose.\n"
        _, clauses = _parse(text, Jurisdiction.US, "terms_conditions")
        assert _identifiers(clauses) == ["preamble"]

    @pytest.mark.parametrize(
        "label",
        [
            "CONFIDENTIAL",
            "TABLE OF CONTENTS",
            "DRAFT",
            "PRIVILEGED",
            "CONFIDENTIAL AND PROPRIETARY",
            "PAGE",
        ],
    )
    def test_denylisted_page_furniture_rejected(self, label: str) -> None:
        text = f"Body text before.\n\n{label}\n\nBody text after.\n"
        parser, clauses = _parse(text, Jurisdiction.US)
        assert _identifiers(clauses) == ["preamble"]
        assert parser.last_rejected_headings == 1

    def test_long_allcaps_line_rejected(self) -> None:
        text = (
            "Body text before.\n"
            "\n"
            "IN NO EVENT SHALL EITHER PARTY BE LIABLE FOR ANY INDIRECT DAMAGES\n"
            "\n"
            "Body text after.\n"
        )
        parser, clauses = _parse(text, Jurisdiction.US)
        assert _identifiers(clauses) == ["preamble"]
        assert parser.last_rejected_headings == 1

    def test_allcaps_without_blank_line_before_rejected(self) -> None:
        text = (
            "Body text before.\n"
            "SOFTWARE PLATFORM\n"
            "\n"
            "More body text.\n"
        )
        parser, clauses = _parse(text, Jurisdiction.US)
        assert _identifiers(clauses) == ["preamble"]
        assert parser.last_rejected_headings == 1

    def test_wrapped_allcaps_paragraph_continuation_rejected(self) -> None:
        text = (
            "Body text before.\n"
            "\n"
            "SUBSCRIPTION FEES REFLECT RISK\n"
            "\n"
            "AND STRATA DISCLAIMS ALL\n"
            "\n"
            "Body text after.\n"
        )
        parser, clauses = _parse(text, Jurisdiction.US)
        # The first ALL-CAPS line is a plausible heading; the second continues
        # it (previous non-blank line is ALL-CAPS, unterminated).
        assert _identifiers(clauses) == ["preamble", "SUBSCRIPTION FEES REFLECT RISK"]
        assert parser.last_rejected_headings == 1

    def test_genuine_allcaps_heading_still_accepted(self) -> None:
        text = (
            "Some introductory prose.\n"
            "\n"
            "REPRESENTATIONS AND WARRANTIES\n"
            "\n"
            "Each party represents that it has authority.\n"
        )
        parser, clauses = _parse(text, Jurisdiction.US)
        assert "REPRESENTATIONS AND WARRANTIES" in _identifiers(clauses)
        assert parser.last_rejected_headings == 0

    def test_us_fixture_has_no_allcaps_phantom_headings(self) -> None:
        text = (FIXTURES_DIR / "us_terms_of_service.txt").read_text(encoding="utf-8")
        _, clauses = _parse(text, Jurisdiction.US, "terms_conditions")
        identifiers = _identifiers(clauses)
        assert "TERMS OF SERVICE" not in identifiers
        assert not any(
            i.startswith("PLEASE READ") or i.startswith("SUBSCRIPTION FEES")
            for i in identifiers
        )

    def test_us_fixture_gains_real_level_zero_sections(self) -> None:
        """`us_terms_of_service.txt` uses bare `Section N.` at top level."""
        text = (FIXTURES_DIR / "us_terms_of_service.txt").read_text(encoding="utf-8")
        _, clauses = _parse(text, Jurisdiction.US, "terms_conditions")
        level_0 = [c for c in clauses if c.level == 0]
        assert len(level_0) >= 10
        assert all(c.identifier.startswith("Section ") for c in level_0)


class TestNumericTopLevelGate:
    """Gate rule (d): UK `<digits> <Capitalised word>` body text."""

    def test_unit_word_remainder_rejected(self) -> None:
        text = (
            "1.  Notices\n"
            "Notice shall be given within\n"
            "3 Business Days after receipt of the notice by the other party.\n"
        )
        parser, clauses = _parse(text)
        assert _identifiers(clauses) == ["1"]
        assert parser.last_rejected_headings == 1

    def test_month_word_remainder_rejected(self) -> None:
        text = "1.  Term\nThe term begins on\n1. January 2024 is the Effective Date.\n"
        parser, clauses = _parse(text)
        assert _identifiers(clauses) == ["1"]
        assert parser.last_rejected_headings == 1

    def test_allcaps_footer_with_page_number_rejected(self) -> None:
        text = "1.  Term\nBody.\n12 CONFIDENTIAL AND PROPRIETARY\nMore body.\n"
        parser, clauses = _parse(text)
        assert _identifiers(clauses) == ["1"]
        assert parser.last_rejected_headings == 1

    def test_sentence_shaped_remainder_rejected(self) -> None:
        text = (
            "1.  Term\n"
            "Body.\n"
            "5 Parties acknowledge that this sentence runs on at considerable "
            "length and finally stops here.\n"
        )
        parser, clauses = _parse(text)
        assert _identifiers(clauses) == ["1"]
        assert parser.last_rejected_headings == 1

    def test_numbered_definition_entry_is_not_rejected_as_prose(self) -> None:
        """A quoted remainder is a definition heading, not prose (D11)."""
        text = (
            '1. "Agreement" means this agreement together with all of the '
            'schedules and appendices attached to it;\n'
        )
        parser, clauses = _parse(text)
        assert _identifiers(clauses) == ["1"]
        assert parser.last_rejected_headings == 0

    def test_comma_continuation_is_not_a_heading(self) -> None:
        """`"Article I, Section 3.01 through 3.04, ..."` is a wrapped sentence."""
        text = (
            "ARTICLE I\n"
            "\n"
            "Section 1.01  Definitions. Terms have the meanings given.\n"
            "\n"
            "The following survive termination:\n"
            "Article I, Section 3.01 through 3.04, Article IV, Article V,\n"
            "Article VI, this Section 8.04, and Article IX.\n"
        )
        parser, clauses = _parse(text, Jurisdiction.US)
        assert _identifiers(clauses).count("Article I") == 1
        assert "Article VI" not in _identifiers(clauses)
        assert parser.last_rejected_headings == 2


class TestRejectionCounter:
    def test_counter_is_reset_between_parses(self) -> None:
        parser = StructureParser(Jurisdiction.UK)
        parser.parse("1. Definitions ......... 3\n\n1.  Definitions\nBody.\n")
        assert parser.last_rejected_headings == 1
        parser.parse("1.  Definitions\nBody.\n")
        assert parser.last_rejected_headings == 0

    def test_counter_starts_at_zero(self) -> None:
        assert StructureParser(Jurisdiction.UK).last_rejected_headings == 0


# ===========================================================================
# 2. Per-jurisdiction section roles
# ===========================================================================


class TestSectionRoles:
    def test_uk_us_containers_are_schedules(self) -> None:
        assert UK_SECTION_ROLES[-1] is DocumentSection.SCHEDULES
        assert US_SECTION_ROLES[-1] is DocumentSection.SCHEDULES
        assert US_SECTION_ROLES[-2] is DocumentSection.SCHEDULES

    def test_eu_chapter_is_operative_and_annex_is_schedules(self) -> None:
        assert EU_SECTION_ROLES[-1] is DocumentSection.OPERATIVE
        assert EU_SECTION_ROLES[-2] is DocumentSection.SCHEDULES

    def test_uk_schedule_clause_is_schedules(self) -> None:
        _, clauses = _parse("SCHEDULE 1 - SERVICES\nBody text.\n")
        assert clauses[0].document_section is DocumentSection.SCHEDULES

    def test_eu_chapter_clause_is_operative(self) -> None:
        _, clauses = _parse(
            "CHAPTER I\n\nArticle 1\n\n1. Body text.\n", Jurisdiction.EU
        )
        chapter = next(c for c in clauses if c.identifier == "Chapter I")
        assert chapter.document_section is DocumentSection.OPERATIVE

    def test_eu_annex_clause_is_schedules(self) -> None:
        _, clauses = _parse("ANNEX I\n\nBody text.\n", Jurisdiction.EU)
        annex = next(c for c in clauses if c.identifier == "Annex I")
        assert annex.document_section is DocumentSection.SCHEDULES

    def test_gdpr_fixture_chapters_are_not_schedules(self) -> None:
        text = (FIXTURES_DIR / "eu_gdpr_excerpt.txt").read_text(encoding="utf-8")
        _, clauses = _parse(text, Jurisdiction.EU)
        chapters = [c for c in clauses if c.identifier.startswith("Chapter ")]
        assert chapters, "expected Chapter clauses in the GDPR fixture"
        assert all(
            c.document_section is not DocumentSection.SCHEDULES for c in chapters
        )

    def test_gdpr_fixture_chunks_have_no_schedules_section(self) -> None:
        text = (FIXTURES_DIR / "eu_gdpr_excerpt.txt").read_text(encoding="utf-8")
        chunks = LegalChunker(jurisdiction="eu", min_chunk_size=0).chunk(text)
        # An EU Chapter heading has no text of its own and is folded into the
        # Article below it, so it is matched on ``hierarchy_path``.
        chapter_chunks = [
            c for c in chunks if c.hierarchy_path.startswith("Chapter ")
        ]
        assert chapter_chunks
        assert all(
            c.document_section is not DocumentSection.SCHEDULES
            for c in chapter_chunks
        )

    def test_custom_jurisdiction_without_section_roles_defaults_to_operative(
        self,
    ) -> None:
        class _Patterns:
            import re as _re

            cross_ref = _re.compile(r"\bPart\s+(\d+)")
            definition = _re.compile(r'"([A-Z][A-Za-z ]+)"\s+means')
            definition_curly = _re.compile(
                "“([A-Z][A-Za-z ]+)”\\s+means"
            )
            definitions_headers = ("definitions",)
            boilerplate_headers = ("general",)
            signature_markers = ("signed by",)

        def _detect(line: str):
            stripped = line.strip()
            if stripped.startswith("Part "):
                return (-1, stripped.split(" - ")[0])
            return None

        register_jurisdiction("g1_roleless", _Patterns(), _detect)
        _, clauses = _parse("Part 1 - Scope\nBody text.\n", "g1_roleless")
        assert clauses[0].document_section is DocumentSection.OPERATIVE


# ===========================================================================
# 3. Alpha vs Roman disambiguation
# ===========================================================================

_JURISDICTIONS = [Jurisdiction.UK, Jurisdiction.US, Jurisdiction.EU]


class TestAlphaRomanDisambiguation:
    @pytest.mark.parametrize("jurisdiction", _JURISDICTIONS)
    def test_roman_list_nests_under_the_preceding_alpha(self, jurisdiction) -> None:
        text = (
            "(a) first alpha item\n"
            "(b) second alpha item\n"
            "(i) first roman item\n"
            "(ii) second roman item\n"
            "(c) third alpha item\n"
        )
        _, clauses = _parse(text, jurisdiction)
        by_id = {c.identifier: c for c in clauses}
        assert by_id["(i)"].level == 4
        assert by_id["(i)"].parent_identifier == "(b)"
        assert by_id["(ii)"].parent_identifier == "(b)"
        assert by_id["(c)"].level == 3
        assert by_id["(c)"].parent_identifier == by_id["(b)"].parent_identifier

    @pytest.mark.parametrize("jurisdiction", _JURISDICTIONS)
    def test_i_after_h_stays_alpha(self, jurisdiction) -> None:
        text = "(g) seventh item\n(h) eighth item\n(i) ninth item\n(j) tenth item\n"
        _, clauses = _parse(text, jurisdiction)
        by_id = {c.identifier: c for c in clauses}
        assert by_id["(i)"].level == 3
        assert by_id["(j)"].parent_identifier == by_id["(i)"].parent_identifier

    @pytest.mark.parametrize("jurisdiction", _JURISDICTIONS)
    def test_leading_roman_defaults_to_roman(self, jurisdiction) -> None:
        _, clauses = _parse("(i) only item\n", jurisdiction)
        assert clauses[0].level == 4

    @pytest.mark.parametrize("label", ["(v)", "(x)", "(l)"])
    def test_other_ambiguous_labels_default_to_roman(self, label: str) -> None:
        _, clauses = _parse(f"{label} an item\n")
        assert clauses[0].level == 4

    def test_c_after_b_stays_alpha(self) -> None:
        _, clauses = _parse("(a) one\n(b) two\n(c) three\n")
        assert all(c.level == 3 for c in clauses)

    def test_state_resets_at_a_more_senior_header(self) -> None:
        text = "1. First\n(g) g\n(h) h\n2. Second\n(i) roman under two\n"
        _, clauses = _parse(text)
        by_id = {c.identifier: c for c in clauses}
        assert by_id["(i)"].level == 4
        assert by_id["(i)"].parent_identifier == "2"

    def test_us_fixture_i_after_h_is_still_alpha(self) -> None:
        """`us_msa.txt` Section 1.01 has an (a)...(i) alpha list."""
        text = (FIXTURES_DIR / "us_msa.txt").read_text(encoding="utf-8")
        _, clauses = _parse(text, Jurisdiction.US)
        alpha_i = [c for c in clauses if c.identifier == "(i)" and c.level == 3]
        assert alpha_i, "expected (i) to remain alpha when it follows (h)"


# ===========================================================================
# 4. detect_level coverage additions
# ===========================================================================


class TestUSCoverage:
    def test_bare_section_is_top_level(self) -> None:
        assert us_detect_level("Section 1.   Definitions") == (0, "Section 1")
        assert us_detect_level("SECTION 4") == (0, "Section 4")

    def test_dotted_section_still_level_1(self) -> None:
        assert us_detect_level("Section 1.01  Definitions.") == (1, "Section 1.01")
        assert us_detect_level("Section 6.01(b)  Cap") == (1, "Section 6.01(b)")

    def test_schedule_does_not_swallow_a_trailing_period(self) -> None:
        assert us_detect_level("Schedule 1.") == (-1, "Schedule 1")
        assert us_detect_level("Schedule 1.2") == (-1, "Schedule 1.2")

    def test_schedule_pattern_field_matches_dotted_numbers_only(self) -> None:
        from lexichunk.jurisdiction.us import US_PATTERNS

        m = US_PATTERNS.schedule.match("Schedule 1.")
        assert m is not None
        assert m.group(1) == "Schedule 1"

    def test_appendix_is_a_container(self) -> None:
        assert us_detect_level("Appendix A") == (-1, "Appendix A")

    def test_article_still_wins_over_bare_section(self) -> None:
        assert us_detect_level("ARTICLE I") == (0, "Article I")


class TestUKCoverage:
    def test_numbered_definition_with_straight_quote(self) -> None:
        assert uk_detect_level('1. "Term" means the period') == (0, "1")

    def test_numbered_definition_with_curly_quote(self) -> None:
        assert uk_detect_level("1. “Term” means the period") == (0, "1")

    def test_digit_after_the_number(self) -> None:
        assert uk_detect_level("1. 2024 Fee Schedule") == (0, "1")

    def test_clause_n_form(self) -> None:
        assert uk_detect_level("Clause 5 Termination") == (0, "Clause 5")
        assert uk_detect_level("Clause 8.3") == (0, "Clause 8.3")

    def test_lowercase_clause_reference_is_not_a_heading(self) -> None:
        assert uk_detect_level("clause 3 (Acceptable Use) of these Terms.") is None

    def test_paren_number_form(self) -> None:
        assert uk_detect_level("1) Definitions") == (0, "1")

    def test_appendix_is_a_container(self) -> None:
        assert uk_detect_level("Appendix 2") == (-1, "Appendix 2")
        assert uk_detect_level("Appendix B") == (-1, "Appendix B")

    def test_existing_negative_cases_unchanged(self) -> None:
        assert uk_detect_level("3. services provided by the supplier") is None
        assert uk_detect_level("This is body text with no clause marker.") is None

    def test_numbered_definitions_block_produces_per_term_clauses(self) -> None:
        text = (
            '1. "Agreement" means this agreement;\n'
            '2. "Client" means the person who buys the Services;\n'
            '3. "Fees" means the amounts payable by the Client;\n'
        )
        _, clauses = _parse(text)
        assert _identifiers(clauses) == ["1", "2", "3"]


class TestEUCoverage:
    def test_recital_with_parentheses(self) -> None:
        assert eu_detect_level("Recital (26)") == (0, "Recital 26")

    def test_recital_without_parentheses(self) -> None:
        assert eu_detect_level("RECITAL 26") == (0, "Recital 26")

    def test_recital_is_classified_as_recitals(self) -> None:
        _, clauses = _parse("Recital (1)\nThe protection of natural persons.\n",
                            Jurisdiction.EU)
        assert clauses[0].document_section is DocumentSection.RECITALS

    def test_article_still_detected(self) -> None:
        assert eu_detect_level("Article 5") == (0, "Article 5")


# ===========================================================================
# 5. Title hygiene + SIGNATURES precision
# ===========================================================================


class TestTitleHygiene:
    def test_title_is_capped(self) -> None:
        long_title = "Word " * 60
        title = _extract_title(f"1. {long_title}", "1")
        assert title is not None
        assert len(title) <= MAX_TITLE_CHARS

    def test_sentence_shaped_remainder_yields_no_title(self) -> None:
        line = "1.1 In this Agreement the following terms shall bear the meanings given to them below."
        assert _extract_title(line, "1.1") is None

    def test_short_sentence_remainder_is_kept(self) -> None:
        assert _extract_title("1.1 Interpretation.", "1.1") == "Interpretation."

    def test_em_dash_is_not_doubled(self) -> None:
        title = _extract_title("SCHEDULE 2 — FEES AND PAYMENT TERMS", "SCHEDULE 2")
        assert title == "FEES AND PAYMENT TERMS"

    def test_identifier_is_stripped_case_insensitively(self) -> None:
        assert _extract_title("CHAPTER I", "Chapter I") is None

    def test_schedule_hierarchy_path_has_a_single_dash(self) -> None:
        text = (FIXTURES_DIR / "uk_service_agreement.txt").read_text(encoding="utf-8")
        chunks = LegalChunker(jurisdiction="uk", doc_type="contract").chunk(text)
        assert not any("— —" in c.hierarchy_path for c in chunks)


class TestSignatureDetection:
    def test_survive_execution_sentence_stays_operative(self) -> None:
        """D17 repro — an unbounded substring match flipped this to SIGNATURES."""
        text = (
            "2.1 Any notices served under this Agreement shall be in writing "
            "and the obligations in this clause shall survive execution.\n"
        )
        _, clauses = _parse(text)
        assert clauses[0].document_section is DocumentSection.OPERATIVE

    def test_signature_page_heading_is_signatures(self) -> None:
        _, clauses = _parse("2. Signature Page\nSigned by the parties.\n")
        assert clauses[0].document_section is DocumentSection.SIGNATURES

    def test_jurisdiction_signature_marker_is_consulted(self) -> None:
        """`signature_markers` was a dead field before G1."""
        _, clauses = _parse("9. In Witness Whereof\nBody.\n")
        assert clauses[0].document_section is DocumentSection.SIGNATURES

    def test_keyword_match_is_word_bounded(self) -> None:
        _, clauses = _parse("3. Backgrounder Services\nBody.\n")
        assert clauses[0].document_section is not DocumentSection.RECITALS

    def test_plural_keywords_still_match(self) -> None:
        _, clauses = _parse("1. Definitions\nBody.\n")
        assert clauses[0].document_section is DocumentSection.DEFINITIONS
