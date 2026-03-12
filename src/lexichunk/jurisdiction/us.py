"""US legal document patterns and conventions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ROMAN = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}


def roman_to_int(s: str) -> int:
    """Convert a Roman numeral string to an integer."""
    s = s.upper()
    result, prev = 0, 0
    for ch in reversed(s):
        val = _ROMAN.get(ch, 0)
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
      (a)                    — alpha sub-clause
      (i)                    — roman sub-clause
      Exhibit A / Schedule 1 — attachments
    """

    article: re.Pattern = field(default_factory=lambda: re.compile(
        r'^(?:ARTICLE|Article)\s+([IVXLC]+)(?:\s*[-\u2013\u2014]\s*([A-Z][^\n]{0,80}))?',
        re.MULTILINE
    ))
    section: re.Pattern = field(default_factory=lambda: re.compile(
        r'^(?:SECTION|Section)\s+(\d+\.\d+(?:\([a-z]\))?)',
        re.MULTILINE
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
        r'^(Schedule\s+[\d.]+(?:\s*[-\u2013]\s*[A-Za-z\s]+)?)',
        re.MULTILINE | re.IGNORECASE
    ))

    cross_ref: re.Pattern = field(default_factory=lambda: re.compile(
        r'\b(?:Section|Article|Exhibit|Schedule|Clause)\s+(\d+(?:\.\d+)*(?:\([a-z]+\))*(?:\([ivxlc]+\))*|[IVXLC]+)',
        re.IGNORECASE
    ))

    definition: re.Pattern = field(default_factory=lambda: re.compile(
        r'"([A-Z][A-Za-z\s\-]{1,60})"\s+(?:means|shall mean|has the meaning|is defined as|refers to)',
        re.MULTILINE
    ))
    definition_curly: re.Pattern = field(default_factory=lambda: re.compile(
        r'\u201c([A-Z][A-Za-z\s\-]{1,60})\u201d\s+(?:means|shall mean|has the meaning)',
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


def detect_level(line: str) -> tuple[int, str] | None:
    """Detect the hierarchy level and identifier of a line for US documents.

    Returns:
        (level, identifier) where level is:
          -2 = Exhibit
          -1 = Schedule
           0 = Article
           1 = Section
           3 = alpha sub-clause "(a)"
           4 = roman sub-clause "(i)"
        Returns None if not a clause header.
    """
    s = line.lstrip()

    m = re.match(r'^(Exhibit\s+[A-Z][\w\-]*)', s, re.IGNORECASE)
    if m:
        return (-2, m.group(1))

    m = re.match(r'^(Schedule\s+[\d.]+)', s, re.IGNORECASE)
    if m:
        return (-1, m.group(1))

    m = re.match(r'^(?:ARTICLE|Article)\s+([IVXLC]+)', s)
    if m:
        return (0, f'Article {m.group(1)}')

    m = re.match(r'^(?:SECTION|Section)\s+(\d+\.\d+(?:\([a-z]\))?)', s)
    if m:
        return (1, f'Section {m.group(1)}')

    m = re.match(r'^\(([a-z])\)\s+\S', s)
    if m:
        return (3, f'({m.group(1)})')

    m = re.match(r'^\(([ivxlc]+)\)\s+\S', s)
    if m:
        return (4, f'({m.group(1)})')

    return None
