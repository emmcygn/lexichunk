"""Regression tests for the second adversarial pass (G7).

One class per confirmed finding.  Every test in this module was written
against a *reproduced* defect: each one fails on the parent commit.
"""

from __future__ import annotations

import pytest

from lexichunk.models import Jurisdiction
from lexichunk.parsers.definitions import DefinitionsExtractor


class TestC2UKScheduleHeaderGroup:
    """C2 — the UK ``next_header_re`` Schedule branch had no capturing group.

    ``level_map`` unconditionally probed ``m.group(4)``, so any document whose
    Definitions clause line-wraps such that a continuation line starts with
    ``"Schedule N"`` raised ``IndexError: no such group`` out of
    ``DefinitionsExtractor.extract()`` — and therefore out of ``chunk()``.
    """

    WRAPPED_SCHEDULE_DOC = """SERVICES AGREEMENT

1. Definitions and Interpretation

In this Agreement the following expressions have the meanings given to them
in this clause. The Supplier shall comply with Clause 1 at all times and
shall observe paragraph 1 of the operating standards. The parties agree
that paragraph 3 of Schedule 1 governs escalation and that paragraph 2 of
Schedule 2 governs data retention throughout the term of this Agreement.

2. Supply of Services

The Supplier shall supply the services described in Schedule 1.

Schedule 1

1. Service Levels

The service levels are set out in this Schedule.
"""

    def test_wrapped_schedule_continuation_does_not_crash(self) -> None:
        terms = DefinitionsExtractor(Jurisdiction.UK).extract(
            self.WRAPPED_SCHEDULE_DOC
        )
        assert isinstance(terms, dict)

    def test_chunker_survives_wrapped_schedule_continuation(self) -> None:
        from lexichunk import LegalChunker

        chunks = LegalChunker(jurisdiction="uk").chunk(self.WRAPPED_SCHEDULE_DOC)
        assert chunks

    @pytest.mark.parametrize("jurisdiction", list(Jurisdiction))
    def test_every_jurisdiction_group_count_matches_level_map(
        self, jurisdiction: Jurisdiction
    ) -> None:
        """The root cause was a group-count/``level_map`` mismatch.

        Assert the invariant directly for all three built-ins so a future
        alternative added without a group fails here rather than in the field.
        """
        extractor = DefinitionsExtractor(jurisdiction)
        # ``_find_section_end`` compiles the pattern locally; drive it over a
        # document containing every alternative it knows about.
        probe = (
            "1. Definitions\n\nBody text.\n\n1.1 Sub\n\n1.1.1 Deep\n\n"
            "2. Next\n\nSchedule 1\n\nExhibit A\n\n"
            "ARTICLE I\n\nSection 1.1\n\nCHAPTER I\n\nArticle 1\n\n"
            "Section 1\n\nANNEX I\n\n3. Para\n"
        )
        # Must not raise IndexError for any candidate the regex matches.
        assert extractor._find_section_end(probe, 0, 0) >= 0


class TestC3UnicodeLineSeparators:
    """C3 — ``_line_offsets`` counted only ``'\n'`` but ``parse()`` splits with
    ``str.splitlines()``, which also breaks on ``\r``, ``\v``, ``\f``,
    ``\x1c``-``\x1e``, ``\x85`` (NEL), ``\u2028`` and ``\u2029``.
    """

    SEPARATORS = ["\u2028", "\u2029", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e"]

    @pytest.mark.parametrize("sep", SEPARATORS)
    def test_chunk_survives_unicode_line_separator(self, sep: str) -> None:
        from lexichunk import LegalChunker

        chunks = LegalChunker(jurisdiction="uk").chunk(f"1. A{sep}{sep}Text\n")
        assert isinstance(chunks, list)

    @pytest.mark.parametrize("sep", SEPARATORS)
    def test_parse_structure_survives_unicode_line_separator(self, sep: str) -> None:
        from lexichunk.parsers.structure import parse_structure

        assert isinstance(
            parse_structure(f"1. A{sep}{sep}Text\n", Jurisdiction.UK), list
        )

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "\n",
            "a",
            "a\n",
            "a\r\nb\n",
            "\ufeff \x85 \u2029",
            "1. A\u2028\u2028Text\n",
            "x\rz\u2028q\x0cw",
        ],
    )
    def test_offsets_agree_with_splitlines(self, text: str) -> None:
        from lexichunk.parsers.structure import _line_offsets

        offsets = _line_offsets(text)
        lines = text.splitlines(keepends=True)
        assert len(offsets) == len(lines)
        for offset, line in zip(offsets, lines):
            assert text[offset : offset + len(line)] == line
