"""Accuracy against hand-built gold annotations.

Every other test in this suite asks whether lexichunk still does what it did
yesterday. These two fixtures ask a different question: is it *right*?

The gold is independent of the parser by construction. Each fixture's
structure — clause identifiers, levels, parentage, defined terms,
cross-references and their targets — is declared first in
``tests/fixtures/generators/generate_<name>.py``, and the document text is
generated from that declaration. The offsets fall out of the generation, so
they were never read back from lexichunk and cannot flatter it. Deriving a
gold file by running the parser and writing down its answers would prove only
that the parser agrees with itself.

Both fixtures are adversarial on purpose:

``uk_pdf_extracted_agreement``
    A UK services agreement as a naive PDF text extractor leaves it. A
    running header and ``Page N of 42`` footer repeat every 45 body lines;
    prose is greedily hard-wrapped at 78 columns, so sentences break
    mid-clause and one cross-reference is split across a line break; and
    ``indemnification`` is broken over a soft hyphen. The trap that mattered
    most is a sentence ending "... the payment terms set out in paragraph 2
    of" that wraps onto a line reading "Schedule 2." — believed, that
    re-parents the rest of the agreement under a schedule 150 lines away.

``us_msa_signed_with_exhibits``
    A fully executed US MSA: WHEREAS recitals, nine ARTICLEs whose titles sit
    on a *second* heading line, an IN WITNESS WHEREOF block with two
    signature stacks, and two exhibits **after** the signatures. The words
    "execution" and "survive execution" appear in operative clauses well
    before the real execution block, to catch a classifier that searches for
    the word rather than the formula.

Every metric here is **span-based**. Comparing identifier strings would test
spelling conventions (is it ``Exhibit A`` or ``EXHIBIT A``, ``1`` or ``1.``?)
rather than accuracy. Asking whether the parser found a clause boundary *at
the right character offset* is the question that matters, and it is one the
gold can answer without agreeing on names.

Thresholds are set below the measured values with enough margin to absorb
ordinary drift, and the exact numbers are printed by
``test_report_gold_metrics`` so a regression shows up as a number, not just a
red test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lexichunk import LegalChunker
from lexichunk.parsers.structure import StructureParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLD_DIR = FIXTURES_DIR / "gold"

# (fixture_name, jurisdiction)
GOLD_CASES: list[tuple[str, str]] = [
    ("uk_pdf_extracted_agreement", "uk"),
    ("us_msa_signed_with_exhibits", "us"),
]

MAX_CHUNK_SIZE = 512
MIN_CHUNK_SIZE = 64

# The synthetic clause the parser prepends for a document's leading text. It
# has no counterpart in the gold, which declares only real clauses, so it is
# excluded from precision rather than counted as a false positive.
_PREAMBLE_LEVEL = -99


def _load(name: str) -> tuple[str, dict[str, Any]]:
    text = (FIXTURES_DIR / f"{name}.txt").read_text(encoding="utf-8")
    gold = json.loads((GOLD_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return text, gold


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


class Measurement:
    """Every gold metric for one fixture, computed once."""

    def __init__(self, name: str, jurisdiction: str) -> None:
        text, gold = _load(name)
        self.name = name
        self.gold = gold
        self.sanitised = LegalChunker.sanitize(text)

        chunker = LegalChunker(
            jurisdiction=jurisdiction,
            max_chunk_size=MAX_CHUNK_SIZE,
            min_chunk_size=MIN_CHUNK_SIZE,
        )
        self.chunks, self.metrics = chunker.chunk_with_metrics(text)
        self.parsed = [
            clause
            for clause in StructureParser(jurisdiction).parse(self.sanitised)
            if clause.level != _PREAMBLE_LEVEL
        ]

        self.gold_clauses = gold["clauses"]
        self.gold_top = [c for c in self.gold_clauses if c["is_top_level"]]

    # -- headings --------------------------------------------------------

    @property
    def heading_recall(self) -> float:
        parsed_starts = {c.char_start for c in self.parsed}
        found = sum(1 for g in self.gold_clauses if g["char_start"] in parsed_starts)
        return found / len(self.gold_clauses)

    @property
    def heading_precision(self) -> float:
        gold_starts = {g["char_start"] for g in self.gold_clauses}
        hit = sum(1 for c in self.parsed if c.char_start in gold_starts)
        return hit / len(self.parsed)

    @property
    def missed_headings(self) -> list[str]:
        parsed_starts = {c.char_start for c in self.parsed}
        return [
            f"{g['identifier']}@{g['char_start']}"
            for g in self.gold_clauses
            if g["char_start"] not in parsed_starts
        ]

    @property
    def spurious_headings(self) -> list[str]:
        gold_starts = {g["char_start"] for g in self.gold_clauses}
        return [
            f"{c.identifier}@{c.char_start}"
            for c in self.parsed
            if c.char_start not in gold_starts
        ]

    # -- top-level boundaries ---------------------------------------------

    @property
    def _parsed_roots(self) -> list[Any]:
        return [c for c in self.parsed if c.parent_uid is None]

    @property
    def top_level_recall(self) -> float:
        root_starts = {c.char_start for c in self._parsed_roots}
        found = sum(1 for g in self.gold_top if g["char_start"] in root_starts)
        return found / len(self.gold_top)

    @property
    def top_level_precision(self) -> float:
        gold_starts = {g["char_start"] for g in self.gold_top}
        roots = self._parsed_roots
        return sum(1 for c in roots if c.char_start in gold_starts) / len(roots)

    @property
    def over_merged_chunks(self) -> list[str]:
        """Chunks whose span covers more than one gold top-level clause."""
        offenders = []
        for chunk in self.chunks:
            spanned = [
                g["identifier"]
                for g in self.gold_top
                if _overlap(
                    chunk.char_start, chunk.char_end, g["char_start"], g["char_end"]
                )
            ]
            if len(spanned) > 1:
                offenders.append(f"chunk {chunk.index} spans {spanned}")
        return offenders

    # -- defined terms -----------------------------------------------------

    @property
    def _found_terms(self) -> set[str]:
        found: set[str] = set()
        for chunk in self.chunks:
            found |= set(chunk.defined_terms_used)
            found |= set(chunk.defined_terms_context)
        return found

    @property
    def defined_term_recall(self) -> float:
        gold_terms = {t["term"] for t in self.gold["defined_terms"]}
        return len(gold_terms & self._found_terms) / len(gold_terms)

    @property
    def missed_terms(self) -> list[str]:
        gold_terms = {t["term"] for t in self.gold["defined_terms"]}
        return sorted(gold_terms - self._found_terms)

    # -- cross-references ---------------------------------------------------

    @staticmethod
    def _normalise(raw: str) -> str:
        """Fold a reference's raw text for comparison.

        Two things have to be folded away, and neither is a defect:

        * **Line breaks.** Hard-wrapped text splits references — the fixture
          contains a literal ``"Schedule\\n2"`` and an ``"Article\\nVI"``.
          lexichunk detects both and reports the raw text it matched, newline
          and all, which is faithful; the gold records the phrase as written.
        * **Case.** ``EXHIBIT A`` as a heading and ``Exhibit A`` in a
          sentence are the same reference.

        Matching is therefore per chunk and per phrase rather than per
        occurrence: lexichunk reports one entry for a reference it saw
        several times in one chunk, so counting occurrences would score it
        down for de-duplicating.
        """
        return " ".join(raw.split()).casefold()

    def _detected_for(self, gold_reference: dict[str, Any]) -> Any:
        """The detected reference matching a gold one, or ``None``."""
        position = gold_reference["char_start"]
        wanted = self._normalise(gold_reference["raw_text"])
        for chunk in self.chunks:
            if not chunk.char_start <= position < chunk.char_end:
                continue
            for reference in chunk.cross_references:
                if self._normalise(reference.raw_text) == wanted:
                    return reference
        return None

    @property
    def _detected_pairs(self) -> list[tuple[dict[str, Any], Any]]:
        pairs = []
        for gold_reference in self.gold["cross_references"]:
            detected = self._detected_for(gold_reference)
            if detected is not None:
                pairs.append((gold_reference, detected))
        return pairs

    @property
    def cross_ref_recall(self) -> float:
        return len(self._detected_pairs) / len(self.gold["cross_references"])

    @property
    def cross_ref_target_precision(self) -> float:
        """Of the references found and resolved, how many land on the right clause.

        "Right" means the resolved chunk's span overlaps the gold target
        clause's span — not that identifier strings match, which would test
        naming conventions instead of resolution.
        """
        resolved = [
            (gold_reference, detected)
            for gold_reference, detected in self._detected_pairs
            if detected.target_chunk_index is not None
        ]
        if not resolved:
            return 0.0
        by_index = {c.index: c for c in self.chunks}
        correct = 0
        for gold_reference, detected in resolved:
            target = by_index[detected.target_chunk_index]
            if _overlap(
                target.char_start,
                target.char_end,
                gold_reference["target_char_start"],
                gold_reference["target_char_end"],
            ):
                correct += 1
        return correct / len(resolved)


@pytest.fixture(scope="module")
def measurements() -> dict[str, Measurement]:
    return {name: Measurement(name, juris) for name, juris in GOLD_CASES}


# ---------------------------------------------------------------------------
# The gold files must describe the fixtures they claim to
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,jurisdiction", GOLD_CASES)
def test_gold_offsets_index_the_sanitised_text(name: str, jurisdiction: str) -> None:
    """Sanitisation must not move anything the gold points at.

    The gold offsets are taken from the generated file. They are only usable
    as an answer key if ``sanitize`` leaves that file alone — otherwise every
    span in the file is silently off by however much sanitisation shifted it.
    """
    text, gold = _load(name)
    assert LegalChunker.sanitize(text) == text, (
        f"{name}: sanitisation rewrites the fixture, so its gold offsets do "
        f"not index the text the chunker sees"
    )
    for clause in gold["clauses"]:
        assert 0 <= clause["char_start"] < clause["char_end"] <= len(text)
    for reference in gold["cross_references"]:
        start = reference["char_start"]
        raw = reference["raw_text"]
        # References are recorded against the flattened text, where a line
        # break inside the phrase shows up as a space.
        assert text[start : start + len(raw)].replace("\n", " ") == raw


@pytest.mark.parametrize("name,jurisdiction", GOLD_CASES)
def test_gold_clause_spans_tile_the_document(name: str, jurisdiction: str) -> None:
    _, gold = _load(name)
    clauses = gold["clauses"]
    for earlier, later in zip(clauses, clauses[1:]):
        assert earlier["char_end"] == later["char_start"], (
            f"{name}: gold spans leave a gap after {earlier['identifier']}"
        )


# ---------------------------------------------------------------------------
# Accuracy thresholds
# ---------------------------------------------------------------------------
#
# Set below the measured values with room for ordinary drift. They are floors
# for "this still works", not targets. test_report_gold_metrics prints what
# was actually achieved.

_THRESHOLDS: dict[str, dict[str, float]] = {
    # Measured 100% on everything except UK target precision, which is
    # 94.8% for three known reasons documented in
    # test_known_cross_reference_resolution_limits below. The floors sit a
    # little under the measured values: high enough that a real regression
    # trips them, loose enough that one clause moving in a future edit of a
    # fixture does not.
    "uk_pdf_extracted_agreement": {
        "heading_recall": 1.0,
        "heading_precision": 1.0,
        "top_level_recall": 1.0,
        "top_level_precision": 1.0,
        "defined_term_recall": 1.0,
        "cross_ref_recall": 0.95,
        "cross_ref_target_precision": 0.90,
    },
    "us_msa_signed_with_exhibits": {
        "heading_recall": 1.0,
        "heading_precision": 1.0,
        "top_level_recall": 1.0,
        "top_level_precision": 1.0,
        "defined_term_recall": 1.0,
        "cross_ref_recall": 0.95,
        "cross_ref_target_precision": 0.95,
    },
}


@pytest.mark.parametrize("name,jurisdiction", GOLD_CASES)
def test_heading_detection(
    name: str, jurisdiction: str, measurements: dict[str, Measurement]
) -> None:
    m = measurements[name]
    floors = _THRESHOLDS[name]
    assert m.heading_recall >= floors["heading_recall"], (
        f"{name}: heading recall {m.heading_recall:.1%}; "
        f"missed {m.missed_headings}"
    )
    assert m.heading_precision >= floors["heading_precision"], (
        f"{name}: heading precision {m.heading_precision:.1%}; "
        f"spurious {m.spurious_headings}"
    )


@pytest.mark.parametrize("name,jurisdiction", GOLD_CASES)
def test_top_level_boundaries(
    name: str, jurisdiction: str, measurements: dict[str, Measurement]
) -> None:
    m = measurements[name]
    floors = _THRESHOLDS[name]
    assert m.top_level_recall >= floors["top_level_recall"], (
        f"{name}: top-level recall {m.top_level_recall:.1%}"
    )
    assert m.top_level_precision >= floors["top_level_precision"], (
        f"{name}: top-level precision {m.top_level_precision:.1%}"
    )


@pytest.mark.parametrize("name,jurisdiction", GOLD_CASES)
def test_no_chunk_merges_two_top_level_clauses(
    name: str, jurisdiction: str, measurements: dict[str, Measurement]
) -> None:
    """Zero, not a threshold.

    A chunk straddling two top-level clauses puts two unrelated obligations
    behind one embedding, and no retrieval score recovers from that. The
    pipeline reports this itself as
    ``chunks_spanning_multiple_top_level_clauses``; here it is checked
    against the *gold* outline rather than the parser's own, so a boundary
    the parser missed entirely still counts.
    """
    m = measurements[name]
    assert m.over_merged_chunks == []
    assert m.metrics.chunks_spanning_multiple_top_level_clauses == 0


@pytest.mark.parametrize("name,jurisdiction", GOLD_CASES)
def test_defined_terms(
    name: str, jurisdiction: str, measurements: dict[str, Measurement]
) -> None:
    m = measurements[name]
    assert m.defined_term_recall >= _THRESHOLDS[name]["defined_term_recall"], (
        f"{name}: defined-term recall {m.defined_term_recall:.1%}; "
        f"missed {m.missed_terms}"
    )


@pytest.mark.parametrize("name,jurisdiction", GOLD_CASES)
def test_cross_references(
    name: str, jurisdiction: str, measurements: dict[str, Measurement]
) -> None:
    m = measurements[name]
    floors = _THRESHOLDS[name]
    assert m.cross_ref_recall >= floors["cross_ref_recall"], (
        f"{name}: cross-reference recall {m.cross_ref_recall:.1%}"
    )
    assert (
        m.cross_ref_target_precision >= floors["cross_ref_target_precision"]
    ), (
        f"{name}: cross-reference target precision "
        f"{m.cross_ref_target_precision:.1%}"
    )


# ---------------------------------------------------------------------------
# The trap each fixture was built around
# ---------------------------------------------------------------------------


def test_a_wrapped_schedule_reference_is_not_a_schedule_heading(
    measurements: dict[str, Measurement],
) -> None:
    """The UK fixture's headline trap.

    "... the payment terms set out in paragraph 2 of" wraps onto a line
    reading "Schedule 2." at column 0. Read as a container heading, it
    re-parents everything below it under a schedule that really begins 150
    lines later — which is exactly what happened before the plausibility
    gate stopped trusting column 0 in hard-wrapped text.
    """
    m = measurements["uk_pdf_extracted_agreement"]
    schedule_starts = [
        c.char_start for c in m.parsed if c.identifier.lower().startswith("schedule")
    ]
    gold_schedule_starts = [
        c["char_start"]
        for c in m.gold["clauses"]
        if c["identifier"].lower().startswith("schedule")
    ]
    assert schedule_starts == gold_schedule_starts, (
        "a wrapped sentence was read as a schedule heading"
    )


def test_exhibits_after_the_signature_block_are_still_parsed(
    measurements: dict[str, Measurement],
) -> None:
    """The US fixture's headline trap.

    The exhibits come *after* IN WITNESS WHEREOF. Anything treating the
    signature block as the end of the document loses them entirely.
    """
    m = measurements["us_msa_signed_with_exhibits"]
    identifiers = {c.identifier.upper() for c in m.parsed}
    assert "EXHIBIT A" in identifiers
    assert "EXHIBIT B" in identifiers

    exhibit_b = next(
        c for c in m.gold["clauses"] if c["identifier"].upper() == "EXHIBIT B"
    )
    covering = [
        c
        for c in m.chunks
        if _overlap(
            c.char_start, c.char_end, exhibit_b["char_start"], exhibit_b["char_end"]
        )
    ]
    assert covering, "Exhibit B produced no chunk at all"


def test_the_word_execution_in_an_operative_clause_is_not_a_signature_block(
    measurements: dict[str, Measurement],
) -> None:
    """"survive execution" appears in Article V, long before the signatures."""
    m = measurements["us_msa_signed_with_exhibits"]
    position = m.sanitised.index("survive execution")
    covering = [
        c for c in m.chunks if c.char_start <= position < c.char_end
    ]
    assert covering, "no chunk covers the phrase"
    assert covering[0].document_section.value != "signatures", (
        f"{covering[0].hierarchy_path!r} was classified as a signature block "
        f"because it contains the word 'execution'"
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_report_gold_metrics(
    measurements: dict[str, Measurement], capsys: pytest.CaptureFixture[str]
) -> None:
    """Print the measured numbers. Run with ``-s`` to see them."""
    with capsys.disabled():
        print()
        for name, _ in GOLD_CASES:
            m = measurements[name]
            print(f"  {name}")
            print(f"    chunks {len(m.chunks)}, gold clauses {len(m.gold_clauses)}, "
                  f"gold top-level {len(m.gold_top)}")
            print(f"    heading      recall {m.heading_recall:6.1%}  "
                  f"precision {m.heading_precision:6.1%}")
            print(f"    top-level    recall {m.top_level_recall:6.1%}  "
                  f"precision {m.top_level_precision:6.1%}")
            print(f"    over-merged chunks  {len(m.over_merged_chunks)}")
            print(f"    defined-term recall {m.defined_term_recall:6.1%}")
            print(f"    cross-ref    recall {m.cross_ref_recall:6.1%}  "
                  f"target precision {m.cross_ref_target_precision:6.1%}")


def test_known_cross_reference_resolution_limits(
    measurements: dict[str, Measurement],
) -> None:
    """The three UK references that resolve to the wrong clause, named.

    A percentage hides which cases fail, so they are pinned individually.
    All three are resolution limits rather than parsing errors — the
    reference is detected, and lands on a clause near the right one:

    * ``paragraph 2`` in the main body means Schedule 2's paragraph 2 ("the
      payment terms set out in paragraph 2 of Schedule 2"), but resolution
      does not read the words after the reference, so it takes the top-level
      clause 2. Fixing it means resolving a reference against the container
      named beside it.
    * ``clause 9.3(b)`` lands on clause 9.2, and ``clause 7.3(b)`` on clause
      7.3 itself, rather than on the ``(b)`` sub-clause each names. Compound
      ``N.N(x)`` identifiers are detected — ``target_identifier`` is right —
      but a lettered sub-clause is not a lookup candidate under its parent's
      number.

    If a change fixes one of these, delete it from here and raise the
    threshold; the test failing because something now resolves *correctly*
    is the point.
    """
    m = measurements["uk_pdf_extracted_agreement"]
    by_index = {c.index: c for c in m.chunks}
    wrong = set()
    for gold_reference, detected in m._detected_pairs:
        if detected.target_chunk_index is None:
            continue
        target = by_index[detected.target_chunk_index]
        if not _overlap(
            target.char_start,
            target.char_end,
            gold_reference["target_char_start"],
            gold_reference["target_char_end"],
        ):
            wrong.add(gold_reference["raw_text"])

    assert wrong == {"paragraph 2", "clause 9.3(b)", "clause 7.3(b)"}, (
        f"the set of mis-resolved references changed: {sorted(wrong)}"
    )
