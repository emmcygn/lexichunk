"""Defined terms extractor for legal documents."""

from __future__ import annotations

import bisect
import logging
import re
from typing import Union

from ..jurisdiction import get_patterns

logger = logging.getLogger(__name__)
from ..jurisdiction.uk import UKPatterns
from ..jurisdiction.us import USPatterns
from ..models import DefinedTerm, Jurisdiction

# Terms that should be filtered out even if capitalised.
_SKIP_TERMS: frozenset[str] = frozenset({
    "The", "A", "An", "This", "That",
    "Each", "Any", "All", "Such", "No",
    "If", "Where", "When", "Upon",
    "In", "For", "By", "At", "On", "To", "Of", "Or", "And", "But", "Not",
    "It", "We", "You", "They", "Our", "Your", "Its",
})

# Regex matching a blank line (zero or more spaces, then newline).
_BLANK_LINE: re.Pattern[str] = re.compile(r"^\s*$", re.MULTILINE)

# Single-quote definition patterns (straight and curly).
# ~30-40% of UK contracts use single quotes for defined terms.
_DEFINITION_SINGLE: re.Pattern[str] = re.compile(
    r"'([A-Z][A-Za-z\s\-]{1,60})'\s+(?:means|shall mean|has the meaning|is defined as|refers to)",
    re.MULTILINE,
)
_DEFINITION_SINGLE_CURLY: re.Pattern[str] = re.compile(
    r"\u2018([A-Z][A-Za-z\s\-]{1,60})\u2019\s+(?:means|shall mean|has the meaning|is defined as|refers to)",
    re.MULTILINE,
)

# "shall have the meaning" form (straight + curly quotes).
# e.g. "Term" shall have the meaning set forth in Section 1.1
_DEFINITION_SHALL_HAVE_MEANING: re.Pattern[str] = re.compile(
    r'["\u201c]([A-Z][A-Za-z\s\-]{1,60})["\u201d]\s+shall have the meaning',
    re.MULTILINE,
)

# Inline parenthetical definitions.
# e.g. (each a "Party" and together the "Parties")
# e.g. (the "Effective Date")
# First, find parenthetical groups that contain at least one quoted term.
_INLINE_PAREN_GROUP: re.Pattern[str] = re.compile(
    r'\([^)]*?["\u201c][A-Z][A-Za-z\s\-]{1,60}["\u201d][^)]*?\)',
    re.MULTILINE,
)
# Then, extract individual quoted terms within a parenthetical group.
_INLINE_PAREN_TERM: re.Pattern[str] = re.compile(
    r'["\u201c]([A-Z][A-Za-z\s\-]{1,60})["\u201d]',
)

# Parenthetical back-reference definitions.
# e.g. the Borrower (as defined in Section 1.1)
_PARENTHETICAL_BACKREF: re.Pattern[str] = re.compile(
    r'the\s+([A-Z][A-Za-z\s\-]{1,60}?)\s*\(\s*as\s+defined\s+in\b',
    re.MULTILINE,
)

# Numbered / lettered clause-header patterns used to detect the start of a new
# clause when scanning a definition body.
_UK_CLAUSE_HEADER: re.Pattern[str] = re.compile(
    r"^(?:\d+\.\d+(?:\.\d+)?\.?\s|\d+\.\s+[A-Z]|\([a-z]\)\s|\([ivxlc]+\)\s)",
    re.MULTILINE,
)
_US_CLAUSE_HEADER: re.Pattern[str] = re.compile(
    r"^(?:(?:ARTICLE|Article)\s+[IVXLC]+|(?:SECTION|Section)\s+\d+\.\d+|"
    r"\([a-z]\)\s|\([ivxlc]+\)\s)",
    re.MULTILINE,
)

# Pattern that matches a clause-number token at the beginning of a line; used
# to infer source_clause when scanning the whole document.
_CLAUSE_LABEL: re.Pattern[str] = re.compile(
    r"^(?:"
    r"(?:ARTICLE|Article)\s+([IVXLC]+)"         # US article
    r"|(?:SECTION|Section)\s+(\d+\.\d+\S*)"     # US section
    r"|(\d+\.\d+\.\d+)\.?\s"                    # UK x.y.z
    r"|(\d+\.\d+)\.?\s"                         # UK x.y
    r"|(\d+)\.\s+[A-Z]"                         # UK x
    r")",
    re.MULTILINE,
)


class DefinitionsExtractor:
    """Extracts capitalised defined terms and their definitions from legal text.

    Supports both UK and US jurisdictions and handles straight/curly-quote
    definition patterns.  The extractor first attempts to locate a dedicated
    definitions section; if none is found it falls back to scanning the entire
    document.

    Attributes:
        _jurisdiction: The jurisdiction whose pattern set will be used.
        _patterns: Compiled pattern dataclass for the jurisdiction.
        _clause_header_re: Regex identifying clause headers for this jurisdiction.
    """

    def __init__(self, jurisdiction: Jurisdiction) -> None:
        """Initialise the extractor for a given jurisdiction.

        Args:
            jurisdiction: The legal jurisdiction (UK or US).
        """
        self._jurisdiction: Jurisdiction = jurisdiction
        self._patterns: Union[UKPatterns, USPatterns] = get_patterns(jurisdiction)
        self._clause_header_re: re.Pattern[str] = (
            _UK_CLAUSE_HEADER if jurisdiction == Jurisdiction.UK else _US_CLAUSE_HEADER
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, text: str) -> dict[str, DefinedTerm]:
        """Extract all defined terms from the document.

        Scans the full text for definition patterns.  Prioritises terms found
        in a definitions section but falls back to document-wide scanning.

        Args:
            text: Full document text.

        Returns:
            Dict mapping term name (str) to DefinedTerm.
        """
        section_text = self._find_definitions_section(text)

        if section_text is not None:
            # Infer the source clause identifier from the section header line.
            source_clause = self._infer_clause_label(section_text) or "definitions"
            section_terms = self._extract_definitions_from_text(section_text, source_clause)
        else:
            section_terms = {}

        # Always do a document-wide pass; definitions-section results take
        # precedence for any term found in both passes.
        wide_terms = self._extract_definitions_from_text(text, "")
        # Merge: wide provides base, section_terms overwrite where duplicated.
        merged: dict[str, DefinedTerm] = {**wide_terms, **section_terms}
        logger.debug("Extracted %d defined terms", len(merged))
        return merged

    def extract_from_section(
        self, section_text: str, source_clause: str
    ) -> dict[str, DefinedTerm]:
        """Extract defined terms from a specific section of text.

        Args:
            section_text: Text of the definitions section.
            source_clause: Identifier of the source clause (e.g. "1.1").

        Returns:
            Dict mapping term name to DefinedTerm.
        """
        return self._extract_definitions_from_text(section_text, source_clause)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_definitions_section(self, text: str) -> str | None:
        """Find and return the text of the definitions section, or None.

        Searches for a clause header whose title matches one of the
        jurisdiction-specific ``definitions_headers`` strings (case-insensitive).
        Extracts from that header to the next same-or-higher-level header.

        Args:
            text: Full document text.

        Returns:
            The text of the definitions section, or ``None`` if not found.
        """
        headers: tuple[str, ...] = self._patterns.definitions_headers  # type: ignore[attr-defined]

        # Build a pattern that finds a line whose lowercased content contains
        # one of the definitions header strings.  We look for the header at the
        # start of a line (possibly preceded by a clause number).
        header_alts = "|".join(re.escape(h) for h in headers)
        # Matches lines such as:
        #   "1. Definitions"  "1.1 Interpretation"  "ARTICLE I — DEFINITIONS"
        #   "Section 1.01 Definitions"  "DEFINITIONS"
        section_start_re = re.compile(
            r"^(?:"
            r"(?:ARTICLE|Article)\s+[IVXLC]+[^\n]*(?:" + header_alts + r")[^\n]*"
            r"|(?:SECTION|Section)\s+[\d.]+[^\n]*(?:" + header_alts + r")[^\n]*"
            r"|\d+(?:\.\d+)*\.?\s+[^\n]*(?:" + header_alts + r")[^\n]*"
            r"|(?:" + header_alts + r")[^\n]*"
            r")",
            re.IGNORECASE | re.MULTILINE,
        )

        match = section_start_re.search(text)
        if match is None:
            return None

        start = match.start()

        # Determine the "level" of the found header so we can stop at the
        # next header of equal or higher importance.
        header_line = match.group(0)
        found_level = self._header_level(header_line)

        # Search for the next header of the same or higher level after the
        # match position.
        end = self._find_section_end(text, match.end(), found_level)
        return text[start:end]

    def _find_section_end(self, text: str, after: int, found_level: int) -> int:
        """Return the character offset where the definitions section ends.

        Scans forward from ``after`` for the next clause header whose level is
        equal to or higher (numerically <=) than ``found_level``.

        Args:
            text: Full document text.
            after: Starting offset for the search (exclusive).
            found_level: Hierarchy level of the definitions header (lower number
                = higher in the hierarchy).

        Returns:
            Character offset of the section end (or end-of-text).
        """
        # We look for lines that look like sibling or ancestor clause headers.
        # "Higher or same level" means level <= found_level.
        if self._jurisdiction == Jurisdiction.UK:
            next_header_re = re.compile(
                r"^(?:"
                r"(\d+\.\d+\.\d+)\.?\s+\S"   # level 2
                r"|(\d+\.\d+)\.?\s+\S"        # level 1
                r"|(\d+)\.?\s+[A-Z]\S"        # level 0
                r"|Schedule\s+\d+"            # level -1
                r")",
                re.MULTILINE,
            )
            level_map = {0: 2, 1: 1, 2: 0, 3: -1}  # group-index → level
        else:
            next_header_re = re.compile(
                r"^(?:"
                r"((?:ARTICLE|Article)\s+[IVXLC]+)"    # level 0
                r"|((?:SECTION|Section)\s+\d+\.\d+)"   # level 1
                r"|(Schedule\s+[\d.]+)"                 # level -1
                r"|(Exhibit\s+[A-Z][\w\-]*)"            # level -2
                r")",
                re.MULTILINE,
            )
            level_map = {0: 0, 1: 1, 2: -1, 3: -2}  # group-index → level

        remaining = text[after:]
        for m in next_header_re.finditer(remaining):
            # Determine the level of this candidate header.
            for grp_idx, lvl in level_map.items():
                if m.group(grp_idx + 1) is not None:
                    candidate_level = lvl
                    break
            else:
                continue

            if candidate_level <= found_level:
                return after + m.start()

        return len(text)

    def _header_level(self, line: str) -> int:
        """Return the hierarchy level of a clause header line.

        Args:
            line: The clause header text.

        Returns:
            Integer level (lower = higher in hierarchy).
        """
        l = line.strip()
        if self._jurisdiction == Jurisdiction.UK:
            if re.match(r"^\d+\.\d+\.\d+", l):
                return 2
            if re.match(r"^\d+\.\d+", l):
                return 1
            if re.match(r"^\d+", l):
                return 0
            return 0
        else:
            if re.match(r"^(?:ARTICLE|Article)", l):
                return 0
            if re.match(r"^(?:SECTION|Section)", l):
                return 1
            return 0

    def _extract_definitions_from_text(
        self, text: str, source_clause: str
    ) -> dict[str, DefinedTerm]:
        """Core extraction: scan text for all definition patterns.

        Runs both ``patterns.definition`` (straight quotes) and
        ``patterns.definition_curly`` (curly quotes) against ``text``,
        deduplicates by term name, extracts the definition body for each
        match, and applies all skip rules.

        Args:
            text: Arbitrary legal text to scan.
            source_clause: Default source clause identifier used when a
                preceding clause label cannot be inferred from position.

        Returns:
            Dict mapping term name (str) to :class:`DefinedTerm`.
        """
        # Collect all raw matches from both patterns together with their
        # positions so we can process them in document order.
        raw_matches: list[tuple[int, int, str]] = []  # (start, end, term)

        for pattern in (
            self._patterns.definition,
            self._patterns.definition_curly,
            _DEFINITION_SINGLE,
            _DEFINITION_SINGLE_CURLY,
            _DEFINITION_SHALL_HAVE_MEANING,
        ):  # type: ignore[attr-defined]
            for m in pattern.finditer(text):
                term = m.group(1).strip()
                raw_matches.append((m.start(), m.end(), term))

        # Sort by position.
        raw_matches.sort(key=lambda t: t[0])

        # Pre-compute all clause-label positions for source_clause inference.
        clause_labels = self._collect_clause_labels(text)

        results: dict[str, DefinedTerm] = {}

        for start, end, term in raw_matches:
            if not self._is_valid_term(term):
                continue

            # Infer the clause this definition lives in.
            clause = self._nearest_clause_label(clause_labels, start) or source_clause

            # Extract the body of the definition.
            body = self._extract_definition_body(text, end)

            if not body:
                continue

            # Only store the first occurrence (document order); the caller
            # merges two passes and definitions-section wins.
            if term not in results:
                results[term] = DefinedTerm(
                    term=term,
                    definition=body,
                    source_clause=clause,
                )

        # --- Inline parenthetical definitions ---
        # These don't have a "means" body; the context is the surrounding
        # sentence.  Extract all quoted terms inside parentheses.
        for group_m in _INLINE_PAREN_GROUP.finditer(text):
            paren_text = group_m.group(0)
            clause = self._nearest_clause_label(clause_labels, group_m.start()) or source_clause or "preamble"
            for term_m in _INLINE_PAREN_TERM.finditer(paren_text):
                term = term_m.group(1).strip()
                if not self._is_valid_term(term):
                    continue
                if term not in results:
                    results[term] = DefinedTerm(
                        term=term,
                        definition=paren_text.strip(),
                        source_clause=clause,
                    )

        # --- Parenthetical back-reference definitions ---
        # e.g. "the Borrower (as defined in Section 1.1)"
        for m in _PARENTHETICAL_BACKREF.finditer(text):
            term = m.group(1).strip()
            if not self._is_valid_term(term):
                continue
            if term not in results:
                clause = self._nearest_clause_label(clause_labels, m.start()) or source_clause or "preamble"
                results[term] = DefinedTerm(
                    term=term,
                    definition=m.group(0).strip(),
                    source_clause=clause,
                )

        return results

    def _extract_definition_body(self, text: str, match_end: int) -> str:
        """Extract the full definition body starting at match_end.

        A definition body ends when:

        - A new definition starts (next ``"Term"`` means pattern).
        - A blank line followed by a clause header.
        - Two consecutive blank lines.

        Args:
            text: Full text being scanned.
            match_end: Character offset immediately after the matched pattern
                (i.e. the character right after the "means" keyword and any
                trailing space).

        Returns:
            The extracted definition text, stripped of leading/trailing
            whitespace.
        """
        remaining = text[match_end:]

        # Find the earliest termination point from any stop condition.
        stop = len(remaining)

        # 1. Next definition match.
        for pat in (self._patterns.definition, self._patterns.definition_curly, _DEFINITION_SINGLE, _DEFINITION_SINGLE_CURLY):  # type: ignore[attr-defined]
            m = pat.search(remaining)
            if m:
                stop = min(stop, m.start())

        # 2. Two consecutive blank lines (paragraph boundary).
        double_blank = re.search(r"\n\s*\n\s*\n", remaining)
        if double_blank:
            stop = min(stop, double_blank.start())

        # 3. Blank line immediately followed by a clause-header line.
        blank_then_header = re.search(
            r"\n[ \t]*\n[ \t]*(?="
            + self._clause_header_re.pattern
            + r")",
            remaining,
            re.MULTILINE,
        )
        if blank_then_header:
            stop = min(stop, blank_then_header.start())

        body = remaining[:stop].strip()
        # Collapse internal runs of whitespace / newlines to a single space
        # so the definition is returned as a clean single-line string.
        body = re.sub(r"\s+", " ", body)
        return body

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _is_valid_term(self, term: str) -> bool:
        """Return True if ``term`` should be kept as a defined term.

        Applies the following rejection rules:

        - Fewer than 2 characters.
        - Pure numeric string.
        - Member of the ``_SKIP_TERMS`` stop-list ("The", "A", etc.).

        Args:
            term: Candidate term extracted from the document.

        Returns:
            ``True`` if the term passes all validity checks.
        """
        if len(term) < 2:
            return False
        if term.isdigit():
            return False
        if term in _SKIP_TERMS:
            return False
        return True

    def _collect_clause_labels(self, text: str) -> list[tuple[int, str]]:
        """Collect (offset, label) pairs for all clause headers in ``text``.

        Args:
            text: Document text to scan.

        Returns:
            List of ``(char_offset, label_string)`` tuples sorted by offset.
        """
        labels: list[tuple[int, str]] = []
        for m in _CLAUSE_LABEL.finditer(text):
            # Pick the first non-None capturing group as the identifier.
            label = next((g for g in m.groups() if g is not None), None)
            if label:
                labels.append((m.start(), label.strip()))
        return labels

    def _nearest_clause_label(
        self, labels: list[tuple[int, str]], pos: int
    ) -> str | None:
        """Return the clause label immediately preceding ``pos``.

        Uses ``bisect`` for O(log n) lookup instead of a linear scan.

        Args:
            labels: Sorted list of ``(offset, label)`` tuples.
            pos: Character offset of the definition match start.

        Returns:
            The label string, or ``None`` if no label precedes ``pos``.
        """
        if not labels:
            return None
        # bisect_left on the offset component; labels is sorted by offset.
        idx = bisect.bisect_left(labels, (pos,))
        # idx is the first label with offset >= pos; we want the one before it.
        if idx == 0:
            return None
        return labels[idx - 1][1]

    def _infer_clause_label(self, section_text: str) -> str | None:
        """Infer a clause identifier from the first line of a section.

        Args:
            section_text: Text of the section (first line is the header).

        Returns:
            Clause identifier string, or ``None`` if it cannot be determined.
        """
        first_line = section_text.split("\n", 1)[0]
        labels = self._collect_clause_labels(first_line)
        if labels:
            return labels[0][1]
        return None


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def extract_defined_terms(
    text: str, jurisdiction: Jurisdiction
) -> dict[str, DefinedTerm]:
    """Extract all defined terms from a legal document.

    Convenience wrapper around :class:`DefinitionsExtractor`.

    Args:
        text: Full document text.
        jurisdiction: The legal jurisdiction (UK or US).

    Returns:
        Dict mapping term name (str) to :class:`DefinedTerm`.
    """
    return DefinitionsExtractor(jurisdiction).extract(text)
