"""Fallback chunking strategy — graceful degradation to sentence-level splitting."""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..models import (
    ClauseType,
    DocumentSection,
    HierarchyNode,
    Jurisdiction,
    LegalChunk,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default abbreviation list — tokens whose trailing dot must NOT trigger a
# sentence split.
# ---------------------------------------------------------------------------
DEFAULT_ABBREVIATIONS: tuple[str, ...] = (
    # Case law reporters
    "U.S.C", "F.2d", "F.3d", "F.Supp", "S.Ct", "L.Ed",
    "A.2d", "A.3d", "N.E", "N.E.2d", "N.W", "N.W.2d",
    "S.E", "S.E.2d", "S.W", "S.W.2d", "S.W.3d", "P.2d", "P.3d",
    "So.2d", "So.3d", "Cal.Rptr", "Fed.Appx",
    "Bankr", "B.R",
    # Entity types
    "LLC", "Ltd", "Inc", "Corp", "plc", "LLP", "L.P", "N.A",
    "Co", "Ass'n", "Assn", "Bros",
    # Latin / scholarly
    "e.g", "i.e", "cf", "et al", "ibid", "viz", "v", "vs",
    "supra", "infra", "id", "op.cit",
    # Legal markers
    "Cl", "Sec", "Art", "No", "vol", "pp", "para", "Sch",
    "Pt", "Ch", "Div", "Reg", "Stat", "Amend", "Ex",
    # US states (common abbreviations)
    "Cal", "Tex", "Fla", "Ill", "Mass", "Conn", "Ariz",
    "Colo", "Minn", "Wash", "Wis", "Tenn", "Okla",
    "Ala", "Ark", "Del", "Ga", "Ind", "Kan", "Ky",
    "Md", "Mich", "Miss", "Mo", "Neb", "Nev",
    "N.J", "N.Y", "N.C", "N.D", "N.M", "N.H",
    "S.C", "S.D", "Va", "Vt", "W.Va",
    # Dates
    "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug",
    "Sep", "Sept", "Oct", "Nov", "Dec",
    # Titles
    "Mr", "Mrs", "Ms", "Dr", "Prof", "Hon", "Rev", "Gen",
    "Gov", "Sen", "Rep", "Sgt", "Capt", "Col", "Maj",
    "Lt", "Cmdr", "Adm",
    # Procedural rules components (Fed. R. Civ. P., Fed. R. Evid., etc.)
    "Fed", "R", "Civ", "Crim", "Evid", "P",
    # Misc legal / business
    "Dept", "Dist", "Cir", "App", "Supp", "Admin",
    "Comm", "Auth", "Bd", "Bur",
    "approx", "est", "max", "min", "avg",
    "St", "Ave", "Blvd",
)


def _compile_abbreviations(
    defaults: tuple[str, ...],
    extras: list[str] | None = None,
) -> re.Pattern[str]:
    """Build a regex pattern from abbreviation tokens.

    Each token is escaped and joined with ``|``.  The compiled pattern
    matches ``\\b<token>\\.`` — i.e. a word-boundary, the abbreviation,
    and its trailing dot.
    """
    all_abbrevs = list(defaults)
    if extras:
        all_abbrevs.extend(extras)
    # Sort by length descending so longer matches take priority.
    all_abbrevs.sort(key=len, reverse=True)
    escaped = [re.escape(a) for a in all_abbrevs]
    return re.compile(r'\b(?:' + '|'.join(escaped) + r')\.')

# Matches a sentence-ending punctuation mark followed by whitespace and an
# uppercase letter (the start of the next sentence).  We use this to discover
# *candidate* boundaries and then filter out abbreviation false-positives.
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')

# Matches a numeric literal with an embedded dot so we avoid splitting inside
# dollar/section amounts such as "$1.5" or "§ 3.1".
_NUMBER_DOT = re.compile(r'\d+\.\d')


def sentence_boundary_positions(
    text: str, abbrev_pattern: re.Pattern[str]
) -> list[int]:
    """Return the character offsets at which a new sentence starts in *text*.

    Candidate boundaries come from :data:`_SENTENCE_BOUNDARY` (sentence-ending
    punctuation followed by whitespace and a capital).  A candidate is rejected
    when the dot belongs to a known abbreviation (per *abbrev_pattern*) or sits
    inside a numeric literal such as ``$1.5`` / ``§ 3.1``.

    Shared by :class:`FallbackChunker` and
    :class:`~lexichunk.strategies.clause_aware.ClauseAwareChunker` so that
    ``extra_abbreviations`` applies identically on both chunking paths.

    Args:
        text: The string to scan.
        abbrev_pattern: Compiled pattern from :func:`_compile_abbreviations`.

    Returns:
        Sorted list of offsets, each strictly greater than 0 and strictly less
        than ``len(text)``, pointing at the first character of a sentence.
    """
    abbrev_ends: set[int] = {m.end() for m in abbrev_pattern.finditer(text)}
    number_dot_ends: set[int] = {m.end() - 1 for m in _NUMBER_DOT.finditer(text)}

    positions: list[int] = []
    for match in _SENTENCE_BOUNDARY.finditer(text):
        # The punctuation character sits just before the whitespace gap.
        punct_pos = match.start()
        if punct_pos in abbrev_ends:
            continue
        if punct_pos in number_dot_ends:
            continue
        positions.append(match.end())
    return positions


from ..utils import approx_tokens as _approx_tokens
from ._cascade import split_to_fit

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
        jurisdiction: ``"uk"``, ``"us"`` or ``"eu"`` (or a
            :class:`~lexichunk.models.Jurisdiction` enum value), or the key of a
            custom registered jurisdiction.  Recorded on every chunk.
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
    consecutive, non-overlapping sentence windows of at most
    ``max_chunk_size`` tokens, producing minimally-populated
    :class:`~lexichunk.models.LegalChunk` objects whose ``hierarchy_path`` is
    a positional ``chunk-N`` placeholder rather than a real clause path.

    Args:
        jurisdiction: ``"uk"``, ``"us"`` or ``"eu"`` (or a
            :class:`~lexichunk.models.Jurisdiction` enum value), or the key of a
            custom registered jurisdiction.  Recorded on every chunk.
        max_chunk_size: Maximum chunk size in approximate tokens.
        min_chunk_size: Minimum chunk size; smaller pieces are merged.
        document_id: Optional document identifier.
        chars_per_token: Number of characters per token for the approximation
            heuristic.  Defaults to 4.
        extra_abbreviations: Additional abbreviations that must not be treated
            as sentence boundaries.  Merged with the built-in list, which is
            never mutated.  Defaults to ``None``.
    """

    def __init__(
        self,
        jurisdiction: Jurisdiction | str,
        max_chunk_size: int = 512,
        min_chunk_size: int = 64,
        document_id: Optional[str] = None,
        chars_per_token: int = 4,
        extra_abbreviations: list[str] | None = None,
    ) -> None:
        self._jurisdiction = jurisdiction
        self._max_chunk_size = max_chunk_size
        self._min_chunk_size = min_chunk_size
        self._document_id = document_id
        self._chars_per_token = chars_per_token
        self._abbrev_pattern = _compile_abbreviations(
            DEFAULT_ABBREVIATIONS, extra_abbreviations
        )

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
        4. Merge *every* window whose size is below ``min_chunk_size`` into its
           neighbour — not only the trailing one — provided the combined window
           still fits within ``max_chunk_size``.
        5. Assign sequential indices.

        ``content`` is the exact ``text[char_start:char_end]`` slice, so a
        caller can reproduce a chunk by slicing the (sanitised) source.

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

        units = self._unit_spans(text)
        if not units:
            return []

        # Accumulate units into windows.  Each window is a list of spans.
        windows: list[list[tuple[int, int]]] = []
        current_window: list[tuple[int, int]] = []

        for unit in units:
            # If adding this unit would push the window's *exact* slice over
            # the cap — and the window already has content — flush first.
            if current_window:
                prospective = current_window + [unit]
                if self._window_tokens(text, prospective) > self._max_chunk_size:
                    windows.append(current_window)
                    current_window = []

            current_window.append(unit)

        # Flush the last window.
        if current_window:
            windows.append(current_window)

        # Merge under-sized windows.  Every window is checked (not just the
        # last), and a merge is only performed when the combined window still
        # fits within max_chunk_size — so fixing an under-run can never create
        # an over-run.
        merged_windows: list[list[tuple[int, int]]] = []
        for window in windows:
            if merged_windows:
                previous = merged_windows[-1]
                if (
                    self._window_tokens(text, previous) < self._min_chunk_size
                    or self._window_tokens(text, window) < self._min_chunk_size
                ):
                    combined = previous + window
                    if self._window_tokens(text, combined) <= self._max_chunk_size:
                        merged_windows[-1] = combined
                        continue
            merged_windows.append(window)
        windows = merged_windows

        # Build LegalChunk objects.
        chunks: list[LegalChunk] = []
        for index, window in enumerate(windows):
            # char_start is the offset of the first sentence in the window;
            # char_end is derived by adding the length of the last sentence
            # to its starting offset.  ``content`` is the *exact* slice between
            # them — never a ``' '.join`` reconstruction — so that
            # ``text[char_start:char_end] == content`` holds byte for byte.
            char_start, char_end = self._window_span(window)
            window_text = text[char_start:char_end]

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
                token_count=_approx_tokens(window_text, self._chars_per_token),
            )
            chunks.append(chunk)

        return chunks

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _unit_spans(self, text: str) -> list[tuple[int, int]]:
        """Return the spans this chunker packs into windows.

        Two properties the raw sentence list does not have:

        **They tile.** ``_split_sentences`` strips each sentence, so the
        whitespace *between* two sentences belonged to neither and fell out
        of the offsets entirely. Consecutive chunks were then one character
        apart — a CUAD evaluation saw this on 21 of 150 contracts, always
        exactly one character and always whitespace. Nothing substantive was
        lost, but "the chunks tile the document" is an invariant callers
        reasonably rely on, and a gold span straddling such a boundary fails
        a containment check for a purely cosmetic reason. Each span
        therefore runs to where the next one starts; only the document's own
        leading and trailing whitespace stays outside.

        **They fit.** A single sentence longer than ``max_chunk_size`` used
        to be emitted whole, because this path had no splitter below "one
        sentence". That is where the cap breaches on real filings came from
        — 7 of 39 chunks over on one contract, worst at 1,220 tokens against
        a limit of 512. Over-sized units go through the same cascade the
        clause-aware path uses, so the cap now means the same thing on both.

        Args:
            text: The document text.

        Returns:
            Contiguous ``(start, end)`` spans, each within the cap.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return []

        starts = [offset for _, offset in sentences]
        last_text, last_offset = sentences[-1]
        # Every span ends where the next begins; the final one ends at the
        # last sentence's own end, so trailing document whitespace is not
        # swept into a chunk.
        ends = starts[1:] + [last_offset + len(last_text)]

        spans: list[tuple[int, int]] = []
        for start, end in zip(starts, ends):
            if (
                _approx_tokens(text[start:end], self._chars_per_token)
                <= self._max_chunk_size
            ):
                spans.append((start, end))
                continue
            spans.extend(
                (start + piece_start, start + piece_end)
                for piece_start, piece_end in split_to_fit(
                    text[start:end],
                    max_tokens=self._max_chunk_size,
                    chars_per_token=self._chars_per_token,
                    identifier=f"<fallback sentence at offset {start}>",
                    logger=logger,
                )
            )
        return spans

    @staticmethod
    def _window_span(window: list[tuple[int, int]]) -> tuple[int, int]:
        """Return the ``(char_start, char_end)`` span covered by *window*.

        Sound because the spans are contiguous: the union of the window's
        spans is exactly the range from the first start to the last end.
        """
        return window[0][0], window[-1][1]

    def _window_tokens(self, text: str, window: list[tuple[int, int]]) -> int:
        """Approximate token count of the exact text slice *window* covers."""
        start, end = self._window_span(window)
        return _approx_tokens(text[start:end], self._chars_per_token)

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
        split_positions = sentence_boundary_positions(text, self._abbrev_pattern)

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
