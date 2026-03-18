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
from ..models import DefinedTerm, Jurisdiction, JurisdictionPatterns

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

# Lowercase-article definitions (straight and single quotes).
# e.g. "the Company" means..., 'the Supplier' means...
# Captures the full term including the article ("the Company", not "Company").
_DEFINITION_ARTICLE: re.Pattern[str] = re.compile(
    r'["\u201c](the\s+[A-Z][A-Za-z\s\-]{1,60})["\u201d]\s+'
    r'(?:means|shall mean|has the meaning|is defined as|refers to)',
    re.MULTILINE,
)
_DEFINITION_ARTICLE_SINGLE: re.Pattern[str] = re.compile(
    r"['\u2018](the\s+[A-Z][A-Za-z\s\-]{1,60})['\u2019]\s+"
    r"(?:means|shall mean|has the meaning|is defined as|refers to)",
    re.MULTILINE,
)

# "Hereinafter" definition pattern.
# e.g. hereinafter referred to as "the Company"
# Supports straight and curly quotes.  The keyword portion is
# case-insensitive via inline (?i:...) but the term capture group
# allows an optional lowercase article before the uppercase term.
_DEFINITION_HEREINAFTER: re.Pattern[str] = re.compile(
    r'(?i:hereinafter\s+(?:referred\s+to\s+as|called|known\s+as))\s+'
    r'["\u201c]((?:the\s+)?[A-Z][A-Za-z\s\-]{1,60})["\u201d]',
    re.MULTILINE,
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
_EU_CLAUSE_HEADER: re.Pattern[str] = re.compile(
    r"^(?:(?:CHAPTER|Chapter)\s+[IVXLC]+|(?:ARTICLE|Article)\s+\d+|"
    r"(?:SECTION|Section)\s+\d+|\d+\.\s+\S|\([a-z]\)\s|\([ivxlc]+\)\s)",
    re.MULTILINE,
)

# Pattern that matches a clause-number token at the beginning of a line; used
# to infer source_clause when scanning the whole document.
_CLAUSE_LABEL: re.Pattern[str] = re.compile(
    r"^(?:"
    r"(?:ARTICLE|Article)\s+([IVXLC]+)"         # US article (Roman)
    r"|(?:ARTICLE|Article)\s+(\d+)"             # EU article (Arabic)
    r"|(?:SECTION|Section)\s+(\d+\.\d+\S*)"     # US section
    r"|(?:CHAPTER|Chapter)\s+([IVXLC]+)"        # EU chapter
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

    def __init__(self, jurisdiction: Jurisdiction | str) -> None:
        """Initialise the extractor for a given jurisdiction.

        Args:
            jurisdiction: The legal jurisdiction (UK or US), or a custom
                jurisdiction string registered via :func:`register_jurisdiction`.
        """
        self._jurisdiction: Jurisdiction | str = jurisdiction
        self._patterns: Union[UKPatterns, USPatterns, JurisdictionPatterns] = get_patterns(jurisdiction)
        if jurisdiction == Jurisdiction.UK:
            self._clause_header_re: re.Pattern[str] = _UK_CLAUSE_HEADER
        elif jurisdiction == Jurisdiction.EU:
            self._clause_header_re = _EU_CLAUSE_HEADER
        else:
            self._clause_header_re = _US_CLAUSE_HEADER

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

        # Build a pattern that finds a clause header whose title IS one of the
        # definitions header strings (at a word boundary, not as a substring of
        # a longer phrase like "Definitions of Key Metrics").
        header_alts = "|".join(re.escape(h) for h in headers)
        # Use word boundaries so "interpretation" matches "Interpretation" but
        # not "Interpretation Guidelines".  The header word must either end the
        # line or be followed by whitespace/punctuation (not more title words).
        bounded = r"(?:" + header_alts + r")(?:\s*$|[\s\-\u2013\u2014,;:])"
        # Matches lines such as:
        #   "1. Definitions"  "1.1 Interpretation"  "ARTICLE I — DEFINITIONS"
        #   "Section 1.01 Definitions"  "DEFINITIONS"
        section_start_re = re.compile(
            r"^(?:"
            r"(?:ARTICLE|Article)\s+[\dIVXLC]+[^\n]*" + bounded
            + r"|(?:SECTION|Section)\s+[\d.]+[^\n]*" + bounded
            + r"|\d+(?:\.\d+)*\.?\s+[^\n]*" + bounded
            + r"|(?:" + header_alts + r")\s*$"
            + r")",
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
        elif self._jurisdiction == Jurisdiction.EU:
            next_header_re = re.compile(
                r"^(?:"
                r"((?:CHAPTER|Chapter)\s+[IVXLC]+)"    # level -1
                r"|((?:ARTICLE|Article)\s+\d+)"         # level 0
                r"|((?:SECTION|Section)\s+\d+)"         # level 1
                r"|((?:ANNEX|Annex)\s+[IVXLC]+)"        # level -2
                r"|(\d+)\.\s"                           # level 2 (numbered paragraph)
                r")",
                re.MULTILINE,
            )
            level_map = {0: -1, 1: 0, 2: 1, 3: -2, 4: 2}  # group-index → level
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
        elif self._jurisdiction == Jurisdiction.EU:
            if re.match(r"^(?:CHAPTER|Chapter)", l):
                return -1
            if re.match(r"^(?:ARTICLE|Article)", l):
                return 0
            if re.match(r"^(?:SECTION|Section)", l):
                return 1
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
            _DEFINITION_ARTICLE,
            _DEFINITION_ARTICLE_SINGLE,
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

        # --- Hereinafter definitions ---
        # e.g. 'XYZ Corp hereinafter referred to as "the Company"'
        # The definition body is the text *before* "hereinafter", not after.
        for m in _DEFINITION_HEREINAFTER.finditer(text):
            term = m.group(1).strip()
            if not self._is_valid_term(term):
                continue
            if term not in results:
                clause = self._nearest_clause_label(clause_labels, m.start()) or source_clause or "preamble"
                # Extract up to ~500 chars preceding context to the last
                # sentence boundary.
                preceding = text[max(0, m.start() - 500):m.start()]
                # Find the last sentence boundary in the preceding text.
                last_dot = preceding.rfind(".")
                if last_dot >= 0:
                    body = preceding[last_dot + 1:].strip()
                else:
                    body = preceding.strip()
                if not body:
                    body = m.group(0).strip()
                results[term] = DefinedTerm(
                    term=term,
                    definition=re.sub(r"\s+", " ", body),
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
        # Extract offsets into a flat list for safe bisect (avoids tuple
        # comparison edge case when pos exactly equals an offset).
        offsets = [o for o, _ in labels]
        idx = bisect.bisect_right(offsets, pos)
        # idx is the first label with offset > pos; we want the one before it.
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
