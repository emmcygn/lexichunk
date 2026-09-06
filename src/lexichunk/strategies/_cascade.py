"""The cascading splitter — one definition of "make this text fit the cap".

Both chunking strategies need to cut a run of text down to ``max_chunk_size``,
and ``max_chunk_size`` is documented as a hard cap, so both must do it the
same way. Keeping the cascade here rather than on either strategy is what
makes that true: :class:`~lexichunk.strategies.clause_aware.ClauseAwareChunker`
uses it for an over-sized clause, and
:class:`~lexichunk.strategies.fallback.FallbackChunker` uses it for a single
sentence that is longer than the whole budget. A CUAD evaluation found the
cap breached by up to 2.4x on real filings, and every breach was on the
fallback path, which had no splitter below "one sentence" at all.

This module deliberately takes ``sentence_cuts`` as an argument instead of
computing them. Sentence detection lives in
:mod:`~lexichunk.strategies.fallback` alongside the abbreviation list, and
``clause_aware`` already imports it from there; accepting the positions as
data keeps this module dependency-free and the import graph acyclic.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Boundary patterns, applied in order of decreasing semantic quality.
#
# Level 0 is sentence-boundary detection, handled separately because it needs
# the compiled abbreviation pattern and is passed in.  Levels 1..4 are these
# plain regexes.  Each match's ``end()`` is the offset at which the *next*
# piece begins.
# ---------------------------------------------------------------------------

_SEMICOLON_BOUNDARY = re.compile(r'(?<=;)\s+')
# "(a) ", "(iv) ", "(A) ", "1.1 " — the start of an enumerated sub-item.
_ENUMERATOR_BOUNDARY = re.compile(r'\s+(?=\([A-Za-z]+\)|\d+\.\d)')
_NEWLINE_BOUNDARY = re.compile(r'\n')
_WHITESPACE_BOUNDARY = re.compile(r'\s+')

CASCADE_PATTERNS: tuple[re.Pattern[str], ...] = (
    _SEMICOLON_BOUNDARY,
    _ENUMERATOR_BOUNDARY,
    _NEWLINE_BOUNDARY,
    _WHITESPACE_BOUNDARY,
)

# Index of the last pattern-driven level (0 = sentences, then CASCADE_PATTERNS).
LAST_CASCADE_LEVEL = len(CASCADE_PATTERNS)


def split_to_fit(
    text: str,
    *,
    max_tokens: int,
    chars_per_token: int,
    sentence_cuts: Sequence[int] = (),
    prefix_chars: int = 0,
    identifier: str = "",
    logger: Optional[logging.Logger] = None,
) -> list[tuple[int, int]]:
    """Split *text* into spans that each fit within *max_tokens*.

    Boundary types are tried in order of decreasing semantic quality, and each
    level is applied **only** to the pieces still over the limit after the
    previous level:

    0. sentence boundaries (supplied by the caller as *sentence_cuts*);
    1. semicolon boundaries — the shape of a long legal proviso containing no
       ``.``/``!``/``?`` at all;
    2. enumerator boundaries — ``(a)``, ``(iv)``, ``1.1``;
    3. newlines;
    4. a hard word window;
    5. a hard character window, which always succeeds.

    Level 5 is what makes the cap an actual cap rather than a strong
    preference. Without it, a run offering no boundary of any kind — an OCR'd
    table, a base64 blob, a 2,485-character line — was emitted whole. Callers
    size the cap to an embedding model's context window, so an overrun is
    silent truncation at embedding time, which is worse than a cut in an
    awkward place.

    Args:
        text: The text to split.
        max_tokens: The cap, in approximate tokens.
        chars_per_token: Characters per token for the size approximation.
        sentence_cuts: Offsets into *text* at which a sentence starts. Pass
            an empty sequence when *text* is already a single sentence.
        prefix_chars: Characters that will be prepended to every resulting
            piece (the ancestor-header prefix). Counted against the budget so
            the *final* token count respects the cap.
        identifier: Clause identifier, used only in the warning logged when a
            run has to be cut inside a word.
        logger: Logger for that warning. Callers pass their own so the
            record's name still says which strategy hit the case, which is
            what the documented logger names promise.

    Returns:
        ``(start, end)`` offsets into *text*, contiguous and in order, that
        exactly tile ``[0, len(text))``.
    """
    if not text:
        return [(0, 0)]

    log = logger if logger is not None else _logger
    warned = False

    def tokens(start: int, end: int) -> int:
        return max(1, (prefix_chars + end - start) // chars_per_token)

    def cuts_for(level: int, start: int, end: int) -> list[int]:
        if level == 0:
            return [p for p in sentence_cuts if start < p < end]
        pattern = CASCADE_PATTERNS[level - 1]
        return [
            m.end()
            for m in pattern.finditer(text, start, end)
            if start < m.end() < end
        ]

    def window_split(start: int, end: int) -> list[tuple[int, int]]:
        """Cut ``[start, end)`` into fixed character windows.

        The last resort, reached only when the text offers no boundary of any
        kind inside the budget — so the cut lands mid-word by construction,
        and that is what the warning reports. Windows are contiguous, so the
        pieces still tile the input exactly.
        """
        nonlocal warned
        # A window of exactly this many characters lands on *max_tokens* once
        # the prefix is counted.  ``max(1, ...)`` guards the degenerate case
        # where the prefix alone consumes the whole budget; a one-character
        # window is then the smallest we can offer, and no split could have
        # satisfied the cap anyway.
        width = max(1, max_tokens * chars_per_token - prefix_chars)
        if not warned:
            warned = True
            log.warning(
                "Indivisible text run of %d chars in clause %r offers no split "
                "point within max_chunk_size (%d tokens); cutting inside a "
                "word to honour the cap",
                end - start,
                identifier or "<unknown>",
                max_tokens,
            )
        return [
            (cursor, min(cursor + width, end))
            for cursor in range(start, end, width)
        ]

    def finalise(start: int, end: int, level: int) -> list[tuple[int, int]]:
        if tokens(start, end) <= max_tokens:
            return [(start, end)]
        return split(start, end, level + 1)

    def split(start: int, end: int, level: int) -> list[tuple[int, int]]:
        if tokens(start, end) <= max_tokens:
            return [(start, end)]
        if level > LAST_CASCADE_LEVEL:
            return window_split(start, end)

        positions = cuts_for(level, start, end)
        if not positions:
            return split(start, end, level + 1)

        pieces: list[tuple[int, int]] = []
        current_start = start
        current_end = start
        for boundary in [*positions, end]:
            if (
                current_end > current_start
                and tokens(current_start, boundary) > max_tokens
            ):
                pieces.extend(finalise(current_start, current_end, level))
                current_start = current_end
            current_end = boundary
        if current_end > current_start:
            pieces.extend(finalise(current_start, current_end, level))
        return pieces

    return split(0, len(text), 0)


__all__ = ["split_to_fit", "CASCADE_PATTERNS", "LAST_CASCADE_LEVEL"]
