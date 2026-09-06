"""Legal document structure parser — section/clause boundary detection.

This module detects clause/section boundaries in legal text and builds a
document hierarchy encoded as a flat list of :class:`ParsedClause` objects.
It is the primary consumer of the jurisdiction-specific ``detect_level``
functions and is itself consumed by the chunker.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..jurisdiction import get_detect_level, get_patterns
from ..models import DocumentSection, HierarchyNode, Jurisdiction

# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class ParsedClause:
    """A single detected clause with its structural metadata.

    Attributes:
        identifier: Normalised identifier string (e.g. ``"1.1"`` or
            ``"Article I"``).
        title: Heading text extracted from the same line as the identifier,
            or ``None`` when no heading is present.
        content: Full text *owned* by this clause, excluding the text of its
            children.  Leading and trailing whitespace is preserved so that
            ``char_start``/``char_end`` offsets remain consistent.
        level: Hierarchy level as returned by the jurisdiction
            ``detect_level`` function.
        parent_identifier: ``identifier`` of the immediately enclosing
            clause, or ``None`` for top-level clauses.
        document_section: High-level :class:`~lexichunk.models.DocumentSection`
            classification.
        char_start: Zero-based character offset of the first character of
            this clause (inclusive) in the original ``text`` argument passed
            to :meth:`StructureParser.parse`.
        char_end: Zero-based character offset one past the last character of
            this clause (exclusive) in the original text.
        children: Direct child :class:`ParsedClause` objects in document
            order.  Populated during parsing but the flat list returned by
            :meth:`StructureParser.parse` is ordered by ``char_start``, not
            nested.
        uid: Stable identifier assigned by :meth:`StructureParser.parse`, a
            monotonically increasing counter (as a string) in the order
            clauses are opened while walking the document.  Distinct from
            ``identifier``, which is derived from the clause's own heading
            text and is not guaranteed unique (e.g. repeated ``"(a)"``
            sub-clauses under different parents).  Defaults to ``""`` for
            construction sites that don't assign one explicitly.
        parent_uid: ``uid`` of the enclosing clause that was open on the
            parser's stack when this clause was created, or ``None`` for
            top-level clauses and the synthetic preamble.  Always refers to
            a clause with a strictly smaller ``uid`` (its parent was opened
            — and thus assigned a uid — first).
    """

    identifier: str
    title: Optional[str]
    content: str
    level: int
    parent_identifier: Optional[str]
    document_section: DocumentSection
    char_start: int
    char_end: int
    children: list[ParsedClause] = field(default_factory=list)
    uid: str = ""
    parent_uid: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# Maximum number of characters kept from a heading line's remainder when it
# is used as a clause ``title``.  Longer remainders are almost always body
# text that happens to follow an identifier on the same line.
MAX_TITLE_CHARS = 120

# A remainder that ends like a sentence and has more words than this is
# treated as prose, not as a heading title.
_MAX_TITLE_WORDS = 12

# Separator characters that may sit between an identifier and its title
# (``"SCHEDULE 2 - FEES"``, ``"Article I — Definitions"``).
_TITLE_SEPARATORS = "-–—:"


def _remainder_after_identifier(line: str, identifier: str) -> str:
    """Return the raw text of *line* that follows *identifier*.

    The identifier token itself (plus an optional trailing dot, any
    whitespace, and a single leading ``-``/``–``/``—``/``:``
    separator) is removed.  Matching is case-insensitive so that a
    normalised identifier such as ``"Chapter I"`` still strips the literal
    ``"CHAPTER I"`` written in the document.

    Args:
        line: The raw header line as found in the source text.
        identifier: The identifier string as returned by ``detect_level``.

    Returns:
        The remaining text, stripped of surrounding whitespace (possibly
        the empty string).
    """
    s = line.lstrip()
    escaped = re.escape(identifier)
    pattern = rf"^{escaped}\.?\s*(?:[{re.escape(_TITLE_SEPARATORS)}]\s*)?"
    remainder = re.sub(pattern, "", s, count=1, flags=re.IGNORECASE)
    return remainder.strip()


def _is_sentence_shaped(remainder: str) -> bool:
    """Return ``True`` when *remainder* reads as prose rather than a title."""
    return (
        remainder.endswith((".", ";"))
        and len(remainder.split()) > _MAX_TITLE_WORDS
    )


def _extract_title(line: str, identifier: str) -> Optional[str]:
    """Return the heading text that follows *identifier* on *line*.

    The function strips the identifier token itself (including any trailing
    dot, a separator dash/colon and surrounding whitespace) from the
    stripped line and returns whatever non-empty text remains, subject to
    two hygiene rules:

    * a remainder that is *sentence-shaped* (more than 12 words and ending
      in ``.`` or ``;``) is body text that happens to share the header
      line, and yields ``None``;
    * anything longer than :data:`MAX_TITLE_CHARS` is truncated, so a
      runaway remainder cannot flood ``hierarchy_path``.

    Args:
        line: The raw header line as found in the source text.
        identifier: The identifier string as returned by ``detect_level``
            (e.g. ``"1.1"`` or ``"(a)"``).

    Returns:
        The heading text, or ``None`` if nothing usable remains.
    """
    remainder = _remainder_after_identifier(line, identifier)
    if not remainder:
        return None
    if _is_sentence_shaped(remainder):
        return None
    if len(remainder) > MAX_TITLE_CHARS:
        remainder = remainder[:MAX_TITLE_CHARS].rstrip()
    return remainder or None


# Maximum number of words the line below an untitled container heading may
# contain to be adopted as that heading's title.
_MAX_ADOPTED_TITLE_WORDS = 8

# Terminal punctuation that marks the line below a heading as prose, not as
# the heading's title.
_ADOPTED_TITLE_TERMINATORS = ('.', ';', ':')

# Words kept lower-case when an ALL-CAPS adopted title is re-cased, unless
# they are the first word ("DEFINITIONS AND INTERPRETATION" →
# "Definitions and Interpretation").
_TITLE_CASE_MINOR_WORDS = frozenset({
    'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'from', 'in', 'nor',
    'of', 'on', 'or', 'the', 'to', 'via', 'with',
})


def _title_case(text: str) -> str:
    """Re-case an ALL-CAPS heading line as a title.

    Each whitespace-separated token is capitalised, except minor words
    (``and``, ``of``, ``the`` …) anywhere but in first position.  Only the
    leading letter is touched, so hyphenated and parenthesised tokens survive
    intact.

    Args:
        text: An ALL-CAPS line.

    Returns:
        The title-cased line.
    """
    words = text.split()
    recased: list[str] = []
    for position, word in enumerate(words):
        lowered = word.lower()
        if position > 0 and lowered in _TITLE_CASE_MINOR_WORDS:
            recased.append(lowered)
        else:
            recased.append(lowered[:1].upper() + lowered[1:])
    return ' '.join(recased)


def _adoptable_title(line: str) -> Optional[str]:
    """Return *line* as a heading title, or ``None`` when it is body text.

    A container heading written over two lines (``ARTICLE I`` / ``DEFINITIONS``)
    leaves the second line as the real title.  It qualifies when it is short
    (at most eight words) and does not end like a sentence.  An ALL-CAPS line
    is re-cased; anything else is kept verbatim, because mixed-case drafting
    (``Subject matter and scope``) is already how the drafter wrote it.

    Args:
        line: The candidate line, as found in the source text.

    Returns:
        The title to use, or ``None``.
    """
    candidate = line.strip()
    if not candidate:
        return None
    if candidate.endswith(_ADOPTED_TITLE_TERMINATORS):
        return None
    if len(candidate.split()) > _MAX_ADOPTED_TITLE_WORDS:
        return None
    if len(candidate) > MAX_TITLE_CHARS:
        return None
    if candidate.isupper():
        return _title_case(candidate)
    return candidate


def _line_offsets(text: str) -> list[int]:
    """Return the character offset at which each line of *text* starts.

    The offsets are derived from ``str.splitlines(keepends=True)`` — the exact
    same splitting rule :meth:`StructureParser.parse` uses to build its
    ``lines`` list — so ``len(_line_offsets(text)) == len(text.splitlines())``
    holds for *every* input, and ``offsets[i]`` always names the start of
    ``lines[i]``.

    A hand-rolled ``'\\n'``-only scan does **not** satisfy that: ``splitlines``
    also breaks on ``\\r``, ``\\v``, ``\\f``, ``\\x1c``–``\\x1e``, ``\\x85``
    (NEL), ``\\u2028`` (LINE SEPARATOR) and ``\\u2029`` (PARAGRAPH SEPARATOR),
    all of which occur in real PDF/RTF/legacy-encoding exports.  Such a scan
    produced fewer offsets than lines and ``parse()`` then indexed past the
    end of the list.

    Args:
        text: The full document string.

    Returns:
        List of integer character offsets, one per line, in document order.
    """
    offsets: list[int] = []
    position = 0
    for line in text.splitlines(keepends=True):
        offsets.append(position)
        position += len(line)
    return offsets


# ---------------------------------------------------------------------------
# Heading-plausibility constants
# ---------------------------------------------------------------------------

# A table-of-contents entry: leader dots (or a wide gutter) followed by a
# right-aligned page number.
_TOC_LEADER_RE = re.compile(r'(?:\.{4,}\s*|\s{3,})\d+$')

# Shape of a standalone ALL-CAPS line.  Matches the fallback branch that the
# US and EU ``detect_level`` functions use for un-numbered headings.
_ALLCAPS_RE = re.compile(r'[A-Z][A-Z \t]+')

# ALL-CAPS lines that are page furniture rather than headings.
_ALLCAPS_DENYLIST = frozenset({
    'CONFIDENTIAL',
    'CONFIDENTIAL AND PROPRIETARY',
    'DRAFT',
    'PRIVILEGED',
    'PRIVILEGED AND CONFIDENTIAL',
    'TABLE OF CONTENTS',
})

# Quote characters that mark a numbered line as a defined-term entry
# (``1. "Term" means ...``) rather than as prose.
_OPENING_QUOTES = '"\u201c\u2018\''

# ``PAGE 3``/``PAGE 3 OF 12`` footers.
_PAGE_RE = re.compile(r'PAGE\b')

# Maximum number of words an ALL-CAPS fallback heading may contain.
# Raised from 8 to 10 so genuine US-style headings such as
# "REPRESENTATIONS AND WARRANTIES OF THE SELLER AND THE COMPANY" (9 words)
# survive.  A rejected heading collapses a whole clause into its predecessor,
# which is a worse outcome than an occasional extra heading.
_MAX_ALLCAPS_WORDS = 10

# A numeric top-level heading whose remainder is longer than this *and* ends
# like a sentence is body text, not a heading.
_MAX_NUMERIC_HEADING_REMAINDER = 80

# First words that mark ``"3 Business Days after receipt..."`` /
# ``"1. January 2024 is the Effective Date"`` as body text rather than as a
# numbered clause heading.
# Deliberately excludes ordinals that double as heading words
# ("second", "per", "percent").
_UNIT_WORDS = frozenset({
    'business', 'calendar', 'working',
    'day', 'days', 'week', 'weeks', 'month', 'months', 'year', 'years',
    'hour', 'hours', 'minute', 'minutes',
    'january', 'february', 'march', 'april', 'may', 'june', 'july',
    'august', 'september', 'october', 'november', 'december',
})

# Maximum number of words in the title of a numbered heading for the
# "reads as a title, not prose" test below.
_MAX_HEADING_TITLE_WORDS = 8

# Lower-case words that appear inside perfectly ordinary title-case headings
# ("Days of Service", "Business Ethics and Anti-Bribery", "May Not Be
# Assigned").  Anything lower-case and *not* in this set marks the remainder
# as running prose rather than a title.
_TITLE_FUNCTION_WORDS = frozenset({
    'a', 'an', 'and', 'as', 'at', 'by', 'for', 'from', 'in', 'into', 'no',
    'not', 'of', 'on', 'or', 'per', 'the', 'to', 'under', 'upon', 'via',
    'with', 'without',
})

# A currency amount immediately after the clause number — "2. GBP 5,000 per
# month for hosting" — is a numbered list item inside a Fees clause, never a
# clause heading.
_MONEY_LEAD_RE = re.compile(
    r'^(?:[£$€¥]|GBP|USD|EUR|JPY)\s*[\d.,]', re.IGNORECASE
)

# A UK postcode anywhere on the line marks it as part of a postal address
# (the tail of a Notices clause), not as a heading.
_UK_POSTCODE_RE = re.compile(
    r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.IGNORECASE
)


def _is_title_shaped(remainder: str) -> bool:
    """Return ``True`` when *remainder* reads as a heading title, not prose.

    Used to decide whether the numbered-clause prose rules should fire.  A
    title is short, carries no terminal punctuation, contains no digits, and
    is written in title case — every word either capitalised or one of a
    small set of lower-case function words.

    ``"Business Continuity"``, ``"Days of Service"`` and ``"May Not Be
    Assigned"`` are title-shaped; ``"Business Days after receipt of an
    invoice."``, ``"January 2024 is the Effective Date"`` and ``"GBP 5,000
    per month for hosting services."`` are not.

    Args:
        remainder: The text following the clause identifier on a header line.

    Returns:
        ``True`` if the text reads as a title.
    """
    if not remainder or remainder.endswith(('.', ';', ':', ',')):
        return False
    words = remainder.split()
    if len(words) > _MAX_HEADING_TITLE_WORDS:
        return False
    for word in words:
        core = word.strip('.,;:()[]{}"\'‘’“”-–—')
        if not core:
            continue
        if any(character.isdigit() for character in core):
            return False
        if core[0].isupper():
            continue
        if core.lower() in _TITLE_FUNCTION_WORDS:
            continue
        return False
    return True

# Single-letter sub-clause labels that are both a valid alpha label and a
# valid Roman numeral, mapped to the alpha label that must immediately
# precede them for the alpha reading to win.
_ROMAN_AMBIGUOUS = {'i': 'h', 'v': 'u', 'x': 'w', 'l': 'k', 'c': 'b'}

_SINGLE_ALPHA_SUB_RE = re.compile(r'^\(([a-z])\)$')

# Level assigned to a sub-label resolved as a Roman numeral.  Shared by the
# UK, US and EU jurisdictions.
_ROMAN_SUB_LEVEL = 4
_ALPHA_SUB_LEVEL = 3

# Sections that a container passes down to everything nested inside it.  A
# paragraph inside "SCHEDULE 1" is part of the schedules, not of the operative
# clauses, however neutrally its own heading reads; the sub-clauses of
# "1. Definitions and interpretation" are part of the definitions; the same
# holds for the recitals.  Only a descendant that would otherwise be OPERATIVE
# inherits, so a descendant that classifies itself (a "Definitions" paragraph
# inside a Schedule) keeps its own, more specific section.
_INHERITED_SECTIONS: frozenset[DocumentSection] = frozenset({
    DocumentSection.SCHEDULES,
    DocumentSection.RECITALS,
    DocumentSection.DEFINITIONS,
})


# ---------------------------------------------------------------------------
# Document-section classification
# ---------------------------------------------------------------------------
#
# These rules deliberately do *not* search for a keyword anywhere in the
# heading.  A bare substring search labelled "Background Checks" (a vetting
# obligation) as RECITALS and "Execution of Services" (a performance clause)
# as SIGNATURES — with the wrong label baked into ``document_section``,
# ``clause_type`` and the ``context_header`` that is embedded and shown to a
# downstream LLM.  A keyword now has to be the heading's *head word* or its
# whole text.

# Words that may sit between real keywords in a heading without making it
# something else ("Definitions and Interpretation", "Background and Recitals").
_HEADING_CONNECTIVES = frozenset({'and', 'or', 'the', 'of', 'a', 'an', '&'})

# A heading is RECITALS only when it *is* one of these (modulo connectives) —
# never merely because it contains one.
_RECITAL_TITLE_WORDS = frozenset({
    'recital', 'recitals', 'background', 'whereas', 'preliminary',
})

# A heading is DEFINITIONS when its head word is one of these, or when the
# whole heading is built from them plus connectives.
_DEFINITION_HEAD_WORDS = frozenset({
    'definition', 'definitions', 'interpretation', 'interpretations',
    'defined',
})

# A heading is SIGNATURES only when it opens with an unambiguous execution
# formula (or with one of the jurisdiction's own ``signature_markers``).
# "Execution of the Works" and "Execution of Services" must not match.
_SIGNATURE_HEAD_RE = re.compile(
    r'^(?:'
    r'in\s+witness\s+whereof'
    r'|signed\s+(?:by|for\s+and\s+on\s+behalf)'
    r'|executed\s+as\s+a\s+deed'
    r'|signature(?:s)?(?:\s+page)?'
    r'|execution\s+(?:page|block|version)'
    r')\b'
)

_WORD_RE = re.compile(r"[a-z0-9&'-]+")


def _heading_words(heading: str) -> list[str]:
    """Return the lower-case word tokens of *heading*."""
    return _WORD_RE.findall(heading.lower())


def _is_keyword_heading(
    words: list[str],
    keywords: frozenset[str],
    *,
    head_word_only: bool,
) -> bool:
    """Return ``True`` when *words* is a heading *about* one of *keywords*.

    Args:
        words: Lower-case word tokens of the heading.
        keywords: The keyword set to test against.
        head_word_only: When ``True``, matching the first non-connective word
            is enough ("Definitions and Interpretation").  When ``False``,
            *every* non-connective word must be a keyword, so
            "Background Checks" does not match while "Background" and
            "Background and Recitals" do.

    Returns:
        ``True`` if the heading qualifies.
    """
    # Bare numbers are part of the label, not of the subject matter:
    # "Recital (1)" and "Recitals 1-5" are still recitals.
    significant = [
        word
        for word in words
        if word not in _HEADING_CONNECTIVES and not word.isdigit()
    ]
    if not significant:
        return False
    if head_word_only:
        return significant[0] in keywords
    return all(word in keywords for word in significant)


def _get_section_roles(
    detect_level_fn: Callable[[str], tuple[int, str] | None],
) -> dict[int, DocumentSection]:
    """Return the ``SECTION_ROLES`` mapping declared by a jurisdiction.

    The mapping is an *optional* module-level attribute of the module that
    defines the jurisdiction's ``detect_level`` function.  It assigns a
    :class:`~lexichunk.models.DocumentSection` to a hierarchy level so that,
    for example, UK/US level ``-1`` (Schedule) is ``SCHEDULES`` while EU
    level ``-1`` (Chapter) is ``OPERATIVE``.

    Args:
        detect_level_fn: The jurisdiction's ``detect_level`` callable.

    Returns:
        A ``{level: DocumentSection}`` dict — empty when the jurisdiction
        declares no mapping (in which case every level defaults to
        ``OPERATIVE``).
    """
    module_name = getattr(detect_level_fn, '__module__', None)
    module = sys.modules.get(module_name) if module_name else None
    roles = getattr(module, 'SECTION_ROLES', None)
    if not isinstance(roles, dict):
        return {}
    return {
        level: role
        for level, role in roles.items()
        if isinstance(level, int) and isinstance(role, DocumentSection)
    }


def _compile_signature_markers(
    jurisdiction: Jurisdiction | str,
) -> Optional[re.Pattern[str]]:
    """Compile a jurisdiction's ``signature_markers`` into one pattern.

    Args:
        jurisdiction: The jurisdiction whose pattern object should be read.

    Returns:
        A compiled whole-word alternation, or ``None`` when the
        jurisdiction declares no usable markers.
    """
    markers = getattr(get_patterns(jurisdiction), 'signature_markers', ())
    cleaned = [
        marker.strip().lower()
        for marker in markers
        if isinstance(marker, str) and marker.strip()
    ]
    if not cleaned:
        return None
    alternation = '|'.join(re.escape(marker) for marker in cleaned)
    return re.compile(rf'\b(?:{alternation})\b')


def _is_allcaps_fallback(stripped: str, level: int, identifier: str) -> bool:
    """Return ``True`` when a match came from an ALL-CAPS level-0 fallback.

    The US and EU ``detect_level`` functions end with a branch that accepts
    any standalone ALL-CAPS line as a level-0 heading, returning the line
    itself as the identifier.  That signature — level 0, identifier equal to
    the stripped line, and the line being ALL-CAPS — is what this detects,
    without the parser needing to know which jurisdiction it is using.
    """
    return (
        level == 0
        and identifier == stripped
        and _ALLCAPS_RE.fullmatch(stripped) is not None
    )


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


class StructureParser:
    """Parse legal documents into a structured clause hierarchy.

    The parser splits the input text into lines and applies the
    jurisdiction-specific ``detect_level`` function to each line to locate
    clause headers.  It maintains a stack of open clauses to track the current
    parent at each level, then emits a **flat** list of :class:`ParsedClause`
    objects ordered by ``char_start``.

    Args:
        jurisdiction: The :class:`~lexichunk.models.Jurisdiction` whose
            detection rules should be used.

    Example::

        parser = StructureParser(Jurisdiction.UK)
        clauses = parser.parse(contract_text)
        for clause in clauses:
            print(clause.identifier, clause.document_section)
    """

    def __init__(
        self, jurisdiction: Jurisdiction | str, doc_type: str = "contract"
    ) -> None:
        self._jurisdiction = jurisdiction
        self._doc_type = doc_type
        self._detect_level: Callable[[str], tuple[int, str] | None] = (
            get_detect_level(jurisdiction)
        )
        self._section_roles = _get_section_roles(self._detect_level)
        self._signature_markers = _compile_signature_markers(jurisdiction)
        #: Number of ``detect_level`` matches rejected by
        #: :meth:`_is_plausible_heading` during the most recent
        #: :meth:`parse` call.  Reset at the start of every parse so a
        #: reused parser instance always reports the current document.
        self.last_rejected_headings: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, text: str) -> list[ParsedClause]:
        """Parse *text* into a flat list of :class:`ParsedClause` objects.

        Each clause's ``content`` contains only the text lines that belong
        directly to that clause (i.e. lines before the next same-or-lower-level
        header at the same depth).  Child clause text is **not** included in
        the parent's ``content``.  The full hierarchy is encoded via
        ``parent_identifier`` and ``level``.

        A synthetic *preamble* clause at ``level=-99`` is emitted for any text
        that appears before the first detected clause header.

        ``document_section`` is classified per clause and then inherited: a
        clause that would otherwise be ``OPERATIVE`` takes the section of its
        nearest enclosing ``SCHEDULES``, ``RECITALS`` or ``DEFINITIONS``
        ancestor, so ``SCHEDULE 1 > 1 — Overview`` is ``SCHEDULES`` rather than
        ``OPERATIVE``.  A descendant with a section of its own (a
        ``Definitions`` paragraph inside a Schedule) keeps it.

        A container heading with no title of its own (``ARTICLE I`` followed by
        ``DEFINITIONS`` on the next line) adopts that next line as its
        ``title``; the line remains part of the body text, so offsets are
        unaffected.

        Args:
            text: The full legal document as a plain-text string.

        Returns:
            Flat list of :class:`ParsedClause` objects in document order
            (ascending ``char_start``).
        """
        lines = text.splitlines(keepends=True)
        offsets = _line_offsets(text)

        # ------------------------------------------------------------------
        # First pass: collect (line_index, level, identifier) for all headers
        # and build a mapping from line_index -> (level, identifier).
        # ------------------------------------------------------------------
        header_map = self._collect_headers(lines)

        # ------------------------------------------------------------------
        # Second pass: build clauses.
        #
        # We iterate lines.  When we hit a header we:
        #   1. Flush accumulated content lines to the *current* clause.
        #   2. Pop the stack to find the parent.
        #   3. Open a new clause on the stack.
        #
        # Stack entries: list of ParsedClause (still "open", i.e. not yet
        # finalised — their char_end and content will be set when they close).
        # ------------------------------------------------------------------

        result_clauses: list[ParsedClause] = []

        # Stack holds open ParsedClause objects + accumulated content lines
        # for each.  We store (clause, content_lines_for_this_clause).
        stack: list[tuple[ParsedClause, list[str]]] = []

        # Buffer for text before the first clause header (preamble text).
        preamble_lines: list[str] = []

        # Monotonic counter assigning a stable `uid` to every ParsedClause in
        # the order it is *opened* (created), not the order it closes or its
        # final char_start-sorted position.  Because a clause's parent is
        # always already open (and thus already assigned a uid) when the
        # child is created, parent_uid always names a strictly smaller uid.
        uid_counter = 0

        def _close_clause(clause: ParsedClause, content_lines: list[str], end_char: int) -> None:
            """Finalise a clause: set content and char_end, append to results."""
            clause.content = ''.join(content_lines)
            clause.char_end = end_char
            result_clauses.append(clause)

        for line_idx, line in enumerate(lines):
            char_pos = offsets[line_idx]

            if line_idx not in header_map:
                # Continuation / body line.
                if stack:
                    stack[-1][1].append(line)
                else:
                    preamble_lines.append(line)
                continue

            # --- This line is a header ---
            level, identifier = header_map[line_idx]

            # Close any open clauses whose level >= current level (they are
            # "siblings" or "children" that are now complete).
            while stack and stack[-1][0].level >= level:
                closing_clause, closing_lines = stack.pop()
                _close_clause(closing_clause, closing_lines, char_pos)

            # Determine parent identifier.
            parent_id: Optional[str] = stack[-1][0].identifier if stack else None

            # Extract title from header line, falling back to the next line
            # for a container heading written over two lines.
            title = _extract_title(line, identifier)
            if title is None and level <= 0:
                title = self._title_from_next_line(lines, line_idx, header_map)

            # Classify document section, then let an enclosing Schedule /
            # Exhibit / Annex (or Recitals block) pass its section down.
            doc_section = self._detect_document_section(identifier, title or '', level)
            if doc_section is DocumentSection.OPERATIVE:
                for open_clause, _lines in reversed(stack):
                    if open_clause.document_section in _INHERITED_SECTIONS:
                        doc_section = open_clause.document_section
                        break

            # Flush preamble if this is the very first header encountered.
            if preamble_lines and not result_clauses:
                preamble_text = ''.join(preamble_lines)
                preamble_section = self._detect_document_section(
                    'preamble', preamble_text[:80], -99
                )
                preamble_clause = ParsedClause(
                    identifier='preamble',
                    title=None,
                    content=preamble_text,
                    level=-99,
                    parent_identifier=None,
                    document_section=preamble_section,
                    char_start=0,
                    char_end=char_pos,
                    children=[],
                    uid=str(uid_counter),
                    parent_uid=None,
                )
                uid_counter += 1
                result_clauses.append(preamble_clause)
                preamble_lines = []

            # Create the new clause (content and char_end filled in later).
            new_clause = ParsedClause(
                identifier=identifier,
                title=title,
                content='',
                level=level,
                parent_identifier=parent_id,
                document_section=doc_section,
                char_start=char_pos,
                char_end=char_pos,  # temporary; overwritten on close
                children=[],
                uid=str(uid_counter),
                parent_uid=stack[-1][0].uid if stack else None,
            )
            uid_counter += 1

            # Register as a child of the current top-of-stack (if any).
            if stack:
                stack[-1][0].children.append(new_clause)

            # The header line itself belongs to this clause's content.
            stack.append((new_clause, [line]))

        # ------------------------------------------------------------------
        # End of file: close all remaining open clauses.
        # ------------------------------------------------------------------
        end_of_text = len(text)

        # Handle case where the entire document had no headers.
        if not stack and preamble_lines:
            preamble_text = ''.join(preamble_lines)
            preamble_clause = ParsedClause(
                identifier='preamble',
                title=None,
                content=preamble_text,
                level=-99,
                parent_identifier=None,
                document_section=DocumentSection.PREAMBLE,
                char_start=0,
                char_end=end_of_text,
                children=[],
                uid=str(uid_counter),
                parent_uid=None,
            )
            uid_counter += 1
            result_clauses.append(preamble_clause)
        else:
            # Flush any preamble that was never flushed (shouldn't happen if
            # there is at least one header, but guard for safety).
            if preamble_lines and not any(c.identifier == 'preamble' for c in result_clauses):
                preamble_text = ''.join(preamble_lines)
                preamble_section = self._detect_document_section('preamble', '', -99)
                preamble_clause = ParsedClause(
                    identifier='preamble',
                    title=None,
                    content=preamble_text,
                    level=-99,
                    parent_identifier=None,
                    document_section=preamble_section,
                    char_start=0,
                    char_end=offsets[
                        next(
                            idx for idx in range(len(lines)) if idx in header_map
                        )
                    ],
                    children=[],
                    uid=str(uid_counter),
                    parent_uid=None,
                )
                uid_counter += 1
                result_clauses.append(preamble_clause)

            while stack:
                closing_clause, closing_lines = stack.pop()
                _close_clause(closing_clause, closing_lines, end_of_text)

        # Sort by char_start to guarantee document order in the flat list.
        result_clauses.sort(key=lambda c: c.char_start)
        return result_clauses

    def parse_structure(self, text: str) -> list[HierarchyNode]:
        """Return a list of :class:`~lexichunk.models.HierarchyNode` objects.

        This is the method consumed by the public ``chunker.parse_structure()``
        API.  It delegates to :meth:`parse` and projects each
        :class:`ParsedClause` onto a lightweight :class:`HierarchyNode`.

        Args:
            text: The full legal document as a plain-text string.

        Returns:
            List of :class:`~lexichunk.models.HierarchyNode` objects in
            document order (ascending ``char_start``).
        """
        clauses = self.parse(text)
        return [
            HierarchyNode(
                level=c.level,
                identifier=c.identifier,
                title=c.title,
                parent=c.parent_identifier,
            )
            for c in clauses
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _title_from_next_line(
        lines: list[str],
        idx: int,
        header_map: dict[int, tuple[int, str]],
    ) -> Optional[str]:
        """Return the title an untitled container heading adopts, or ``None``.

        US and EU house style splits a container heading over two lines::

            ARTICLE I
            DEFINITIONS

        The second line is not itself a heading (the ALL-CAPS gate rejects it
        for lack of a preceding blank line), so without this it would be lost
        as body text and ``hierarchy_path`` would read a bare ``Article I``.
        The line is only *read*, never consumed: it stays in the clause's
        content and every character offset is unchanged.

        Args:
            lines: The document's lines.
            idx: Index of the heading line.
            header_map: The accepted headings, used to refuse a line that is a
                heading in its own right.

        Returns:
            The adopted title, or ``None``.
        """
        for next_idx in range(idx + 1, len(lines)):
            if not lines[next_idx].strip():
                continue
            if next_idx in header_map:
                return None
            return _adoptable_title(lines[next_idx])
        return None

    def _collect_headers(self, lines: list[str]) -> dict[int, tuple[int, str]]:
        """Run ``detect_level`` over *lines* and keep the plausible matches.

        Three things happen here, in order, for every line:

        1. the jurisdiction's ``detect_level`` proposes ``(level,
           identifier)``;
        2. :meth:`_is_plausible_heading` may veto the proposal (rejections
           are counted in :attr:`last_rejected_headings`);
        3. an accepted single-letter sub-label that is ambiguous between an
           alpha and a Roman reading (``(i)``, ``(v)``, ``(x)``, ``(l)``,
           ``(c)``) is resolved using the previous alpha label seen at the
           same indent — ``(i)`` right after ``(h)`` is alpha, anything else
           is Roman.

        Args:
            lines: The document's lines, as produced by ``splitlines``.

        Returns:
            Mapping from line index to the accepted ``(level, identifier)``.
        """
        header_map: dict[int, tuple[int, str]] = {}
        rejected = 0

        # Last *alpha* sub-label accepted at a given indent (and overall),
        # used to disambiguate (i)/(v)/(x)/(l)/(c).  Cleared whenever a
        # more senior header opens a new sub-label namespace.
        prev_alpha_by_indent: dict[int, str] = {}
        prev_alpha: Optional[str] = None

        for idx, line in enumerate(lines):
            result = self._detect_level(line)
            if result is None:
                continue
            if not self._is_plausible_heading(lines, idx, result):
                rejected += 1
                continue

            level, identifier = result
            indent = len(line) - len(line.lstrip())

            single_alpha = _SINGLE_ALPHA_SUB_RE.match(identifier)
            if level == _ALPHA_SUB_LEVEL and single_alpha is not None:
                predecessor = _ROMAN_AMBIGUOUS.get(single_alpha.group(1))
                if predecessor is not None:
                    previous = prev_alpha_by_indent.get(indent, prev_alpha)
                    if previous != f'({predecessor})':
                        level = _ROMAN_SUB_LEVEL

            if level < _ALPHA_SUB_LEVEL:
                prev_alpha_by_indent.clear()
                prev_alpha = None
            elif level == _ALPHA_SUB_LEVEL and single_alpha is not None:
                prev_alpha_by_indent[indent] = identifier
                prev_alpha = identifier

            header_map[idx] = (level, identifier)

        self.last_rejected_headings = rejected
        return header_map

    def _is_plausible_heading(
        self,
        lines: list[str],
        idx: int,
        result: tuple[int, str],
    ) -> bool:
        """Return ``True`` when ``lines[idx]`` really looks like a heading.

        ``detect_level`` is a stateless, per-line regex match: anything
        *shaped* like a header is one.  This gate adds the surrounding-line
        context that a single ``re.match`` cannot see.  It is **reject-only**
        — it never promotes a line to a heading, so a false negative simply
        leaves the line as body text (the same outcome as no match at all).

        Rules:

        * **Table of contents** — leader dots or a wide gutter followed by a
          right-aligned page number.
        * **Wrapped sentences** — a remainder that opens with a comma is the
          middle of a sentence (``"Article I, Section 3.01 through 3.04,
          Article IV, ..."`` in a survival clause), not a heading.
        * **Containers** (levels ``-1``/``-2``: Schedule, Exhibit, Annex,
          Chapter) must start at column 0, follow a blank line, or follow a
          line that ended a sentence; this rejects a word-wrapped
          ``"     Schedule 2."`` mid-sentence inside a clause, which would
          otherwise re-parent the rest of the document.
        * **ALL-CAPS fallback headings** must follow a blank line, contain
          at most ten words, not be page furniture (``CONFIDENTIAL``,
          ``TABLE OF CONTENTS``, ``PAGE 3 OF 12`` …), and not continue an
          ALL-CAPS paragraph that was left unterminated on the previous
          non-blank line.
        * **Numeric top-level clauses** are rejected when the text after the
          number is a currency amount (``2. GBP 5,000 per month …`` — a Fees
          list item) or the line carries a postcode (the tail of a Notices
          clause's postal address).  They are also rejected when they read as
          prose *and* are not title-shaped: a long remainder ending in
          ``.``/``;``, or one starting with a unit or month word
          (``3 Business Days …``).  ``_is_title_shaped`` is what keeps
          ``"2. Business Continuity"`` and ``"4. Days of Service"`` — short,
          title-cased, unpunctuated — out of those two rules.  A remainder
          opening with a quote is exempt from the length test: that is the
          numbered-definition layout ``1. "Term" means …``.

        Args:
            lines: The document's lines.
            idx: Index of the candidate line.
            result: The ``(level, identifier)`` proposed by ``detect_level``.

        Returns:
            ``True`` to accept the heading, ``False`` to reject it.
        """
        level, identifier = result
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            return False

        # (a) Table-of-contents entry.
        if _TOC_LEADER_RE.search(line.rstrip()):
            return False

        # Text after the identifier; used by rules (d) and (e) below.
        remainder = _remainder_after_identifier(line, identifier)

        # (b) Container levels must start at column 0, follow a blank line, or
        #     follow a line that ended a sentence.  The third alternative was
        #     added because a real "Schedule 2" heading is routinely typed
        #     directly under the last line of the preceding clause with no
        #     blank line between them; rejecting it collapses the entire
        #     schedule into the clause above.
        if level in (-1, -2):
            starts_at_column_0 = not line[:1].isspace()
            previous = lines[idx - 1].rstrip() if idx > 0 else ''
            blank_before = idx > 0 and not previous.strip()
            terminated_before = previous.endswith(('.', '!', '?', ':', ';'))
            if not (starts_at_column_0 or blank_before or terminated_before):
                return False

        # (c) ALL-CAPS level-0 fallback.
        if _is_allcaps_fallback(stripped, level, identifier):
            if idx == 0 or lines[idx - 1].strip():
                return False
            if len(stripped.split()) > _MAX_ALLCAPS_WORDS:
                return False
            if stripped in _ALLCAPS_DENYLIST or _PAGE_RE.match(stripped):
                return False
            if self._continues_allcaps_paragraph(lines, idx):
                return False

        # (d) Numeric top-level clause.
        if level == 0 and identifier.isdigit():
            if remainder:
                upper = remainder.upper()
                if upper in _ALLCAPS_DENYLIST or _PAGE_RE.match(upper):
                    return False
                # A currency amount straight after the number is a numbered
                # list item inside a Fees clause ("2. GBP 5,000 per month"),
                # not clause 2 of the agreement.
                if _MONEY_LEAD_RE.match(remainder):
                    return False
                # A postcode on the line makes it part of a postal address —
                # the tail of a Notices clause, not a new clause.
                if _UK_POSTCODE_RE.search(stripped):
                    return False
                # The two prose rules below only fire when the remainder does
                # *not* read as a heading title.  Both used to fire on shape
                # alone and swallowed real headings: "2. Business Continuity"
                # was rejected because "business" is a unit word, and any
                # legitimate heading longer than 80 characters ending in a
                # full stop was rejected as a sentence.  A rejected heading
                # is not merely mis-levelled — its whole clause body is
                # absorbed into the previous clause, with no chunk, no
                # hierarchy_path and no way to retrieve it by its own title.
                if not _is_title_shaped(remainder):
                    first_word = remainder.split()[0].strip('.,;:()').lower()
                    if first_word in _UNIT_WORDS:
                        return False
                    # A numbered definition entry (`1. "Term" means ...`) is
                    # long and semicolon-terminated but *is* a heading, so
                    # the prose test does not apply to it.
                    if (
                        remainder[0] not in _OPENING_QUOTES
                        and len(remainder) > _MAX_NUMERIC_HEADING_REMAINDER
                        and remainder.endswith(('.', ';'))
                    ):
                        return False

        # (e) A heading's text never *continues* the previous line: a
        #     remainder that opens with a comma is a wrapped sentence
        #     (`"Article I, Section 3.01 through 3.04, ..."`).
        if remainder.startswith(','):
            return False

        return True

    def _continues_allcaps_paragraph(self, lines: list[str], idx: int) -> bool:
        """Return ``True`` when ``lines[idx]`` continues an ALL-CAPS block.

        A wrapped ALL-CAPS disclaimer looks exactly like a run of ALL-CAPS
        "headings".  If the previous non-blank line is itself ALL-CAPS, does
        not end with sentence punctuation, and is not a *structural* header
        (``ARTICLE I``, ``CHAPTER II`` …), then this line is the rest of
        that paragraph rather than a new heading.
        """
        j = idx - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j < 0:
            return False

        previous = lines[j].strip()
        if _ALLCAPS_RE.fullmatch(previous) is None:
            return False
        if previous.endswith(('.', '!', '?', ':', ';')):
            return False

        previous_result = self._detect_level(lines[j])
        if previous_result is not None and not _is_allcaps_fallback(
            previous, previous_result[0], previous_result[1]
        ):
            return False
        return True

    def _detect_document_section(
        self,
        identifier: str,
        title: str,
        level: int,
    ) -> DocumentSection:
        """Classify a clause into a :class:`~lexichunk.models.DocumentSection`.

        The classification is based on the lowercased ``title`` and
        ``identifier`` strings and, for boundary cases, on ``level`` and the
        number of characters preceding the clause in the original document.

        Rules (evaluated in order — first match wins):

        * **Container role**: the jurisdiction's ``SECTION_ROLES`` mapping
          assigns a role to ``level`` (typically ``SCHEDULES`` for
          Schedule/Exhibit/Annex levels).  A mapping to ``OPERATIVE`` — or
          no mapping at all — falls through to the keyword rules.
        * **SIGNATURES**: the heading *opens with* an execution formula
          (``"IN WITNESS WHEREOF"``, ``"SIGNED by"``, ``"SIGNED for and on
          behalf"``, ``"EXECUTED as a deed"``, ``"Signature page"``,
          ``"Execution page"``) or with one of the jurisdiction's
          ``signature_markers``.  A performance clause such as ``"Execution
          of Services"`` deliberately does **not** match.
        * **RECITALS**: the *whole* heading is built from ``"recital(s)"``,
          ``"background"``, ``"whereas"`` or ``"preliminary"`` plus
          connectives.  ``"Background Checks"`` — a vetting obligation —
          deliberately does **not** match.
        * **DEFINITIONS**: the heading's *head word* is ``"definition(s)"``,
          ``"interpretation(s)"`` or ``"defined"`` (so both ``"Definitions"``
          and ``"Definitions and Interpretation"`` match).

        These three rules match on the heading text — ``title`` when there is
        one, otherwise ``identifier`` (an ALL-CAPS fallback heading carries
        its text there).  They are deliberately anchored rather than
        substring searches: an unanchored search labelled ``"2. Background
        Checks"`` as ``RECITALS`` with classification confidence 1.00 and
        ``"2. Execution of Services"`` as ``SIGNATURES``, and that label is
        baked into ``clause_type`` and into the ``context_header`` that gets
        embedded and shown to a downstream LLM.
        * **PREAMBLE**: identifier is literally ``"preamble"`` or
          ``"whereas"``.
        * **OPERATIVE**: everything else.

        Args:
            identifier: The clause identifier (e.g. ``"1"`` or ``"Article I"``).
            title: The heading text on the same line (may be empty string).
            level: The numeric hierarchy level.

        Returns:
            A :class:`~lexichunk.models.DocumentSection` member.
        """
        is_tc = self._doc_type == "terms_conditions"

        # Container roles (Schedule / Exhibit / Annex / Chapter) come from
        # the jurisdiction's SECTION_ROLES map; OPERATIVE means "no special
        # role", so fall through to the keyword rules below.
        role = self._section_roles.get(level)
        if role is not None and role is not DocumentSection.OPERATIVE:
            return role

        # The heading text these rules classify.  An ALL-CAPS fallback heading
        # carries its text in ``identifier`` with an empty ``title``, so fall
        # back to the identifier when there is no title.
        heading = title.strip() or identifier.strip()
        words = _heading_words(heading)

        # Signature blocks — skip for T&C documents (false positives).
        # The heading must *open with* an execution formula, so a performance
        # clause titled "Execution of Services" stays OPERATIVE.
        if not is_tc and (
            _SIGNATURE_HEAD_RE.match(heading.lower()) is not None
            or (
                self._signature_markers is not None
                and self._signature_markers.match(heading.lower()) is not None
            )
        ):
            return DocumentSection.SIGNATURES

        # Recitals / background — skip for T&C documents (false positives).
        # Whole-heading match only: "Background Checks" is a vetting
        # obligation, not the recitals.
        if not is_tc and _is_keyword_heading(
            words, _RECITAL_TITLE_WORDS, head_word_only=False
        ):
            return DocumentSection.RECITALS

        # Definitions sections — head word is enough, so both "Definitions"
        # and "Definitions and Interpretation" match.
        if _is_keyword_heading(
            words, _DEFINITION_HEAD_WORDS, head_word_only=True
        ) or (
            len(words) >= 2
            and words[0] == 'defined'
            and words[1].startswith('term')
        ):
            return DocumentSection.DEFINITIONS

        # Synthetic preamble node (level == -99) or identifier keyword.
        if identifier.lower() in ('preamble', 'whereas') or level == -99:
            return DocumentSection.PREAMBLE

        return DocumentSection.OPERATIVE


# ---------------------------------------------------------------------------
# Module-level convenience wrapper
# ---------------------------------------------------------------------------


def parse_structure(
    text: str,
    jurisdiction: Jurisdiction,
    doc_type: str = "contract",
) -> list[ParsedClause]:
    """Parse a legal document into a flat list of :class:`ParsedClause` objects.

    This is a thin convenience wrapper around
    :class:`StructureParser` ``.parse()``.

    Args:
        text: The full legal document as a plain-text string.
        jurisdiction: The :class:`~lexichunk.models.Jurisdiction` to use for
            clause-header detection.
        doc_type: Document type hint — ``"contract"`` or
            ``"terms_conditions"``.

    Returns:
        Flat list of :class:`ParsedClause` objects in document order
        (ascending ``char_start``).

    Example::

        from lexichunk.models import Jurisdiction
        from lexichunk.parsers.structure import parse_structure

        clauses = parse_structure(contract_text, Jurisdiction.UK)
    """
    return StructureParser(jurisdiction, doc_type=doc_type).parse(text)


__all__ = [
    "ParsedClause",
    "StructureParser",
    "parse_structure",
]
