"""UK legal document patterns and conventions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import DocumentSection


@dataclass
class UKPatterns:
    """Compiled regex patterns for UK legal document structure.

    UK contracts use flat numeric numbering:
      1.  Top-level clause
      1.1 Subsection
      1.1.1 Sub-subsection
      (a) Alpha sub-clause
      (i) Roman sub-clause
    """

    # Most-specific first
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
    schedule: re.Pattern = field(default_factory=lambda: re.compile(
        r'^((?:Schedule\s+\d+|Appendix\s+[\dA-Z][\w-]*)(?:\s*[-\u2013]\s*[A-Za-z\s]+)?)',
        re.MULTILINE | re.IGNORECASE
    ))

    # Cross-references
    cross_ref: re.Pattern = field(default_factory=lambda: re.compile(
        r'\b(?:Clauses?|Sections?|paragraphs?|Schedules?)\s+(\d+(?:\.\d+)*(?:\([a-z]+\))*(?:\([ivxlc]+\))*)',
        re.IGNORECASE
    ))

    # Definition patterns — straight and curly quotes
    definition: re.Pattern = field(default_factory=lambda: re.compile(
        r'"([A-Z][A-Za-z\s\-]{1,60})"\s+(?:means|shall mean|has the meaning|is defined as|refers to)',
        re.MULTILINE
    ))
    definition_curly: re.Pattern = field(default_factory=lambda: re.compile(
        r'\u201c([A-Z][A-Za-z\s\-]{1,60})\u201d\s+(?:means|shall mean|has the meaning)',
        re.MULTILINE
    ))

    definitions_headers: tuple = field(default_factory=lambda: (
        'definitions', 'interpretation', 'defined terms',
    ))
    boilerplate_headers: tuple = field(default_factory=lambda: (
        'general', 'miscellaneous', 'general provisions',
    ))
    signature_markers: tuple = field(default_factory=lambda: (
        'in witness whereof', 'signed by', 'executed by', 'as witness',
        'authorised signatory', 'duly authorised',
    ))


UK_PATTERNS = UKPatterns()


#: Optional per-jurisdiction mapping from hierarchy level to
#: :class:`~lexichunk.models.DocumentSection`.  Read by
#: :class:`~lexichunk.parsers.structure.StructureParser`; any level absent
#: from this mapping defaults to ``OPERATIVE``.
SECTION_ROLES: dict[int, DocumentSection] = {
    -1: DocumentSection.SCHEDULES,  # Schedule / Appendix
    -2: DocumentSection.SCHEDULES,  # reserved for Exhibit-style containers
}


def detect_level(line: str) -> tuple[int, str] | None:
    """Detect the hierarchy level and identifier of a line.

    Args:
        line: A single line of text (may be indented).

    Returns:
        (level, identifier) where level is:
          -1 = Schedule / Appendix
           0 = top-level clause (e.g. "1.", "1)", "Clause 1")
           1 = subsection (e.g. "1.1")
           2 = sub-subsection (e.g. "1.1.1")
           3 = alpha sub-clause "(a)"
           4 = roman sub-clause "(i)"
        Returns None if line is not a clause header.

    Note:
        Detection is deliberately permissive: ``StructureParser`` applies a
        heading-plausibility gate to every match, so shapes that also occur
        in body text (a numbered line followed by a quote or a digit, for
        example) are filtered out there rather than here.
    """
    s = line.lstrip()

    m = re.match(r'^(Schedule\s+\d+|Appendix\s+[\dA-Z][\w-]*)', s, re.IGNORECASE)
    if m:
        return (-1, m.group(1))

    m = re.match(r'^(\d+\.\d+\.\d+)\.?\s+\S', s)
    if m:
        return (2, m.group(1))

    m = re.match(r'^(\d+\.\d+)\.?\s+\S', s)
    if m:
        return (1, m.group(1))

    m = re.match(r'^(Clause\s+\d+(?:\.\d+)*)(?:\s|$)', s)
    if m:
        return (0, m.group(1))

    # Top-level clause: "1.  Definitions", '1. "Term" means ...' (straight
    # or curly quote), "1) Definitions" or "1. 2024 Fee Schedule".  The
    # plausibility gate rejects the body-text lookalikes this admits
    # (e.g. "3 Business Days after receipt ...").
    m = re.match(r'^(\d+)[.)]?\s+(?:[A-Z]\S|["\u201c\u2018]|\d)', s)
    if m:
        return (0, m.group(1))

    m = re.match(r'^\(([a-z])\)\s+\S', s)
    if m:
        return (3, f'({m.group(1)})')

    m = re.match(r'^\(([ivxlc]+)\)\s+\S', s)
    if m:
        return (4, f'({m.group(1)})')

    return None
