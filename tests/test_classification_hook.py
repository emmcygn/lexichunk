"""Low-confidence classification hook.

The hook is the seam for an LLM (or any bespoke model) that a caller only
wants to pay for on the chunks the keyword scorer was unsure about.  These
tests pin the contract: who gets offered, what a return value does, what
``classification_source`` says afterwards, and why an unpicklable hook is
rejected before ``chunk_batch(workers>1)`` starts a pool.
"""

from __future__ import annotations

import pickle

import pytest

from lexichunk import LegalChunker
from lexichunk.enrichment.clause_type import ClassificationResult
from lexichunk.exceptions import ConfigurationError
from lexichunk.models import ClauseType, LegalChunk

_DOCUMENT = (
    "1. Definitions\n"
    "In this agreement the following terms have the meanings given below.\n"
    "\n"
    "2. Miscellany\n"
    "The parties note the following items for completeness of the record.\n"
    "\n"
    "3. Governing Law\n"
    "This agreement is governed by the laws of England and Wales and the "
    "parties submit to the exclusive jurisdiction of the English courts.\n"
)


# ---------------------------------------------------------------------------
# Module-level hooks (picklable, so they also work under workers>1)
# ---------------------------------------------------------------------------


def always_services(
    chunk: LegalChunk, result: ClassificationResult
) -> ClauseType | None:
    """Claim every low-confidence chunk as SERVICES."""
    return ClauseType.SERVICES


def never_decides(
    chunk: LegalChunk, result: ClassificationResult
) -> ClauseType | None:
    """Decline every chunk, leaving the keyword verdict in place."""
    return None


def returns_a_string(
    chunk: LegalChunk, result: ClassificationResult
) -> ClauseType | None:
    """A hook that ignores the contract and returns a bare string."""
    return "services"  # type: ignore[return-value]


class _Recorder:
    """A picklable callable that records what it was offered."""

    def __init__(self) -> None:
        self.seen: list[tuple[int, float, ClauseType]] = []

    def __call__(
        self, chunk: LegalChunk, result: ClassificationResult
    ) -> ClauseType | None:
        self.seen.append((chunk.index, result.confidence, result.clause_type))
        return None


# ---------------------------------------------------------------------------
# Default behaviour
# ---------------------------------------------------------------------------


def test_no_hook_leaves_source_as_keyword() -> None:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    for chunk in chunker.chunk(_DOCUMENT):
        assert chunk.classification_source == "keyword"


def test_hook_returning_none_changes_nothing() -> None:
    baseline = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk(_DOCUMENT)
    hooked = LegalChunker(
        jurisdiction="uk", min_chunk_size=0, classification_hook=never_decides
    ).chunk(_DOCUMENT)
    assert [c.to_dict() for c in baseline] == [c.to_dict() for c in hooked]


# ---------------------------------------------------------------------------
# Who gets offered
# ---------------------------------------------------------------------------


def test_only_chunks_below_the_threshold_are_offered() -> None:
    recorder = _Recorder()
    chunker = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=recorder,
        classification_hook_threshold=0.5,
    )
    chunks = chunker.chunk(_DOCUMENT)
    offered = {index for index, _, _ in recorder.seen}
    expected = {c.index for c in chunks if c.classification_confidence < 0.5}
    assert offered == expected
    for _, confidence, _ in recorder.seen:
        assert confidence < 0.5


def test_threshold_zero_never_fires() -> None:
    recorder = _Recorder()
    LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=recorder,
        classification_hook_threshold=0.0,
    ).chunk(_DOCUMENT)
    assert recorder.seen == []


def test_threshold_one_offers_every_chunk_below_certainty() -> None:
    recorder = _Recorder()
    chunker = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=recorder,
        classification_hook_threshold=1.0,
    )
    chunks = chunker.chunk(_DOCUMENT)
    expected = {c.index for c in chunks if c.classification_confidence < 1.0}
    assert {index for index, _, _ in recorder.seen} == expected


def test_hook_receives_the_full_classification_result() -> None:
    seen: list[ClassificationResult] = []

    def capture(
        chunk: LegalChunk, result: ClassificationResult
    ) -> ClauseType | None:
        seen.append(result)
        return None

    LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=capture,
        classification_hook_threshold=1.0,
    ).chunk(_DOCUMENT)
    assert seen
    for result in seen:
        assert isinstance(result, ClassificationResult)
        assert 0.0 <= result.confidence <= 1.0
        # The per-type scores mapping is exactly what the chunk cannot carry.
        assert hasattr(result, "scores")


# ---------------------------------------------------------------------------
# What a returned ClauseType does
# ---------------------------------------------------------------------------


def test_returned_type_is_applied_and_sourced() -> None:
    chunker = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=always_services,
        classification_hook_threshold=0.5,
    )
    chunks = chunker.chunk(_DOCUMENT)
    overridden = [c for c in chunks if c.classification_source == "hook"]
    assert overridden, "expected at least one low-confidence chunk"
    for chunk in overridden:
        assert chunk.clause_type is ClauseType.SERVICES
    # Chunks the scorer was confident about are untouched by the hook.
    baseline = {
        c.index: c.clause_type
        for c in LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk(_DOCUMENT)
    }
    for chunk in chunks:
        if chunk.classification_source == "keyword":
            assert chunk.clause_type is baseline[chunk.index]


def test_confidence_is_not_rewritten_by_the_hook() -> None:
    baseline = {
        c.index: c.classification_confidence
        for c in LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk(_DOCUMENT)
    }
    hooked = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=always_services,
        classification_hook_threshold=0.5,
    ).chunk(_DOCUMENT)
    for chunk in hooked:
        assert chunk.classification_confidence == baseline[chunk.index]


def test_classification_source_round_trips_through_to_dict() -> None:
    chunker = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=always_services,
        classification_hook_threshold=1.0,
    )
    chunk = chunker.chunk(_DOCUMENT)[0]
    payload = chunk.to_dict()
    assert payload["classification_source"] == chunk.classification_source
    assert (
        LegalChunk.from_dict(payload).classification_source
        == chunk.classification_source
    )


def test_hook_runs_before_context_enrichment() -> None:
    """Stage 5 must see the hook's clause type, not the keyword one."""

    def to_insurance(
        chunk: LegalChunk, result: ClassificationResult
    ) -> ClauseType | None:
        return ClauseType.INSURANCE

    chunker = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=to_insurance,
        classification_hook_threshold=1.0,
    )
    for chunk in chunker.chunk(_DOCUMENT):
        if chunk.classification_source == "hook" and chunk.context_header:
            assert "insurance" in chunk.context_header.lower()
            break
    else:  # pragma: no cover - the fixture always produces one
        pytest.fail("no hooked chunk carried a context header")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_non_callable_hook_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="must be callable"):
        LegalChunker(jurisdiction="uk", classification_hook="nope")  # type: ignore[arg-type]


@pytest.mark.parametrize("threshold", [-0.1, 1.1, 2.0])
def test_threshold_out_of_range_is_rejected(threshold: float) -> None:
    with pytest.raises(ConfigurationError, match=r"must be in \[0.0, 1.0\]"):
        LegalChunker(jurisdiction="uk", classification_hook_threshold=threshold)


@pytest.mark.parametrize("threshold", ["0.5", None, True])
def test_threshold_of_the_wrong_type_is_rejected(threshold: object) -> None:
    with pytest.raises(ConfigurationError, match="must be a float"):
        LegalChunker(
            jurisdiction="uk",
            classification_hook_threshold=threshold,  # type: ignore[arg-type]
        )


def test_hook_returning_a_non_clause_type_is_rejected() -> None:
    chunker = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=returns_a_string,
        classification_hook_threshold=1.0,
    )
    with pytest.raises(ConfigurationError, match="must return a ClauseType"):
        chunker.chunk(_DOCUMENT)


# ---------------------------------------------------------------------------
# chunk_batch
# ---------------------------------------------------------------------------


def test_serial_batch_accepts_an_unpicklable_hook() -> None:
    result = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=lambda chunk, res: ClauseType.SERVICES,
        classification_hook_threshold=1.0,
    ).chunk_batch([_DOCUMENT, _DOCUMENT], workers=1)
    assert result.error_count == 0
    assert result.total_chunks > 0


def test_parallel_batch_rejects_an_unpicklable_hook_up_front() -> None:
    chunker = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=lambda chunk, res: ClauseType.SERVICES,
    )
    with pytest.raises(ConfigurationError, match="cannot be pickled"):
        chunker.chunk_batch([_DOCUMENT] * 4, workers=2)


def test_the_rejection_names_the_fix() -> None:
    chunker = LegalChunker(
        jurisdiction="uk", classification_hook=lambda chunk, res: None
    )
    with pytest.raises(ConfigurationError) as excinfo:
        chunker.chunk_batch([_DOCUMENT] * 4, workers=2)
    message = str(excinfo.value)
    assert "module-level function" in message
    assert "workers=1" in message


def test_a_picklable_hook_is_accepted_for_parallel_batches() -> None:
    """The guard must not reject a hook that would actually have worked."""
    from lexichunk.chunker import _require_picklable_hook

    _require_picklable_hook(always_services)
    assert pickle.loads(pickle.dumps(always_services)) is always_services


def test_the_hook_is_carried_in_the_worker_config() -> None:
    from lexichunk.chunker import _chunk_single, _ChunkerConfig

    config = _ChunkerConfig(
        jurisdiction=LegalChunker(jurisdiction="uk").jurisdiction,  # type: ignore[arg-type]
        doc_type="contract",
        max_chunk_size=512,
        min_chunk_size=0,
        include_definitions=True,
        include_context_header=True,
        document_id=None,
        chars_per_token=4,
        extra_abbreviations=None,
        extra_clause_signals=None,
        enable_definition_cache=True,
        max_cache_size=128,
        classification_hook=always_services,
        classification_hook_threshold=1.0,
    )
    # Round-trip the config exactly as ProcessPoolExecutor would.
    revived = pickle.loads(pickle.dumps(config))
    chunks = _chunk_single(revived, _DOCUMENT, None)
    assert any(c.classification_source == "hook" for c in chunks)


def test_worker_config_validates_its_threshold() -> None:
    from lexichunk.chunker import _ChunkerConfig

    with pytest.raises(ConfigurationError, match=r"must be in \[0.0, 1.0\]"):
        _ChunkerConfig(
            jurisdiction=LegalChunker(jurisdiction="uk").jurisdiction,  # type: ignore[arg-type]
            doc_type="contract",
            max_chunk_size=512,
            min_chunk_size=0,
            include_definitions=True,
            include_context_header=True,
            document_id=None,
            chars_per_token=4,
            extra_abbreviations=None,
            extra_clause_signals=None,
            enable_definition_cache=True,
            max_cache_size=128,
            classification_hook=None,
            classification_hook_threshold=3.0,
        )


# ---------------------------------------------------------------------------
# classify_all_detailed
# ---------------------------------------------------------------------------


def test_classify_all_detailed_matches_classify_all() -> None:
    from lexichunk.enrichment.clause_type import ClauseTypeClassifier

    chunker = LegalChunker(
        jurisdiction="uk", min_chunk_size=0, include_context_header=False
    )
    chunks = chunker.chunk(_DOCUMENT)
    classifier = ClauseTypeClassifier()
    results = classifier.classify_all_detailed(chunks)
    assert len(results) == len(chunks)
    for chunk, result in zip(chunks, results):
        assert chunk.clause_type is result.clause_type
        assert chunk.classification_confidence == result.confidence
        assert chunk.secondary_clause_type is result.secondary_clause_type
