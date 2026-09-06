"""Clause-aware chunking strategy — primary chunking logic.

This module provides :class:`ClauseAwareChunker`, which converts the flat list
of :class:`~lexichunk.parsers.structure.ParsedClause` objects produced by
:class:`~lexichunk.parsers.structure.StructureParser` into a list of
:class:`~lexichunk.models.LegalChunk` objects.  Chunks respect clause
boundaries: a clause is never split mid-way unless it exceeds the configured
token limit.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..models import (
    ClauseType,
    HierarchyNode,
    Jurisdiction,
    LegalChunk,
)
from ..parsers.structure import ParsedClause
from ..utils import approx_tokens as _approx_tokens
from .fallback import (
    DEFAULT_ABBREVIATIONS,
    _compile_abbreviations,
    sentence_boundary_positions,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cascading splitter — boundary patterns, applied in order of preference.
#
# Level 0 is sentence-boundary detection (abbreviation-aware, shared with
# FallbackChunker) and is handled separately because it needs the compiled
# abbreviation pattern.  Levels 1..4 are these plain regexes.  Each match's
# ``end()`` is the offset at which the *next* piece begins.
# ---------------------------------------------------------------------------

_SEMICOLON_BOUNDARY = re.compile(r'(?<=;)\s+')
# "(a) ", "(iv) ", "(A) ", "1.1 " — the start of an enumerated sub-item.
_ENUMERATOR_BOUNDARY = re.compile(r'\s+(?=\([A-Za-z]+\)|\d+\.\d)')
_NEWLINE_BOUNDARY = re.compile(r'\n')
_WHITESPACE_BOUNDARY = re.compile(r'\s+')

_CASCADE_PATTERNS: tuple[re.Pattern[str], ...] = (
    _SEMICOLON_BOUNDARY,
    _ENUMERATOR_BOUNDARY,
    _NEWLINE_BOUNDARY,
    _WHITESPACE_BOUNDARY,
)

# Index of the last cascade level (0 = sentences, then _CASCADE_PATTERNS).
_LAST_CASCADE_LEVEL = len(_CASCADE_PATTERNS)


# ---------------------------------------------------------------------------
# Main chunker
# ---------------------------------------------------------------------------


class ClauseAwareChunker:
    """Chunk a legal document at clause boundaries.

    Operates on the flat list of :class:`~lexichunk.parsers.structure.ParsedClause`
    objects produced by :class:`~lexichunk.parsers.structure.StructureParser`.
    Respects clause boundaries — never splits mid-clause unless the clause
    exceeds ``max_chunk_size``.

    **Offsets are the single source of truth.**  A chunk's body is the exact
    slice ``original_text[char_start:char_end]``; ``content`` is that body with
    the ancestor header lines (if any) prepended, so
    ``chunk.content.endswith(original_text[chunk.char_start:chunk.char_end])``
    always holds.  ``char_end`` is the end of the clause's *own* text, so a
    parent chunk's span never overlaps its descendants'.

    **Hierarchy-aware merging.**  ``min_chunk_size`` is a preference, hierarchy
    is a fact: a group below ``min_chunk_size`` is merged only with (a) an
    adjacent sibling sharing the same ``parent_uid`` *and* ``document_section``
    or (b) its own immediately-preceding parent group.  Two container-level
    groups (``level <= 0`` — top-level clauses, Schedules, the preamble) are
    never merged into one another, so an under-sized top-level clause is
    emitted as a short chunk rather than being folded into an unrelated
    neighbour.  A merged group's metadata (``hierarchy``, ``hierarchy_path``,
    ``document_section``, ``original_header``) comes from the structurally
    dominant clause — the parent in case (b), the first sibling in case (a).

    Attributes:
        last_merged_identifiers: Populated by every :meth:`chunk` call (and
            reset at its start).  Maps the index of each emitted chunk that
            covers **more than one** clause to the list of *all* clause
            identifiers whose text that chunk contains, in document order,
            starting with the dominant clause's own identifier.  Chunks
            covering a single clause are absent from the mapping — their only
            identifier is already ``chunk.hierarchy.identifier``.  This is how
            a child folded into its parent (e.g. ``4.1`` merged into ``4``)
            stays discoverable for cross-reference resolution, which needs to
            map ``"clause 4.1"`` onto the chunk that actually contains it.

    Args:
        jurisdiction: UK or US.
        max_chunk_size: Maximum chunk size in approximate tokens (default 512).
            Enforced as a hard cap: an over-sized clause is split with a
            cascading splitter and a final :meth:`_enforce_max` pass re-splits
            anything still over the limit after merging.
        min_chunk_size: Minimum chunk size; smaller clauses are merged with an
            adjacent sibling where the hierarchy allows (default 64).
        document_id: Optional document identifier attached to every chunk.
        chars_per_token: Number of characters per token for the approximation
            heuristic.  Defaults to 4.
        extra_abbreviations: Additional abbreviations (without the trailing
            dot) whose full stop must not be treated as a sentence boundary by
            the cascading splitter.
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
        self.last_merged_identifiers: dict[int, list[str]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk(
        self,
        clauses: list[ParsedClause],
        original_text: str,
    ) -> list[LegalChunk]:
        """Convert parsed clauses into :class:`~lexichunk.models.LegalChunk` objects.

        Algorithm:

        1. For each :class:`~lexichunk.parsers.structure.ParsedClause`, compute
           the approximate token size of its final ``content`` (own text plus
           the ancestor headers that will be prepended).
        2. If that exceeds ``max_chunk_size`` → split with the cascading
           splitter (:meth:`_split_text_cascading`).
        3. Merge groups below ``min_chunk_size`` where — and only where — the
           hierarchy allows (:meth:`_merge_small_clauses`).
        4. Re-split anything still over ``max_chunk_size``
           (:meth:`_enforce_max`).
        5. Emit one :class:`~lexichunk.models.LegalChunk` per group, with
           sequential ``index`` values and a ``hierarchy_path``.

        Preamble clauses (``level == -99``) that contain only whitespace are
        skipped.  Non-empty preambles are included as their own chunk.

        Args:
            clauses: Flat list from
                :meth:`~lexichunk.parsers.structure.StructureParser.parse`,
                in document order.
            original_text: The original (sanitised) document text.  Chunk
                bodies are sliced from it directly.

        Returns:
            List of :class:`~lexichunk.models.LegalChunk` objects in document
            order.
        """
        # Build a uid → ParsedClause lookup for hierarchy walking.  Keying on
        # `identifier` would be ambiguous: identifiers repeat across a document
        # (a Schedule restarting at "1", repeated "(a)" sub-clauses), and a
        # last-write-wins dict would then splice one section's headers into
        # another section's chunk.  `uid` is unique by construction.
        clause_map: dict[str, ParsedClause] = {c.uid: c for c in clauses}

        self.last_merged_identifiers = {}

        # ------------------------------------------------------------------
        # Step 1: Filter and expand clauses into groups.
        #
        # Each "group" is a list[ParsedClause] that will eventually become a
        # single LegalChunk.  Oversized clauses are expanded into multiple
        # sub-groups here.
        # ------------------------------------------------------------------
        groups: list[list[ParsedClause]] = []

        for clause in clauses:
            # Skip empty preamble clauses.
            if clause.level == -99 and not clause.content.strip():
                continue

            prefix = self._content_prefix(clause, clause_map)
            tokens = _approx_tokens(prefix + clause.content, self._chars_per_token)

            if tokens > self._max_chunk_size:
                # Split into smaller pieces.
                sub_clauses = self._split_oversized_clause(
                    clause, prefix_chars=len(prefix)
                )
                # Each sub-clause becomes its own initial group.
                for sub in sub_clauses:
                    groups.append([sub])
            else:
                groups.append([clause])

        # ------------------------------------------------------------------
        # Step 2: Merge groups that are below min_chunk_size.
        # ------------------------------------------------------------------
        groups = self._merge_small_clauses(groups)

        # ------------------------------------------------------------------
        # Step 2b: Hard cap — nothing leaves this method over max_chunk_size
        # unless it is genuinely indivisible (which is logged).
        # ------------------------------------------------------------------
        groups = self._enforce_max(groups, clause_map)

        # ------------------------------------------------------------------
        # Step 3: Convert each group into a LegalChunk.
        # ------------------------------------------------------------------
        legal_chunks: list[LegalChunk] = []

        for idx, group in enumerate(groups):
            if len(group) > 1:
                dominant = self._dominant(group)
                identifiers = [dominant.identifier]
                identifiers.extend(
                    c.identifier for c in group if c is not dominant
                )
                self.last_merged_identifiers[idx] = identifiers
            chunk = self._group_to_chunk(group, idx, clause_map, original_text)
            legal_chunks.append(chunk)

        return legal_chunks

    # ------------------------------------------------------------------
    # Structural helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _own_end(clause: ParsedClause) -> int:
        """Return the end offset of *clause*'s **own** text.

        ``ParsedClause.char_end`` marks where the clause *closes* — i.e. past
        the end of every descendant, because a clause only closes when a
        same-or-more-senior header arrives.  ``content`` however holds only the
        contiguous run of lines the clause owns directly, starting at
        ``char_start``.  The own-text span is therefore
        ``[char_start, char_start + len(content))``, and those spans tile the
        document without overlap.
        """
        return clause.char_start + len(clause.content)

    @staticmethod
    def _dominant(group: list[ParsedClause]) -> ParsedClause:
        """Return the structurally dominant clause of *group*.

        The most senior clause (lowest ``level``); ties are broken by document
        order.  For a child merged into its parent this is the parent; for a
        run of merged siblings it is the first sibling.
        """
        best = group[0]
        for clause in group[1:]:
            if clause.level < best.level:
                best = clause
        return best

    @staticmethod
    def _origin_uid(clause: ParsedClause) -> str:
        """Return the uid of the clause *clause* originated from.

        Synthetic pieces produced by :meth:`_split_oversized_clause` carry a
        ``"<parent uid>#p<n>"`` uid; every other clause returns its own uid.
        """
        return clause.uid.split('#', 1)[0]

    @staticmethod
    def _is_container(clause: ParsedClause) -> bool:
        """Whether *clause* sits at a container level (top-level or above).

        Levels ``0`` (top-level clause / Article), ``-1``/``-2``
        (Schedule / Exhibit / Chapter) and ``-99`` (preamble) each own a
        self-contained part of the document; two of them are never merged into
        a single chunk because no single-valued ``hierarchy_path``,
        ``clause_type`` or ``document_section`` could honestly describe the
        result.
        """
        return clause.level <= 0

    # ------------------------------------------------------------------
    # Hierarchy path
    # ------------------------------------------------------------------

    def _build_hierarchy_path(
        self,
        clause: ParsedClause,
        clause_map: dict[str, ParsedClause],
    ) -> str:
        """Build a human-readable hierarchy path string.

        Walks up the ``parent_uid`` chain using *clause_map* to collect
        ancestor nodes, reverses them, then joins with ``" > "``.  ``uid`` is
        used rather than ``parent_identifier`` because identifiers are not
        unique across a document.

        If a node has a title it is formatted as ``"identifier — title"``
        (e.g. ``"Article VII — Indemnification"``); otherwise just the
        identifier is used.

        Args:
            clause: The clause to build the path for.
            clause_map: Dict mapping ``uid`` → :class:`ParsedClause`.

        Returns:
            Hierarchy path string, e.g.
            ``"Article VII — Indemnification > Section 7.2 > (a)"``.
        """
        parts: list[str] = []
        current: Optional[ParsedClause] = clause
        seen: set[str] = set()

        while current is not None:
            if current.title:
                label = f"{current.identifier} — {current.title}"
            else:
                label = current.identifier
            parts.append(label)

            parent_uid = current.parent_uid
            if parent_uid is None or parent_uid in seen:
                break
            seen.add(parent_uid)
            current = clause_map.get(parent_uid)

        parts.reverse()
        return " > ".join(parts)

    def _collect_ancestor_headers(
        self,
        clause: ParsedClause,
        clause_map: dict[str, ParsedClause],
    ) -> list[str]:
        """Collect ancestor header lines in root→leaf order (excluding *clause* itself).

        Walks up the ``parent_uid`` chain, collects each ancestor's header as
        ``"identifier title"`` (or just identifier if no title), then reverses
        to produce root-first ordering.

        Preamble clauses (``level == -99``) return an empty list.

        Args:
            clause: The clause whose ancestors to collect.
            clause_map: Dict mapping ``uid`` → :class:`ParsedClause`.

        Returns:
            List of header strings in root→leaf order.
        """
        if clause.level == -99:
            return []

        ancestors: list[str] = []
        parent_uid = clause.parent_uid
        seen: set[str] = set()

        while parent_uid is not None and parent_uid not in seen:
            seen.add(parent_uid)
            parent = clause_map.get(parent_uid)
            if parent is None:
                break
            if parent.title:
                ancestors.append(f"{parent.identifier} {parent.title}".strip())
            else:
                ancestors.append(parent.identifier.strip())
            parent_uid = parent.parent_uid

        ancestors.reverse()
        return ancestors

    def _content_prefix(
        self,
        clause: ParsedClause,
        clause_map: dict[str, ParsedClause],
    ) -> str:
        """Return the exact string prepended to a chunk body for *clause*.

        Either ``""`` or the ancestor header lines joined by newlines with a
        trailing newline, so that ``prefix + body`` is the chunk's ``content``.
        """
        headers = self._collect_ancestor_headers(clause, clause_map)
        if not headers:
            return ""
        return '\n'.join(headers) + '\n'

    # ------------------------------------------------------------------
    # Cascading splitter
    # ------------------------------------------------------------------

    def _split_text_cascading(
        self,
        text: str,
        *,
        prefix_chars: int = 0,
        identifier: str = "",
    ) -> list[tuple[int, int]]:
        """Split *text* into spans that each fit within ``max_chunk_size``.

        Boundary types are tried in order of decreasing semantic quality, and
        each level is applied **only** to the pieces that are still over the
        limit after the previous level:

        0. sentence boundaries (abbreviation-aware — the same detector
           :class:`~lexichunk.strategies.fallback.FallbackChunker` uses, so
           ``extra_abbreviations`` applies here too);
        1. semicolon boundaries (``"…; "``) — the common shape of a long
           legal proviso that contains no ``.``/``!``/``?`` at all;
        2. enumerator boundaries — ``(a)``, ``(iv)``, ``1.1``;
        3. newlines;
        4. a hard word window.

        Args:
            text: The text to split.
            prefix_chars: Number of characters that will be prepended to every
                resulting piece (the ancestor-header prefix).  Counted against
                the budget so the *final* ``token_count`` respects the cap.
            identifier: Clause identifier, used only in the warning logged when
                a piece is genuinely indivisible.

        Returns:
            A list of ``(start, end)`` offsets into *text*, contiguous and in
            order, that exactly tile ``[0, len(text))``.
        """
        if not text:
            return [(0, 0)]

        sentence_cuts = sentence_boundary_positions(text, self._abbrev_pattern)
        warned = False

        def tokens(start: int, end: int) -> int:
            return max(1, (prefix_chars + end - start) // self._chars_per_token)

        def cuts_for(level: int, start: int, end: int) -> list[int]:
            if level == 0:
                return [p for p in sentence_cuts if start < p < end]
            pattern = _CASCADE_PATTERNS[level - 1]
            return [
                m.end()
                for m in pattern.finditer(text, start, end)
                if start < m.end() < end
            ]

        def finalise(start: int, end: int, level: int) -> list[tuple[int, int]]:
            if tokens(start, end) <= self._max_chunk_size:
                return [(start, end)]
            return split(start, end, level + 1)

        def split(start: int, end: int, level: int) -> list[tuple[int, int]]:
            nonlocal warned
            if tokens(start, end) <= self._max_chunk_size:
                return [(start, end)]
            if level > _LAST_CASCADE_LEVEL:
                if not warned:
                    warned = True
                    logger.warning(
                        "Indivisible text run of %d chars in clause %r exceeds "
                        "max_chunk_size (%d tokens); emitting it oversized",
                        end - start,
                        identifier or "<unknown>",
                        self._max_chunk_size,
                    )
                return [(start, end)]

            positions = cuts_for(level, start, end)
            if not positions:
                return split(start, end, level + 1)

            pieces: list[tuple[int, int]] = []
            current_start = start
            current_end = start
            for boundary in [*positions, end]:
                if (
                    current_end > current_start
                    and tokens(current_start, boundary) > self._max_chunk_size
                ):
                    pieces.extend(finalise(current_start, current_end, level))
                    current_start = current_end
                current_end = boundary
            if current_end > current_start:
                pieces.extend(finalise(current_start, current_end, level))
            return pieces

        return split(0, len(text), 0)

    # ------------------------------------------------------------------
    # Oversized clause splitting
    # ------------------------------------------------------------------

    def _split_oversized_clause(
        self,
        clause: ParsedClause,
        prefix_chars: int = 0,
    ) -> list[ParsedClause]:
        """Split an oversized clause's **own** text into smaller pieces.

        Child clauses are not consulted: they are already separate
        :class:`~lexichunk.parsers.structure.ParsedClause` objects in the flat
        list and their text is not part of ``clause.content``.  Only this
        clause's own content is divided, using :meth:`_split_text_cascading`
        (sentences → semicolons → enumerators → newlines → hard word window).

        Each returned piece is a synthetic
        :class:`~lexichunk.parsers.structure.ParsedClause` whose ``content`` is
        an exact slice of ``clause.content`` and whose offsets are absolute, so
        the pieces tile the original clause's span with no gap and no overlap.
        Pieces inherit the clause's ``level``, ``title``, ``parent_identifier``,
        ``parent_uid`` and ``document_section``; their ``identifier`` is
        suffixed ``".__part<n>"`` and their ``uid`` ``"#p<n>"``.

        Args:
            clause: The oversized :class:`~lexichunk.parsers.structure.ParsedClause`.
            prefix_chars: Length of the ancestor-header prefix that will be
                prepended to each piece's ``content``, counted against the
                token budget.

        Returns:
            List of synthetic :class:`~lexichunk.parsers.structure.ParsedClause`
            objects, or ``[clause]`` when no split point exists.
        """
        spans = self._split_text_cascading(
            clause.content,
            prefix_chars=prefix_chars,
            identifier=clause.identifier,
        )
        if len(spans) <= 1:
            return [clause]

        result: list[ParsedClause] = []
        for part_index, (start, end) in enumerate(spans):
            result.append(
                ParsedClause(
                    identifier=f"{clause.identifier}.__part{part_index}",
                    title=clause.title,
                    content=clause.content[start:end],
                    level=clause.level,
                    parent_identifier=clause.parent_identifier,
                    document_section=clause.document_section,
                    char_start=clause.char_start + start,
                    char_end=clause.char_start + end,
                    children=[],
                    uid=f"{clause.uid}#p{part_index}",
                    parent_uid=clause.parent_uid,
                )
            )
        return result

    # ------------------------------------------------------------------
    # Small-clause merging
    # ------------------------------------------------------------------

    def _group_tokens(self, group: list[ParsedClause]) -> int:
        """Approximate token count of a group's own text (no header prefix)."""
        return _approx_tokens(
            ''.join(c.content for c in group), self._chars_per_token
        )

    def _groups_can_merge(
        self,
        left: list[ParsedClause],
        right: list[ParsedClause],
    ) -> bool:
        """Whether the adjacent groups *left* and *right* may become one chunk.

        Permitted, and only these:

        * two pieces of the *same* oversized clause;
        * **(b)** ``right`` starts with a direct child of ``left``'s dominant
          clause (a section heading plus its first sub-clause);
        * **(a)** ``right`` starts with a sibling of ``left``'s dominant clause
          — same ``parent_uid`` and same ``document_section`` — that is not
          more senior than it, and they are not both container-level.

        Everything else is refused: there is no correct single-valued
        ``hierarchy_path`` / ``clause_type`` / ``document_section`` for a chunk
        spanning, say, Confidentiality and Termination, so a short chunk is the
        honest outcome.
        """
        left_dominant = self._dominant(left)
        right_first = right[0]

        # Two pieces of one oversized clause — always safe to recombine.
        if '#' in right_first.uid and self._origin_uid(
            left[-1]
        ) == self._origin_uid(right_first):
            return True

        # (b) A child folded into its own immediately-preceding parent group.
        if (
            right_first.parent_uid is not None
            and right_first.parent_uid == left_dominant.uid
        ):
            return True

        # (a) Successive siblings under the same parent and section.
        if (
            right_first.parent_uid == left_dominant.parent_uid
            and right_first.document_section == left_dominant.document_section
            and right_first.level >= left_dominant.level
            and not (
                self._is_container(left_dominant)
                and self._is_container(right_first)
            )
        ):
            return True

        return False

    def _merge_small_clauses(
        self,
        groups: list[list[ParsedClause]],
    ) -> list[list[ParsedClause]]:
        """Merge under-sized groups with a neighbour *where the hierarchy allows*.

        A group is a candidate for merging when it, or the group immediately
        before it, is below ``min_chunk_size``.  The merge happens only if
        :meth:`_groups_can_merge` permits it **and** the combined group still
        fits within ``max_chunk_size`` — fixing an under-run never creates an
        over-run.  Refused merges leave a short chunk in place, which is
        correct: ``min_chunk_size`` is a preference, hierarchy is a fact.

        Args:
            groups: List of clause groups (each group → one chunk).

        Returns:
            Merged list of groups; each group contains one or more
            :class:`~lexichunk.parsers.structure.ParsedClause` objects, in
            document order, with the dominant clause first.
        """
        if not groups:
            return groups

        merged: list[list[ParsedClause]] = []

        for group in groups:
            if merged:
                previous = merged[-1]
                if (
                    self._group_tokens(previous) < self._min_chunk_size
                    or self._group_tokens(group) < self._min_chunk_size
                ) and self._groups_can_merge(previous, group):
                    combined = previous + group
                    if self._group_tokens(combined) <= self._max_chunk_size:
                        merged[-1] = combined
                        continue
            merged.append(group)

        return merged

    # ------------------------------------------------------------------
    # Hard maximum enforcement
    # ------------------------------------------------------------------

    def _enforce_max(
        self,
        groups: list[list[ParsedClause]],
        clause_map: dict[str, ParsedClause],
    ) -> list[list[ParsedClause]]:
        """Re-split any group whose final ``content`` would exceed the cap.

        Runs after merging, so it also accounts for the ancestor-header prefix
        that :meth:`_group_to_chunk` prepends.  This is the safety net that
        makes ``max_chunk_size`` a contract rather than a hint.
        """
        result: list[list[ParsedClause]] = []
        for group in groups:
            result.extend(self._enforce_max_group(group, clause_map))
        return result

    def _enforce_max_group(
        self,
        group: list[ParsedClause],
        clause_map: dict[str, ParsedClause],
    ) -> list[list[ParsedClause]]:
        """Return *group*, or the pieces it must be broken into to fit the cap."""
        dominant = self._dominant(group)
        prefix_chars = len(self._content_prefix(dominant, clause_map))
        body_chars = sum(len(c.content) for c in group)

        if max(1, (prefix_chars + body_chars) // self._chars_per_token) <= (
            self._max_chunk_size
        ):
            return [group]

        if len(group) > 1:
            # Undo the merge and re-check each clause on its own terms (each
            # gets its own, generally shorter, ancestor prefix).
            result: list[list[ParsedClause]] = []
            for clause in group:
                result.extend(self._enforce_max_group([clause], clause_map))
            return result

        parts = self._split_oversized_clause(group[0], prefix_chars=prefix_chars)
        if len(parts) <= 1:
            return [group]
        return [[part] for part in parts]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _group_to_chunk(
        self,
        group: list[ParsedClause],
        index: int,
        clause_map: dict[str, ParsedClause],
        original_text: str,
    ) -> LegalChunk:
        """Convert a group of clauses into a single :class:`~lexichunk.models.LegalChunk`.

        The chunk body is the **exact slice** of *original_text* from the first
        clause's ``char_start`` to the last clause's own-text end (see
        :meth:`_own_end`) — never a reconstruction — so no separator the source
        does not contain is ever introduced and the span never reaches into a
        descendant's text.  ``content`` is that body with the ancestor headers
        prepended; ``original_header`` remains this chunk's *own* header line.

        Metadata (``hierarchy``, ``hierarchy_path``, ``document_section``,
        ``original_header``) is taken from the structurally dominant clause,
        not blindly from ``group[0]``.

        Args:
            group: Non-empty list of :class:`~lexichunk.parsers.structure.ParsedClause`
                objects to combine, in document order.
            index: Sequential chunk index (0-based).
            clause_map: Dict mapping ``uid`` →
                :class:`~lexichunk.parsers.structure.ParsedClause`, used for
                hierarchy path construction.
            original_text: The document text the clause offsets refer to.

        Returns:
            A fully populated :class:`~lexichunk.models.LegalChunk`.
        """
        first = group[0]
        last = group[-1]
        dominant = self._dominant(group)

        char_start = first.char_start
        char_end = self._own_end(last)

        if 0 <= char_start <= char_end <= len(original_text):
            raw_content = original_text[char_start:char_end]
        else:  # pragma: no cover — offsets out of sync with the text
            raw_content = ''.join(c.content for c in group)

        hierarchy = HierarchyNode(
            level=dominant.level,
            identifier=dominant.identifier,
            title=dominant.title,
            parent=dominant.parent_identifier,
        )

        hierarchy_path = self._build_hierarchy_path(dominant, clause_map)

        # Build original_header for this chunk's own clause.
        if dominant.level == -99:
            original_header = ""
        elif dominant.title:
            original_header = f"{dominant.identifier} {dominant.title}".strip()
        else:
            original_header = dominant.identifier.strip()

        # Prepend ancestor headers (root→leaf order) for retrieval context.
        content = self._content_prefix(dominant, clause_map) + raw_content

        return LegalChunk(
            content=content,
            index=index,
            hierarchy=hierarchy,
            hierarchy_path=hierarchy_path,
            document_section=dominant.document_section,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction=self._jurisdiction,
            cross_references=[],
            defined_terms_used=[],
            defined_terms_context={},
            context_header="",
            document_id=self._document_id,
            char_start=char_start,
            char_end=char_end,
            token_count=_approx_tokens(content, self._chars_per_token),
            original_header=original_header,
        )


__all__ = ["ClauseAwareChunker"]
