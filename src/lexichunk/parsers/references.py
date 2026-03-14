"""Cross-reference detector and resolver for legal documents."""

from __future__ import annotations

import logging
import re
import string
from typing import TYPE_CHECKING, Optional

from ..models import CrossReference, Jurisdiction

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..models import LegalChunk
from ..jurisdiction import get_patterns

# ---------------------------------------------------------------------------
# Extended patterns — applied on top of the jurisdiction cross_ref pattern
# ---------------------------------------------------------------------------

EXTENDED_PATTERNS: list[re.Pattern[str]] = [
    # "as defined in Section/Clause X", "pursuant to Clause 3.2(a)", etc.
    re.compile(
        r'\b(?:as defined in|pursuant to|subject to|in accordance with|'
        r'set forth in|described in|referred to in|specified in)\s+'
        r'(?:Section|Clause|Article|paragraph|Schedule|Exhibit)\s+'
        r'(\d+(?:\.\d+)*(?:\([a-z]+\))*(?:\([ivxlc]+\))*)',
        re.IGNORECASE,
    ),
    # "this Section X" / "this Clause X"
    re.compile(
        r'\bthis\s+(?:Section|Clause|Article)\s+(\d+(?:\.\d+)*(?:\([a-z]+\))*)',
        re.IGNORECASE,
    ),
]

# Prefix words used in cross-reference labels, needed when building variant
# lookup keys in the resolve step.
_LABEL_WORDS: tuple[str, ...] = (
    "section",
    "clause",
    "article",
    "paragraph",
    "schedule",
    "exhibit",
)

# Punctuation translation table for identifier normalisation.
# Preserve dots and parentheses — they are structurally meaningful in legal
# identifiers like "3.1(a)".  Only strip the remaining punctuation characters.
_STRIP_PUNCT = str.maketrans(
    "", "", string.punctuation.replace(".", "").replace("(", "").replace(")", "")
)

# Pattern matching trailing conjunctive identifiers after a detected ref.
# Captures sequences like ", 3.2, 3.3 and 3.4" or ", 3.2 or 3.3".
_CONJUNCTIVE_TAIL = re.compile(
    r'(?:\s*,\s*|\s+(?:and|or)\s+)'
    r'(\d+(?:\.\d+)*(?:\([a-z]+\))*(?:\([ivxlc]+\))*)',
    re.IGNORECASE,
)


class ReferenceDetector:
    """Detect and resolve cross-references in legal document text.

    Attributes:
        jurisdiction: The jurisdiction whose patterns are used for detection.
    """

    def __init__(self, jurisdiction: Jurisdiction | str) -> None:
        """Initialise the detector for a given jurisdiction.

        Args:
            jurisdiction: One of ``Jurisdiction.UK`` or ``Jurisdiction.US``,
                or a custom jurisdiction string.
        """
        self.jurisdiction: Jurisdiction | str = jurisdiction
        self._patterns: list[re.Pattern[str]] = [
            get_patterns(jurisdiction).cross_ref,
            *EXTENDED_PATTERNS,
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, text: str) -> list[CrossReference]:
        """Detect all cross-references in a piece of text.

        Each compiled pattern is applied to *text*.  For patterns that embed
        the identifier in capturing group 1 the full matched string is used as
        ``raw_text`` and group 1 as ``target_identifier``.  Results are
        deduplicated by normalised ``target_identifier`` — so that "Clause 3.2"
        and "subject to Clause 3.2" both pointing at identifier ``"3.2"``
        produce only one ``CrossReference`` (the first match wins).

        Args:
            text: Chunk or document text to scan.

        Returns:
            List of ``CrossReference`` objects with ``target_chunk_index=None``
            at this stage.
        """
        seen: set[str] = set()  # normalised target_identifiers already emitted
        refs: list[CrossReference] = []

        for pattern in self._patterns:
            for match in pattern.finditer(text):
                raw_text: str = match.group(0)
                # All our patterns store the identifier in group 1.
                # Fall back to the full match if the pattern has no groups
                # (defensive; should not happen with the patterns above).
                target_identifier: str = (
                    match.group(1) if match.lastindex and match.lastindex >= 1
                    else raw_text
                )
                norm = self._normalise_identifier(target_identifier)
                if norm and norm not in seen:
                    seen.add(norm)
                    refs.append(
                        CrossReference(
                            raw_text=raw_text,
                            target_identifier=target_identifier,
                        )
                    )

                # Scan for conjunctive tails: ", 3.2, 3.3 and 3.4"
                tail_pos = match.end()
                for tail_match in _CONJUNCTIVE_TAIL.finditer(text, tail_pos):
                    # Only accept tails contiguous with the previous match end.
                    if tail_match.start() != tail_pos:
                        break
                    tail_id = tail_match.group(1)
                    tail_norm = self._normalise_identifier(tail_id)
                    if tail_norm and tail_norm not in seen:
                        seen.add(tail_norm)
                        refs.append(
                            CrossReference(
                                raw_text=tail_match.group(0).strip(" ,"),
                                target_identifier=tail_id,
                            )
                        )
                    tail_pos = tail_match.end()

        logger.debug("Detected %d cross-references", len(refs))
        return refs

    def resolve(
        self,
        chunks_with_refs: list[tuple[list[CrossReference], str]],
    ) -> list[list[CrossReference]]:
        """Resolve cross-reference target identifiers to chunk indices.

        Second-pass resolution: builds a normalised identifier → chunk index
        map from the chunk identifiers supplied, then fills in
        ``target_chunk_index`` on every ``CrossReference`` whose
        ``target_identifier`` matches an entry in that map.

        For each chunk identifier the map stores:
        * The identifier itself (normalised).
        * Variants prefixed with each label word (``"clause 1.1"``,
          ``"section 1.1"``, …) so that a reference like ``"Section 1.1"``
          can resolve to a chunk whose own identifier is simply ``"1.1"``.

        Args:
            chunks_with_refs: List of ``(cross_references, chunk_identifier)``
                tuples, one per chunk, in document order (index 0 = first
                chunk).

        Returns:
            Updated list of cross-reference lists with ``target_chunk_index``
            filled in where a match was found.  Unresolvable references keep
            ``target_chunk_index=None``.
        """
        # Build normalised identifier → chunk index lookup and a parallel
        # mapping of chunk_index → raw identifier for partial matching.
        index_map: dict[str, int] = {}
        raw_identifiers: dict[int, str] = {}
        for chunk_index, (_refs, identifier) in enumerate(chunks_with_refs):
            if not identifier:
                continue
            raw_identifiers[chunk_index] = identifier
            norm = self._normalise_identifier(identifier)
            if norm and norm not in index_map:
                index_map[norm] = chunk_index
            # Also register label-prefixed variants so that bare numeric
            # identifiers (e.g. "1.1") are reachable via "clause 1.1" etc.
            for label in _LABEL_WORDS:
                variant = self._normalise_identifier(f"{label} {identifier}")
                if variant and variant not in index_map:
                    index_map[variant] = chunk_index

        # Second pass: resolve each cross-reference.
        resolved: list[list[CrossReference]] = []
        for _refs, _identifier in chunks_with_refs:
            updated: list[CrossReference] = []
            for ref in _refs:
                norm_target = self._normalise_identifier(ref.target_identifier)
                target_index: Optional[int] = index_map.get(norm_target)
                if target_index is None:
                    # Try prefixed variants of the target identifier as well.
                    for label in _LABEL_WORDS:
                        variant = self._normalise_identifier(
                            f"{label} {ref.target_identifier}"
                        )
                        target_index = index_map.get(variant)
                        if target_index is not None:
                            break
                if target_index is None:
                    # Partial matching fallback: find the first chunk whose
                    # raw identifier starts with the ref's identifier + ".".
                    # This lets a ref to "4" resolve to "4.1" (first child).
                    target_index = self._partial_match(
                        ref.target_identifier, raw_identifiers
                    )
                updated.append(
                    CrossReference(
                        raw_text=ref.raw_text,
                        target_identifier=ref.target_identifier,
                        target_chunk_index=target_index,
                    )
                )
            resolved.append(updated)

        return resolved

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_label(identifier: str) -> str:
        """Strip leading label words from an identifier string.

        E.g. ``"Article VII"`` → ``"VII"``, ``"Section 4.1"`` → ``"4.1"``,
        ``"4.1"`` → ``"4.1"`` (unchanged).
        """
        lower = identifier.lower().strip()
        for label in _LABEL_WORDS:
            prefix = label + " "
            if lower.startswith(prefix):
                return identifier.strip()[len(prefix):]
        return identifier.strip()

    def _partial_match(
        self,
        raw_target: str,
        raw_identifiers: dict[int, str],
    ) -> Optional[int]:
        """Find the first chunk whose identifier is a child of *raw_target*.

        A "child" identifier starts with the bare target followed by a dot.
        E.g. target ``"4"`` matches ``"4.1"`` but not ``"14"`` or ``"41"``.

        Args:
            raw_target: The raw target_identifier from the CrossReference.
            raw_identifiers: Mapping of chunk_index → raw identifier string
                for each chunk.

        Returns:
            The chunk index of the first matching child, or ``None``.
        """
        bare_target = self._strip_label(raw_target).lower()
        prefix = bare_target + "."

        best_index: Optional[int] = None
        for chunk_idx, raw_id in raw_identifiers.items():
            bare_id = self._strip_label(raw_id).lower()
            if bare_id.startswith(prefix) and len(bare_id) > len(bare_target):
                if best_index is None or chunk_idx < best_index:
                    best_index = chunk_idx

        return best_index

    def _normalise_identifier(self, raw: str) -> str:
        """Normalise an identifier for lookup (lowercase, strip punctuation).

        Whitespace is also collapsed so that ``"Section  1.1"`` and
        ``"Section 1.1"`` map to the same key.

        Args:
            raw: The raw identifier or label string.

        Returns:
            A normalised string suitable for use as a dictionary key.
        """
        lowered = raw.lower()
        stripped = lowered.translate(_STRIP_PUNCT)
        return " ".join(stripped.split())


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def detect_references(
    text: str,
    jurisdiction: Jurisdiction,
) -> list[CrossReference]:
    """Detect cross-references in a text chunk.

    Convenience wrapper that constructs a ``ReferenceDetector`` and calls
    ``detect`` in a single expression.

    Args:
        text: Chunk or document text to scan.
        jurisdiction: The jurisdiction whose patterns should be used.

    Returns:
        List of ``CrossReference`` objects with ``target_chunk_index=None``.
    """
    return ReferenceDetector(jurisdiction).detect(text)


def resolve_references(
    chunks: list[LegalChunk],
    jurisdiction: Jurisdiction | str,
) -> list[LegalChunk]:
    """Resolve cross-references across all chunks (second pass).

    Builds a ``ReferenceDetector``, collects ``(cross_references, identifier)``
    pairs from each chunk, calls ``resolve``, then mutates
    ``chunk.cross_references`` in-place with the resolved lists.

    Args:
        chunks: A list of ``LegalChunk`` instances.  The function accesses
            ``chunk.cross_references`` (``list[CrossReference]``) and
            ``chunk.hierarchy.identifier`` (``str``) on each element.
        jurisdiction: The jurisdiction whose patterns were used during
            detection.

    Returns:
        The same *chunks* list, with ``cross_references`` updated in-place on
        every element.
    """
    detector = ReferenceDetector(jurisdiction)
    pairs: list[tuple[list[CrossReference], str]] = [
        (c.cross_references, c.hierarchy.identifier) for c in chunks
    ]
    resolved = detector.resolve(pairs)

    total_refs = 0
    total_resolved = 0
    for chunk, refs in zip(chunks, resolved):
        chunk.cross_references = refs
        chunk.cross_ref_total = len(refs)
        chunk.cross_ref_resolved = sum(
            1 for r in refs if r.target_chunk_index is not None
        )
        total_refs += chunk.cross_ref_total
        total_resolved += chunk.cross_ref_resolved

    rate = total_resolved / total_refs if total_refs > 0 else 1.0
    logger.debug(
        "Cross-reference resolution: %d/%d resolved (%.1f%%)",
        total_resolved, total_refs, rate * 100,
    )

    return chunks
