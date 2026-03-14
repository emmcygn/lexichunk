"""Clause type classifier — keyword-based heuristics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..models import ClauseType, DocumentSection

if TYPE_CHECKING:
    from ..models import LegalChunk

# ---------------------------------------------------------------------------
# Signal table
# ---------------------------------------------------------------------------

CLAUSE_SIGNALS: dict[ClauseType, list[str]] = {
    ClauseType.DEFINITIONS: [
        "means",
        "shall mean",
        "has the meaning",
        "defined as",
        "is defined",
        "definition",
        "interpretation",
        "defined terms",
    ],
    ClauseType.INDEMNIFICATION: [
        "indemnify",
        "indemnification",
        "hold harmless",
        "indemnified party",
        "indemnifying party",
        "losses and damages",
        "defend and indemnify",
    ],
    ClauseType.TERMINATION: [
        "terminate",
        "termination",
        "expiry",
        "expiration",
        "upon termination",
        "right to terminate",
        "notice of termination",
    ],
    ClauseType.CONFIDENTIALITY: [
        "confidential",
        "confidentiality",
        "non-disclosure",
        "nda",
        "proprietary information",
        "trade secret",
    ],
    ClauseType.LIMITATION_OF_LIABILITY: [
        "limit of liability",
        "aggregate liability",
        "shall not exceed",
        "in no event",
        "limitation of liability",
        "cap on liability",
        "maximum liability",
    ],
    ClauseType.GOVERNING_LAW: [
        "governed by",
        "governing law",
        "jurisdiction",
        "courts of",
        "choice of law",
        "applicable law",
    ],
    ClauseType.FORCE_MAJEURE: [
        "force majeure",
        "act of god",
        "beyond reasonable control",
        "unforeseeable circumstances",
        "natural disaster",
    ],
    ClauseType.PAYMENT: [
        "payment",
        "invoice",
        "fee",
        "fees",
        "price",
        "consideration",
        "payable",
        "billing",
        "charge",
    ],
    ClauseType.DATA_PROTECTION: [
        "personal data",
        "data protection",
        "gdpr",
        "privacy",
        "data controller",
        "data processor",
        "data subject",
        "uk gdpr",
        "ccpa",
        "personal information",
    ],
    ClauseType.REPRESENTATIONS: [
        "represents",
        "representation",
        "represents and warrants",
        "representation and warranty",
    ],
    ClauseType.WARRANTIES: [
        "warrants",
        "warranty",
        "warranted",
        "warrant that",
        "no warranty",
        "as is",
    ],
    ClauseType.INTELLECTUAL_PROPERTY: [
        "intellectual property",
        "ip rights",
        "licence",
        "license",
        "copyright",
        "patent",
        "trade mark",
        "trademark",
    ],
    ClauseType.ASSIGNMENT: [
        "assign",
        "assignment",
        "transfer",
        "novation",
        "not assign",
        "without consent",
    ],
    ClauseType.NOTICES: [
        "notices",
        "notice shall be",
        "written notice",
        "notice in writing",
        "notice to",
        "notification",
    ],
    ClauseType.ENTIRE_AGREEMENT: [
        "entire agreement",
        "whole agreement",
        "supersedes",
        "prior agreements",
        "complete agreement",
    ],
    ClauseType.SEVERABILITY: [
        "severability",
        "invalid or unenforceable",
        "severable",
        "severed",
        "remaining provisions",
    ],
    ClauseType.DISPUTE_RESOLUTION: [
        "arbitration",
        "mediation",
        "dispute resolution",
        "arbitrator",
        "adr",
        "alternative dispute",
    ],
    ClauseType.AMENDMENT: [
        "amendment",
        "variation",
        "modification",
        "amend",
        "vary",
        "in writing signed",
    ],
    ClauseType.COVENANTS: [
        "covenant",
        "covenants",
        "undertake",
        "undertakes",
        "shall not",
    ],
    ClauseType.CONDITIONS: [
        "condition precedent",
        "conditions to closing",
        "condition to",
        "closing condition",
        "satisfaction of conditions",
    ],
    ClauseType.PREAMBLE: [],  # classified via DocumentSection, not keywords
    ClauseType.RECITALS: ["whereas", "recitals", "background"],
    ClauseType.BOILERPLATE: [
        "counterparts",
        "waiver",
        "further assurance",
        "costs and expenses",
        "no partnership",
    ],
    ClauseType.ACCEPTABLE_USE: [
        "acceptable use",
        "prohibited content",
        "prohibited use",
        "prohibited activities",
    ],
    ClauseType.USER_RESTRICTIONS: [
        "restrictions on use",
        "reverse engineer",
        "decompile",
        "disassemble",
        "derivative works",
        "sublicense",
    ],
    ClauseType.ACCOUNT_SECURITY: [
        "account security",
        "login credentials",
        "multi-factor authentication",
        "unauthorized access",
        "password",
        "account credentials",
    ],
    ClauseType.UNKNOWN: [],
}

# ---------------------------------------------------------------------------
# DocumentSection → ClauseType direct mappings
# ---------------------------------------------------------------------------

_SECTION_TO_CLAUSE_TYPE: dict[DocumentSection, ClauseType] = {
    DocumentSection.DEFINITIONS: ClauseType.DEFINITIONS,
    DocumentSection.PREAMBLE: ClauseType.PREAMBLE,
    DocumentSection.RECITALS: ClauseType.RECITALS,
}

# Bonus points awarded when the hierarchy path contains a clause-type hint.
_PATH_BONUS: float = 3.0


# ---------------------------------------------------------------------------
# Internal scoring helper
# ---------------------------------------------------------------------------


def _score(
    content_lower: str,
    path_lower: str,
    signals: dict[ClauseType, list[str]] | None = None,
) -> dict[ClauseType, float]:
    """Compute per-ClauseType keyword scores for lowercased inputs.

    Each signal match in *content_lower* contributes a weight equal to the
    number of words in that signal (so multi-word phrases outweigh single
    words). When the clause type's canonical name appears in *path_lower*
    an additional bonus of ``_PATH_BONUS`` points is added.

    Args:
        content_lower: Lowercased chunk content to score.
        path_lower: Lowercased hierarchy path string to score.
        signals: Signal table to use.  Defaults to ``CLAUSE_SIGNALS``.

    Returns:
        A mapping from ClauseType to its accumulated score; only clause
        types with a score greater than zero are included.
    """
    effective_signals = signals if signals is not None else CLAUSE_SIGNALS
    scores: dict[ClauseType, float] = {}

    for clause_type, signal_list in effective_signals.items():
        score = 0.0

        for signal in signal_list:
            if signal in content_lower:
                # Longer phrases receive higher weight than single words.
                score += len(signal.split())

        # Bonus when the hierarchy path explicitly names the clause type.
        type_name = clause_type.value.replace("_", " ")
        if type_name in path_lower:
            score += _PATH_BONUS

        if score > 0:
            scores[clause_type] = score

    return scores


# ---------------------------------------------------------------------------
# Public classification function
# ---------------------------------------------------------------------------


def _merge_signals(
    extra_signals: dict[ClauseType, list[str]] | None,
) -> dict[ClauseType, list[str]] | None:
    """Merge extra signals into the base ``CLAUSE_SIGNALS`` table.

    Returns ``None`` when there are no extras (so ``_score`` uses its
    default), or a new merged dict when extras are provided.
    """
    if not extra_signals:
        return None
    merged = {ct: list(sigs) for ct, sigs in CLAUSE_SIGNALS.items()}
    for ct, extras in extra_signals.items():
        if ct in merged:
            merged[ct] = merged[ct] + extras
        else:
            merged[ct] = list(extras)
    return merged


def classify_clause_type(
    content: str,
    hierarchy_path: str = "",
    document_section: Optional[DocumentSection] = None,
    extra_signals: dict[ClauseType, list[str]] | None = None,
) -> ClauseType:
    """Classify a chunk of legal text into a ClauseType.

    Uses keyword scoring: each signal match in the lowercased content adds
    weight proportional to the number of words in that signal (phrase-length
    bonus) to the matching ClauseType's score.  Multi-word phrases therefore
    score higher than single words for the same match.  The ClauseType with
    the highest score wins; ties are broken by the insertion order of
    ``CLAUSE_SIGNALS``.

    The following structural overrides are applied **before** keyword
    scoring and take unconditional precedence:

    * ``document_section == DocumentSection.DEFINITIONS``
      → returns :attr:`ClauseType.DEFINITIONS`
    * ``document_section == DocumentSection.PREAMBLE``
      → returns :attr:`ClauseType.PREAMBLE`
    * ``document_section == DocumentSection.RECITALS``
      → returns :attr:`ClauseType.RECITALS`

    Additionally, if *hierarchy_path* contains a clause-type name (e.g.
    ``"indemnification"``) it contributes ``_PATH_BONUS`` extra points to
    that type during scoring.

    Args:
        content: The chunk text to classify.
        hierarchy_path: The hierarchy path string
            (e.g. ``"Article VII > Section 7.2"``).
        document_section: The document section this chunk belongs to, or
            ``None`` when not known.
        extra_signals: Additional clause-type keywords to merge with the
            built-in ``CLAUSE_SIGNALS`` table before scoring.

    Returns:
        The most likely :class:`ClauseType`, or
        :attr:`ClauseType.UNKNOWN` if no signals matched.
    """
    # ---- structural overrides (fast path) ---------------------------------
    if document_section is not None:
        direct = _SECTION_TO_CLAUSE_TYPE.get(document_section)
        if direct is not None:
            return direct

    # ---- keyword scoring --------------------------------------------------
    content_lower = content.lower()
    path_lower = hierarchy_path.lower()

    merged = _merge_signals(extra_signals)
    scores = _score(content_lower, path_lower, signals=merged)

    if not scores:
        return ClauseType.UNKNOWN

    # Select the clause type with the highest score.  Because Python dicts
    # preserve insertion order (3.7+) and CLAUSE_SIGNALS is an ordered dict
    # literal, ties are broken by the order clauses appear in CLAUSE_SIGNALS.
    best: ClauseType = max(scores, key=lambda ct: scores[ct])
    return best


# ---------------------------------------------------------------------------
# Optional classifier wrapper
# ---------------------------------------------------------------------------


class ClauseTypeClassifier:
    """Clause type classifier using keyword heuristics.

    Can be instantiated for repeated use; internally delegates every
    classification decision to :func:`classify_clause_type`.

    Args:
        extra_signals: Optional dict mapping :class:`ClauseType` to
            additional keyword strings.  These are merged with the built-in
            ``CLAUSE_SIGNALS`` table before scoring.

    Example::

        classifier = ClauseTypeClassifier()
        clause_type = classifier.classify("The Supplier shall indemnify …")
        chunks = classifier.classify_all(chunks)
    """

    def __init__(
        self,
        extra_signals: dict[ClauseType, list[str]] | None = None,
    ) -> None:
        self._extra_signals = extra_signals

    def classify(
        self,
        content: str,
        hierarchy_path: str = "",
        document_section: Optional[DocumentSection] = None,
    ) -> ClauseType:
        """Classify a single chunk of legal text.

        Args:
            content: The chunk text to classify.
            hierarchy_path: Optional hierarchy path string for bonus scoring.
            document_section: Optional document section for structural
                override logic.

        Returns:
            The most likely :class:`ClauseType` for the given text.
        """
        return classify_clause_type(
            content, hierarchy_path, document_section,
            extra_signals=self._extra_signals,
        )

    def classify_all(self, chunks: list[LegalChunk]) -> list[LegalChunk]:
        """Classify ``clause_type`` on a list of LegalChunk objects in-place.

        Iterates over *chunks*, calling :meth:`classify` for each item using
        ``chunk.content``, ``chunk.hierarchy_path``, and
        ``chunk.document_section``.  The result is written back to
        ``chunk.clause_type``.

        Args:
            chunks: List of :class:`~lexichunk.models.LegalChunk` objects.
                Each must expose ``.content``, ``.hierarchy_path``, and
                ``.document_section`` attributes.

        Returns:
            The same list with ``clause_type`` populated on every chunk.
        """
        for chunk in chunks:
            chunk.clause_type = self.classify(
                chunk.content,
                chunk.hierarchy_path,
                chunk.document_section,
            )
        return chunks
