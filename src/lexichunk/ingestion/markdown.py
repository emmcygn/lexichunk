"""``#``-heading markdown → lexichunk.

Markdown is what most document pipelines already produce — it is what
Docling exports, what ``pandoc`` emits, what an LLM extraction step returns,
and what half the internal converters in a legaltech stack hand downstream.
If you have markdown with real headings, you have structure, and you should
not make lexichunk re-derive it from the flattened text.

.. code-block:: python

    from lexichunk import LegalChunker
    from lexichunk.ingestion import from_markdown

    sections = from_markdown(markdown_text, jurisdiction="uk")
    chunks = LegalChunker(jurisdiction="uk").chunk_documents(sections)

Only ATX headings (``# Heading``) are read.  Fenced code blocks are skipped
so a ``#`` comment inside one cannot open a section.  Because the source is
plain text, every section records its ``char_start``/``char_end`` in it, so
``chunk_documents`` populates ``raw_char_start``/``raw_char_end`` and each
chunk can be pointed back at the markdown it came from.
"""

from __future__ import annotations

import re

from ..exceptions import InputError
from ..models import Jurisdiction, Section
from ._common import SectionAccumulator

__all__ = ["from_markdown"]

# An ATX heading: up to three leading spaces, one to six '#', a space, text.
# Trailing '#' characters are the optional closing sequence.
_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")

# A fenced code block delimiter: ``` or ~~~ , three or more.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def from_markdown(
    text: str,
    *,
    jurisdiction: Jurisdiction | str = "uk",
) -> list[Section]:
    """Convert ``#``-heading markdown into :class:`~lexichunk.models.Section` records.

    Each heading opens a section; everything up to the next heading is its
    body.  Text before the first heading becomes a preamble section.

    Heading depth maps as ``#`` → level 0 (a top-level clause), ``##`` →
    level 1, and so on — but only where the heading carries no legal
    numbering.  ``## 5.2 Payment Terms`` is a subsection because ``5.2``
    says so, not because it has two hashes; a converter that emitted every
    clause at the same depth still produces a correct hierarchy.

    Args:
        text: The markdown source.
        jurisdiction: Whose numbering rules to apply to heading text.

    Returns:
        Sections in document order, each carrying its
        ``char_start``/``char_end`` in *text*, ready for
        :meth:`~lexichunk.chunker.LegalChunker.chunk_documents`.

    Raises:
        InputError: If *text* is not a ``str``.
    """
    if not isinstance(text, str):
        raise InputError(
            f"from_markdown() expects a str, got {type(text).__name__}."
        )

    accumulator = SectionAccumulator(jurisdiction, separator="\n")
    in_fence = False
    fence_marker = ""
    fence_length = 0
    offset = 0

    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        line_start = offset
        offset += len(line)

        fence = _FENCE_RE.match(stripped)
        if fence is not None:
            delimiter = fence.group(1)
            marker = delimiter[0]
            suffix = fence.group(2)
            closing_suffix = suffix[:-1] if suffix.endswith("\r") else suffix
            valid_closing_suffix = not closing_suffix.strip(" \t")
            if not in_fence:
                if marker != "`" or "`" not in suffix:
                    in_fence = True
                    fence_marker = marker
                    fence_length = len(delimiter)
            elif (
                marker == fence_marker
                and len(delimiter) >= fence_length
                and valid_closing_suffix
            ):
                in_fence = False
                fence_marker = ""
                fence_length = 0
            if in_fence or valid_closing_suffix:
                accumulator.add_line(
                    stripped,
                    char_start=line_start,
                    char_end=line_start + len(stripped),
                )
                continue

        heading = None if in_fence else _HEADING_RE.match(stripped)
        if heading is not None:
            accumulator.start_section(
                heading.group(2),
                len(heading.group(1)) - 1,
                char_start=line_start,
                char_end=line_start + len(stripped),
            )
            continue

        accumulator.add_line(
            stripped, char_start=line_start, char_end=line_start + len(stripped)
        )

    return accumulator.result()
