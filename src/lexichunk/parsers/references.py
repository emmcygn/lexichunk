"""Cross-reference detector and resolver for legal documents."""

from __future__ import annotations

import logging
import re
import string
from typing import TYPE_CHECKING, Optional

from ..models import CrossReference, Jurisdiction

logger = logging.getLogger(__name__)

# Roman numeral pattern for normalisation.  Anchored and restricted to
# structurally valid numerals (I–III, IV, V–VIII, IX, X–XXX, XL, L, etc.)
# to avoid false positives on English words like "Civil" or "Vivid".
_ROMAN_RE = re.compile(
    r'^(M{0,3})(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$',
)
_ROMAN_MAP = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}


def _roman_to_arabic(s: str) -> str:
    """Convert a Roman numeral token to its Arabic string, or return as-is.

    Only converts strings that are structurally valid Roman numerals (e.g.
    ``"VII"``, ``"XIV"``).  English words composed of Roman-numeral characters
    (``"Civil"``, ``"Vivid"``) are returned unchanged.
    """
    if not s:
        return s
    upper = s.upper()
    if not _ROMAN_RE.match(upper):
        return s
    result, prev = 0, 0
    for ch in reversed(upper):
        val = _ROMAN_MAP.get(ch, 0)
        if val == 0:
            return s  # not a valid Roman numeral
        if val < prev:
            result -= val
        else:
            result += val
        prev = val
    if result == 0:
        return s  # empty match → not a numeral
    return str(result)

if TYPE_CHECKING:
    from ..models import LegalChunk
from ..jurisdiction import get_patterns

# ---------------------------------------------------------------------------
# Extended patterns — applied on top of the jurisdiction cross_ref pattern
# ---------------------------------------------------------------------------

EXTENDED_PATTERNS: list[re.Pattern[str]] = [
    # "as defined in Section/Clause X", "pursuant to Clause 3.2(a)", etc.
    # The identifier group carries ``(?:\(\d+\))*`` so that EU pinpoint
    # citations ("in accordance with Article 6(1)(f)") capture the *same*
    # identifier as the jurisdiction cross_ref pattern and are deduplicated
    # against it, instead of emitting a coarser duplicate reference (D18).
    re.compile(
        r'\b(?:as defined in|pursuant to|subject to|in accordance with|'
        r'set forth in|described in|referred to in|specified in)\s+'
        r'(?:Section|Clause|Article|paragraph|Schedule|Exhibit|Annexe?|'
        r'Chapter|Recital)\s+'
        r'(\d+(?:\.\d+)*(?:\(\d+\))*(?:\([a-z]+\))*(?:\([ivxlc]+\))*)',
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
    "chapter",
    "annex",
    "recital",
)

# The canonical reference kind used when a reference carries only a number.
DEFAULT_KIND = "clause"

# Label word (singular, lower-case) → canonical kind.  ``annexe`` is the
# British spelling of ``annex``; both normalise to ``annex``.
_KIND_ALIASES: dict[str, str] = {
    "annexe": "annex",
    "sub-clause": "clause",
    "subclause": "clause",
    "sub-paragraph": "paragraph",
    "subparagraph": "paragraph",
}

# Kinds whose target *must* carry the same label word on the chunk side.  A
# reference to "Annex I" may never fall back to a bare numbered paragraph "1"
# and "Schedule 1" may never resolve to "Clause 1" (D19).
_CONTAINER_KINDS: frozenset[str] = frozenset(
    {"schedule", "exhibit", "annex", "chapter", "recital"}
)

# Ordinary, interchangeable kinds.  Legal drafting uses clause/section/
# paragraph for the same construct, and a chunk identifier is very often a
# bare number ("3.1") with no label at all.
_ORDINARY_KINDS: tuple[str, ...] = ("clause", "section", "paragraph")

# Regex used to read the label word out of a matched reference's raw text.
# The *last* label word before the identifier wins, so "as defined in
# Schedule 2" yields "schedule", not a stray earlier word.
_KIND_IN_RAW = re.compile(
    r'\b(sub-?clauses?|sub-?paragraphs?|clauses?|sections?|articles?|'
    r'paragraphs?|schedules?|exhibits?|chapters?|annexe?s?|recitals?)\b',
    re.IGNORECASE,
)

# Regex used to split a *chunk* identifier ("Schedule 1", "Article VII") into
# its label word and its number.  Anchored at the start of the identifier.
_KIND_IN_IDENTIFIER = re.compile(
    r'^\s*(clause|section|article|paragraph|schedule|exhibit|chapter|'
    r'annexe?|recital)s?\b[\s.:\-]*',
    re.IGNORECASE,
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

# Pattern matching a range tail after a detected ref: "3 to 7",
# "2.1 through 2.4", "3.2–3.4" (en-dash), "3.2—3.4" (em-dash).
# Only integer-tailed identifiers participate in a range, so the upper bound
# is a plain dotted number.
_RANGE_TAIL = re.compile(
    r'(?:\s+(?:to|through|thru)\s+|\s*[–—-]\s*)'
    r'(\d+(?:\.\d+)*)',
    re.IGNORECASE,
)

# Upper bound on how many references a single range may expand to.  Guards
# against pathological input like "Sections 1 to 100000", and bounds the blast
# radius of any range the heuristics below still get wrong.
_MAX_RANGE_EXPANSION = 20

# The explicit range words.  When one of these joins the two bounds the phrase
# is unambiguously a range and no further checks apply.
_EXPLICIT_RANGE_RE = re.compile(r'\s+(?:to|through|thru)\s+', re.IGNORECASE)

# Words that, immediately after the upper bound, show the second number was a
# quantity or a date rather than a clause identifier: "clause 12 - 30 days",
# "Clause 9 - 15 January 2025".
_QUANTITY_FOLLOWERS = frozenset({
    'day', 'days', 'week', 'weeks', 'month', 'months', 'year', 'years',
    'hour', 'hours', 'minute', 'minutes', 'second', 'seconds',
    'business', 'working', 'calendar', 'copy', 'copies', 'counterpart',
    'counterparts', 'percent', 'per', 'cent',
    'january', 'february', 'march', 'april', 'may', 'june', 'july',
    'august', 'september', 'october', 'november', 'december',
})

_FIRST_WORD_RE = re.compile(r'[A-Za-z]+')

# Number of alphabetic words inside an enclosing parenthesis that make it a
# prose aside rather than a bare citation.
_PAREN_PROSE_WORDS = 3


def _paren_encloses_prose(text: str, start: int, end: int) -> bool:
    """Return ``True`` when ``text[start:end]`` sits inside a prose aside.

    A parenthesis that also carries several words of running text is an aside
    ("(see clause 12 - which we discuss below - 30)"), and a dash inside one
    is punctuation, not a range operator.

    Args:
        text: The text being scanned.
        start: Start offset of the candidate range phrase.
        end: End offset of the candidate range phrase.

    Returns:
        ``True`` when the phrase is inside such a parenthesis.
    """
    open_index = text.rfind('(', 0, start)
    if open_index == -1 or ')' in text[open_index:start]:
        return False
    close_index = text.find(')', end)
    if close_index == -1:
        return False
    inner = text[open_index + 1:close_index]
    words = [word for word in re.findall(r'[A-Za-z]+', inner)]
    return len(words) >= _PAREN_PROSE_WORDS


def _is_range_operator(
    text: str,
    head_start: int,
    head_raw: str,
    range_match: re.Match[str],
) -> bool:
    """Return ``True`` when a matched range tail really joins two identifiers.

    ``_RANGE_TAIL`` accepts both the explicit form (``"3 to 7"``) and the bare
    dash (``"3 - 7"``).  The bare dash is also ordinary legal punctuation — a
    parenthetical aside — so treating every one as a range operator fabricated
    large numbers of plausible-looking references:

    * ``"The notice period in clause 12 - 30 days - shall apply"`` produced 19
      references, clauses 12 through 30;
    * ``"Refer to Schedule 1 - 5 copies must be provided"`` produced 5
      schedule references, where the ``5`` is a copy count;
    * ``"Clause 9 - 15 January 2025 is the deadline"`` produced 7 references
      from a date.

    The explicit ``to``/``through``/``thru`` form is always accepted.  A bare
    dash is accepted only when the citation is written the way a real range is
    written — a plural label (``"clauses 3 - 5"``) or a tight, unspaced dash
    (``"Clauses 3.2-3.4"``) — the upper bound is not followed by a quantity or
    month word, and the phrase is not inside a parenthesised prose aside.
    Same-shape and ascending-order checks live in
    :meth:`ReferenceDetector._expand_range` and still apply on top of this.

    Args:
        text: The full text being scanned.
        head_start: Offset where the head reference match began.
        head_raw: The head match's own text (e.g. ``"clauses 3"``).
        range_match: The matched range tail.

    Returns:
        ``True`` to treat the tail as a range operator.
    """
    joiner = range_match.group(0)[: range_match.start(1) - range_match.start()]
    if _EXPLICIT_RANGE_RE.fullmatch(joiner):
        return True

    # A range needs a label to range over; a bare number head ("12 - 30") is
    # never enough evidence.
    label = _FIRST_WORD_RE.search(head_raw)
    if label is None:
        return False

    plural_label = label.group(0).lower().endswith('s')
    tight_dash = not any(character.isspace() for character in joiner)
    if not (plural_label or tight_dash):
        return False

    following = _FIRST_WORD_RE.search(text, range_match.end())
    if (
        following is not None
        and following.start() <= range_match.end() + 1
        and following.group(0).lower() in _QUANTITY_FOLLOWERS
    ):
        return False

    return not _paren_encloses_prose(text, head_start, range_match.end())


def normalise_kind(label: str) -> str:
    """Return the canonical, lower-case kind for a reference label word.

    Plural forms are singularised (``"Schedules"`` → ``"schedule"``) and
    spelling variants are folded (``"Annexe"`` → ``"annex"``).  An
    unrecognised or empty label yields :data:`DEFAULT_KIND`.

    Args:
        label: A raw label word as it appears in the document.

    Returns:
        One of the canonical kind strings, or ``"clause"``.
    """
    word = label.strip().lower()
    if not word:
        return DEFAULT_KIND
    if word in _KIND_ALIASES:
        return _KIND_ALIASES[word]
    # Singularise: "schedules" → "schedule", "annexes" → "annexe" → "annex".
    if word.endswith("s") and word[:-1] in _KIND_ALIASES:
        return _KIND_ALIASES[word[:-1]]
    if word.endswith("es") and word[:-2] in _LABEL_WORDS:
        return word[:-2]
    if word.endswith("s") and word[:-1] in _LABEL_WORDS:
        return word[:-1]
    if word in _LABEL_WORDS:
        return word
    return DEFAULT_KIND


def _dedup_family(kind: str) -> str:
    """Return the deduplication family for a reference kind.

    Clause/section/paragraph are interchangeable labels for the same construct
    and resolve to the same chunk, so "Clause 5" and "Section 5" in one chunk
    are a single reference.  Containers and articles keep their own family, so
    "Schedule 1" and "Clause 1" remain two distinct references.

    Args:
        kind: A canonical reference kind.

    Returns:
        The family key used for deduplication.
    """
    return DEFAULT_KIND if kind in _ORDINARY_KINDS else kind


def _candidate_kinds(kind: str) -> tuple[str, ...]:
    """Return the chunk kinds a reference of *kind* may resolve to, in order.

    The returned tuple is a *priority* list: the first entry that has any
    candidate chunk wins, so an ``Article VII`` reference prefers a chunk
    identified as ``"Article VII"`` over a bare ``"VII"``.

    Container kinds (schedule/exhibit/annex/chapter/recital) are strict — they
    only ever match a chunk carrying the same label word, which is what stops
    ``Annex I`` resolving to numbered paragraph ``1``.

    Args:
        kind: The canonical kind of the reference.

    Returns:
        Tuple of chunk-side kind keys, most preferred first.  ``""`` denotes a
        chunk whose identifier carries no label word at all.
    """
    if kind in _CONTAINER_KINDS:
        return (kind,)
    if kind == "article":
        return ("article", "")
    # Ordinary kinds: exact label, then bare identifiers, then the sibling
    # ordinary labels, and finally article-labelled chunks (a US document
    # numbers its top level "Article VII" but drafters write "Clause VII").
    others = tuple(k for k in _ORDINARY_KINDS if k != kind)
    return (kind, "", *others, "article")


class ReferenceDetector:
    """Detect and resolve cross-references in legal document text.

    Attributes:
        jurisdiction: The jurisdiction whose patterns are used for detection.
    """

    def __init__(self, jurisdiction: Jurisdiction | str) -> None:
        """Initialise the detector for a given jurisdiction.

        Args:
            jurisdiction: ``"uk"``, ``"us"`` or ``"eu"`` (or a
                :class:`~lexichunk.models.Jurisdiction` enum value), or the key of a
                custom jurisdiction registered via :func:`register_jurisdiction`.
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
        ``raw_text`` and group 1 as ``target_identifier``.  The label word in
        the matched text determines ``target_kind`` (``"clause"`` when the
        match carries only a number).

        Conjunctive tails (``", 3.2, 3.3 and 3.4"``) and ranges
        (``"3 to 7"``, ``"2.1 through 2.4"``, ``"3.2–3.4"``) immediately
        following a match are expanded into individual references that inherit
        the head match's kind.  Every reference produced from a range carries
        the *full* range phrase as its ``raw_text``.

        Results are deduplicated by ``(kind, normalised identifier)`` — so
        "Clause 3.2" and "subject to Clause 3.2" produce a single reference,
        while "Schedule 1" and "Clause 1" produce two.

        Args:
            text: Chunk or document text to scan.

        Returns:
            List of ``CrossReference`` objects with ``target_chunk_index=None``
            at this stage.
        """
        seen: set[tuple[str, str]] = set()  # (kind family, normalised number)
        refs: list[CrossReference] = []

        def _emit(raw_text: str, identifier: str, kind: str) -> None:
            identifier = identifier.strip().rstrip(".")
            norm = self._normalise_number(identifier)
            if not norm:
                return
            key = (_dedup_family(kind), norm)
            if key in seen:
                return
            seen.add(key)
            refs.append(
                CrossReference(
                    raw_text=raw_text,
                    target_identifier=identifier,
                    target_kind=kind,
                )
            )

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
                kind = self._kind_from_raw(raw_text)

                tail_pos = match.end()

                # Ranges: "clauses 3 to 7", "Sections 2.1 through 2.4".
                range_match = _RANGE_TAIL.match(text, tail_pos)
                if range_match is not None and not _is_range_operator(
                    text, match.start(), raw_text, range_match
                ):
                    range_match = None
                if range_match is not None:
                    expanded = self._expand_range(
                        target_identifier, range_match.group(1)
                    )
                    if expanded:
                        phrase = text[match.start():range_match.end()]
                        for member in expanded:
                            _emit(phrase, member, kind)
                        tail_pos = range_match.end()
                    else:
                        _emit(raw_text, target_identifier, kind)
                else:
                    _emit(raw_text, target_identifier, kind)

                # Scan for conjunctive tails: ", 3.2, 3.3 and 3.4"
                for tail_match in _CONJUNCTIVE_TAIL.finditer(text, tail_pos):
                    # Only accept tails contiguous with the previous match end.
                    if tail_match.start() != tail_pos:
                        break
                    _emit(tail_match.group(0).strip(" ,"), tail_match.group(1), kind)
                    tail_pos = tail_match.end()

        logger.debug("Detected %d cross-references", len(refs))
        return refs

    def resolve(
        self,
        chunks_with_refs: list[tuple[list[CrossReference], str]],
        *,
        sections: Optional[list[str]] = None,
        ancestors: Optional[list[str]] = None,
        extra_identifiers: Optional[dict[int, list[str]]] = None,
        continuation_indices: Optional[set[int]] = None,
    ) -> list[list[CrossReference]]:
        """Resolve cross-reference target identifiers to chunk indices.

        Second-pass resolution.  A ``(kind, number) → [chunk index, …]`` map is
        built from the chunk identifiers supplied; every candidate is recorded,
        not just the first.  A reference resolves when exactly one compatible
        candidate exists, or when the ambiguity can be broken by the referring
        chunk's ``document_section`` or top-level ancestor.  **An ambiguity that
        cannot be broken leaves ``target_chunk_index=None``** — a wrong pointer
        is worse than an unresolved one.

        Lookup proceeds in three stages, each restricted to kinds compatible
        with the reference (see :func:`_candidate_kinds`):

        1. Exact ``(kind, number)`` match.
        2. Child match — a reference to ``"4"`` resolves to ``"4.1"``, served
           from a prefix index built once per call rather than a linear scan.
        3. Parent match — a pinpoint citation such as ``"6(1)(f)"`` falls back
           to ``"6(1)"`` and then to ``"6"``.

        Args:
            chunks_with_refs: List of ``(cross_references, chunk_identifier)``
                tuples, one per chunk, in document order (index 0 = first
                chunk).
            sections: Optional per-chunk ``document_section`` labels, parallel
                to *chunks_with_refs*, used to break ambiguities.
            ancestors: Optional per-chunk top-level ancestor labels, parallel
                to *chunks_with_refs*, used to break ambiguities that
                *sections* could not.
            extra_identifiers: Optional mapping of chunk index → additional
                identifiers that chunk absorbed (e.g. a merged chunk that
                swallowed sub-clause ``"4.1"``), so references to the absorbed
                identifier still resolve.
            continuation_indices: Optional set of chunk indices that continue a
                clause which *starts* in an earlier chunk (the tail pieces of
                an over-sized clause).  Every piece carries the clause's own
                identifier, so only the first one is registered as a lookup
                candidate and a reference to that clause resolves to where the
                clause begins.  These chunks' own references are still
                resolved.

        Returns:
            Updated list of cross-reference lists with ``target_chunk_index``
            filled in where an unambiguous match was found.  Unresolvable or
            ambiguous references keep ``target_chunk_index=None``.
        """
        # (kind, normalised number) → candidate chunk indices, in order.
        index_map: dict[tuple[str, str], list[int]] = {}
        # (kind, normalised ancestor number) → descendant chunk indices.
        prefix_map: dict[tuple[str, str], list[int]] = {}

        def _add(
            bucket: dict[tuple[str, str], list[int]],
            key: tuple[str, str],
            chunk_index: int,
        ) -> None:
            # One chunk contributes at most one candidate per key.  A merged
            # chunk registers both its own identifier and the identifiers it
            # absorbed, and those overlap (the dominant clause's identifier is
            # in both lists) — registering it twice would make the chunk look
            # ambiguous with itself and resolve to nothing.
            candidates = bucket.setdefault(key, [])
            if not candidates or candidates[-1] != chunk_index:
                candidates.append(chunk_index)

        def _register(chunk_index: int, identifier: str) -> None:
            if not identifier:
                return
            kind, number = self._split_identifier(identifier)
            if not number:
                return
            _add(index_map, (kind, number), chunk_index)
            for ancestor in self._ancestor_numbers(number):
                _add(prefix_map, (kind, ancestor), chunk_index)

        extras = extra_identifiers or {}
        continuations = continuation_indices or set()
        for chunk_index, (_refs, identifier) in enumerate(chunks_with_refs):
            if chunk_index in continuations:
                continue
            # Own identifier and absorbed identifiers are registered together
            # so every entry for one chunk lands consecutively, which is what
            # makes the cheap duplicate check in ``_add`` exact.
            _register(chunk_index, identifier)
            for absorbed in extras.get(chunk_index, ()):
                _register(chunk_index, absorbed)

        # Second pass: resolve each cross-reference.
        resolved: list[list[CrossReference]] = []
        for chunk_index, (_refs, _identifier) in enumerate(chunks_with_refs):
            section = sections[chunk_index] if sections else None
            ancestor = ancestors[chunk_index] if ancestors else None
            updated: list[CrossReference] = []
            for ref in _refs:
                reference_kind = self._reference_kind(ref)
                target_index = self._lookup(
                    ref,
                    index_map,
                    prefix_map,
                    sections,
                    ancestors,
                    section,
                    ancestor,
                    chunk_index,
                )
                updated.append(
                    CrossReference(
                        raw_text=ref.raw_text,
                        target_identifier=ref.target_identifier,
                        target_chunk_index=target_index,
                        target_kind=reference_kind,
                    )
                )
            resolved.append(updated)

        return resolved

    # ------------------------------------------------------------------
    # Private helpers — lookup
    # ------------------------------------------------------------------

    def _reference_kind(self, ref: CrossReference) -> str:
        kind_from_id, _number = self._split_identifier(ref.target_identifier)
        if kind_from_id:
            return kind_from_id
        reference_kind = ref.target_kind or DEFAULT_KIND
        raw_kind = self._kind_from_raw(ref.raw_text)
        if reference_kind == DEFAULT_KIND and raw_kind not in _ORDINARY_KINDS:
            return raw_kind
        return reference_kind

    def _lookup(
        self,
        ref: CrossReference,
        index_map: dict[tuple[str, str], list[int]],
        prefix_map: dict[tuple[str, str], list[int]],
        sections: Optional[list[str]],
        ancestors: Optional[list[str]],
        section: Optional[str],
        ancestor: Optional[str],
        self_index: Optional[int] = None,
    ) -> Optional[int]:
        """Resolve a single reference against the pre-built lookup maps.

        Args:
            ref: The reference to resolve.
            index_map: Exact ``(kind, number)`` → candidate indices.
            prefix_map: ``(kind, ancestor number)`` → descendant indices.
            sections: Per-chunk section labels, or ``None``.
            ancestors: Per-chunk top-level ancestor labels, or ``None``.
            section: The referring chunk's section label, or ``None``.
            ancestor: The referring chunk's top-level ancestor, or ``None``.
            self_index: Index of the referring chunk, used as the final
                tie-break when a chunk names its own identifier.

        Returns:
            The resolved chunk index, or ``None`` when unresolvable or
            ambiguous.
        """
        kind_from_id, number = self._split_identifier(ref.target_identifier)
        if not number:
            return None
        kinds = _candidate_kinds(kind_from_id or self._reference_kind(ref))

        # 1. Exact match, honouring kind priority.
        for kind in kinds:
            candidates = index_map.get((kind, number))
            if candidates:
                return self._disambiguate(
                    candidates, sections, ancestors, section, ancestor,
                    self_index,
                )

        # 2. Child match — "4" resolves to its first child "4.1".
        for kind in kinds:
            candidates = prefix_map.get((kind, number))
            if candidates:
                # Historical behaviour: the lowest chunk index wins.
                return min(candidates)

        # 3. Parent match — "6(1)(f)" falls back to "6(1)", then "6".
        for parent in self._ancestor_numbers(number):
            for kind in kinds:
                candidates = index_map.get((kind, parent))
                if candidates:
                    return self._disambiguate(
                        candidates, sections, ancestors, section, ancestor,
                        self_index,
                    )

        return None

    @staticmethod
    def _disambiguate(
        candidates: list[int],
        sections: Optional[list[str]],
        ancestors: Optional[list[str]],
        section: Optional[str],
        ancestor: Optional[str],
        self_index: Optional[int] = None,
    ) -> Optional[int]:
        """Pick a single chunk index from *candidates*, or ``None``.

        A single candidate resolves immediately.  Otherwise the candidates are
        narrowed to those sharing the referring chunk's ``document_section``
        and then to those sharing its top-level ancestor.  Should more than one
        candidate still survive, a candidate that *is* the referring chunk wins
        — a chunk that names its own identifier ("the obligations in paragraph
        1 above") is talking about itself.  If nothing breaks the tie, the
        reference is left unresolved.

        Args:
            candidates: Candidate chunk indices, in document order.
            sections: Per-chunk section labels, or ``None``.
            ancestors: Per-chunk top-level ancestor labels, or ``None``.
            section: The referring chunk's section label, or ``None``.
            ancestor: The referring chunk's top-level ancestor, or ``None``.
            self_index: Index of the referring chunk, or ``None``.

        Returns:
            The single surviving candidate, or ``None`` when still ambiguous.
        """
        if len(candidates) == 1:
            return candidates[0]

        pool = candidates
        if sections is not None and section is not None:
            narrowed = [i for i in pool if sections[i] == section]
            if narrowed:
                pool = narrowed
                if len(pool) == 1:
                    return pool[0]
        if ancestors is not None and ancestor is not None:
            narrowed = [i for i in pool if ancestors[i] == ancestor]
            if narrowed:
                pool = narrowed
                if len(pool) == 1:
                    return pool[0]

        if self_index is not None and self_index in pool:
            return self_index

        # Genuinely ambiguous — a wrong pointer is worse than no pointer.
        return None

    # ------------------------------------------------------------------
    # Private helpers — identifiers
    # ------------------------------------------------------------------

    @staticmethod
    def _kind_from_raw(raw_text: str) -> str:
        """Return the canonical kind implied by a matched reference's text.

        The *last* label word in the match wins, so "as defined in Schedule 2"
        yields ``"schedule"``.  Text with no label word yields
        :data:`DEFAULT_KIND`.

        Args:
            raw_text: The full matched reference text.

        Returns:
            A canonical kind string.
        """
        last: Optional[str] = None
        for m in _KIND_IN_RAW.finditer(raw_text):
            last = m.group(1)
        return normalise_kind(last) if last else DEFAULT_KIND

    def _split_identifier(
        self, identifier: str, default_kind: str = ""
    ) -> tuple[str, str]:
        """Split an identifier into its ``(kind, normalised number)`` pair.

        ``"Schedule 1"`` → ``("schedule", "1")``; ``"Article VII"`` →
        ``("article", "7")``; ``"4.1"`` → ``(default_kind, "4.1")``.  The
        Roman→Arabic conversion is applied to the *number* only, never to the
        label word.

        Args:
            identifier: A chunk identifier or reference target identifier.
            default_kind: Kind returned when the identifier carries no label
                word.  Defaults to ``""`` (a bare, label-less chunk).

        Returns:
            ``(kind, normalised_number)``.
        """
        text = identifier.strip()
        m = _KIND_IN_IDENTIFIER.match(text)
        if m is None:
            return default_kind, self._normalise_number(text)
        return normalise_kind(m.group(1)), self._normalise_number(text[m.end():])

    @staticmethod
    def _normalise_number(raw: str) -> str:
        """Normalise the numeric part of an identifier for lookup.

        Lower-cases, strips punctuation other than dots and parentheses,
        removes a trailing period (US ``"Schedule 1."`` house style bakes one
        into the identifier), collapses whitespace, and converts a bare Roman
        numeral to Arabic so ``"Article VII"`` and ``"Article 7"`` share a key.

        Args:
            raw: The number portion of an identifier.

        Returns:
            A normalised string suitable for use as part of a dictionary key.
        """
        lowered = raw.lower().strip()
        stripped = lowered.translate(_STRIP_PUNCT)
        collapsed = " ".join(stripped.split())
        collapsed = collapsed.rstrip(".")
        if not collapsed:
            return ""
        return _roman_to_arabic(collapsed)

    @staticmethod
    def _ancestor_numbers(number: str) -> list[str]:
        """Return the ancestor identifiers of *number*, nearest first.

        ``"6(1)(f)"`` → ``["6(1)", "6"]``; ``"3.2.1"`` → ``["3.2", "3"]``;
        ``"4"`` → ``[]``.

        Args:
            number: A normalised identifier number.

        Returns:
            List of ancestor numbers, closest ancestor first.
        """
        ancestors: list[str] = []
        current = number
        while True:
            if current.endswith(")") and "(" in current:
                parent = current[:current.rindex("(")]
            elif "." in current:
                parent = current.rsplit(".", 1)[0]
            else:
                break
            parent = parent.rstrip(".")
            if not parent or parent == current:
                break
            ancestors.append(parent)
            current = parent
        return ancestors

    @staticmethod
    def _expand_range(start: str, end: str) -> list[str]:
        """Expand an inclusive identifier range into its members.

        Only integer ranges are expanded.  For dotted identifiers the *last*
        component is expanded and the shared prefix must match, so
        ``"2.1"``–``"2.4"`` yields ``2.1, 2.2, 2.3, 2.4`` while
        ``"2.1"``–``"3.4"`` is rejected.  Zero padding is preserved when both
        bounds share it, so ``"3.01"``–``"3.04"`` yields ``3.01 … 3.04`` and
        not ``3.1 … 3.4``.

        Args:
            start: Lower-bound identifier (the head match's identifier).
            end: Upper-bound identifier from the range tail.

        Returns:
            The expanded members including both bounds, or ``[]`` when the
            pair is not a well-formed, in-order, reasonably sized range.
        """
        start_parts = start.strip().rstrip(".").split(".")
        end_parts = end.strip().rstrip(".").split(".")
        if len(start_parts) != len(end_parts):
            return []
        if start_parts[:-1] != end_parts[:-1]:
            return []
        if not start_parts[-1].isdigit() or not end_parts[-1].isdigit():
            return []
        if not all(p.isdigit() for p in start_parts[:-1]):
            return []
        low, high = int(start_parts[-1]), int(end_parts[-1])
        if high <= low or (high - low) >= _MAX_RANGE_EXPANSION:
            return []
        prefix = ".".join(start_parts[:-1])
        if prefix:
            prefix += "."
        # Preserve zero padding ("3.01"–"3.04" must not become "3.1"–"3.4").
        width = (
            len(start_parts[-1])
            if len(start_parts[-1]) == len(end_parts[-1])
            else 0
        )
        return [f"{prefix}{n:0{width}d}" for n in range(low, high + 1)]


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
    *,
    extra_identifiers: Optional[dict[int, list[str]]] = None,
    continuation_indices: Optional[set[int]] = None,
) -> list[LegalChunk]:
    """Resolve cross-references across all chunks (second pass).

    Builds a ``ReferenceDetector``, collects ``(cross_references, identifier)``
    pairs from each chunk together with each chunk's ``document_section`` and
    top-level ancestor (used to break identifier ambiguities), calls
    ``resolve``, then mutates ``chunk.cross_references`` in-place with the
    resolved lists.

    Args:
        chunks: A list of ``LegalChunk`` instances.  The function accesses
            ``chunk.cross_references`` (``list[CrossReference]``),
            ``chunk.hierarchy.identifier`` (``str``),
            ``chunk.document_section`` and ``chunk.hierarchy_path`` on each
            element.
        jurisdiction: The jurisdiction whose patterns were used during
            detection.
        extra_identifiers: Optional mapping of chunk index → extra identifiers
            that chunk absorbed during merging, so a merged chunk that
            swallowed sub-clause ``"4.1"`` still resolves ``"clause 4.1"``.
        continuation_indices: Optional set of chunk indices that continue a
            clause starting in an earlier chunk, so ``"clause 1.1"`` resolves
            to the piece where clause 1.1 begins rather than going ambiguous
            across its pieces.

    Returns:
        The same *chunks* list, with ``cross_references`` updated in-place on
        every element.
    """
    detector = ReferenceDetector(jurisdiction)
    pairs: list[tuple[list[CrossReference], str]] = [
        (c.cross_references, c.hierarchy.identifier) for c in chunks
    ]
    sections = [str(c.document_section) for c in chunks]
    ancestors = [c.hierarchy_path.split(" > ")[0].strip() for c in chunks]
    resolved = detector.resolve(
        pairs,
        sections=sections,
        ancestors=ancestors,
        extra_identifiers=extra_identifiers,
        continuation_indices=continuation_indices,
    )

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
