"""Shared machinery for the ingestion adapters.

Every adapter does the same three things — refine a heading against the
jurisdiction's own numbering rules, accumulate the body content that follows
it, and emit :class:`~lexichunk.models.Section` records — so all three live
here and the per-format modules stay small enough to read in one sitting.
"""

from __future__ import annotations

from typing import Optional

from ..jurisdiction import get_detect_level
from ..models import Jurisdiction, Section
from ..parsers.structure import is_allcaps_fallback

__all__ = ["SectionAccumulator", "refine_heading", "PREAMBLE_LEVEL"]

#: Level given to text that precedes the first heading.  Matches the synthetic
#: preamble :class:`~lexichunk.parsers.structure.StructureParser` emits, and
#: :func:`~lexichunk.documents.build_document` knows not to synthesise a
#: header line for it.
PREAMBLE_LEVEL = -99

# Separator characters an upstream converter may leave between a heading's
# number and its text ("ARTICLE IV - INDEMNIFICATION").
_TITLE_SEPARATORS = "-–—:."


def refine_heading(
    heading: str,
    jurisdiction: Jurisdiction | str,
    fallback_level: int,
) -> tuple[str, Optional[str], int]:
    """Split a heading into ``(identifier, title, level)``.

    An upstream converter tells you a heading's *depth* — Docling's
    ``SectionHeaderItem.level``, ``unstructured``'s ``category_depth``,
    markdown's ``#`` count.  It does not tell you that ``5.2`` is a
    subsection of ``5``, or that ``SCHEDULE 1`` is a container rather than a
    top-level clause; that is jurisdiction knowledge, and lexichunk already
    has it in ``detect_level``.

    So: when the heading *starts with* legal numbering, take the level and
    identifier from the jurisdiction rules and keep the rest as the title.
    A converter that puts a schedule and a clause at the same heading depth
    has said they are equally deep; the numbering says otherwise, and the
    numbering is right.

    When the heading carries no numbering — a bare ``CONFIDENTIALITY`` —
    ``detect_level``'s ALL-CAPS fallback branch would hand the whole line
    back as a level-0 identifier, which says only "this line is shouty" and
    adds nothing to what the converter already reported.  That one case is
    ignored and the converter's own depth is kept, with the heading text as
    the identifier.  A heading that *is* nothing but numbering
    (``Schedule 1``, ``Exhibit A``) is a real detection and is used.

    Args:
        heading: The heading text as the upstream parser reported it.
        jurisdiction: Whose ``detect_level`` rules to apply.
        fallback_level: The level to use when the heading carries no legal
            numbering, derived from the converter's own depth.

    Returns:
        ``(identifier, title, level)``.  *title* is ``None`` when the
        heading is nothing but its identifier.

    Example::

        refine_heading("5.2 Payment Terms", "uk", 0)
        # -> ("5.2", "Payment Terms", 1)
        refine_heading("CONFIDENTIALITY", "uk", 0)
        # -> ("CONFIDENTIALITY", None, 0)
    """
    text = " ".join(heading.split())
    if not text:
        return "", None, fallback_level

    detected = get_detect_level(jurisdiction)(text)
    if detected is not None:
        level, identifier = detected
        if identifier and not is_allcaps_fallback(text, level, identifier):
            remainder = text[len(identifier):].lstrip()
            remainder = remainder.lstrip(_TITLE_SEPARATORS).strip()
            return identifier, (remainder or None), level

    return text, None, fallback_level


class SectionAccumulator:
    """Collects body content under the most recent heading.

    Adapters walk a flat stream — a heading, some paragraphs, a list, a
    table, the next heading — and this turns that stream into
    :class:`~lexichunk.models.Section` records.  Content seen before the
    first heading becomes a preamble section, exactly as the structure
    parser would treat leading text.

    Args:
        jurisdiction: Whose numbering rules :func:`refine_heading` applies.
        separator: Joins the accumulated blocks into the section's body.
            ``"\\n\\n"`` for adapters whose items are whole blocks (Docling,
            ``unstructured``); ``"\\n"`` for one that feeds in single lines
            (markdown), where the source's own blank lines already separate
            the paragraphs.
    """

    def __init__(
        self, jurisdiction: Jurisdiction | str, separator: str = "\n\n"
    ) -> None:
        self._jurisdiction = jurisdiction
        self._separator = separator
        self._sections: list[Section] = []
        self._identifier: Optional[str] = None
        self._title: Optional[str] = None
        self._level: int = PREAMBLE_LEVEL
        self._blocks: list[str] = []
        self._start: Optional[int] = None
        self._end: Optional[int] = None
        self._line_source_start: Optional[int] = None
        self._line_source_end: Optional[int] = None
        self._line_source_aligned = True
        self._heading_span: Optional[tuple[int, int]] = None
        self._open = False

    def start_section(
        self,
        heading: str,
        fallback_level: int,
        *,
        char_start: Optional[int] = None,
        char_end: Optional[int] = None,
    ) -> None:
        """Close the current section and open one for *heading*.

        Args:
            heading: The heading text as reported upstream.
            fallback_level: Level to use when the heading carries no legal
                numbering.
            char_start: Optional offset of the *heading line* in the source.
                Used as the section's span only when no body content
                follows, so that a heading-only section still points
                somewhere sensible without skewing the body's own mapping.
            char_end: Optional exclusive end of the heading line's span.
        """
        self.flush()
        identifier, title, level = refine_heading(
            heading, self._jurisdiction, fallback_level
        )
        self._identifier = identifier
        self._title = title
        self._level = level
        self._heading_span = (
            (char_start, char_end)
            if char_start is not None and char_end is not None
            else None
        )
        self._open = True

    def add_text(
        self,
        text: str,
        *,
        char_start: Optional[int] = None,
        char_end: Optional[int] = None,
    ) -> None:
        """Append a body block to the section currently open.

        Args:
            text: The block's text.  Blank blocks are ignored, so a run of
                empty lines never widens the recorded span.
            char_start: Optional offset of this block in the source; the
                section's span grows to cover it.
            char_end: Optional exclusive end of that span.
        """
        if not text or not text.strip():
            return
        self._line_source_aligned = False
        self._blocks.append(text.strip("\n"))
        self._widen(char_start, char_end)

    def add_line(
        self,
        line: str,
        *,
        char_start: Optional[int] = None,
        char_end: Optional[int] = None,
    ) -> None:
        """Append one source line verbatim, blank lines included.

        For an adapter working line by line rather than block by block
        (markdown), the source's own blank lines *are* the paragraph
        structure and must survive into the section body.  Only a non-blank
        line widens the recorded span, so trailing blank lines never stretch
        a section over the gap before the next heading.

        Args:
            line: The line, without its terminator.
            char_start: Optional offset of the line in the source.
            char_end: Optional exclusive end of that span.
        """
        self._blocks.append(line)
        if char_start is None or char_end is None:
            self._line_source_aligned = False
        elif self._line_source_start is None:
            self._line_source_start = char_start
            self._line_source_end = char_end
        elif (
            self._line_source_end is None
            or char_start != self._line_source_end + len(self._separator)
        ):
            self._line_source_aligned = False
        else:
            self._line_source_end = char_end
        if line.strip():
            self._widen(char_start, char_end)

    def _widen(self, char_start: Optional[int], char_end: Optional[int]) -> None:
        """Grow the open section's recorded source span to cover a block."""
        if char_start is not None:
            self._start = (
                char_start if self._start is None else min(self._start, char_start)
            )
        if char_end is not None:
            self._end = char_end if self._end is None else max(self._end, char_end)

    def flush(self) -> None:
        """Emit the section currently open, if it has anything in it."""
        untrimmed_body = self._separator.join(self._blocks)
        leading_trimmed = len(untrimmed_body) - len(
            untrimmed_body.lstrip("\r\n")
        )
        body = untrimmed_body[leading_trimmed:].rstrip()
        if self._open or body.strip():
            start, end = self._start, self._end
            if (
                body
                and self._line_source_aligned
                and self._line_source_start is not None
            ):
                start = self._line_source_start + leading_trimmed
                end = start + len(body)
            if start is None and end is None and self._heading_span is not None:
                start, end = self._heading_span
            self._sections.append(
                Section(
                    identifier=self._identifier or "preamble",
                    title=self._title,
                    text=body,
                    level=self._level,
                    char_start=start,
                    char_end=end,
                )
            )
        self._identifier = None
        self._title = None
        self._level = PREAMBLE_LEVEL
        self._blocks = []
        self._start = None
        self._end = None
        self._line_source_start = None
        self._line_source_end = None
        self._line_source_aligned = True
        self._heading_span = None
        self._open = False

    def result(self) -> list[Section]:
        """Flush anything still open and return every section, in order."""
        self.flush()
        return self._sections
