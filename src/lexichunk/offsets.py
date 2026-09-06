"""Mapping between raw input offsets and sanitised-text offsets.

:meth:`~lexichunk.chunker.LegalChunker.sanitize` rewrites the input before
anything else looks at it — it strips a UTF-8 BOM, folds ``\\r\\n``/``\\r``
to ``\\n``, drops null bytes and applies Unicode NFC normalisation.  Every
``char_start``/``char_end`` the pipeline reports therefore indexes the
*sanitised* string, which is not the string the caller passed in.

Anything that wants to highlight a chunk inside the original file — a
viewer, a redline, a citation back to a PDF text layer — needs the inverse.
:class:`OffsetMap` is that inverse: a monotonic array built during
sanitisation, exposing :meth:`OffsetMap.to_raw`,
:meth:`OffsetMap.to_raw_span` and :meth:`OffsetMap.to_sanitised`.
"""

from __future__ import annotations

import unicodedata
from bisect import bisect_left

__all__ = ["OffsetMap", "sanitize_with_map"]


# Maximum number of merge passes the NFC segmenter will run before giving up
# and treating the whole string as one run (see :func:`_nfc_with_map`).
_MAX_MERGE_PASSES = 8


class OffsetMap:
    """A monotonic map between sanitised-text and raw-input offsets.

    Instances are produced by :func:`sanitize_with_map` (and by
    :meth:`~lexichunk.chunker.LegalChunker.sanitize_with_map`, its public
    alias).  They are immutable and cheap to keep alongside a document.

    **Run semantics.**  Sanitisation is a sequence of *runs*: one or more
    raw characters collapsing to zero or more sanitised characters.  A BOM
    is a one-character run producing nothing; ``"\\r\\n"`` is a
    two-character run producing ``"\\n"``; an NFD sequence such as
    ``"e" + U+0301`` is a two-character run producing ``"é"``.  Every
    sanitised index maps to the **start of the raw run it came from**, so
    :meth:`to_raw` is non-decreasing but not necessarily strictly
    increasing.

    Because of that, ``raw[to_raw(a):to_raw(b)]`` re-sanitises to exactly
    ``sanitised[a:b]`` whenever *a* and *b* each sit at the start of a run
    — which is every index for the transformations that actually occur in
    text extracted from real documents (BOM, CRLF, nulls, NFD sequences),
    since each of those runs yields at most one sanitised character.  The
    one exception is a rare NFC *expansion* (``U+0958`` normalises to two
    characters), where several sanitised indices share one raw index and a
    span that starts mid-run is widened to the run start.

    Args:
        to_raw_offsets: For each sanitised index, the raw index its run
            starts at.  ``None`` means the identity map — nothing was
            rewritten, so the two strings are the same and every offset
            already lines up.
        raw_length: Length of the raw input string.
        sanitised_length: Length of the sanitised string.
    """

    __slots__ = ("_offsets", "_raw_length", "_sanitised_length")

    def __init__(
        self,
        to_raw_offsets: list[int] | None,
        raw_length: int,
        sanitised_length: int,
    ) -> None:
        self._offsets = to_raw_offsets
        self._raw_length = raw_length
        self._sanitised_length = sanitised_length

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def is_identity(self) -> bool:
        """``True`` when sanitisation changed nothing and offsets line up.

        The common case for text that is already NFC, LF-only and free of
        BOMs and null bytes.  No per-character array is allocated at all.
        """
        return self._offsets is None

    @property
    def raw_length(self) -> int:
        """Length of the raw input string this map was built from."""
        return self._raw_length

    @property
    def sanitised_length(self) -> int:
        """Length of the sanitised string this map was built from."""
        return self._sanitised_length

    def __repr__(self) -> str:
        return (
            f"OffsetMap(raw_length={self._raw_length}, "
            f"sanitised_length={self._sanitised_length}, "
            f"identity={self.is_identity})"
        )

    # ------------------------------------------------------------------
    # Sanitised -> raw
    # ------------------------------------------------------------------

    def to_raw(self, index: int) -> int:
        """Return the raw offset that sanitised offset *index* came from.

        Args:
            index: A sanitised-text offset in ``[0, sanitised_length]``.
                The end-of-string value is accepted (and maps to
                ``raw_length``) so that half-open spans can be mapped with
                one call per endpoint.

        Returns:
            The raw offset at which *index*'s run begins.

        Raises:
            IndexError: If *index* is outside ``[0, sanitised_length]``.
            TypeError: If *index* is not an ``int``.
        """
        index = _check_index(index, self._sanitised_length, "sanitised")
        if index == self._sanitised_length:
            return self._raw_length
        if self._offsets is None:
            return index
        return self._offsets[index]

    def to_raw_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a half-open sanitised span onto the raw input.

        Args:
            start: Inclusive sanitised start offset.
            end: Exclusive sanitised end offset; must be ``>= start``.

        Returns:
            ``(raw_start, raw_end)``.  Re-sanitising
            ``raw[raw_start:raw_end]`` reproduces ``sanitised[start:end]``
            (see the class docstring for the one expansion caveat).

        Raises:
            IndexError: If either endpoint is out of range.
            ValueError: If *end* is less than *start*.
        """
        raw_start = self.to_raw(start)
        raw_end = self.to_raw(end)
        if end < start:
            raise ValueError(
                f"end ({end}) must be >= start ({start}) in to_raw_span()"
            )
        return raw_start, raw_end

    # ------------------------------------------------------------------
    # Raw -> sanitised
    # ------------------------------------------------------------------

    def to_sanitised(self, index: int) -> int:
        """Return the sanitised offset that raw offset *index* lands on.

        For a raw character that survived sanitisation this is that
        character's own sanitised offset.  For a raw character that was
        *removed* (a BOM, a null byte, the ``\\r`` of a ``\\r\\n`` pair, the
        combining mark of an NFD sequence) it is the offset the surrounding
        run collapsed to — i.e. the next surviving character's position.

        ``to_sanitised(to_raw(i)) == i`` holds for every sanitised offset
        *i* that starts a run.

        Args:
            index: A raw-input offset in ``[0, raw_length]``.

        Returns:
            The corresponding sanitised offset in
            ``[0, sanitised_length]``.

        Raises:
            IndexError: If *index* is outside ``[0, raw_length]``.
            TypeError: If *index* is not an ``int``.
        """
        index = _check_index(index, self._raw_length, "raw")
        if self._offsets is None:
            return index
        if index >= self._raw_length:
            return self._sanitised_length
        position = bisect_left(self._offsets, index)
        return min(position, self._sanitised_length)


def _check_index(index: int, limit: int, kind: str) -> int:
    """Validate an offset argument and return it.

    Args:
        index: The candidate offset.
        limit: The inclusive upper bound (a string length).
        kind: ``"raw"`` or ``"sanitised"``, used in the error message.

    Returns:
        *index*, unchanged.

    Raises:
        TypeError: If *index* is not an ``int`` (``bool`` is rejected too).
        IndexError: If *index* is outside ``[0, limit]``.
    """
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError(
            f"{kind} offset must be an int, got {type(index).__name__}"
        )
    if not 0 <= index <= limit:
        raise IndexError(
            f"{kind} offset {index} out of range [0, {limit}]"
        )
    return index


# ---------------------------------------------------------------------------
# Sanitisation with offset tracking
# ---------------------------------------------------------------------------


def _drop_char(
    text: str, offsets: list[int] | None, target: str
) -> tuple[str, list[int] | None]:
    """Remove every occurrence of *target* from *text*, updating the map."""
    if target not in text:
        return text, offsets
    kept: list[str] = []
    new_offsets: list[int] = []
    for position, character in enumerate(text):
        if character == target:
            continue
        kept.append(character)
        new_offsets.append(offsets[position] if offsets is not None else position)
    return "".join(kept), new_offsets


def _fold_crlf(
    text: str, offsets: list[int] | None
) -> tuple[str, list[int] | None]:
    """Fold ``"\\r\\n"`` pairs to ``"\\n"``, updating the map."""
    if "\r\n" not in text:
        return text, offsets
    kept: list[str] = []
    new_offsets: list[int] = []
    position = 0
    length = len(text)
    while position < length:
        source = offsets[position] if offsets is not None else position
        if text[position] == "\r" and position + 1 < length and text[position + 1] == "\n":
            kept.append("\n")
            new_offsets.append(source)
            position += 2
            continue
        kept.append(text[position])
        new_offsets.append(source)
        position += 1
    return "".join(kept), new_offsets


def _nfc_with_map(
    text: str, offsets: list[int] | None
) -> tuple[str, list[int] | None]:
    """Apply NFC normalisation to *text*, updating the map.

    NFC composes a base character with its following combining marks, so a
    run of raw characters can collapse into one.  The text is therefore cut
    into *runs* that normalise independently, and every character the run
    produces is mapped back to the run's first character.

    Runs start as combining sequences (a starter plus the non-starters that
    follow it).  That is not always safe on its own — Hangul jamo compose
    across two starters (``L + V + T`` → one syllable) — so adjacent runs
    are merged wherever normalising them separately would differ from
    normalising them together, and the result is verified against
    ``unicodedata.normalize`` before being returned.

    Args:
        text: The text to normalise.
        offsets: The map accumulated so far, or ``None`` for identity.

    Returns:
        ``(normalised_text, offsets)``.
    """
    if unicodedata.is_normalized("NFC", text):
        return text, offsets

    target = unicodedata.normalize("NFC", text)

    boundaries = [0]
    for position in range(1, len(text)):
        if unicodedata.combining(text[position]) == 0:
            boundaries.append(position)
    boundaries.append(len(text))
    runs = [
        (boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)
    ]

    pieces: list[str] = []
    for _ in range(_MAX_MERGE_PASSES):
        merged: list[tuple[int, int]] = []
        for run in runs:
            if merged:
                left_start, left_end = merged[-1]
                start, end = run
                joint = unicodedata.normalize("NFC", text[left_start:end])
                separate = unicodedata.normalize(
                    "NFC", text[left_start:left_end]
                ) + unicodedata.normalize("NFC", text[start:end])
                if joint != separate:
                    merged[-1] = (left_start, end)
                    continue
            merged.append(run)
        runs = merged
        pieces = [unicodedata.normalize("NFC", text[s:e]) for s, e in runs]
        if "".join(pieces) == target:
            break
    else:
        # Unreachable for any text seen in practice: a run structure that
        # still disagrees with unicodedata after eight merge passes.  One
        # run over the whole string is trivially correct as a *string*; the
        # map it yields is coarse (every offset points at 0), which is
        # strictly better than returning a map that is simply wrong.
        runs = [(0, len(text))]
        pieces = [target]

    new_offsets: list[int] = []
    for (start, _end), piece in zip(runs, pieces):
        source = offsets[start] if offsets is not None else start
        new_offsets.extend([source] * len(piece))
    return target, new_offsets


def sanitize_with_map(text: str) -> tuple[str, OffsetMap]:
    """Sanitise *text* and return it alongside its :class:`OffsetMap`.

    The returned string is character-for-character identical to
    :meth:`~lexichunk.chunker.LegalChunker.sanitize`'s output — the two
    share this implementation's transformation order (BOM, ``\\r\\n``,
    ``\\r``, null bytes, NFC).  The extra work of building the map is
    skipped entirely for text that needs no rewriting, in which case
    :attr:`OffsetMap.is_identity` is ``True``.

    Args:
        text: Raw input text.

    Returns:
        ``(sanitised_text, offset_map)``.

    Raises:
        TypeError: If *text* is not a ``str``.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"sanitize_with_map() expects a str, got {type(text).__name__}"
        )

    raw_length = len(text)
    offsets: list[int] | None = None

    current, offsets = _drop_char(text, offsets, "﻿")
    current, offsets = _fold_crlf(current, offsets)
    # A bare "\r" becomes "\n" one-for-one, so the map is untouched.
    current = current.replace("\r", "\n")
    current, offsets = _drop_char(current, offsets, "\x00")
    current, offsets = _nfc_with_map(current, offsets)

    return current, OffsetMap(offsets, raw_length, len(current))
