"""Clause-aware chunking strategy — primary chunking logic.

This module provides :class:`ClauseAwareChunker`, which converts the flat list
of :class:`~lexichunk.parsers.structure.ParsedClause` objects produced by
:class:`~lexichunk.parsers.structure.StructureParser` into a list of
:class:`~lexichunk.models.LegalChunk` objects.  Chunks respect clause
boundaries: a clause is never split mid-way unless it exceeds the configured
token limit.
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Main chunker
# ---------------------------------------------------------------------------


class ClauseAwareChunker:
    """Chunk a legal document at clause boundaries.

    Operates on the flat list of :class:`~lexichunk.parsers.structure.ParsedClause`
    objects produced by :class:`~lexichunk.parsers.structure.StructureParser`.
    Respects clause boundaries — never splits mid-clause unless the clause
    exceeds ``max_chunk_size``.

    Args:
        jurisdiction: UK or US.
        max_chunk_size: Maximum chunk size in approximate tokens (default 512).
        min_chunk_size: Minimum chunk size; smaller clauses are merged with
            the next sibling (default 64).
        document_id: Optional document identifier attached to every chunk.
        chars_per_token: Number of characters per token for the approximation
            heuristic.  Defaults to 4.
    """

    def __init__(
        self,
        jurisdiction: Jurisdiction | str,
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

    def chunk(
        self,
        clauses: list[ParsedClause],
        original_text: str,
    ) -> list[LegalChunk]:
        """Convert parsed clauses into :class:`~lexichunk.models.LegalChunk` objects.

        Algorithm:

        1. For each :class:`~lexichunk.parsers.structure.ParsedClause`, compute
           its approximate token size.
        2. If ``size < min_chunk_size`` → mark for merging with the next sibling.
        3. If ``size > max_chunk_size`` → split at sub-clause boundaries.
        4. Otherwise → emit as a single :class:`~lexichunk.models.LegalChunk`.
        5. Assign sequential ``index`` values.
        6. Build ``hierarchy_path`` for each chunk.

        Preamble clauses (``level == -99``) that contain only whitespace are
        skipped.  Non-empty preambles are included as their own chunk.

        Args:
            clauses: Flat list from
                :meth:`~lexichunk.parsers.structure.StructureParser.parse`,
                in document order.
            original_text: The original document text (used for char offsets).

        Returns:
            List of :class:`~lexichunk.models.LegalChunk` objects in document
            order.
        """
        # Build a fast identifier → ParsedClause lookup for hierarchy walking.
        clause_map: dict[str, ParsedClause] = {c.identifier: c for c in clauses}

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

            tokens = _approx_tokens(clause.content, self._chars_per_token)

            if tokens > self._max_chunk_size:
                # Split into smaller pieces.
                sub_clauses = self._split_oversized_clause(clause, clauses)
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
        # Step 3: Convert each group into a LegalChunk.
        # ------------------------------------------------------------------
        legal_chunks: list[LegalChunk] = []

        for idx, group in enumerate(groups):
            chunk = self._group_to_chunk(group, idx, clause_map)
            legal_chunks.append(chunk)

        return legal_chunks

    # ------------------------------------------------------------------
    # Hierarchy path
    # ------------------------------------------------------------------

    def _build_hierarchy_path(
        self,
        clause: ParsedClause,
        clause_map: dict[str, ParsedClause],
    ) -> str:
        """Build a human-readable hierarchy path string.

        Walks up the ``parent_identifier`` chain using *clause_map* to collect
        ancestor nodes, reverses them, then joins with ``" > "``.

        If a node has a title it is formatted as ``"identifier — title"``
        (e.g. ``"Article VII — Indemnification"``); otherwise just the
        identifier is used.

        Args:
            clause: The clause to build the path for.
            clause_map: Dict mapping ``identifier`` → :class:`ParsedClause`.

        Returns:
            Hierarchy path string, e.g.
            ``"Article VII — Indemnification > Section 7.2 > (a)"``.
        """
        parts: list[str] = []
        current: Optional[ParsedClause] = clause

        while current is not None:
            if current.title:
                label = f"{current.identifier} \u2014 {current.title}"
            else:
                label = current.identifier
            parts.append(label)

            parent_id = current.parent_identifier
            if parent_id is None:
                break
            current = clause_map.get(parent_id)

        parts.reverse()
        return " > ".join(parts)

    # ------------------------------------------------------------------
    # Oversized clause splitting
    # ------------------------------------------------------------------

    def _split_oversized_clause(
        self,
        clause: ParsedClause,
        all_clauses: list[ParsedClause],
    ) -> list[ParsedClause]:
        """Split an oversized clause into smaller pieces.

        Strategy (in order):

        1. Find child clauses in *all_clauses* whose ``parent_identifier``
           equals ``clause.identifier``.  If children exist, return them as
           the split pieces — they are already separate
           :class:`~lexichunk.parsers.structure.ParsedClause` objects in the
           flat list.
        2. If no children (leaf clause), fall back to sentence-boundary
           splitting.  Sentences are accumulated until ``max_chunk_size`` is
           reached, then a synthetic
           :class:`~lexichunk.parsers.structure.ParsedClause` is emitted for
           each group.

        Args:
            clause: The oversized :class:`~lexichunk.parsers.structure.ParsedClause`.
            all_clauses: Full flat list (used to look up children).

        Returns:
            List of :class:`~lexichunk.parsers.structure.ParsedClause` objects
            (sub-clauses or sentence-split synthetics).
        """
        # Note: child clauses are already in the flat list and will be
        # processed by the main loop.  We only need to split this clause's
        # *own* content (which excludes children's content).

        # Sentence-boundary splitting.
        sentences = re.split(r'(?<=[.!?])\s+', clause.content)

        result: list[ParsedClause] = []
        current_sentences: list[str] = []
        current_tokens = 0
        part_index = 0

        # Compute each sentence's start offset within the original document by
        # scanning through the clause content.  This avoids the broken arithmetic
        # that previously produced negative char_start values.
        content = clause.content
        sentence_offsets: list[int] = []  # document-absolute offset per sentence
        scan_pos = 0
        for sentence in sentences:
            loc = content.find(sentence, scan_pos)
            if loc < 0:
                loc = scan_pos  # fallback: use current scan position
            sentence_offsets.append(clause.char_start + loc)
            scan_pos = loc + len(sentence)

        def _flush(
            sentences_buf: list[str], start: int, end: int, part_idx: int,
        ) -> ParsedClause:
            text = ' '.join(sentences_buf)
            return ParsedClause(
                identifier=f"{clause.identifier}.__part{part_idx}",
                title=clause.title,
                content=text,
                level=clause.level,
                parent_identifier=clause.parent_identifier,
                document_section=clause.document_section,
                char_start=start,
                char_end=end,
                children=[],
            )

        group_start = clause.char_start

        for i, sentence in enumerate(sentences):
            sentence_tokens = _approx_tokens(sentence, self._chars_per_token)

            if current_sentences and (current_tokens + sentence_tokens > self._max_chunk_size):
                # Flush: char_end is the start of the current sentence.
                group_end = sentence_offsets[i]
                result.append(_flush(current_sentences, group_start, group_end, part_index))
                part_index += 1
                current_sentences = []
                current_tokens = 0
                group_start = sentence_offsets[i]

            current_sentences.append(sentence)
            current_tokens += sentence_tokens

        # Flush any remaining sentences.
        if current_sentences:
            result.append(
                _flush(current_sentences, group_start, clause.char_end, part_index)
            )

        # If splitting yielded nothing useful, return the clause as-is.
        return result if result else [clause]

    # ------------------------------------------------------------------
    # Small-clause merging
    # ------------------------------------------------------------------

    def _merge_small_clauses(
        self,
        groups: list[list[ParsedClause]],
    ) -> list[list[ParsedClause]]:
        """Merge groups that fall below ``min_chunk_size`` with their neighbours.

        Groups are lists of :class:`~lexichunk.parsers.structure.ParsedClause`
        that will be combined into one chunk.  A small group is merged
        *forward* into the next group when possible; if it is the last group
        it is merged *backward* into the previous group.

        Args:
            groups: List of clause groups (each group → one chunk).

        Returns:
            Merged list of groups; each group will contain one or more
            :class:`~lexichunk.parsers.structure.ParsedClause` objects.
        """
        if not groups:
            return groups

        def _group_tokens(group: list[ParsedClause]) -> int:
            return _approx_tokens('\n'.join(c.content for c in group), self._chars_per_token)

        merged: list[list[ParsedClause]] = []

        i = 0
        while i < len(groups):
            group = groups[i]
            tokens = _group_tokens(group)

            if tokens < self._min_chunk_size:
                if i + 1 < len(groups):
                    # Merge forward: combine with the next group.
                    groups[i + 1] = group + groups[i + 1]
                    i += 1
                    continue
                elif merged:
                    # Last group: merge backward into the previous one.
                    merged[-1].extend(group)
                    i += 1
                    continue
                # Only one group total and it's small — keep it as-is.

            merged.append(group)
            i += 1

        return merged

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _group_to_chunk(
        self,
        group: list[ParsedClause],
        index: int,
        clause_map: dict[str, ParsedClause],
    ) -> LegalChunk:
        """Convert a group of clauses into a single :class:`~lexichunk.models.LegalChunk`.

        For a group spanning multiple merged clauses, their ``content`` strings
        are concatenated with a newline separator.  ``char_start`` is taken
        from the first clause and ``char_end`` from the last clause.
        ``document_section`` is taken from the first clause (merged clauses are
        expected to be siblings sharing the same section).

        Args:
            group: Non-empty list of :class:`~lexichunk.parsers.structure.ParsedClause`
                objects to combine.
            index: Sequential chunk index (0-based).
            clause_map: Dict mapping ``identifier`` →
                :class:`~lexichunk.parsers.structure.ParsedClause`, used for
                hierarchy path construction.

        Returns:
            A fully populated :class:`~lexichunk.models.LegalChunk`.
        """
        first = group[0]
        last = group[-1]

        raw_content = '\n'.join(c.content for c in group)

        hierarchy = HierarchyNode(
            level=first.level,
            identifier=first.identifier,
            title=first.title,
            parent=first.parent_identifier,
        )

        hierarchy_path = self._build_hierarchy_path(first, clause_map)

        # Build original_header for this chunk's own clause.
        if first.level == -99:
            original_header = ""
        elif first.title:
            original_header = f"{first.identifier} {first.title}".strip()
        else:
            original_header = first.identifier.strip()

        # Collect ancestor headers (root→leaf order) and prepend to content.
        ancestor_headers = self._collect_ancestor_headers(first, clause_map)
        if ancestor_headers:
            content = '\n'.join(ancestor_headers) + '\n' + raw_content
        else:
            content = raw_content

        return LegalChunk(
            content=content,
            index=index,
            hierarchy=hierarchy,
            hierarchy_path=hierarchy_path,
            document_section=first.document_section,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction=self._jurisdiction,
            cross_references=[],
            defined_terms_used=[],
            defined_terms_context={},
            context_header="",
            document_id=self._document_id,
            char_start=first.char_start,
            char_end=last.char_end,
            token_count=_approx_tokens(content, self._chars_per_token),
            original_header=original_header,
        )


    def _collect_ancestor_headers(
        self,
        clause: ParsedClause,
        clause_map: dict[str, ParsedClause],
    ) -> list[str]:
        """Collect ancestor header lines in root→leaf order (excluding *clause* itself).

        Walks up the ``parent_identifier`` chain, collects each ancestor's
        header as ``"identifier title"`` (or just identifier if no title),
        then reverses to produce root-first ordering.

        Preamble clauses (``level == -99``) return an empty list.

        Args:
            clause: The clause whose ancestors to collect.
            clause_map: Dict mapping ``identifier`` → :class:`ParsedClause`.

        Returns:
            List of header strings in root→leaf order.
        """
        if clause.level == -99:
            return []

        ancestors: list[str] = []
        parent_id = clause.parent_identifier

        while parent_id is not None:
            parent = clause_map.get(parent_id)
            if parent is None:
                break
            if parent.title:
                ancestors.append(f"{parent.identifier} {parent.title}".strip())
            else:
                ancestors.append(parent.identifier.strip())
            parent_id = parent.parent_identifier

        ancestors.reverse()
        return ancestors


__all__ = ["ClauseAwareChunker"]
