"""Defined terms extractor for legal documents."""

from __future__ import annotations

import bisect
import logging
import re
from typing import Optional

from .._patterns import (
    CLOSE_QUOTE,
    NOT_AFTER_WORD,
    OPEN_QUOTE,
    TERM_ANY,
    TERM_ANY_SHORT,
    TERM_CHARS,
    TERM_LOWER,
    TERM_UPPER,
)
from ..jurisdiction import get_detect_level, get_patterns

logger = logging.getLogger(__name__)
from ..models import DefinedTerm, Jurisdiction, JurisdictionPatterns

# Terms that should be filtered out even if capitalised.
_SKIP_TERMS: frozenset[str] = frozenset({
    "The", "A", "An", "This", "That",
    "Each", "Any", "All", "Such", "No",
    "If", "Where", "When", "Upon",
    "In", "For", "By", "At", "On", "To", "Of", "Or", "And", "But", "Not",
    "It", "We", "You", "They", "Our", "Your", "Its",
})

# Case-folded view of ``_SKIP_TERMS``, consulted only for lowercase-initial
# terms so that the behaviour of capitalised terms is unchanged.
_SKIP_TERMS_LOWER: frozenset[str] = frozenset(t.lower() for t in _SKIP_TERMS)

# Regex matching a blank line (zero or more spaces, then newline).
_BLANK_LINE: re.Pattern[str] = re.compile(r"^\s*$", re.MULTILINE)

# A standalone ALL-CAPS line starting a new operative section.  A definition
# body must stop before one even when no blank line separates them: the last
# definition of a section otherwise ran straight into the heading below it
# ("Charlie" -> "the third letter. GOVERNING LAW This Agreement is governed
# by ...").
_ALLCAPS_LINE_AHEAD: re.Pattern[str] = re.compile(
    r"\n[ \t]*(?=[A-Z][A-Z \t&/-]{2,}[ \t]*(?:\n|$))"
)

# A clause-entry marker ("1.2", "(a)", "(iv)", "Section 1.2", "Article II")
# left dangling at the end of a captured definition body.  When definitions
# are separated by a single newline rather than a blank line, the next entry's
# own marker sits between the end of this definition and the quote that opens
# the next term, so it is captured as part of this definition's text
# ("the first thing. 1.2").
#
# The leading ``\n`` is load-bearing: it is what distinguishes that dangling
# marker from a number that legitimately ends the sentence, as in
# ``"Gamma" shall have the meaning set forth in Section 3.`` — so this is
# applied to the raw slice, before newlines are collapsed to spaces.
_TRAILING_CLAUSE_LABEL: re.Pattern[str] = re.compile(
    r"\n[ \t]*(?:"
    r"\d+(?:\.\d+)*\.?"
    r"|\([a-z]\)"
    r"|\([ivxlc]+\)"
    r"|(?:Section|Article|Clause|Paragraph|Chapter)\s+"
    r"(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.?)"
    r")[ \t]*\Z",
    re.IGNORECASE,
)

# How far back a "hereinafter" definition looks for its body.
_HEREINAFTER_LOOKBACK: int = 500

# Two blank lines — a paragraph boundary, and one of the conditions that ends
# a definition body.  Compiled once; it used to be re-looked-up per call.
_DOUBLE_BLANK_LINE: re.Pattern[str] = re.compile(r"\n\s*\n\s*\n")

# How far past the best-known body end each stop-condition search may look.
# See :meth:`DefinitionsExtractor._extract_definition_body`: only the earliest
# match start matters, so a search need only cover the current boundary plus
# the widest span any stop pattern can match.  Every stop pattern matches a
# quoted term and a keyword, a blank-line pair, or a single line, so 4 KB is
# orders of magnitude more than enough; the value exists to make the loop
# linear in the document rather than quadratic, not to be tight.
_STOP_SEARCH_SLACK: int = 4096

# Runs of whitespace inside a captured term name.
_TERM_WHITESPACE: re.Pattern[str] = re.compile(r"\s+")


def _normalise_term(term: str) -> str:
    """Collapse internal whitespace in a captured defined-term name.

    The term character classes include ``\\s``, so a quoted term that wraps
    across a line is captured with a literal newline inside it
    (``"Indemnifying\\nParty"``) — a dictionary key no lookup for the rendered
    term can ever match (D16).

    Args:
        term: The raw captured term name.

    Returns:
        The term with internal whitespace runs collapsed to single spaces and
        leading/trailing whitespace removed.
    """
    return _TERM_WHITESPACE.sub(" ", term).strip()

# Single-quote definition patterns (straight and curly).
# ~30-40% of UK contracts use single quotes for defined terms.
_DEFINITION_SINGLE: re.Pattern[str] = re.compile(
    NOT_AFTER_WORD + rf"'({TERM_UPPER})'\s+"
    r"(?:means|shall mean|has the meaning|is defined as|refers to)",
    re.MULTILINE,
)
_DEFINITION_SINGLE_CURLY: re.Pattern[str] = re.compile(
    NOT_AFTER_WORD + rf"\u2018({TERM_UPPER})\u2019\s+"
    r"(?:means|shall mean|has the meaning|is defined as|refers to)",
    re.MULTILINE,
)

# "shall have the meaning" form (straight + curly quotes).
# e.g. "Term" shall have the meaning set forth in Section 1.1
_DEFINITION_SHALL_HAVE_MEANING: re.Pattern[str] = re.compile(
    NOT_AFTER_WORD + rf'["\u201c]({TERM_UPPER})["\u201d]\s+shall have the meaning',
    re.MULTILINE,
)

# Inline parenthetical definitions.
# e.g. (each a "Party" and together the "Parties")
# e.g. (the "Effective Date")
# First, find parenthetical groups that contain at least one quoted term.
_INLINE_PAREN_GROUP: re.Pattern[str] = re.compile(
    rf'\([^)]*?["\u201c]{TERM_UPPER}["\u201d][^)]*?\)',
    re.MULTILINE,
)
# Then, extract individual quoted terms within a parenthetical group.
_INLINE_PAREN_TERM: re.Pattern[str] = re.compile(
    NOT_AFTER_WORD + rf'["\u201c]({TERM_UPPER})["\u201d]',
)

# Lowercase-article definitions (straight and single quotes).
# e.g. "the Company" means..., 'the Supplier' means...
# Captures the full term including the article ("the Company", not "Company").
_DEFINITION_ARTICLE: re.Pattern[str] = re.compile(
    NOT_AFTER_WORD + rf'["\u201c](the\s+{TERM_UPPER})["\u201d]\s+'
    r'(?:means|shall mean|has the meaning|is defined as|refers to)',
    re.MULTILINE,
)
_DEFINITION_ARTICLE_SINGLE: re.Pattern[str] = re.compile(
    NOT_AFTER_WORD + rf"['\u2018](the\s+{TERM_UPPER})['\u2019]\s+"
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
    + NOT_AFTER_WORD
    + rf'["\u201c]((?:the\s+)?{TERM_UPPER})["\u201d]',
    re.MULTILINE,
)

# Lowercase-initial quoted definitions (straight, curly and single quotes).
# e.g. "business day" means any day other than a Saturday or Sunday.
# Most contracts capitalise defined terms, but not all; without this pattern
# the term is invisible rather than merely mis-cased (D27).
_DEFINITION_LOWERCASE: re.Pattern[str] = re.compile(
    NOT_AFTER_WORD + rf"{OPEN_QUOTE}({TERM_LOWER}){CLOSE_QUOTE}\s+"
    r"(?:means|shall mean|has the meaning|is defined as|refers to)",
    re.MULTILINE,
)

# Parenthesised-plural defined terms, e.g. "Affiliate(s)" means ...
# The canonical term is the singular stem; the plural form is registered as an
# alias so downstream whole-word matching finds both (D27).
_DEFINITION_PAREN_PLURAL: re.Pattern[str] = re.compile(
    NOT_AFTER_WORD + rf"{OPEN_QUOTE}({TERM_ANY_SHORT})\((s|es)\)"
    rf"{CLOSE_QUOTE}\s+"
    r"(?:means|shall mean|has the meaning|is defined as|refers to)",
    re.MULTILINE,
)

# The "individually as a 'X' and collectively as the 'Y'" idiom, which defines
# two terms (singular and plural) with one shared definition and - unlike
# ``_INLINE_PAREN_GROUP`` - carries no enclosing parentheses (D27).
# e.g. Each of Provider and Customer may be referred to individually as a
#      "Party" and collectively as the "Parties."
_DEFINITION_INDIVIDUALLY_COLLECTIVELY: re.Pattern[str] = re.compile(
    r"individually\s+as\s+(?:an?|the)\s+"
    + NOT_AFTER_WORD + rf"{OPEN_QUOTE}({TERM_ANY})[.,]?{CLOSE_QUOTE}"
    r"[^\"'“”‘’]{0,80}?"
    r"collectively\s+as\s+(?:an?|the)\s+"
    + NOT_AFTER_WORD + rf"{OPEN_QUOTE}({TERM_ANY})[.,]?{CLOSE_QUOTE}",
    re.IGNORECASE | re.MULTILINE,
)

# Parenthetical back-reference definitions.
# e.g. the Borrower (as defined in Section 1.1)
_PARENTHETICAL_BACKREF: re.Pattern[str] = re.compile(
    rf'the\s+([A-Z][{TERM_CHARS}]{{1,60}}?)\s*\(\s*as\s+defined\s+in\b',
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

    Supports every built-in jurisdiction (UK, US and EU) as well as custom
    registered ones, and handles straight/curly-quote definition patterns.  The extractor first attempts to locate a dedicated
    definitions section; if none is found it falls back to scanning the entire
    document.

    Attributes:
        _jurisdiction: The jurisdiction whose pattern set will be used.
        _patterns: Compiled pattern dataclass for the jurisdiction.
        _detect_level: Registered clause-header detector for this jurisdiction.
    """

    def __init__(self, jurisdiction: Jurisdiction | str) -> None:
        """Initialise the extractor for a given jurisdiction.

        Args:
            jurisdiction: ``"uk"``, ``"us"`` or ``"eu"`` (or a
                :class:`~lexichunk.models.Jurisdiction` enum value), or the key of a
                custom jurisdiction registered via :func:`register_jurisdiction`.
        """
        self._jurisdiction: Jurisdiction | str = jurisdiction
        self._patterns: JurisdictionPatterns = get_patterns(jurisdiction)
        self._detect_level = get_detect_level(jurisdiction)

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
        offset = after
        for line in text[after:].splitlines(keepends=True):
            detected = self._detect_level(line.rstrip("\r\n"))
            if (
                detected is not None
                and detected[0] <= found_level
                and self._is_boundary_heading(line, detected)
            ):
                return offset
            offset += len(line)

        return len(text)

    def _header_level(self, line: str) -> int:
        """Return the hierarchy level of a clause header line.

        Args:
            line: The clause header text.

        Returns:
            Integer level (lower = higher in hierarchy).
        """
        detected = self._detect_level(line)
        return detected[0] if detected is not None else 0

    @staticmethod
    def _is_boundary_heading(line: str, detected: tuple[int, str]) -> bool:
        identifier = detected[1]
        if not re.match(
            r"^(?:clause|section|article|chapter|schedule|appendix|exhibit|annexe?|recital)\b",
            identifier,
            re.IGNORECASE,
        ):
            return True
        stripped = line.lstrip()
        remainder = stripped[len(identifier) :].lstrip(" .:\t-\u2013\u2014")
        return not remainder or not remainder[0].islower()

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

        for pattern in self._definition_patterns():
            for m in pattern.finditer(text):
                term = _normalise_term(m.group(1))
                raw_matches.append((m.start(), m.end(), term))

        # Parenthesised plurals: '"Affiliate(s)" means …'.  The canonical term
        # is the singular stem; the plural form is registered as an alias so a
        # whole-word search for either form finds the definition.
        plural_aliases: dict[str, str] = {}  # alias term → canonical term
        for m in _DEFINITION_PAREN_PLURAL.finditer(text):
            stem = _normalise_term(m.group(1))
            raw_matches.append((m.start(), m.end(), stem))
            plural_aliases[stem + m.group(2)] = stem

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

        # Register plural aliases for parenthesised-plural definitions so that
        # both "Affiliate" and "Affiliates" find the same definition.
        for alias, canonical in plural_aliases.items():
            canonical_dt = results.get(canonical)
            if canonical_dt is not None and alias not in results:
                results[alias] = DefinedTerm(
                    term=alias,
                    definition=canonical_dt.definition,
                    source_clause=canonical_dt.source_clause,
                )

        # --- "individually as a 'X' and collectively as the 'Y'" ---
        # Defines two terms sharing one definition, without parentheses.
        for m in _DEFINITION_INDIVIDUALLY_COLLECTIVELY.finditer(text):
            clause = (
                self._nearest_clause_label(clause_labels, m.start())
                or source_clause
                or "preamble"
            )
            definition = re.sub(r"\s+", " ", m.group(0).strip())
            for group_index in (1, 2):
                term = _normalise_term(m.group(group_index))
                if not self._is_valid_term(term):
                    continue
                if term not in results:
                    results[term] = DefinedTerm(
                        term=term,
                        definition=definition,
                        source_clause=clause,
                    )

        # --- Inline parenthetical definitions ---
        # These don't have a "means" body; the context is the surrounding
        # sentence.  Extract all quoted terms inside parentheses.
        for group_m in _INLINE_PAREN_GROUP.finditer(text):
            paren_text = group_m.group(0)
            clause = self._nearest_clause_label(clause_labels, group_m.start()) or source_clause or "preamble"
            for term_m in _INLINE_PAREN_TERM.finditer(paren_text):
                term = _normalise_term(term_m.group(1))
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
            term = _normalise_term(m.group(1))
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
            term = _normalise_term(m.group(1))
            if not self._is_valid_term(term):
                continue
            if term not in results:
                clause = self._nearest_clause_label(clause_labels, m.start()) or source_clause or "preamble"
                body = self._hereinafter_body(text, m.start())
                if not body:
                    body = m.group(0).strip()
                results[term] = DefinedTerm(
                    term=term,
                    definition=re.sub(r"\s+", " ", body),
                    source_clause=clause,
                )

        return results

    def _definition_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Return every pattern that can *start* a definition, in scan order.

        Both :meth:`_extract_definitions_from_text` and
        :meth:`_extract_definition_body` consult this single list — the body
        extractor must stop at *any* pattern the extractor recognises, or a
        definition body runs straight through the next definition (D15).

        Returns:
            Tuple of compiled patterns whose group 1 is the defined term.
        """
        return (
            self._patterns.definition,  # type: ignore[attr-defined]
            self._patterns.definition_curly,  # type: ignore[attr-defined]
            _DEFINITION_SINGLE,
            _DEFINITION_SINGLE_CURLY,
            _DEFINITION_SHALL_HAVE_MEANING,
            _DEFINITION_ARTICLE,
            _DEFINITION_ARTICLE_SINGLE,
            _DEFINITION_LOWERCASE,
        )

    def _hereinafter_body(self, text: str, match_start: int) -> str:
        """Return the definition body preceding a "hereinafter" match.

        The body is the preceding text back to the nearest sentence-ish
        boundary (``.``, ``;`` or a newline) within a 500-character window.
        When the window contains no boundary at all *and* was truncated
        mid-word, the leading partial word is dropped so the body never begins
        in the middle of a word (D26).

        Args:
            text: Full text being scanned.
            match_start: Offset of the "hereinafter" match.

        Returns:
            The whitespace-normalised definition body (possibly empty).
        """
        window_start = max(0, match_start - _HEREINAFTER_LOOKBACK)
        preceding = text[window_start:match_start]

        boundary = max(
            preceding.rfind("."), preceding.rfind(";"), preceding.rfind("\n")
        )
        if boundary >= 0:
            body = preceding[boundary + 1:]
        elif window_start > 0:
            # The window was truncated; skip to the next word boundary rather
            # than starting mid-word.
            ws = re.search(r"\s", preceding)
            body = preceding[ws.end():] if ws is not None else ""
        else:
            body = preceding

        return re.sub(r"\s+", " ", body.strip())

    def _extract_definition_body(self, text: str, match_end: int) -> str:
        """Extract the full definition body starting at match_end.

        A definition body ends when:

        - A new definition starts — *any* of the patterns the extractor uses,
          including the "shall have the meaning", lowercase-article,
          parenthesised-plural, lowercase-initial and hereinafter forms.
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
        #
        # Every search below is bounded to the best boundary found so far plus
        # _STOP_SEARCH_SLACK.  Unbounded, this loop was quadratic in the
        # document: each of the ~14 stop patterns scanned from the definition
        # to the end of the text, once per definition.  A pattern with no
        # further match anywhere -- the common case, since most documents use
        # two or three definition forms, not fourteen -- paid a full scan
        # every time.  On a 292k-character CUAD contract with 414 definitions
        # that was 20 seconds, against 0.04s median for the corpus, and it
        # scaled with content rather than length: synthetic text of twice the
        # size chunked in 2% of the time because it had nothing to define.
        #
        # Bounding is safe because only the *earliest* start matters.  A match
        # starting at or after `stop` cannot lower it, and one starting before
        # `stop` is still found so long as it spans less than the slack --
        # which every stop pattern does by a wide margin (they match a quoted
        # term and a keyword, a blank-line pair, or a single line).
        stop = len(remaining)

        def note(match: Optional[re.Match[str]]) -> None:
            nonlocal stop
            if match is not None and match.start() < stop:
                stop = match.start()

        def limit() -> int:
            return min(len(remaining), stop + _STOP_SEARCH_SLACK)

        # 1. Next definition match — every start pattern the extractor uses.
        for pat in (
            *self._definition_patterns(),
            _DEFINITION_PAREN_PLURAL,
            _DEFINITION_HEREINAFTER,
        ):
            note(pat.search(remaining, 0, limit()))

        # 2. Two consecutive blank lines (paragraph boundary).
        note(_DOUBLE_BLANK_LINE.search(remaining, 0, limit()))

        # 3. Blank line immediately followed by a clause-header line.
        #    Scanned line by line rather than with one pre-built regex: the
        #    header test is the jurisdiction's registered ``detect_level``
        #    plus the boundary-heading heuristic, which no single pattern
        #    expresses — and going through the registry is what makes a
        #    custom registered jurisdiction's boundaries apply here at all.
        #    Bounded by the same ``limit()`` as the searches above so the
        #    scan stays linear in the document; a candidate whose blank run
        #    starts at or after ``stop`` could not lower it anyway.
        window = remaining[: limit()]
        lines = window.splitlines(keepends=True)
        if len(window) < len(remaining) and lines and not lines[-1].endswith("\n"):
            # A line the bound cut in half is not a heading; drop it.
            lines.pop()
        line_offset = 0
        blank_start: int | None = None
        for line in lines:
            if line.strip():
                detected = self._detect_level(line.rstrip("\r\n"))
                if (
                    blank_start is not None
                    and detected is not None
                    and self._is_boundary_heading(line, detected)
                ):
                    stop = min(stop, blank_start)
                    break
                blank_start = None
            elif blank_start is None:
                blank_start = line_offset
            line_offset += len(line)

        # 4. A standalone ALL-CAPS line — an operative heading typed directly
        #    under the last definition of a section, with no blank line.
        note(_ALLCAPS_LINE_AHEAD.search(remaining, 0, limit()))

        # 5. Drop a dangling next-entry marker.  Stop condition 1 ends the
        #    body at the quote that opens the *next* term, so when entries are
        #    separated by a single newline instead of a blank line that
        #    entry's own number ("1.2", "(b)") sits inside this body.  Done on
        #    the raw slice, because the newline before the marker is what
        #    tells it apart from a sentence-final number.
        body = _TRAILING_CLAUSE_LABEL.sub("", remaining[:stop].rstrip()).strip()
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
        - A lowercase-initial term whose case-folded form is in the stop-list
          (only lowercase-initial terms are checked case-insensitively, so the
          treatment of capitalised terms is unchanged).

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
        if term[0].islower() and term.lower() in _SKIP_TERMS_LOWER:
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
        jurisdiction: ``"uk"``, ``"us"`` or ``"eu"`` (or a
            :class:`~lexichunk.models.Jurisdiction` enum value), or the key of a
            custom registered jurisdiction.

    Returns:
        Dict mapping term name (str) to :class:`DefinedTerm`.
    """
    return DefinitionsExtractor(jurisdiction).extract(text)
