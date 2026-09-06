"""Turning externally-parsed structure into something the pipeline can chunk.

:meth:`~lexichunk.chunker.LegalChunker.chunk` starts from a wall of text and
has to *find* the clause boundaries.  A caller who already ran Docling,
``unstructured``, or their own converter over the source knows where the
headings were — and that knowledge, taken from the PDF's own layout or the
DOCX's own outline, usually beats anything line-based detection can recover
from the flattened text.

This module is the bridge.  It takes :class:`~lexichunk.models.Section`
records (or ready-made :class:`~lexichunk.parsers.structure.ParsedClause`
objects) and produces the two things stages 2–8 need: a single text string,
and clauses whose ``char_start``/``content`` tile that string exactly.  The
tiling is what keeps every downstream invariant true — a chunk body is still
the literal slice ``text[char_start:char_end]``, spans still do not overlap,
and snapshots still reproduce.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import replace
from typing import Callable, Optional

from .exceptions import InputError
from .models import DocumentSection, Section
from .offsets import OffsetMap, sanitize_with_map
from .parsers.structure import ParsedClause

#: ``(identifier, title, level) -> DocumentSection`` — normally
#: :meth:`~lexichunk.parsers.structure.StructureParser.classify_document_section`.
SectionClassifier = Callable[[str, str, int], DocumentSection]

#: ``str -> str`` — normally
#: :meth:`~lexichunk.chunker.LegalChunker.sanitize`.
Sanitiser = Callable[[str], str]

__all__ = ["build_document", "SourceSpanIndex"]

# Sections whose classification a container passes down to everything nested
# inside it.  Mirrors ``StructureParser._INHERITED_SECTIONS``: a paragraph
# inside "SCHEDULE 1" belongs to the schedules however neutrally its own
# heading reads.
#: The synthetic level ``StructureParser`` gives text that precedes the first
#: heading.  It is a sibling of the top-level clauses, never their parent.
_PREAMBLE_LEVEL = -99

_INHERITED_SECTIONS: frozenset[DocumentSection] = frozenset(
    {
        DocumentSection.SCHEDULES,
        DocumentSection.RECITALS,
        DocumentSection.DEFINITIONS,
    }
)


class SourceSpanIndex:
    """Maps reconstructed-document offsets back to the caller's source text.

    Built only when every :class:`~lexichunk.models.Section` carried both
    ``char_start`` and ``char_end``.  Calling an instance has the same shape
    as :meth:`~lexichunk.offsets.OffsetMap.to_raw_span`, so the pipeline can
    use either interchangeably to populate
    ``LegalChunk.raw_char_start``/``raw_char_end``.

    A chunk offset that falls on a *synthesised header line* — the
    ``"identifier title"`` line this module emits, which has no counterpart
    in the caller's source — maps to the start of that section's source
    span, since that is the nearest position in the source that the header
    actually describes.  For an empty-bodied section whose source span is
    the original heading, a non-empty reconstructed span covers that whole
    heading because its rewritten fragments have no exact source boundaries.

    Args:
        body_starts: Offset of each section's body in the reconstructed text.
        body_ends: Exclusive counterpart to *body_starts*.
        block_starts: Offset of each section's whole block (header line
            included) in the reconstructed text.
        source_starts: Each section's ``char_start`` in the caller's source.
        source_ends: Each section's ``char_end`` in the caller's source.
        body_offset_maps: Optional per-section maps from sanitised body
            offsets to the caller-supplied section text.  Omission preserves
            the original identity-mapping constructor behaviour.
    """

    __slots__ = (
        "_body_starts",
        "_body_ends",
        "_block_starts",
        "_source_starts",
        "_source_ends",
        "_body_offset_maps",
    )

    def __init__(
        self,
        body_starts: list[int],
        body_ends: list[int],
        block_starts: list[int],
        source_starts: list[int],
        source_ends: list[int],
        body_offset_maps: list[OffsetMap] | None = None,
    ) -> None:
        self._body_starts = body_starts
        self._body_ends = body_ends
        self._block_starts = block_starts
        self._source_starts = source_starts
        self._source_ends = source_ends
        self._body_offset_maps = (
            body_offset_maps
            if body_offset_maps is not None
            else [
                OffsetMap(None, body_end - body_start, body_end - body_start)
                for body_start, body_end in zip(body_starts, body_ends)
            ]
        )

    def _section_at(self, offset: int) -> int:
        """Return the index of the section whose block contains *offset*."""
        index = bisect_right(self._block_starts, offset) - 1
        return max(0, min(index, len(self._block_starts) - 1))

    def _body_offset(self, offset: int, index: int) -> int:
        """Return a reconstructed offset relative to a section's body."""
        within = min(offset, self._body_ends[index]) - self._body_starts[index]
        return max(0, min(within, self._body_offset_maps[index].sanitised_length))

    def _project_start(self, offset: int, index: int) -> int:
        """Project a reconstructed start into section *index*'s source span."""
        source_start = self._source_starts[index]
        source_end = self._source_ends[index]
        if offset <= self._body_starts[index]:
            return source_start
        within = self._body_offset(offset, index)
        return min(
            source_start + self._body_offset_maps[index].to_raw(within),
            source_end,
        )

    def _project_end(self, offset: int, index: int) -> int:
        """Project a reconstructed end into section *index*'s source span."""
        source_start = self._source_starts[index]
        source_end = self._source_ends[index]
        offset_map = self._body_offset_maps[index]
        if offset_map.sanitised_length == 0:
            return source_end
        if offset <= self._body_starts[index]:
            return source_start
        within = self._body_offset(offset, index)
        _, raw_end = offset_map.to_raw_span(0, within)
        return min(source_start + raw_end, source_end)

    def __call__(self, start: int, end: int) -> tuple[int, int]:
        """Map a reconstructed half-open span onto the caller's source text."""
        first = self._section_at(start)
        raw_start = self._project_start(start, first)
        if end <= start:
            return raw_start, raw_start
        last = self._section_at(max(end - 1, 0))
        raw_end = self._project_end(end, last)
        return raw_start, max(raw_start, raw_end)


def _header_line(identifier: str, title: Optional[str]) -> str:
    """Render a section's heading as the single line the chunker will see."""
    heading = (title or "").strip()
    if not heading or heading == identifier:
        return identifier
    return f"{identifier} {heading}"


def _resolve_identifier(section: Section, position: int) -> str:
    """Return the identifier to use for *section*, falling back to its title.

    Args:
        section: The section being converted.
        position: Its index in the input sequence, for the error message.

    Returns:
        A non-empty identifier string.

    Raises:
        InputError: If the section has neither an identifier nor a title.
    """
    identifier = (section.identifier or "").strip()
    if identifier:
        return identifier
    title = (section.title or "").strip()
    if title:
        return title
    raise InputError(
        f"sections[{position}] has neither an identifier nor a title; one of "
        f"them must name the section."
    )


def _validate_section(section: object, position: int) -> Section:
    """Type-check one element of the ``sections`` argument."""
    if not isinstance(section, Section):
        raise InputError(
            f"sections[{position}] must be a Section, got "
            f"{type(section).__name__}."
        )
    if not isinstance(section.text, str):
        raise InputError(
            f"sections[{position}].text must be a str, got "
            f"{type(section.text).__name__}."
        )
    if isinstance(section.level, bool) or not isinstance(section.level, int):
        raise InputError(
            f"sections[{position}].level must be an int, got "
            f"{type(section.level).__name__}."
        )
    for name in ("char_start", "char_end"):
        value = getattr(section, name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise InputError(
                f"sections[{position}].{name} must be a non-negative int or "
                f"None, got {value!r}."
            )
    if (
        section.char_start is not None
        and section.char_end is not None
        and section.char_end < section.char_start
    ):
        raise InputError(
            f"sections[{position}].char_end ({section.char_end}) must be >= "
            f"char_start ({section.char_start})."
        )
    return section


def _sanitised_section(section: Section, sanitise: Sanitiser) -> Section:
    """Return *section* with every text field sanitised.

    Args:
        section: An already type-checked section.
        sanitise: The ``str -> str`` sanitiser to apply.

    Returns:
        A new :class:`~lexichunk.models.Section`; the original is untouched.
    """
    return replace(
        section,
        identifier=sanitise(section.identifier or ""),
        title=(sanitise(section.title) if section.title is not None else None),
        text=sanitise(section.text),
    )


def _assign_parents(
    levels: list[int],
    identifiers: list[str],
    declared_parents: list[Optional[str]],
) -> list[Optional[int]]:
    """Work out each section's parent index.

    A declared ``parent_identifier`` wins when it names an *earlier*
    section; otherwise the parent is the nearest preceding section with a
    strictly smaller level, which is the same stack discipline
    :meth:`~lexichunk.parsers.structure.StructureParser.parse` uses.

    The synthetic preamble level (``-99``) is deliberately never pushed onto
    the stack.  It sits *before* the first heading rather than above it, so
    the parser leaves it parentless and never nests anything inside it —
    treating it as an ancestor would re-parent the whole document under it
    and turn every top-level clause into its child.

    Args:
        levels: Each section's hierarchy level, in document order.
        identifiers: Each section's resolved identifier.
        declared_parents: Each section's ``parent_identifier``, or ``None``.

    Returns:
        A parent index per section (``None`` for roots).

    Raises:
        InputError: If a declared parent identifier names no earlier section.
    """
    parents: list[Optional[int]] = []
    stack: list[int] = []
    last_seen: dict[str, int] = {}

    for position, level in enumerate(levels):
        while stack and levels[stack[-1]] >= level:
            stack.pop()
        inferred = stack[-1] if stack else None

        declared = declared_parents[position]
        if declared is None:
            parents.append(inferred)
        else:
            key = declared.strip()
            if key not in last_seen:
                raise InputError(
                    f"sections[{position}].parent_identifier {declared!r} does "
                    f"not match any earlier section's identifier."
                )
            parents.append(last_seen[key])

        if level != _PREAMBLE_LEVEL:
            stack.append(position)
        last_seen[identifiers[position]] = position

    return parents


def _subtree_ends(
    parents: list[Optional[int]], starts: list[int], total: int
) -> list[int]:
    """Compute each clause's ``char_end`` — the end of its whole subtree.

    ``ParsedClause.char_end`` marks where a clause *closes*, past the end of
    every descendant, because the structure parser only closes a clause when
    a same-or-more-senior header arrives.  Reproduce that here so clauses
    built from sections behave identically downstream.

    Args:
        parents: Parent index per clause (``None`` for roots).
        starts: ``char_start`` per clause.
        total: Length of the reconstructed text.

    Returns:
        ``char_end`` per clause.
    """
    count = len(parents)
    # Subtree sizes, right to left: every descendant has a larger index than
    # its ancestor, so a node's size is complete by the time we reach it.
    sizes = [1] * count
    for position in range(count - 1, -1, -1):
        parent = parents[position]
        if parent is not None and parent < position:
            sizes[parent] += sizes[position]

    ends: list[int] = []
    for position in range(count):
        after = position + sizes[position]
        ends.append(starts[after] if after < count else total)
    return ends


def _inherit_sections(
    own: list[DocumentSection], parents: list[Optional[int]]
) -> list[DocumentSection]:
    """Let an enclosing Schedule / Recitals / Definitions pass its section down.

    Only a clause that would otherwise be ``OPERATIVE`` inherits, so a
    ``Definitions`` paragraph inside a Schedule keeps its own, more specific
    classification — matching
    :meth:`~lexichunk.parsers.structure.StructureParser.parse`.
    """
    resolved = list(own)
    for position, section in enumerate(own):
        if section is not DocumentSection.OPERATIVE:
            continue
        ancestor = parents[position]
        while ancestor is not None:
            if resolved[ancestor] in _INHERITED_SECTIONS:
                resolved[position] = resolved[ancestor]
                break
            ancestor = parents[ancestor]
    return resolved


def _build_from_sections(
    sections: Sequence[object],
    classify: SectionClassifier,
    sanitise: Sanitiser,
) -> tuple[str, list[ParsedClause], SourceSpanIndex | None]:
    """Reconstruct a document from :class:`~lexichunk.models.Section` records."""
    source_sections = [
        _validate_section(section, position)
        for position, section in enumerate(sections)
    ]
    validated = [
        _sanitised_section(section, sanitise) for section in source_sections
    ]
    identifiers = [
        _resolve_identifier(section, position)
        for position, section in enumerate(validated)
    ]
    levels = [section.level for section in validated]
    parents = _assign_parents(
        levels, identifiers, [section.parent_identifier for section in validated]
    )

    pieces: list[str] = []
    block_starts: list[int] = []
    body_starts: list[int] = []
    body_ends: list[int] = []
    cursor = 0
    last = len(validated) - 1

    for position, section in enumerate(validated):
        # A preamble is the text *before* the first heading, so it has no
        # heading of its own — its identifier is a label, not something that
        # appears in the document. Synthesising a header line for it would
        # inject a word the source never contained.
        header = (
            ""
            if section.level == _PREAMBLE_LEVEL
            else _header_line(identifiers[position], section.title) + "\n"
        )
        body = section.text
        if body and not body.endswith("\n"):
            body += "\n"
        # A blank line between blocks, folded into the *preceding* clause's
        # own content so the clauses tile the text with no gaps.
        separator = "" if position == last else "\n"
        block = header + body + separator

        block_starts.append(cursor)
        body_starts.append(cursor + len(header))
        body_ends.append(cursor + len(header) + len(body))
        pieces.append(block)
        cursor += len(block)

    text = "".join(pieces)

    own_sections: list[DocumentSection] = []
    for position, section in enumerate(validated):
        own_sections.append(
            classify(
                identifiers[position], (section.title or "").strip(), levels[position]
            )
        )
    resolved_sections = _inherit_sections(own_sections, parents)
    ends = _subtree_ends(parents, block_starts, len(text))

    clauses = []
    for position, section in enumerate(validated):
        parent = parents[position]
        clauses.append(
            ParsedClause(
                identifier=identifiers[position],
                title=(section.title or None),
                content=pieces[position],
                level=levels[position],
                parent_identifier=(
                    identifiers[parent] if parent is not None else None
                ),
                document_section=resolved_sections[position],
                char_start=block_starts[position],
                char_end=ends[position],
                children=[],
                uid=str(position),
                parent_uid=(str(parent) if parent is not None else None),
            )
        )
    for position, clause in enumerate(clauses):
        parent = parents[position]
        if parent is not None:
            clauses[parent].children.append(clause)

    index: SourceSpanIndex | None = None
    if validated and all(
        section.char_start is not None and section.char_end is not None
        for section in validated
    ):
        sanitised_bodies_with_maps = [
            sanitize_with_map(section.text) for section in source_sections
        ]
        if all(
            body_with_map[0] == section.text
            for body_with_map, section in zip(
                sanitised_bodies_with_maps, validated
            )
        ):
            index = SourceSpanIndex(
                body_starts=body_starts,
                body_ends=body_ends,
                block_starts=block_starts,
                source_starts=[int(section.char_start or 0) for section in validated],
                source_ends=[int(section.char_end or 0) for section in validated],
                body_offset_maps=[
                    body_with_map[1] for body_with_map in sanitised_bodies_with_maps
                ],
            )

    return text, clauses, index


def _build_from_parsed_clauses(
    clauses: Sequence[object],
    sanitise: Sanitiser,
) -> tuple[str, list[ParsedClause], None]:
    """Re-base ready-made :class:`ParsedClause` objects onto their own text.

    The structure parser's clause contents tile the document exactly — every
    line belongs to precisely one clause — so concatenating them in document
    order rebuilds the text, and the cumulative lengths give the offsets.
    Passing ``StructureParser.parse(text)`` straight back in therefore
    reproduces ``chunk(text)`` exactly, which is the property that makes this
    path safe to build a custom parser against.
    """
    validated: list[ParsedClause] = []
    for position, clause in enumerate(clauses):
        if not isinstance(clause, ParsedClause):
            raise InputError(
                f"sections[{position}] must be a ParsedClause, got "
                f"{type(clause).__name__}. Do not mix Section and "
                f"ParsedClause records in one call."
            )
        validated.append(replace(clause, content=sanitise(clause.content)))

    starts: list[int] = []
    cursor = 0
    for clause in validated:
        starts.append(cursor)
        cursor += len(clause.content)
    text = "".join(clause.content for clause in validated)

    # A clause that carries a uid came from a real parser, so its own
    # parentage is authoritative — including `parent_uid is None`, which
    # means "root" and not "unknown". Only a clause with no uid at all (a
    # hand-built list) falls back to level nesting.
    uid_positions = {
        clause.uid: position
        for position, clause in enumerate(validated)
        if clause.uid
    }
    levels = [clause.level for clause in validated]
    identifiers = [clause.identifier for clause in validated]
    inferred = _assign_parents(levels, identifiers, [None] * len(validated))

    parents: list[Optional[int]] = []
    for position, clause in enumerate(validated):
        if clause.uid:
            parent = uid_positions.get(clause.parent_uid or "")
            if parent is not None and parent >= position:
                parent = None
        else:
            parent = inferred[position]
        parents.append(parent)

    ends = _subtree_ends(parents, starts, len(text))

    rebuilt = []
    for position, clause in enumerate(validated):
        parent = parents[position]
        rebuilt.append(
            ParsedClause(
                identifier=clause.identifier,
                title=clause.title,
                content=clause.content,
                level=clause.level,
                parent_identifier=(
                    validated[parent].identifier if parent is not None else None
                ),
                document_section=clause.document_section,
                char_start=starts[position],
                char_end=ends[position],
                children=[],
                uid=str(position),
                parent_uid=(str(parent) if parent is not None else None),
            )
        )
    for position, clause in enumerate(rebuilt):
        parent = parents[position]
        if parent is not None:
            rebuilt[parent].children.append(clause)

    return text, rebuilt, None


def build_document(
    sections: object,
    classify: SectionClassifier,
    sanitise: Sanitiser,
) -> tuple[str, list[ParsedClause], SourceSpanIndex | None]:
    """Build ``(text, clauses, source_span_index)`` from externally-parsed structure.

    Accepts either a sequence of :class:`~lexichunk.models.Section` records
    or a sequence of :class:`~lexichunk.parsers.structure.ParsedClause`
    objects; the two must not be mixed in one call.

    Args:
        sections: The structure to convert.
        classify: ``(identifier, title, level) -> DocumentSection``, normally
            :meth:`~lexichunk.parsers.structure.StructureParser.classify_document_section`
            so external sections land in the same buckets a natively-parsed
            document would.
        sanitise: ``str -> str``, normally
            :meth:`~lexichunk.chunker.LegalChunker.sanitize`.  Applied to
            every caller-supplied string *before* assembly, so the
            reconstruction is sanitised by construction and each clause's
            content stays an exact slice of it.

    Returns:
        ``(text, clauses, source_span_index)``.  *source_span_index* is
        ``None`` unless every section carried source offsets and *sanitise*
        produced the same body text as the built-in mapped sanitiser.

    Raises:
        InputError: If *sections* is not a sequence, is empty, mixes the two
            record types, or contains an invalid record.
    """
    if isinstance(sections, (str, bytes, bytearray)):
        raise InputError(
            f"chunk_documents() expects a sequence of Section or ParsedClause "
            f"records, got {type(sections).__name__}."
        )
    if not isinstance(sections, Sequence):
        try:
            sections = list(sections)  # type: ignore[call-overload]
        except TypeError:
            raise InputError(
                f"chunk_documents() expects a sequence of Section or "
                f"ParsedClause records, got {type(sections).__name__}."
            ) from None

    items = list(sections)  # type: ignore[call-overload]
    if not items:
        raise InputError(
            "chunk_documents() requires at least one section; got an empty "
            "sequence. Use chunk() for a document you have no structure for."
        )

    if isinstance(items[0], ParsedClause):
        return _build_from_parsed_clauses(items, sanitise)
    return _build_from_sections(items, classify, sanitise)
