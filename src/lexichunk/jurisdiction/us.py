"""US legal document patterns and conventions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .._patterns import NOT_AFTER_WORD, TERM_UPPER
from ..exceptions import ParsingError
from ..models import DocumentSection

_ROMAN = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}


def roman_to_int(s: str) -> int:
    """Convert a Roman numeral string to an integer.

    Args:
        s: A string containing only valid Roman numeral characters
            (I, V, X, L, C, D, M — case-insensitive).

    Returns:
        The integer value of the Roman numeral.

    Raises:
        ValueError: If *s* is empty or contains non-Roman characters.
    """
    if not s:
        raise ParsingError("Empty string is not a valid Roman numeral")
    s = s.upper()
    for ch in s:
        if ch not in _ROMAN:
            raise ParsingError(
                f"Invalid Roman numeral character: {ch!r} in {s!r}"
            )
    result, prev = 0, 0
    for ch in reversed(s):
        val = _ROMAN[ch]
        if val < prev:
            result -= val
        else:
            result += val
        prev = val
    return result


@dataclass
class USPatterns:
    """Compiled regex patterns for US legal document structure.

    US contracts use multi-tier structure:
      ARTICLE I / Article I  — top-level (Roman numerals)
      Section 1.01           — section
      1. / 1.1 / 1.1.1       — bare-decimal top-level, section, sub-section
      (a)                    — alpha sub-clause
      (i)                    — roman sub-clause
      Exhibit A / Schedule 1 — attachments

    The bare-decimal tier matters more than the ``ARTICLE``/``Section``
    tier in practice.  A CUAD evaluation over 150 real SEC exhibit filings
    found ``jurisdiction="us"`` recovering five or more top-level clauses
    in only 14% of contracts, against 31% for ``jurisdiction="uk"`` on the
    *same* US filings, because the ``us`` profile required a literal
    ``Section``/``ARTICLE`` marker and the ``uk`` profile did not.  Bare
    ``1. Definitions.`` is the dominant US commercial drafting style.
    """

    article: re.Pattern = field(default_factory=lambda: re.compile(
        r'^(?:ARTICLE|Article)\s+([IVXLC]+)(?:\s*[-\u2013\u2014]\s*([A-Z][^\n]{0,80}))?',
        re.MULTILINE
    ))
    section: re.Pattern = field(default_factory=lambda: re.compile(
        r'^(?:SECTION|Section)\s+(\d+\.\d+(?:\([a-z]\))?)',
        re.MULTILINE
    ))
    # Bare-decimal numbering, identical in shape to the UK profile's.
    subsection_3: re.Pattern = field(default_factory=lambda: re.compile(
        r'^(\d+\.\d+\.\d+)\.?\s+', re.MULTILINE
    ))
    subsection_2: re.Pattern = field(default_factory=lambda: re.compile(
        r'^(\d+\.\d+)\.?\s+', re.MULTILINE
    ))
    top_level: re.Pattern = field(default_factory=lambda: re.compile(
        r'^(\d+)\.?\s+([A-Z][A-Za-z\s]{2,60})(?:\n|$)', re.MULTILINE
    ))
    alpha_sub: re.Pattern = field(default_factory=lambda: re.compile(
        r'^\(([a-z])\)\s+', re.MULTILINE
    ))
    roman_sub: re.Pattern = field(default_factory=lambda: re.compile(
        r'^\(([ivxlc]+)\)\s+', re.MULTILINE
    ))
    exhibit: re.Pattern = field(default_factory=lambda: re.compile(
        r'^(Exhibit\s+[A-Z][\w\-]*(?:\s*[-\u2013]\s*[A-Za-z\s]+)?)',
        re.MULTILINE
    ))
    schedule: re.Pattern = field(default_factory=lambda: re.compile(
        r'^((?:Schedule\s+\d+(?:\.\d+)*|Appendix\s+[\dA-Z][\w-]*)(?:\s*[-\u2013]\s*[A-Za-z\s]+)?)',
        re.MULTILINE | re.IGNORECASE
    ))

    # The trailing ``(?-i:[A-Z])(?![A-Za-z])`` alternative is what makes
    # "Exhibit A" a reference. US agreements name their attachments by
    # letter -- "attached hereto as Exhibit A", "the form set out in
    # Exhibit B" -- and ``detect_level`` already recognises ``EXHIBIT A``
    # as a container heading, so without this a document contained an
    # Exhibit A chunk that no reference could ever resolve to. Worse, it
    # was inconsistent: ``Exhibit C`` happened to resolve, because C is a
    # Roman numeral, while A, B and D did not.
    #
    # The scoped ``(?-i:...)`` turns IGNORECASE off for that one
    # alternative so it matches a genuinely capitalised letter, and the
    # lookahead requires the letter to stand alone -- "Schedule Terms" is
    # not a reference to a schedule named "T".
    cross_ref: re.Pattern = field(default_factory=lambda: re.compile(
        r'\b(?:Sections?|Articles?|Exhibits?|Schedules?|Clauses?)\s+'
        r'(\d+(?:\.\d+)*(?:\([a-z]+\))*(?:\([ivxlc]+\))*|[IVXLC]+'
        r'|(?-i:[A-Z])(?![A-Za-z]))',
        re.IGNORECASE
    ))

    definition: re.Pattern = field(default_factory=lambda: re.compile(
        NOT_AFTER_WORD + rf'"({TERM_UPPER})"\s+'
        r'(?:means|shall mean|has the meaning|is defined as|refers to)',
        re.MULTILINE
    ))
    definition_curly: re.Pattern = field(default_factory=lambda: re.compile(
        NOT_AFTER_WORD + rf'\u201c({TERM_UPPER})\u201d\s+'
        r'(?:means|shall mean|has the meaning)',
        re.MULTILINE
    ))

    definitions_headers: tuple = field(default_factory=lambda: (
        'definitions', 'defined terms', 'interpretation',
        'article i', 'article 1',
    ))
    boilerplate_headers: tuple = field(default_factory=lambda: (
        'miscellaneous', 'general', 'general provisions',
    ))
    signature_markers: tuple = field(default_factory=lambda: (
        'in witness whereof', 'executed as of', 'signed by',
        'authorized signatory', 'duly authorized',
    ))


US_PATTERNS = USPatterns()


#: Optional per-jurisdiction mapping from hierarchy level to
#: :class:`~lexichunk.models.DocumentSection`.  Read by
#: :class:`~lexichunk.parsers.structure.StructureParser`; any level absent
#: from this mapping defaults to ``OPERATIVE``.
SECTION_ROLES: dict[int, DocumentSection] = {
    -1: DocumentSection.SCHEDULES,  # Schedule / Appendix
    -2: DocumentSection.SCHEDULES,  # Exhibit
}


def detect_level(line: str) -> tuple[int, str] | None:
    """Detect the hierarchy level and identifier of a line for US documents.

    Returns:
        (level, identifier) where level is:
          -2 = Exhibit
          -1 = Schedule / Appendix
           0 = Article, a bare "Section N" heading, or a bare-decimal
               top-level clause ("1." / "1) Definitions")
           1 = Section (dotted, e.g. "Section 1.01" or bare "1.1")
           2 = bare sub-subsection ("1.1.1")
           3 = alpha sub-clause "(a)"
           4 = roman sub-clause "(i)"
        Returns None if not a clause header.

    Note:
        Detection is deliberately permissive: ``StructureParser`` applies
        a heading-plausibility gate to every match, so page furniture and
        wrapped ALL-CAPS disclaimers are filtered out there rather than
        here.
    """
    s = line.lstrip()

    m = re.match(r'^(Exhibit\s+[A-Z][\w\-]*)', s, re.IGNORECASE)
    if m:
        return (-2, m.group(1))

    m = re.match(
        r'^(Schedule\s+\d+(?:\.\d+)*|Appendix\s+[\dA-Z][\w-]*)',
        s,
        re.IGNORECASE,
    )
    if m:
        return (-1, m.group(1))

    m = re.match(r'^(?:ARTICLE|Article)\s+([IVXLC]+)', s)
    if m:
        return (0, f'Article {m.group(1)}')

    m = re.match(r'^(?:SECTION|Section)\s+(\d+\.\d+(?:\([a-z]\))?)', s)
    if m:
        return (1, f'Section {m.group(1)}')

    # Bare "Section 1." / "SECTION 1" headings (no dotted sub-number) are
    # the top-level unit in documents that do not use ARTICLE headings.
    m = re.match(r'^(?:SECTION|Section)\s+(\d+)\.?(?:\s|$)', s)
    if m:
        return (0, f'Section {m.group(1)}')

    # Bare-decimal numbering — "1.1.1", "1.1", "1. Definitions".  These are
    # the same three patterns the UK profile uses, and they are what the
    # dominant US commercial drafting style actually looks like; requiring
    # a literal "Section"/"ARTICLE" marker is what made ``us`` the worse
    # profile for US filings.  Most-specific first, so "1.1.1" is not read
    # as "1.1" followed by junk.
    #
    # The trailing ``\S`` on the dotted forms is load-bearing: it demands
    # whitespace *and* then a non-space character after the number, so the
    # wrapped sentence fragment "4.5; (c) all outstanding fees ..." (where
    # ";" immediately follows the number) is not read as clause 4.5.  The
    # remaining wrapped-continuation cases (a line ending in the word
    # "Section", with "7.2. Continued use ..." wrapped onto the line
    # below it) are rejected by the
    # heading-plausibility gate in ``parsers.structure``, which can see the
    # preceding line and this function cannot.
    m = re.match(r'^(\d+\.\d+\.\d+)\.?\s+\S', s)
    if m:
        return (2, m.group(1))

    m = re.match(r'^(\d+\.\d+)\.?\s+\S', s)
    if m:
        return (1, m.group(1))

    # Top-level: "1.  Definitions", '1. "Term" means ...' (straight or
    # curly quote), "1) Definitions" or "1. 2024 Fee Schedule".
    m = re.match(r'^(\d+)[.)]?\s+(?:[A-Z]\S|["“‘]|\d)', s)
    if m:
        return (0, m.group(1))

    m = re.match(r'^\(([a-z])\)\s+\S', s)
    if m:
        return (3, f'({m.group(1)})')

    m = re.match(r'^\(([ivxlc]+)\)\s+\S', s)
    if m:
        return (4, f'({m.group(1)})')

    # Standalone ALL-CAPS header (e.g. "REPRESENTATIONS AND WARRANTIES").
    # Must be at least 2 characters, all uppercase letters/spaces, with at
    # least one letter, and not already caught by ARTICLE/SECTION above.
    stripped = s.strip()
    if (
        len(stripped) >= 2
        and re.fullmatch(r'[A-Z][A-Z \t]+', stripped)
        and not stripped.startswith(('ARTICLE', 'SECTION', 'EXHIBIT', 'SCHEDULE'))
    ):
        return (0, stripped)

    return None
