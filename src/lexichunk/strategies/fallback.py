"""Fallback chunking strategy — graceful degradation to sentence-level splitting."""

from __future__ import annotations

import re
from typing import Optional

from ..models import (
    ClauseType,
    DocumentSection,
    HierarchyNode,
    Jurisdiction,
    LegalChunk,
)

# ---------------------------------------------------------------------------
# Abbreviation pattern — matches tokens whose trailing dot must NOT trigger a
# sentence split.  The pattern is used in _split_sentences to skip candidate
# boundary positions that are actually abbreviations.
# ---------------------------------------------------------------------------
_ABBREVS = re.compile(
    r'\b(?:U\.S\.C|F\.[23]d|LLC|Ltd|Inc|Corp|plc|LLP|'
    r'e\.g|i\.e|cf|et al|ibid|viz|'
    r'Cl|Sec|Art|No|vol|pp|para|'
    r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec'
    r')\.'
)

# Matches a sentence-ending punctuation mark followed by whitespace and an
# uppercase letter (the start of the next sentence).  We use this to discover
# *candidate* boundaries and then filter out abbreviation false-positives.
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')

# Matches a numeric literal with an embedded dot so we avoid splitting inside
# dollar/section amounts such as "$1.5" or "§ 3.1".
_NUMBER_DOT = re.compile(r'\d+\.\d')


def _approx_tokens(text: str, chars_per_token: int = 4) -> int:
    """Approximate token count using a configurable character-to-token ratio.

    Args:
        text: Any string whose token count should be estimated.
        chars_per_token: Number of characters per token.  Defaults to 4.

    Returns:
        A positive integer approximation of the token count.
    """
    return max(1, len(text) // chars_per_token)


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def chunk_fallback(
    text: str,
    jurisdiction: Jurisdiction,
    max_chunk_size: int = 512,
    min_chunk_size: int = 64,
    document_id: Optional[str] = None,
) -> list[LegalChunk]:
    """Chunk text using the fallback sentence-level strategy.

    Args:
        text: Full document text to be chunked.
        jurisdiction: UK or US jurisdiction for the resulting chunks.
        max_chunk_size: Maximum chunk size in approximate tokens.
        min_chunk_size: Minimum chunk size; smaller trailing pieces are merged
            into the previous chunk.
        document_id: Optional document identifier attached to every chunk.

    Returns:
        List of :class:`~lexichunk.models.LegalChunk` objects.
    """
    return FallbackChunker(
        jurisdiction=jurisdiction,
        max_chunk_size=max_chunk_size,
        min_chunk_size=min_chunk_size,
        document_id=document_id,
    ).chunk(text)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class FallbackChunker:
    """Fallback sentence-level chunker for unrecognised legal document formats.

    Used when the structure parser finds no clause headers.  Splits text into
    overlapping sentence windows up to ``max_chunk_size`` tokens, producing
    minimally-populated :class:`~lexichunk.models.LegalChunk` objects.

    Args:
        jurisdiction: UK or US.
        max_chunk_size: Maximum chunk size in approximate tokens.
        min_chunk_size: Minimum chunk size; smaller pieces are merged.
        document_id: Optional document identifier.
        chars_per_token: Number of characters per token for the approximation
            heuristic.  Defaults to 4.
    """

    def __init__(
        self,
        jurisdiction: Jurisdiction,
        max_chunk_size: int = 512,
        min_chunk_size: int = 64,
        document_id: Optional[str] = None,
        chars_per_token: int = 4,
    ) -> None:
        self._jurisdiction = jurisdiction
        self._max_chunk_size = max_chunk_size
        self._min_chunk_size = min_chunk_size
        self._document_id = document_id
        self._chars_per_token = chars_per_token

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk(self, text: str) -> list[LegalChunk]:
        """Split text into sentence-grouped chunks.

        Algorithm:

        1. Split text into sentences using :meth:`_split_sentences`.
        2. Accumulate sentences into a window until ``max_chunk_size`` is
           reached.
        3. When a window is full, emit it as a :class:`~lexichunk.models.LegalChunk`
           and start a new window.
        4. Merge any trailing window whose size is below ``min_chunk_size``
           into the previous chunk.
        5. Assign sequential indices.

        Each chunk gets:

        - ``hierarchy``: ``HierarchyNode(level=0, identifier=f"chunk-{index}")``
        - ``hierarchy_path``: ``f"chunk-{index}"``
        - ``document_section``: :attr:`~lexichunk.models.DocumentSection.OPERATIVE`
        - ``clause_type``: :attr:`~lexichunk.models.ClauseType.UNKNOWN`
        - ``char_start`` / ``char_end`` computed from sentence positions.

        Args:
            text: Full document text.

        Returns:
            List of :class:`~lexichunk.models.LegalChunk` objects.
        """
        if not text or not text.strip():
            return []

        sentences = self._split_sentences(text)
        if not sentences:
            return []

        # Accumulate sentences into windows.
        # Each window is represented as a list of (sentence, char_offset) pairs.
        windows: list[list[tuple[str, int]]] = []
        current_window: list[tuple[str, int]] = []
        current_tokens: int = 0

        for sentence, offset in sentences:
            sentence_tokens = _approx_tokens(sentence, self._chars_per_token)

            # If adding this sentence would exceed the cap *and* we already
            # have content in the window, flush before adding.
            if current_tokens + sentence_tokens > self._max_chunk_size and current_window:
                windows.append(current_window)
                current_window = []
                current_tokens = 0

            current_window.append((sentence, offset))
            current_tokens += sentence_tokens

        # Flush the last window.
        if current_window:
            windows.append(current_window)

        # Merge a tiny trailing window into the previous one.
        if len(windows) > 1:
            last_tokens = _approx_tokens(
                " ".join(s for s, _ in windows[-1]),
                self._chars_per_token,
            )
            if last_tokens < self._min_chunk_size:
                windows[-2].extend(windows[-1])
                windows.pop()

        # Build LegalChunk objects.
        chunks: list[LegalChunk] = []
        for index, window in enumerate(windows):
            window_text = " ".join(s for s, _ in window)
            # char_start is the offset of the first sentence in the window;
            # char_end is derived by adding the length of the last sentence
            # to its starting offset.
            char_start = window[0][1]
            last_sentence, last_offset = window[-1]
            char_end = last_offset + len(last_sentence)

            identifier = f"chunk-{index}"
            chunk = LegalChunk(
                content=window_text,
                index=index,
                hierarchy=HierarchyNode(
                    level=0,
                    identifier=identifier,
                    title=None,
                    parent=None,
                ),
                hierarchy_path=identifier,
                document_section=DocumentSection.OPERATIVE,
                clause_type=ClauseType.UNKNOWN,
                jurisdiction=self._jurisdiction,
                char_start=char_start,
                char_end=char_end,
                document_id=self._document_id,
            )
            chunks.append(chunk)

        return chunks

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _split_sentences(self, text: str) -> list[tuple[str, int]]:
        """Split text into sentences, returning ``(sentence, char_offset)`` pairs.

        Uses regex-based splitting that handles common legal abbreviations
        (``U.S.C.``, ``F.3d.``, ``LLC.``, ``Ltd.``, ``e.g.``, ``i.e.``,
        etc.) to avoid false splits.  Number patterns such as ``$1.5`` are
        also protected.

        Strategy:

        1. Collect all candidate sentence-boundary positions using
           :data:`_SENTENCE_BOUNDARY`.
        2. Reject any candidate position that is immediately preceded by a
           known abbreviation match or by a number-dot-number pattern.
        3. Use the surviving split positions to slice the original text.

        Args:
            text: Document text.

        Returns:
            List of ``(sentence_text, char_start_offset)`` tuples.  Sentences
            are stripped of leading and trailing whitespace; empty strings are
            omitted.
        """
        # Collect the character positions of all abbreviation matches so we
        # can quickly test whether a candidate boundary is a false positive.
        abbrev_ends: set[int] = {m.end() for m in _ABBREVS.finditer(text)}
        number_dot_ends: set[int] = {m.end() - 1 for m in _NUMBER_DOT.finditer(text)}

        # Find all candidate split positions (the position of the whitespace
        # that follows the sentence-ending punctuation).
        split_positions: list[int] = []
        for match in _SENTENCE_BOUNDARY.finditer(text):
            boundary_start = match.start()  # position of the whitespace gap
            # The punctuation character sits just before the whitespace gap.
            punct_pos = boundary_start  # inclusive end of the previous token

            # Reject if the dot is part of a known abbreviation.
            if punct_pos in abbrev_ends:
                continue

            # Reject if the dot is inside a number literal (e.g. "§ 3.1 ").
            if punct_pos in number_dot_ends:
                continue

            split_positions.append(match.end())  # start of next sentence

        # Build (sentence, offset) pairs from the split positions.
        sentences: list[tuple[str, int]] = []
        prev = 0
        for pos in split_positions:
            raw = text[prev:pos]
            stripped = raw.strip()
            if stripped:
                # Compute the true char offset of the stripped content.
                leading_space = len(raw) - len(raw.lstrip())
                sentences.append((stripped, prev + leading_space))
            prev = pos

        # Remainder after the last split.
        raw = text[prev:]
        stripped = raw.strip()
        if stripped:
            leading_space = len(raw) - len(raw.lstrip())
            sentences.append((stripped, prev + leading_space))

        return sentences
