"""Fixture generator framework: emit a document *and* its gold annotation.

The point of a gold annotation is to be independent of the parser.  Deriving
one by running lexichunk over a fixture and writing the answers down proves
only that the parser agrees with itself.  So these fixtures go the other way:
the *structure is declared first* — clause identifiers, levels, parentage,
defined terms, cross-references — and the document text is generated from it.
The gold offsets fall out of that generation, at which point they are true by
construction and the parser has had no say in them.

Every content module declares:

``PREAMBLE``
    Paragraphs before the first heading.
``CLAUSES``
    A list of :class:`Clause` in document order.
``DEFINED_TERMS``
    ``{term: definition}`` — the definition text exactly as it appears after
    ``means`` in the body, without the trailing punctuation.
``CROSS_REFERENCES``
    ``(raw_text, target_identifier, kind)`` triples.  Every occurrence of
    *raw_text* in the finished document is recorded as a gold reference, and
    :func:`emit` refuses to produce a fixture whose text contains a
    reference-shaped phrase that no triple covers — so the gold list is
    provably complete, not merely plausible.

Run a generator directly to (re)write its fixture and gold file.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

FIXTURES_DIR = Path(__file__).resolve().parent.parent
GOLD_DIR = FIXTURES_DIR / "gold"

WRAP_COLUMNS = 78


@dataclass
class Clause:
    """One declared clause, before any text has been generated.

    Attributes:
        identifier: The identifier lexichunk should report — ``"7.3"``,
            ``"(b)"``, ``"Schedule 1"``, ``"Article IV"``.
        heading: The heading *line* as it appears in the document, which
            normally opens with the identifier.
        level: The hierarchy level the identifier implies.
        parent: The enclosing clause's ``identifier``, or ``None``.
        paragraphs: Body paragraphs, unwrapped.  Emitted after the heading
            line, wrapped to :data:`WRAP_COLUMNS`.
        title: The heading text after the identifier, for the gold record.
            Defaults to *subtitle* when one is given, else to whatever
            follows the identifier in *heading*.
        subtitle: A second heading line, emitted directly beneath *heading*
            with no blank line between them.  This is the US convention —
            ``ARTICLE I`` on one line and ``DEFINITIONS AND
            INTERPRETATION`` on the next — and the reason the fixture
            exercises it is that the title then lives on a line the
            identifier does not appear on.
    """

    identifier: str
    heading: str
    level: int
    parent: Optional[str]
    paragraphs: list[str] = field(default_factory=list)
    title: Optional[str] = None
    subtitle: Optional[str] = None


def wrap(text: str, columns: int = WRAP_COLUMNS) -> list[str]:
    """Greedily hard-wrap *text*, exactly as a PDF text extractor would.

    Deliberately not :func:`textwrap.fill`: no long-word breaking, no
    sentence-aware widow control, no hanging indents.  A greedy fill at a
    fixed column is what falls out of laying glyphs on a page, and it is what
    puts a line break in the middle of ``clause 7.3(b)``.

    Args:
        text: One paragraph.
        columns: Maximum line width.

    Returns:
        The wrapped lines.
    """
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= columns:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def force_soft_hyphen(lines: list[str], word: str, split_at: int) -> list[str]:
    """Break *word* across a line boundary with a soft hyphen.

    Justified text in a real agreement hyphenates, and the extractor keeps
    the hyphen: ``indemnifi-`` at the end of one line and ``cation`` at the
    start of the next.  Nothing downstream can recover the word by looking at
    either line alone, which is exactly why a fixture needs one.

    Args:
        lines: Already-wrapped lines, modified into the returned copy.
        word: The word to break.
        split_at: How many characters stay on the first line.

    Returns:
        A new list of lines with the first occurrence of *word* broken.

    Raises:
        ValueError: If *word* does not occur in *lines*.
    """
    for index, line in enumerate(lines):
        position = line.find(word)
        if position == -1:
            continue
        head = f"{line[:position]}{word[:split_at]}-"
        tail = f"{word[split_at:]}{line[position + len(word):]}".strip()
        return [*lines[:index], head, tail, *lines[index + 1:]]
    raise ValueError(f"{word!r} does not occur in the generated lines")


def force_line_break(lines: list[str], phrase: str, after_word: str) -> list[str]:
    """Break a line immediately after *after_word* inside *phrase*.

    Greedy wrapping puts a line break wherever the column runs out, which
    lands one somewhere harmless most of the time.  A fixture cannot rely on
    luck for the case that matters most — a cross-reference split between its
    label and its number, ``"... as set out in clause"`` / ``"7.3(b) ..."``,
    where each half on its own says nothing and the second half looks exactly
    like a clause heading.  So one is placed deliberately.

    Args:
        lines: Already-wrapped lines.
        phrase: The text to find, e.g. ``"as set out in clause 7.3(b)"``.
        after_word: The word inside *phrase* to break after.

    Returns:
        A new list of lines with the break applied.

    Raises:
        ValueError: If *phrase* does not occur on a single line.
    """
    for index, line in enumerate(lines):
        position = line.find(phrase)
        if position == -1:
            continue
        cut = line.index(after_word, position) + len(after_word)
        head = line[:cut].rstrip()
        tail = line[cut:].lstrip()
        return [*lines[:index], head, tail, *lines[index + 1:]]
    raise ValueError(f"{phrase!r} does not occur on any single wrapped line")


class _Writer:
    """Accumulates lines and tracks the character offset of each one."""

    def __init__(
        self,
        *,
        page_lines: Optional[int] = None,
        running_header: str = "",
        running_footer: str = "",
        total_pages: int = 42,
    ) -> None:
        self._lines: list[str] = []
        self._page_lines = page_lines
        self._running_header = running_header
        self._running_footer = running_footer
        self._total_pages = total_pages
        self._since_break = 0
        self._page = 1
        #: Indices of lines that are clause headings rather than body text.
        self.heading_lines: set[int] = set()

    @property
    def offset(self) -> int:
        """The character offset the next line will start at."""
        return sum(len(line) + 1 for line in self._lines)

    def add(self, line: str, *, furniture: bool = False) -> None:
        """Append one line, inserting page furniture at page boundaries."""
        self._lines.append(line)
        if furniture or self._page_lines is None:
            return
        self._since_break += 1
        if self._since_break >= self._page_lines:
            self._since_break = 0
            self.add("", furniture=True)
            if self._running_footer:
                self.add(
                    self._running_footer.format(
                        page=self._page, total=self._total_pages
                    ),
                    furniture=True,
                )
            self._page += 1
            if self._running_header:
                self.add(self._running_header, furniture=True)
            self.add("", furniture=True)

    def add_heading(self, text: str) -> None:
        """Append a heading, wrapped like body text, marking every line.

        Wrapping matters for an inline sub-clause whose whole text *is*
        its heading line ("(a) references to clauses and Schedules are
        references to clauses of, and Schedules to, this Agreement;").
        For an ordinary short heading wrapping is a no-op.
        """
        for line in wrap(text):
            index = len(self._lines)
            self.add(line)
            self.heading_lines.add(index)

    def masked_text(self) -> str:
        """Return the document with heading lines blanked to spaces.

        Same length as :meth:`text`, so offsets carry over unchanged, but
        a heading cannot be mistaken for a cross-reference.
        ``Section 3.02`` written as a heading *is* the clause; the same
        string in a body paragraph is a reference to it, and only the
        second belongs in the gold annotation.
        """
        return '\n'.join(
            " " * len(line) if index in self.heading_lines else line
            for index, line in enumerate(self._lines)
        ) + '\n'

    def add_all(self, lines: list[str]) -> None:
        """Append several lines."""
        for line in lines:
            self.add(line)

    def text(self) -> str:
        """Return the accumulated document."""
        return "\n".join(self._lines) + "\n"


# A reference-shaped phrase: a label word followed by an identifier.  Used to
# prove the declared CROSS_REFERENCES list is complete rather than merely
# plausible.
_REFERENCE_SHAPE = re.compile(
    r"\b(?:[Cc]lauses?|[Ss]ections?|[Ss]chedules?|[Ee]xhibits?|[Aa]rticles?"
    r"|[Aa]nnexes?|[Pp]aragraphs?)\s+"
    r"(?:\d+(?:\.\d+)*(?:\([a-z0-9]+\))*|[IVXLC]+\b|[A-Z]\b)"
)


def _term_span(text: str, term: str) -> tuple[int, int]:
    """Locate a defined term's definition span in *text*.

    Args:
        text: The finished document.
        term: The defined term, without quotes.

    Returns:
        ``(start, end)`` covering the opening quote through the punctuation
        that closes the definition sentence.

    Raises:
        ValueError: If the term's definition cannot be located.
    """
    opening = text.find(f'"{term}" means')
    if opening == -1:
        raise ValueError(f'no definition of "{term}" found in the fixture')
    cursor = opening
    while cursor < len(text):
        character = text[cursor]
        if character == ";":
            return opening, cursor + 1
        if character == "." and not text[cursor - 3 : cursor].endswith(("No", "Ltd")):
            # A full stop that is not an abbreviation ends the definition.
            following = text[cursor + 1 : cursor + 2]
            if following in ("", "\n", " "):
                return opening, cursor + 1
        cursor += 1
    return opening, len(text)


def _parent_indices(clauses: list[Clause]) -> list[Optional[int]]:
    """Resolve each clause's ``parent`` identifier to a clause *index*.

    Identifiers are not unique across a whole agreement — "1", "2" and "3"
    are top-level clauses *and* the paragraph numbers inside each schedule,
    and "(a)" occurs under several different sub-clauses.  Document order
    settles it: a clause's parent is the nearest *preceding* clause carrying
    that identifier.

    Args:
        clauses: The declared clauses, in document order.

    Returns:
        One entry per clause: the parent's index, or ``None`` for a root.

    Raises:
        ValueError: If a declared parent does not appear earlier in the list.
    """
    parents: list[Optional[int]] = []
    for index, clause in enumerate(clauses):
        if clause.parent is None:
            parents.append(None)
            continue
        for candidate in range(index - 1, -1, -1):
            if clauses[candidate].identifier == clause.parent:
                parents.append(candidate)
                break
        else:
            raise ValueError(
                f"clause {clause.identifier!r} declares parent "
                f"{clause.parent!r}, which does not appear before it"
            )
    return parents


def _ancestors(index: int, parents: list[Optional[int]]) -> set[int]:
    """Return the indices of every ancestor of *index*."""
    chain: set[int] = set()
    cursor = parents[index]
    while cursor is not None:
        chain.add(cursor)
        cursor = parents[cursor]
    return chain


_SUBCLAUSE_TARGET = re.compile(r"^(?P<parent>.+?)(?P<label>\([a-z0-9]+\))$")

# What may *not* follow a declared reference for the match to be that
# reference.  Without this, "clause 6" was recorded at every "clause 6.1",
# "Article VI" at every "Article VII" and "Article VIII", and "Article I" at
# every "Article IV" — inventing gold references the document does not
# contain and then scoring lexichunk down for not finding them.  A trailing
# "." is fine (a sentence ends), a trailing ".3" is not (it is clause 6.3).
_IDENTIFIER_CONTINUES = re.compile(r"[0-9A-Za-z(]|\.\d")


def _resolve_target(
    clauses: list[Clause],
    parents: list[Optional[int]],
    starts: list[int],
    identifier: str,
    position: int,
) -> int:
    """Return the index of the clause a reference at *position* points at.

    Identifiers repeat: "1", "2" and "3" are top-level clauses *and* the
    paragraph numbers inside each schedule.  Three things disambiguate,
    in order:

    * **A qualified path.**  ``"Schedule 2/3"`` is paragraph 3 *of Schedule
      2* — which is what "in accordance with paragraph 3 of this Schedule 2"
      means even though the sentence sits in the main body, where scope
      alone would wrongly pick top-level clause 3.
    * **A compound sub-clause identifier.**  ``"9.3(b)"`` names the ``(b)``
      whose parent is ``9.3``.
    * **Scope**, as a reader resolves it: a bare "paragraph 2" written
      inside Schedule 2 means Schedule 2's, and a bare "clause 2" in the
      main body means the top-level one.

    Raises:
        ValueError: If nothing matches, or if none of the three settles it —
            in which case the fixture's declaration is genuinely ambiguous
            and must say which clause it means.
    """

    def matching(label: str, within: Optional[int]) -> list[int]:
        """Indices whose identifier is *label*, optionally under *within*."""
        compound = _SUBCLAUSE_TARGET.match(label)
        found = []
        for index, clause in enumerate(clauses):
            if compound is not None:
                if not (
                    clause.identifier == compound["label"]
                    and clause.parent == compound["parent"]
                ):
                    continue
            elif clause.identifier != label:
                continue
            if within is not None and within not in _ancestors(index, parents):
                continue
            found.append(index)
        return found

    # A "/"-qualified path names each enclosing clause in turn.
    segments = identifier.split("/")
    scope: Optional[int] = None
    for depth, segment in enumerate(segments):
        candidates = matching(segment, scope)
        if not candidates:
            raise ValueError(
                f"cross-reference target {identifier!r} matches no declared "
                f"clause at segment {segment!r}"
            )
        if len(candidates) == 1:
            scope = candidates[0]
            continue
        if depth < len(segments) - 1:
            raise ValueError(
                f"cross-reference target {identifier!r} is ambiguous at "
                f"segment {segment!r}"
            )
        # Last segment, still ambiguous — fall back to the reader's rule:
        # prefer the candidate in the same container as the reference.
        containers = [
            index
            for index, clause in enumerate(clauses)
            if clause.level < 0 and starts[index] <= position
        ]
        here = containers[-1] if containers else None

        def container_of(index: int) -> Optional[int]:
            enclosing = [
                ancestor
                for ancestor in _ancestors(index, parents)
                if clauses[ancestor].level < 0
            ]
            return max(enclosing) if enclosing else None

        scoped = [index for index in candidates if container_of(index) == here]
        if len(scoped) != 1:
            raise ValueError(
                f"cross-reference target {identifier!r} at offset {position} "
                f"is ambiguous between "
                f"{[clauses[index].identifier for index in candidates]}; "
                f"qualify it in the fixture's CROSS_REFERENCES, e.g. "
                f'"Schedule 2/{segment}"'
            )
        scope = scoped[0]

    assert scope is not None
    return scope


def emit(
    *,
    name: str,
    preamble: list[str],
    clauses: list[Clause],
    defined_terms: dict[str, str],
    cross_references: list[tuple[str, str, str]],
    description: str,
    page_lines: Optional[int] = None,
    running_header: str = "",
    running_footer: str = "",
    soft_hyphens: Optional[list[tuple[str, int]]] = None,
    line_breaks: Optional[list[tuple[str, str]]] = None,
) -> tuple[str, dict[str, Any]]:
    """Generate a fixture's text and its gold annotation.

    Args:
        name: Fixture base name (no extension).
        preamble: Paragraphs before the first heading.
        clauses: The declared structure, in document order.
        defined_terms: ``{term: definition}``.
        cross_references: ``(raw_text, target_identifier, kind)`` triples.
        description: One line recorded in the gold file.
        page_lines: Insert page furniture every this many body lines.
        running_header: Repeated header line, or ``""`` for none.
        running_footer: Repeated footer line; ``{page}`` and ``{total}`` are
            substituted.
        soft_hyphens: ``(word, split_at)`` pairs to break across lines.
        line_breaks: ``(phrase, after_word)`` pairs; a line break is forced
            inside each phrase, just after *after_word*.  Used to put a
            break in the middle of a cross-reference.

    Returns:
        ``(text, gold)``.

    Raises:
        ValueError: If the text contains a reference-shaped phrase that
            *cross_references* does not cover, or a declared term or
            reference cannot be located.
    """
    writer = _Writer(
        page_lines=page_lines,
        running_header=running_header,
        running_footer=running_footer,
    )

    for paragraph in preamble:
        writer.add_all(wrap(paragraph))
        writer.add("")

    starts: list[int] = []
    for clause in clauses:
        starts.append(writer.offset)
        writer.add_heading(clause.heading)
        if clause.subtitle:
            # No blank line between them: a two-line US article heading is
            # typed as one unit, and that is what the parser has to cope with.
            writer.add_heading(clause.subtitle)
        writer.add("")
        for paragraph in clause.paragraphs:
            lines = wrap(paragraph)
            for word, split_at in soft_hyphens or ():
                if any(word in line for line in lines):
                    lines = force_soft_hyphen(lines, word, split_at)
            for phrase, after_word in line_breaks or ():
                if any(phrase in line for line in lines):
                    lines = force_line_break(lines, phrase, after_word)
            writer.add_all(lines)
            writer.add("")

    text = writer.text()
    if unicodedata.normalize("NFC", text) != text:
        raise ValueError("generated text is not NFC-normalised")

    # Clause spans are the clause's *own* extent — from its heading line to
    # the next heading at any level — so they tile the document without
    # overlap and can be compared to chunk spans directly.
    ends = [*starts[1:], len(text)]

    # Headings are masked out: only *body* occurrences are references.
    # Masking preserves length, so an offset into `searchable` is an
    # offset into `text`.
    searchable = writer.masked_text().replace("\n", " ")

    declared = {raw for raw, _target, _kind in cross_references}
    for match in _REFERENCE_SHAPE.finditer(searchable):
        phrase = " ".join(match.group(0).split())
        if phrase not in declared:
            raise ValueError(
                f"undeclared reference-shaped phrase {phrase!r}; add it to "
                f"CROSS_REFERENCES or reword the sentence"
            )

    parent_indices = _parent_indices(clauses)

    gold_references: list[dict[str, Any]] = []
    flattened = searchable
    for raw, target, kind in cross_references:
        positions = [
            match.start()
            for match in re.finditer(re.escape(raw), flattened)
            if not _IDENTIFIER_CONTINUES.match(flattened, match.end())
        ]
        if not positions:
            raise ValueError(f"declared reference {raw!r} does not occur")
        for position in positions:
            target_index = _resolve_target(
                clauses, parent_indices, starts, target, position
            )
            gold_references.append(
                {
                    "raw_text": raw,
                    "target_identifier": target,
                    "target_kind": kind,
                    "char_start": position,
                    # The target's span, resolved here rather than left to
                    # the reader: identifiers repeat across schedules, so a
                    # span is the only unambiguous way to say which clause a
                    # reference points at — and it lets a test check
                    # resolution without matching identifier spellings.
                    "target_char_start": starts[target_index],
                    "target_char_end": ends[target_index],
                }
            )

    gold = {
        "fixture": name,
        "description": description,
        "provenance": (
            "Generated by tests/fixtures/generators/generate_"
            f"{name}.py. The structure below was declared first and the "
            "document text was produced from it, so these offsets are true "
            "by construction and were never read back from the parser."
        ),
        "span_semantics": (
            "char_start/char_end index the SANITISED text and cover the "
            "clause's own extent: its heading line through to the next "
            "heading at any level. Spans tile the document without overlap. "
            "is_top_level marks a root structural unit (no parent), which is "
            "the same definition PipelineMetrics.top_level_clause_count uses."
        ),
        "clauses": [
            {
                "identifier": clause.identifier,
                "title": (
                    clause.title
                    if clause.title is not None
                    else clause.subtitle or _title_of(clause)
                ),
                "level": clause.level,
                "parent": clause.parent,
                "is_top_level": clause.parent is None,
                "char_start": start,
                "char_end": end,
            }
            for clause, start, end in zip(clauses, starts, ends)
        ],
        "defined_terms": [
            {
                "term": term,
                "definition": definition,
                "char_start": _term_span(text, term)[0],
                "char_end": _term_span(text, term)[1],
            }
            for term, definition in defined_terms.items()
        ],
        "cross_references": gold_references,
    }
    return text, gold


def _title_of(clause: Clause) -> Optional[str]:
    """Return the heading text following the identifier, or ``None``."""
    heading = clause.heading.strip()
    if not heading.startswith(clause.identifier):
        return heading or None
    remainder = heading[len(clause.identifier):].lstrip()
    remainder = remainder.lstrip(".-–—: ").strip()
    return remainder or None


def write(name: str, text: str, gold: dict[str, Any]) -> None:
    """Write a fixture and its gold annotation to disk."""
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURES_DIR / f"{name}.txt").write_text(text, encoding="utf-8", newline="\n")
    (GOLD_DIR / f"{name}.json").write_text(
        json.dumps(gold, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"wrote {name}.txt ({len(text):,} chars, {text.count(chr(10)):,} lines) "
        f"and gold/{name}.json "
        f"({len(gold['clauses'])} clauses, "
        f"{len(gold['defined_terms'])} terms, "
        f"{len(gold['cross_references'])} references)"
    )
