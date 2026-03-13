"""Legal document structure parser — section/clause boundary detection.

This module detects clause/section boundaries in legal text and builds a
document hierarchy encoded as a flat list of :class:`ParsedClause` objects.
It is the primary consumer of the jurisdiction-specific ``detect_level``
functions and is itself consumed by the chunker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..jurisdiction import get_detect_level
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_title(line: str, identifier: str) -> Optional[str]:
    """Return the heading text that follows *identifier* on *line*.

    The function strips the identifier token itself (including any trailing
    dot, closing parenthesis or similar punctuation) from the stripped line
    and returns whatever non-empty text remains on that line, or ``None``.

    Args:
        line: The raw header line as found in the source text.
        identifier: The identifier string as returned by ``detect_level``
            (e.g. ``"1.1"`` or ``"(a)"``).

    Returns:
        The heading text, or ``None`` if only whitespace remains.
    """
    s = line.lstrip()

    # Build an escaped version of the identifier so we can reliably locate it.
    escaped = re.escape(identifier)

    # The identifier may be followed by an optional dot / closing paren, then
    # optional whitespace before the title text starts.
    pattern = rf'^{escaped}\.?\s*'
    remainder = re.sub(pattern, '', s, count=1)
    title = remainder.strip()
    return title if title else None


def _line_offsets(text: str) -> list[int]:
    """Return a list of character offsets for the start of every line.

    The first entry is always ``0``; subsequent entries point to the character
    immediately after each ``'\\n'`` in *text*.

    Args:
        text: The full document string.

    Returns:
        List of integer character offsets, one per line.
    """
    offsets = [0]
    for i, ch in enumerate(text):
        if ch == '\n':
            offsets.append(i + 1)
    return offsets


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
        self, jurisdiction: Jurisdiction, doc_type: str = "contract"
    ) -> None:
        self._jurisdiction = jurisdiction
        self._doc_type = doc_type
        self._detect_level: Callable[[str], tuple[int, str] | None] = (
            get_detect_level(jurisdiction)
        )

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
        header_map: dict[int, tuple[int, str]] = {}
        for idx, line in enumerate(lines):
            result = self._detect_level(line)
            if result is not None:
                header_map[idx] = result

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

            # Extract title from header line.
            title = _extract_title(line, identifier)

            # Classify document section.
            doc_section = self._detect_document_section(identifier, title or '', level)

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
                )
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
            )

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
            )
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
                )
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

        * **SCHEDULES**: ``level`` is ``-1`` (Schedule) or ``-2`` (Exhibit).
        * **SIGNATURES**: title/identifier contains ``"signature"``,
          ``"execution"``, ``"in witness"``, or ``"signed"``.
        * **RECITALS**: title/identifier contains ``"recital"``,
          ``"background"``, or ``"whereas"``.
        * **DEFINITIONS**: title/identifier contains ``"definition"``,
          ``"interpretation"``, or ``"defined term"``.
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
        combined = (identifier + ' ' + title).lower()
        is_tc = self._doc_type == "terms_conditions"

        # Schedules / Exhibits are identified purely by level.
        if level in (-1, -2):
            return DocumentSection.SCHEDULES

        # Signature blocks — skip for T&C documents (false positives).
        if not is_tc and any(
            kw in combined
            for kw in ('signature', 'execution', 'in witness', 'signed')
        ):
            return DocumentSection.SIGNATURES

        # Recitals / background — skip for T&C documents (false positives).
        if not is_tc and any(
            kw in combined for kw in ('recital', 'background', 'whereas')
        ):
            return DocumentSection.RECITALS

        # Definitions sections.
        if any(kw in combined for kw in ('definition', 'interpretation', 'defined term')):
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
