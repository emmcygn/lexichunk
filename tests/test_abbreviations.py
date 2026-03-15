"""Tests for expanded abbreviation handling — v0.3.0 robustness."""

from __future__ import annotations

import pytest

from lexichunk import LegalChunker
from lexichunk.models import Jurisdiction
from lexichunk.strategies.fallback import FallbackChunker


@pytest.fixture
def fb() -> FallbackChunker:
    return FallbackChunker(jurisdiction=Jurisdiction.US)


def sentences_from(fb: FallbackChunker, text: str) -> list[str]:
    """Helper: split text and return just the sentence strings."""
    return [s for s, _ in fb._split_sentences(text)]


# ---------------------------------------------------------------------------
# Category: Case law reporters — abbreviation dot should NOT split
# Each test has: abbreviation (should NOT split) + real boundary (should split)
# ---------------------------------------------------------------------------

class TestCaseLawReporters:
    def test_usc(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "See 42 U.S.C. Section 1983 for guidance. The court ruled otherwise.")
        assert len(s) == 2
        assert "U.S.C." in s[0]

    def test_f2d(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Reported in 100 F.2d. at page 50 of the record. The ruling was clear.")
        # F.2d. should not split
        assert "F.2d." in s[0]

    def test_f3d(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "See 200 F.3d. at 150 for the holding. The court affirmed.")
        assert "F.3d." in s[0]

    def test_s_ct(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "See 500 S.Ct. Reports for citation purposes. The justices agreed unanimously.")
        assert len(s) == 2
        assert "S.Ct." in s[0]

    def test_fed_appx(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "See 300 Fed.Appx. Reports filed last year. The panel affirmed the ruling.")
        assert len(s) == 2


# ---------------------------------------------------------------------------
# Category: Entity types — dot should NOT split
# ---------------------------------------------------------------------------

class TestEntityTypes:
    def test_llc(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Acme LLC. The company was founded in 2020. The board approved.")
        assert len(s) == 2
        assert "LLC." in s[0]

    def test_ltd(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Barclays Ltd. The bank operates in many regions. The regulator approved.")
        assert len(s) == 2
        assert "Ltd." in s[0]

    def test_inc(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Google Inc. The company develops many products. The market responded.")
        assert len(s) == 2
        assert "Inc." in s[0]

    def test_corp(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Microsoft Corp. The entity is incorporated in Delaware. The filing was complete.")
        assert len(s) == 2


# ---------------------------------------------------------------------------
# Category: Latin / scholarly — dot should NOT split
# ---------------------------------------------------------------------------

class TestLatinScholarly:
    def test_eg(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Common torts, e.g. Negligence or battery, are actionable. The plaintiff must prove harm.")
        assert len(s) == 2
        assert "e.g." in s[0]

    def test_ie(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "The party, i.e. The defendant in this matter, must pay costs. The court so ordered.")
        assert len(s) == 2
        assert "i.e." in s[0]

    def test_et_al(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Smith et al. The court considered their arguments at length. The ruling followed.")
        assert len(s) == 2


# ---------------------------------------------------------------------------
# Category: Legal markers — dot should NOT split
# ---------------------------------------------------------------------------

class TestLegalMarkers:
    def test_no(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Case No. The matter was filed in the district court. The judge assigned it.")
        assert len(s) == 2
        assert "No." in s[0]

    def test_sec(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "See Sec. The provision applies to all parties involved. The terms are binding.")
        assert len(s) == 2

    def test_art(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Under Art. The article provides detailed guidance here. The interpretation is settled.")
        assert len(s) == 2

    def test_cl(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "See Cl. The clause is binding on successors and assigns. The obligation continues.")
        assert len(s) == 2


# ---------------------------------------------------------------------------
# Category: Titles — dot should NOT split
# ---------------------------------------------------------------------------

class TestTitles:
    def test_mr(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Mr. Smith testified under oath at the hearing. The witness was credible.")
        assert len(s) == 2
        assert "Mr." in s[0]

    def test_dr(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Dr. Jones submitted the expert report to the court. The findings were decisive.")
        assert len(s) == 2

    def test_prof(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Prof. Brown lectured on tort law to the students. The class took detailed notes.")
        assert len(s) == 2


# ---------------------------------------------------------------------------
# Category: Dates — dot should NOT split
# ---------------------------------------------------------------------------

class TestDates:
    def test_jan(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Filed on Jan. The deadline was then extended by the court. The motion was granted.")
        assert len(s) == 2

    def test_sept(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Effective Sept. The agreement commenced on that date. The obligations began immediately.")
        assert len(s) == 2


# ---------------------------------------------------------------------------
# Category: US states — dot should NOT split
# ---------------------------------------------------------------------------

class TestUSStates:
    def test_cal(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Filed in Cal. The court had personal jurisdiction over all. The venue was proper.")
        assert len(s) == 2

    def test_mass(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Under Mass. The law governs this particular dispute completely. The court applied it.")
        assert len(s) == 2

    def test_tex(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "In Tex. The statute applies to all oil and gas leases. The provision is mandatory.")
        assert len(s) == 2


# ---------------------------------------------------------------------------
# Negative tests — real sentence boundaries MUST split
# ---------------------------------------------------------------------------

class TestRealBoundaries:
    def test_normal_period_splits(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "The contract is valid. The parties agree.")
        assert len(s) == 2

    def test_question_mark_splits(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Is the contract valid? The parties dispute.")
        assert len(s) == 2

    def test_exclamation_splits(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "The verdict was unanimous! The defense appealed.")
        assert len(s) == 2

    def test_multiple_sentences(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "First sentence. Second sentence. Third sentence.")
        assert len(s) == 3


# ---------------------------------------------------------------------------
# extra_abbreviations parameter
# ---------------------------------------------------------------------------

class TestExtraAbbreviations:
    def test_extra_abbreviation_prevents_split(self) -> None:
        fb = FallbackChunker(
            jurisdiction=Jurisdiction.US,
            extra_abbreviations=["Cust"],
        )
        s = sentences_from(fb, "See Cust. The customer agreed to the terms fully. The contract was signed.")
        assert len(s) == 2
        assert "Cust." in s[0]

    def test_extra_abbreviation_via_legal_chunker(self) -> None:
        chunker = LegalChunker(jurisdiction="us", extra_abbreviations=["Cust"])
        assert chunker is not None

    def test_without_extra_abbreviation_splits(self) -> None:
        """Without adding 'Cust' as extra, it should be treated as a real boundary."""
        fb = FallbackChunker(jurisdiction=Jurisdiction.US)
        s = sentences_from(fb, "See Cust. The customer agreed to the terms fully. The contract was signed.")
        assert len(s) == 3  # Cust. splits + second real boundary


# ---------------------------------------------------------------------------
# Adversarial abbreviation tests
# ---------------------------------------------------------------------------

class TestAdversarialAbbreviations:
    def test_abbreviation_at_start(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "Dr. Smith filed the case in federal court. The judge agreed with him.")
        assert len(s) == 2
        assert "Dr." in s[0]

    def test_consecutive_abbreviations(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "See Corp. Ltd. The entity is registered and valid. Another detail follows.")
        assert any("Corp." in sent for sent in s)

    def test_abbreviation_inside_quotes(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, 'He said "see e.g. Smith v. Jones" in the brief filed. The court noted the argument.')
        assert len(s) == 2

    def test_abbreviation_in_parenthetical(self, fb: FallbackChunker) -> None:
        s = sentences_from(fb, "The ruling (see Corp. filing from last year) was clear. The appeal followed promptly.")
        assert len(s) == 2
