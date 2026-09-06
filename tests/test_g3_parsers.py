"""Work package G3 — cross-reference and definitions parser regressions.

Covers the defects catalogued in the engineering-synthesis review:

* D15 — definition body runs through the next definition.
* D16 — defined-term keys can contain a literal newline.
* D18 — duplicate, inconsistent references for EU pinpoint citations.
* D19 — resolution ignores the label word (``Annex I`` → paragraph ``1``).
* D21 — ``to`` / ``through`` / dash ranges silently drop the upper bound.
* D25 — ``_partial_match`` was an unindexed linear scan (quadratic resolve).
* D26 — the hereinafter lookback could start a body mid-word.
* D27 — lowercase / parenthesised-plural / "individually as" terms unsupported.

Plus the multi-candidate, ambiguity-safe resolution design (F2.3) and the
``extra_identifiers`` hook used by merged chunks (F4).
"""

from __future__ import annotations

import re
import time

from lexichunk.models import (
    ClauseType,
    CrossReference,
    DocumentSection,
    HierarchyNode,
    Jurisdiction,
    LegalChunk,
)
from lexichunk.parsers.definitions import (
    _DEFINITION_INDIVIDUALLY_COLLECTIVELY,
    _DEFINITION_LOWERCASE,
    _DEFINITION_PAREN_PLURAL,
    DefinitionsExtractor,
)
from lexichunk.parsers.references import (
    _RANGE_TAIL,
    EXTENDED_PATTERNS,
    ReferenceDetector,
    resolve_references,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _kinds(refs: list[CrossReference]) -> dict[str, str]:
    """Map target_identifier → target_kind for a reference list."""
    return {r.target_identifier: r.target_kind for r in refs}


def _ids(refs: list[CrossReference]) -> list[str]:
    return [r.target_identifier for r in refs]


def _chunk(
    index: int,
    identifier: str,
    *,
    refs: list[CrossReference] | None = None,
    section: DocumentSection = DocumentSection.OPERATIVE,
    path: str | None = None,
) -> LegalChunk:
    """Build a minimal LegalChunk for resolution tests."""
    return LegalChunk(
        content=f"Chunk {identifier}",
        index=index,
        hierarchy=HierarchyNode(level=0, identifier=identifier),
        hierarchy_path=path if path is not None else identifier,
        document_section=section,
        clause_type=ClauseType.UNKNOWN,
        jurisdiction=Jurisdiction.UK,
        cross_references=refs or [],
    )


# ---------------------------------------------------------------------------
# D19 — reference kind
# ---------------------------------------------------------------------------


class TestReferenceKind:
    def test_bare_number_defaults_to_clause(self) -> None:
        """A reference carrying only a number is a clause reference."""
        ref = CrossReference(raw_text="Clause 3.2", target_identifier="3.2")
        assert ref.target_kind == "clause"

    def test_to_dict_includes_target_kind(self) -> None:
        ref = CrossReference(
            raw_text="Annex I", target_identifier="I", target_kind="annex"
        )
        assert ref.to_dict()["target_kind"] == "annex"

    def test_kind_per_label_word(self) -> None:
        cases = [
            (Jurisdiction.UK, "subject to Clause 3.2", "3.2", "clause"),
            (Jurisdiction.UK, "See Schedule 1 hereto", "1", "schedule"),
            (Jurisdiction.UK, "as set out in paragraph 4", "4", "paragraph"),
            (Jurisdiction.US, "described in Section 7.01", "7.01", "section"),
            (Jurisdiction.US, "see Exhibit 2 attached", "2", "exhibit"),
            (Jurisdiction.US, "set forth in Article VII", "VII", "article"),
            (Jurisdiction.EU, "set out in Annex I", "I", "annex"),
            (Jurisdiction.EU, "see Chapter II", "II", "chapter"),
            (Jurisdiction.EU, "see Recital 26", "26", "recital"),
        ]
        for jurisdiction, text, identifier, kind in cases:
            refs = ReferenceDetector(jurisdiction).detect(text)
            assert _kinds(refs).get(identifier) == kind, (
                f"{text!r} → expected kind {kind!r} for {identifier!r}; "
                f"got {_kinds(refs)}"
            )

    def test_plural_labels_get_singular_kind(self) -> None:
        """'Schedules 1 and 2' / 'clauses 3 and 4' get the right kind."""
        refs = ReferenceDetector(Jurisdiction.UK).detect(
            "Schedules 1 and 2 apply, and clauses 3 and 4 also apply."
        )
        kinds = {(r.target_kind, r.target_identifier) for r in refs}
        assert ("schedule", "1") in kinds
        assert ("schedule", "2") in kinds
        assert ("clause", "3") in kinds
        assert ("clause", "4") in kinds

    def test_annexe_british_spelling_normalises(self) -> None:
        refs = ReferenceDetector(Jurisdiction.EU).detect("see Annexes I and II")
        assert {r.target_kind for r in refs} == {"annex"}

    def test_roman_normalisation_applies_to_number_not_label(self) -> None:
        """'Annex I' keeps kind 'annex'; only its number is Roman-normalised."""
        detector = ReferenceDetector(Jurisdiction.EU)
        refs = detector.detect("set out in Annex I")
        assert refs[0].target_kind == "annex"
        # The label word survives; the number matches an Arabic-numbered chunk.
        resolved = detector.resolve([(refs, "Article 1"), ([], "Annex 1")])
        assert resolved[0][0].target_chunk_index == 1


class TestKindScopedResolution:
    def test_annex_never_resolves_to_numbered_paragraph(self) -> None:
        """D19 repro: 'Annex I' must not resolve to numbered paragraph '1'."""
        detector = ReferenceDetector(Jurisdiction.EU)
        refs = detector.detect("as set out in Annex I")
        pairs = [(refs, "Article 1"), ([], "1"), ([], "Annex II")]
        resolved = detector.resolve(pairs)
        assert resolved[0][0].target_kind == "annex"
        assert resolved[0][0].target_chunk_index is None

    def test_schedule_and_clause_resolve_to_different_chunks(self) -> None:
        detector = ReferenceDetector(Jurisdiction.UK)
        refs = detector.detect("See Schedule 1 and Clause 1 below.")
        pairs = [(refs, "9"), ([], "1"), ([], "Schedule 1")]
        resolved = detector.resolve(pairs)
        targets = {r.target_kind: r.target_chunk_index for r in resolved[0]}
        assert targets["clause"] == 1
        assert targets["schedule"] == 2
        assert targets["clause"] != targets["schedule"]

    def test_chapter_does_not_resolve_to_bare_number(self) -> None:
        detector = ReferenceDetector(Jurisdiction.EU)
        refs = detector.detect("see Chapter II")
        resolved = detector.resolve([(refs, "Article 1"), ([], "2")])
        assert resolved[0][0].target_chunk_index is None

    def test_article_label_preferred_over_bare_number(self) -> None:
        """A labelled 'Article 6' chunk beats a bare paragraph '6' chunk."""
        detector = ReferenceDetector(Jurisdiction.EU)
        refs = detector.detect("in accordance with Article 6")
        pairs = [(refs, "Article 1"), ([], "6"), ([], "Article 6")]
        resolved = detector.resolve(pairs)
        assert resolved[0][0].target_chunk_index == 2


# ---------------------------------------------------------------------------
# F2.3 — multi-candidate resolution and ambiguity safety
# ---------------------------------------------------------------------------


class TestAmbiguityHandling:
    def test_duplicate_identifier_is_left_unresolved(self) -> None:
        """Two chunks share identifier '1.1' → the reference stays None."""
        detector = ReferenceDetector(Jurisdiction.UK)
        ref = CrossReference(raw_text="Clause 1.1", target_identifier="1.1")
        pairs = [([ref], "9"), ([], "1.1"), ([], "1.1")]
        assert detector.resolve(pairs)[0][0].target_chunk_index is None

    def test_section_breaks_the_tie(self) -> None:
        detector = ReferenceDetector(Jurisdiction.UK)
        ref = CrossReference(raw_text="Clause 1.1", target_identifier="1.1")
        pairs = [([ref], "9"), ([], "1.1"), ([], "1.1")]
        resolved = detector.resolve(
            pairs, sections=["operative", "schedules", "operative"]
        )
        assert resolved[0][0].target_chunk_index == 2

    def test_ancestor_breaks_the_tie_when_section_cannot(self) -> None:
        detector = ReferenceDetector(Jurisdiction.UK)
        ref = CrossReference(raw_text="Clause 1.1", target_identifier="1.1")
        pairs = [([ref], "9"), ([], "1.1"), ([], "1.1")]
        resolved = detector.resolve(
            pairs,
            sections=["operative", "operative", "operative"],
            ancestors=["9", "SCHEDULE 1", "9"],
        )
        assert resolved[0][0].target_chunk_index == 2

    def test_still_ambiguous_after_both_filters_stays_none(self) -> None:
        detector = ReferenceDetector(Jurisdiction.UK)
        ref = CrossReference(raw_text="Clause 1.1", target_identifier="1.1")
        pairs = [([ref], "9"), ([], "1.1"), ([], "1.1")]
        resolved = detector.resolve(
            pairs,
            sections=["operative", "operative", "operative"],
            ancestors=["9", "9", "9"],
        )
        assert resolved[0][0].target_chunk_index is None

    def test_single_candidate_still_resolves(self) -> None:
        detector = ReferenceDetector(Jurisdiction.UK)
        ref = CrossReference(raw_text="Clause 1.2", target_identifier="1.2")
        resolved = detector.resolve([([ref], "1.1"), ([], "1.2")])
        assert resolved[0][0].target_chunk_index == 1


class TestExtraIdentifiers:
    def test_absorbed_identifier_resolves(self) -> None:
        """A merged chunk that absorbed '4.1' still resolves 'clause 4.1'."""
        detector = ReferenceDetector(Jurisdiction.UK)
        refs = detector.detect("subject to clause 4.1")
        pairs = [(refs, "9"), ([], "5")]
        assert detector.resolve(pairs)[0][0].target_chunk_index is None
        resolved = detector.resolve(pairs, extra_identifiers={1: ["4.1"]})
        assert resolved[0][0].target_chunk_index == 1

    def test_absorbed_identifier_respects_kind(self) -> None:
        detector = ReferenceDetector(Jurisdiction.UK)
        refs = detector.detect("see Schedule 4")
        pairs = [(refs, "9"), ([], "5")]
        resolved = detector.resolve(pairs, extra_identifiers={1: ["4"]})
        assert resolved[0][0].target_chunk_index is None
        resolved = detector.resolve(pairs, extra_identifiers={1: ["Schedule 4"]})
        assert resolved[0][0].target_chunk_index == 1

    def test_resolve_references_keyword_argument(self) -> None:
        """``resolve_references`` accepts ``extra_identifiers`` as a keyword."""
        detector = ReferenceDetector(Jurisdiction.UK)
        refs = detector.detect("subject to clause 4.1")
        chunks = [_chunk(0, "9", refs=refs), _chunk(1, "5")]

        resolve_references(chunks, Jurisdiction.UK)
        assert chunks[0].cross_references[0].target_chunk_index is None
        assert chunks[0].cross_ref_resolved == 0

        refs = detector.detect("subject to clause 4.1")
        chunks = [_chunk(0, "9", refs=refs), _chunk(1, "5")]
        resolve_references(
            chunks, Jurisdiction.UK, extra_identifiers={1: ["4.1"]}
        )
        assert chunks[0].cross_references[0].target_chunk_index == 1
        assert chunks[0].cross_ref_resolved == 1

    def test_resolve_references_uses_section_to_disambiguate(self) -> None:
        detector = ReferenceDetector(Jurisdiction.UK)
        refs = detector.detect("subject to clause 1.1")
        chunks = [
            _chunk(0, "9", refs=refs),
            _chunk(1, "1.1", section=DocumentSection.SCHEDULES),
            _chunk(2, "1.1", section=DocumentSection.OPERATIVE),
        ]
        resolve_references(chunks, Jurisdiction.UK)
        assert chunks[0].cross_references[0].target_chunk_index == 2


# ---------------------------------------------------------------------------
# D25 — prefix index instead of a linear scan
# ---------------------------------------------------------------------------


class TestPartialMatchScaling:
    @staticmethod
    def _pairs(clause_count: int) -> list[tuple[list[CrossReference], str]]:
        pairs: list[tuple[list[CrossReference], str]] = []
        for i in range(1, clause_count + 1):
            # A reference to the parent identifier only — the case that used
            # to trigger the linear `_partial_match` scan for every reference.
            ref = CrossReference(
                raw_text=f"Clause {i}", target_identifier=str(i)
            )
            pairs.append(([ref], f"{i}.0"))
            for j in range(1, 4):
                pairs.append(([], f"{i}.{j}"))
        return pairs

    @staticmethod
    def _time(pairs: list[tuple[list[CrossReference], str]]) -> float:
        detector = ReferenceDetector(Jurisdiction.UK)
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            detector.resolve(pairs)
            best = min(best, time.perf_counter() - start)
        return best

    def test_resolution_scales_roughly_linearly(self) -> None:
        """20x the input must not cost ~400x the time (D25).

        The pre-fix implementation scanned every chunk identifier for every
        unresolved reference, so a 20x document cost ~150x the time.  The
        bound here is deliberately generous (8x for a 20x input) so the test
        fails only on a genuine return to quadratic behaviour.
        """
        small = self._time(self._pairs(50))
        large = self._time(self._pairs(50 * 20))
        # Guard against a degenerate (unmeasurably fast) baseline.
        assert small > 0
        assert large < small * 20 * 8, (
            f"resolution scaled super-linearly: {small * 1000:.2f}ms → "
            f"{large * 1000:.2f}ms for a 20x input"
        )

    def test_partial_match_still_prefers_lowest_chunk_index(self) -> None:
        detector = ReferenceDetector(Jurisdiction.UK)
        ref = CrossReference(raw_text="Clause 4", target_identifier="4")
        pairs = [([ref], "1.1"), ([], "4.3"), ([], "4.1"), ([], "4.2")]
        assert detector.resolve(pairs)[0][0].target_chunk_index == 1


# ---------------------------------------------------------------------------
# D21 — ranges
# ---------------------------------------------------------------------------


class TestRanges:
    def test_integer_range_with_to(self) -> None:
        refs = ReferenceDetector(Jurisdiction.UK).detect(
            "see clauses 3 to 7 of this Agreement"
        )
        assert _ids(refs) == ["3", "4", "5", "6", "7"]

    def test_dotted_range_with_through(self) -> None:
        refs = ReferenceDetector(Jurisdiction.US).detect(
            "pursuant to Sections 2.1 through 2.4"
        )
        assert _ids(refs) == ["2.1", "2.2", "2.3", "2.4"]

    def test_en_dash_range(self) -> None:
        refs = ReferenceDetector(Jurisdiction.UK).detect(
            "as set out in Clauses 3.2–3.4"
        )
        assert _ids(refs) == ["3.2", "3.3", "3.4"]

    def test_em_dash_range(self) -> None:
        refs = ReferenceDetector(Jurisdiction.UK).detect(
            "as set out in Clauses 3.2—3.4"
        )
        assert _ids(refs) == ["3.2", "3.3", "3.4"]

    def test_zero_padded_range_keeps_its_padding(self) -> None:
        """'Section 3.01 through 3.04' (us_msa house style) keeps the zero."""
        refs = ReferenceDetector(Jurisdiction.US).detect(
            "as set forth in Section 3.01 through 3.04"
        )
        assert _ids(refs) == ["3.01", "3.02", "3.03", "3.04"]

    def test_uneven_width_range_is_not_zero_padded(self) -> None:
        refs = ReferenceDetector(Jurisdiction.UK).detect("see clauses 8 to 11")
        assert _ids(refs) == ["8", "9", "10", "11"]

    def test_range_members_share_the_full_phrase_as_raw_text(self) -> None:
        refs = ReferenceDetector(Jurisdiction.UK).detect(
            "see clauses 3 to 7 of this Agreement"
        )
        assert {r.raw_text for r in refs} == {"clauses 3 to 7"}

    def test_range_members_share_the_head_kind(self) -> None:
        refs = ReferenceDetector(Jurisdiction.UK).detect("see Schedules 1 to 3")
        assert {r.target_kind for r in refs} == {"schedule"}

    def test_mismatched_prefix_is_not_a_range(self) -> None:
        """'2.1 to 3.4' spans two parents — not expanded."""
        refs = ReferenceDetector(Jurisdiction.US).detect(
            "pursuant to Sections 2.1 through 3.4"
        )
        assert _ids(refs) == ["2.1"]

    def test_implausibly_large_range_is_not_expanded(self) -> None:
        refs = ReferenceDetector(Jurisdiction.UK).detect(
            "see clauses 1 to 5000 of this Agreement"
        )
        assert _ids(refs) == ["1"]

    def test_descending_range_is_not_expanded(self) -> None:
        refs = ReferenceDetector(Jurisdiction.UK).detect("see clauses 7 to 3")
        assert _ids(refs) == ["7"]

    def test_range_members_resolve_individually(self) -> None:
        detector = ReferenceDetector(Jurisdiction.UK)
        refs = detector.detect("see clauses 3 to 5")
        pairs = [(refs, "9"), ([], "3"), ([], "4"), ([], "5")]
        resolved = detector.resolve(pairs)
        assert [r.target_chunk_index for r in resolved[0]] == [1, 2, 3]

    def test_range_followed_by_conjunctive_tail(self) -> None:
        refs = ReferenceDetector(Jurisdiction.UK).detect(
            "see clauses 3 to 5 and 9"
        )
        assert _ids(refs) == ["3", "4", "5", "9"]


# ---------------------------------------------------------------------------
# D18 — EU pinpoint citations
# ---------------------------------------------------------------------------


class TestEUPinpointCitations:
    def test_single_reference_with_precise_identifier(self) -> None:
        refs = ReferenceDetector(Jurisdiction.EU).detect(
            "in accordance with Article 6(1)(f) GDPR"
        )
        assert len(refs) == 1, f"expected one reference; got {_ids(refs)}"
        assert refs[0].target_identifier == "6(1)(f)"
        assert refs[0].target_kind == "article"

    def test_resolves_to_the_article_chunk_via_parent_fallback(self) -> None:
        detector = ReferenceDetector(Jurisdiction.EU)
        refs = detector.detect("in accordance with Article 6(1)(f)")
        pairs = [(refs, "Article 1"), ([], "Article 6"), ([], "1")]
        resolved = detector.resolve(pairs)
        assert resolved[0][0].target_chunk_index == 1

    def test_extended_pattern_captures_digit_parens(self) -> None:
        m = EXTENDED_PATTERNS[0].search("in accordance with Article 6(1)(f)")
        assert m is not None
        assert m.group(1) == "6(1)(f)"

    def test_exact_pinpoint_chunk_wins_over_parent(self) -> None:
        detector = ReferenceDetector(Jurisdiction.EU)
        refs = detector.detect("in accordance with Article 6(1)")
        pairs = [(refs, "Article 1"), ([], "Article 6"), ([], "Article 6(1)")]
        resolved = detector.resolve(pairs)
        assert resolved[0][0].target_chunk_index == 2


# ---------------------------------------------------------------------------
# Trailing-period identifiers
# ---------------------------------------------------------------------------


class TestTrailingPeriod:
    def test_target_identifier_has_no_trailing_period(self) -> None:
        for text, jurisdiction in (
            ("See Section 3.2.", Jurisdiction.UK),
            ("Subject to Clause 1.2.3.", Jurisdiction.UK),
        ):
            refs = ReferenceDetector(jurisdiction).detect(text)
            assert refs
            assert not any(r.target_identifier.endswith(".") for r in refs)

    def test_chunk_identifier_trailing_period_still_resolves(self) -> None:
        """US 'Schedule 1.' house style bakes a period into the identifier."""
        detector = ReferenceDetector(Jurisdiction.US)
        refs = detector.detect("as described in Schedule 1 hereto")
        resolved = detector.resolve([(refs, "Article I"), ([], "Schedule 1.")])
        assert resolved[0][0].target_chunk_index == 1


# ---------------------------------------------------------------------------
# ReDoS safety for the new patterns
# ---------------------------------------------------------------------------


class TestNewPatternsReDoS:
    BUDGET = 2.0

    def _assert_fast(self, pattern: re.Pattern[str], text: str) -> None:
        start = time.perf_counter()
        pattern.findall(text)
        elapsed = time.perf_counter() - start
        assert elapsed < self.BUDGET, (
            f"{pattern.pattern!r} took {elapsed:.1f}s on {len(text)} chars"
        )

    def test_range_tail_pathological(self) -> None:
        self._assert_fast(_RANGE_TAIL, ("1 to " * 2000) + "x")

    def test_extended_pattern_digit_parens_pathological(self) -> None:
        text = "in accordance with Article 6" + "(1)" * 2000 + "X"
        self._assert_fast(EXTENDED_PATTERNS[0], text)

    def test_extended_pattern_mixed_parens_pathological(self) -> None:
        text = "pursuant to Section 1" + "(i)" * 1500 + "!"
        self._assert_fast(EXTENDED_PATTERNS[0], text)

    def test_definition_lowercase_pathological(self) -> None:
        self._assert_fast(_DEFINITION_LOWERCASE, '"someterm" and ' * 2000)

    def test_definition_paren_plural_pathological(self) -> None:
        self._assert_fast(_DEFINITION_PAREN_PLURAL, '"Term(s)" and ' * 2000)

    def test_individually_collectively_pathological(self) -> None:
        text = ("individually as a " * 2000) + '"Party" ' + ("x" * 5000)
        self._assert_fast(_DEFINITION_INDIVIDUALLY_COLLECTIVELY, text)

    def test_detect_on_pathological_range_text(self) -> None:
        detector = ReferenceDetector(Jurisdiction.UK)
        start = time.perf_counter()
        detector.detect("clause " + " to ".join(str(i) for i in range(600)))
        assert time.perf_counter() - start < self.BUDGET


# ---------------------------------------------------------------------------
# D15 — definition body stop set
# ---------------------------------------------------------------------------


class TestDefinitionBodyStops:
    def test_body_stops_at_every_definition_start_pattern(self) -> None:
        text = (
            '"Alpha" means the first party to this agreement.\n'
            '"the Beta Entity" means the second party to this agreement.\n'
            '"Gamma" shall have the meaning set forth in Section 3.\n'
            '"business day" means any day other than a Saturday.\n'
            '"Delta(s)" means an item delivered under this agreement.\n'
        )
        result = DefinitionsExtractor(Jurisdiction.UK).extract(text)
        assert result["Alpha"].definition == "the first party to this agreement."
        assert (
            result["the Beta Entity"].definition
            == "the second party to this agreement."
        )
        assert result["Gamma"].definition == "set forth in Section 3."
        assert result["business day"].definition == "any day other than a Saturday."
        for term, dt in result.items():
            assert "means" not in dt.definition, (
                f"{term!r} definition ran into the next definition: "
                f"{dt.definition!r}"
            )

    def test_body_stops_at_hereinafter(self) -> None:
        text = (
            '"Alpha" means the first party to this agreement '
            'and Beta Ltd, hereinafter referred to as "The Second Party", '
            "shall be the counterparty."
        )
        result = DefinitionsExtractor(Jurisdiction.UK).extract(text)
        assert "hereinafter" not in result["Alpha"].definition


# ---------------------------------------------------------------------------
# D16 — whitespace in term names
# ---------------------------------------------------------------------------


class TestTermWhitespaceNormalisation:
    def test_wrapped_term_has_no_newline(self) -> None:
        text = (
            'the indemnifying party (the "Indemnifying\nParty") shall '
            "notify the other party."
        )
        result = DefinitionsExtractor(Jurisdiction.US).extract(text)
        assert "Indemnifying Party" in result
        assert not any("\n" in key for key in result)

    def test_us_msa_fixture_has_no_newline_keys(self, us_msa: str) -> None:
        result = DefinitionsExtractor(Jurisdiction.US).extract(us_msa)
        assert not any("\n" in key for key in result), (
            f"newline in keys: {[k for k in result if chr(10) in k]}"
        )
        assert "Indemnifying Party" in result

    def test_us_tos_fixture_has_no_newline_keys(
        self, us_terms_of_service: str
    ) -> None:
        result = DefinitionsExtractor(Jurisdiction.US).extract(
            us_terms_of_service
        )
        assert not any("\n" in key for key in result)
        assert "Customer Indemnitees" in result

    def test_extracted_term_matches_its_own_key(self, us_msa: str) -> None:
        result = DefinitionsExtractor(Jurisdiction.US).extract(us_msa)
        for key, dt in result.items():
            assert dt.term == key


# ---------------------------------------------------------------------------
# D26 — hereinafter lookback boundary
# ---------------------------------------------------------------------------


class TestHereinafterLookback:
    def test_body_never_starts_mid_word(self) -> None:
        """A period-free sentence longer than the lookback window."""
        filler = (
            "the parties agree to the terms and provisions set out more "
            "particularly in clause 14 "
        ) * 12
        text = filler + 'hereinafter referred to as "The Company" shall apply'
        result = DefinitionsExtractor(Jurisdiction.UK).extract(text)
        body = result["The Company"].definition
        assert body
        # The first token must be a whole word from the source text.
        assert f" {body.split()[0]} " in f" {filler} "

    def test_semicolon_is_a_boundary(self) -> None:
        text = (
            "The supplier shall deliver the goods; "
            'Acme Ltd, hereinafter called "The Supplier", agrees.'
        )
        result = DefinitionsExtractor(Jurisdiction.UK).extract(text)
        assert result["The Supplier"].definition.startswith("Acme Ltd")

    def test_sentence_boundary_still_wins(self) -> None:
        text = (
            "Global Services Inc, a Delaware corporation. The corporation "
            'hereinafter referred to as "The Provider" shall deliver services.'
        )
        result = DefinitionsExtractor(Jurisdiction.UK).extract(text)
        assert result["The Provider"].definition == "The corporation"


# ---------------------------------------------------------------------------
# D27 — lowercase, parenthesised-plural and "individually as" terms
# ---------------------------------------------------------------------------


class TestLowercaseAndPluralTerms:
    def test_lowercase_quoted_term(self) -> None:
        result = DefinitionsExtractor(Jurisdiction.UK).extract(
            '"business day" means any day other than a Saturday or Sunday.'
        )
        assert "business day" in result

    def test_lowercase_curly_and_single_quotes(self) -> None:
        for text in (
            "“business day” means any day other than a Saturday.",
            "'business day' means any day other than a Saturday.",
        ):
            result = DefinitionsExtractor(Jurisdiction.UK).extract(text)
            assert "business day" in result, f"failed for {text!r}"

    def test_lowercase_stop_word_still_rejected(self) -> None:
        result = DefinitionsExtractor(Jurisdiction.UK).extract(
            '"the" means the definite article used throughout.'
        )
        assert "the" not in result

    def test_parenthesised_plural_stores_singular_and_plural(self) -> None:
        result = DefinitionsExtractor(Jurisdiction.UK).extract(
            '"Affiliate(s)" means any entity that controls the party.'
        )
        assert "Affiliate" in result
        assert "Affiliates" in result
        assert "Affiliate(s)" not in result
        assert result["Affiliate"].definition == result["Affiliates"].definition
        assert result["Affiliate"].definition.startswith("any entity")

    def test_parenthesised_plural_es_form(self) -> None:
        result = DefinitionsExtractor(Jurisdiction.UK).extract(
            '"Process(es)" means an operation performed on data.'
        )
        assert "Process" in result
        assert "Processes" in result

    def test_individually_collectively_idiom(self) -> None:
        result = DefinitionsExtractor(Jurisdiction.US).extract(
            "Each of Provider and Customer may be referred to individually as "
            'a "Party" and collectively as the "Parties."'
        )
        assert "Party" in result
        assert "Parties" in result
        assert result["Party"].definition == result["Parties"].definition

    def test_party_and_parties_extracted_from_us_msa(self, us_msa: str) -> None:
        """D27/#11 repro against the shipped fixture."""
        result = DefinitionsExtractor(Jurisdiction.US).extract(us_msa)
        assert "Party" in result, f"got {sorted(result)}"
        assert "Parties" in result, f"got {sorted(result)}"
