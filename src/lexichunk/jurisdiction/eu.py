"""EU Directives/Regulations legal document patterns and conventions.

Covers the structure used in EU legislative instruments (GDPR, DSA, DMA,
AI Act, ePrivacy Directive, etc.):

    Chapter I / CHAPTER I   — top-level grouping
    Article 1 / ARTICLE 1   — primary structural unit
    Section 1               — sub-grouping within a chapter
    1. / 2. / 3.            — numbered paragraphs within an article
    (a) / (b) / (c)         — alpha sub-points
    (i) / (ii) / (iii)      — roman sub-points
    Recital (1) / (2) ...   — non-binding preamble recitals
    Annex I / ANNEX I       — attachments
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .._patterns import NOT_AFTER_WORD, TERM_UPPER
from ..models import DocumentSection


@dataclass
class EUPatterns:
    """Compiled regex patterns for EU legislative document structure.

    EU Directives and Regulations use a distinctive structure:
      CHAPTER I / Chapter I       — top-level grouping (Roman numerals)
      Article 1 / ARTICLE 1       — primary unit (Arabic numerals)
      Section 1                   — sub-grouping within chapter
      1. / 2.                     — numbered paragraphs within articles
      (a) / (b)                   — alpha sub-points
      (i) / (ii)                  — roman sub-points
      Annex I / ANNEX I           — attachments (Roman numerals)
      Recital (1) / (2)           — preamble recitals
    """

    chapter: re.Pattern[str] = field(default_factory=lambda: re.compile(
        r'^(?:CHAPTER|Chapter)\s+([IVXLC]+)(?:\s*[-\u2013\u2014]\s*([A-Z][^\n]{0,80}))?',
        re.MULTILINE,
    ))
    article: re.Pattern[str] = field(default_factory=lambda: re.compile(
        r'^(?:ARTICLE|Article)\s+(\d+)(?:\s*[-\u2013\u2014]\s*([A-Z][^\n]{0,80}))?',
        re.MULTILINE,
    ))
    section: re.Pattern[str] = field(default_factory=lambda: re.compile(
        r'^(?:SECTION|Section)\s+(\d+)(?:\s*[-\u2013\u2014]\s*([A-Z][^\n]{0,80}))?',
        re.MULTILINE,
    ))
    paragraph: re.Pattern[str] = field(default_factory=lambda: re.compile(
        r'^(\d+)\.\s+', re.MULTILINE,
    ))
    alpha_sub: re.Pattern[str] = field(default_factory=lambda: re.compile(
        r'^\(([a-z])\)\s+', re.MULTILINE,
    ))
    roman_sub: re.Pattern[str] = field(default_factory=lambda: re.compile(
        r'^\(([ivxlc]+)\)\s+', re.MULTILINE,
    ))
    annex: re.Pattern[str] = field(default_factory=lambda: re.compile(
        r'^(?:ANNEX|Annex)\s+([IVXLC]+[\w\-]*(?:\s*[-\u2013]\s*[A-Za-z\s]+)?)',
        re.MULTILINE,
    ))

    cross_ref: re.Pattern[str] = field(default_factory=lambda: re.compile(
        r'\b(?:Articles?|Chapters?|Sections?|paragraphs?|Annexe?s?|Recitals?)'
        r'\s+(\d+(?:\(\d+\))*(?:\([a-z]+\))*|[IVXLC]+)',
        re.IGNORECASE,
    ))

    definition: re.Pattern[str] = field(default_factory=lambda: re.compile(
        NOT_AFTER_WORD + rf"['\u2018]({TERM_UPPER})['\u2019]\s+"
        r"(?:means|shall mean|has the meaning|is defined as|refers to)",
        re.MULTILINE,
    ))
    definition_curly: re.Pattern[str] = field(default_factory=lambda: re.compile(
        NOT_AFTER_WORD + rf'\u201c({TERM_UPPER})\u201d\s+'
        r'(?:means|shall mean|has the meaning|is defined as|refers to)',
        re.MULTILINE,
    ))

    definitions_headers: tuple[str, ...] = field(default_factory=lambda: (
        'definitions', 'interpretation', 'defined terms',
        'subject matter and definitions',
        'definitions and scope',
    ))
    boilerplate_headers: tuple[str, ...] = field(default_factory=lambda: (
        'final provisions', 'general provisions',
        'transitional and final provisions',
    ))
    signature_markers: tuple[str, ...] = field(default_factory=lambda: (
        'done at brussels', 'done at strasbourg', 'done at luxembourg',
        'for the european parliament', 'for the council',
        'the president', 'the secretary-general',
    ))


EU_PATTERNS = EUPatterns()


#: Optional per-jurisdiction mapping from hierarchy level to
#: :class:`~lexichunk.models.DocumentSection`.  Read by
#: :class:`~lexichunk.parsers.structure.StructureParser`; any level absent
#: from this mapping defaults to ``OPERATIVE``.
#:
#: Note that an EU Chapter (level -1) is a *grouping of operative
#: Articles*, not an attachment -- unlike the UK/US Schedule that shares
#: the same level number.  Only an Annex (level -2) is SCHEDULES.
SECTION_ROLES: dict[int, DocumentSection] = {
    -1: DocumentSection.OPERATIVE,  # Chapter
    -2: DocumentSection.SCHEDULES,  # Annex
}


def detect_level(line: str) -> tuple[int, str] | None:
    """Detect the hierarchy level and identifier of a line for EU documents.

    Returns:
        (level, identifier) where level is:
          -2 = Annex
          -1 = Chapter
           0 = Article, Recital (n), or a standalone ALL-CAPS line
               (identifier = the line itself)
           1 = Section
           2 = Numbered paragraph (1., 2., 3.)
           3 = Alpha sub-point (a), (b)
           4 = Roman sub-point (i), (ii)
        Returns None if not a clause header.

    Note:
        Detection is deliberately permissive: ``StructureParser`` applies
        a heading-plausibility gate to every match, so page furniture and
        wrapped ALL-CAPS disclaimers are filtered out there rather than
        here.
    """
    s = line.lstrip()

    m = re.match(r'^(?:ANNEX|Annex)\s+([IVXLC]+[\w\-]*)', s)
    if m:
        return (-2, f'Annex {m.group(1)}')

    m = re.match(r'^(?:CHAPTER|Chapter)\s+([IVXLC]+)', s)
    if m:
        return (-1, f'Chapter {m.group(1)}')

    m = re.match(r'^(?:RECITAL|Recital)\s+\(?(\d+)\)?', s)
    if m:
        return (0, f'Recital {m.group(1)}')

    m = re.match(r'^(?:ARTICLE|Article)\s+(\d+)', s)
    if m:
        return (0, f'Article {m.group(1)}')

    m = re.match(r'^(?:SECTION|Section)\s+(\d+)', s)
    if m:
        return (1, f'Section {m.group(1)}')

    m = re.match(r'^(\d+)\.\s+\S', s)
    if m:
        return (2, m.group(1))

    m = re.match(r'^\(([a-z])\)\s+\S', s)
    if m:
        return (3, f'({m.group(1)})')

    m = re.match(r'^\(([ivxlc]+)\)\s+\S', s)
    if m:
        return (4, f'({m.group(1)})')

    # Standalone ALL-CAPS header (e.g. "GENERAL PROVISIONS").
    stripped = s.strip()
    if (
        len(stripped) >= 2
        and re.fullmatch(r'[A-Z][A-Z \t]+', stripped)
        and not stripped.startswith((
            'ARTICLE', 'CHAPTER', 'SECTION', 'ANNEX', 'RECITAL',
        ))
    ):
        return (0, stripped)

    return None
