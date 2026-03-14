"""Performance benchmarks for lexichunk.

Run with: pytest benchmarks/ --benchmark-enable
"""

from __future__ import annotations

import pytest

from lexichunk import LegalChunker


# ---------------------------------------------------------------------------
# chunk() per fixture doc
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_chunk_uk_service_agreement(benchmark, uk_service_agreement: str) -> None:  # type: ignore[no-untyped-def]
    chunker = LegalChunker(jurisdiction="uk")
    benchmark(chunker.chunk, uk_service_agreement)


@pytest.mark.benchmark
def test_chunk_us_msa(benchmark, us_msa: str) -> None:  # type: ignore[no-untyped-def]
    chunker = LegalChunker(jurisdiction="us")
    benchmark(chunker.chunk, us_msa)


@pytest.mark.benchmark
def test_chunk_uk_terms_conditions(benchmark, uk_terms_conditions: str) -> None:  # type: ignore[no-untyped-def]
    chunker = LegalChunker(jurisdiction="uk", doc_type="terms_conditions")
    benchmark(chunker.chunk, uk_terms_conditions)


@pytest.mark.benchmark
def test_chunk_us_terms_of_service(benchmark, us_terms_of_service: str) -> None:  # type: ignore[no-untyped-def]
    chunker = LegalChunker(jurisdiction="us", doc_type="terms_conditions")
    benchmark(chunker.chunk, us_terms_of_service)


# ---------------------------------------------------------------------------
# chunk_batch() serial vs parallel
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_batch_serial(benchmark, uk_service_agreement: str, us_msa: str) -> None:  # type: ignore[no-untyped-def]
    chunker = LegalChunker(jurisdiction="uk")
    texts = [uk_service_agreement, us_msa, uk_service_agreement]
    benchmark(chunker.chunk_batch, texts, workers=1)


@pytest.mark.benchmark
def test_batch_parallel(benchmark, uk_service_agreement: str, us_msa: str) -> None:  # type: ignore[no-untyped-def]
    chunker = LegalChunker(jurisdiction="uk")
    texts = [uk_service_agreement, us_msa, uk_service_agreement]
    benchmark(chunker.chunk_batch, texts, workers=2)


# ---------------------------------------------------------------------------
# Definition cache hit vs miss
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_definition_cache_miss(benchmark, uk_service_agreement: str) -> None:  # type: ignore[no-untyped-def]
    """First call — cache miss, full extraction."""

    def run() -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunker.chunk(uk_service_agreement)

    benchmark(run)


@pytest.mark.benchmark
def test_definition_cache_hit(benchmark, uk_service_agreement: str) -> None:  # type: ignore[no-untyped-def]
    """Second call — cache hit, skips extraction."""
    chunker = LegalChunker(jurisdiction="uk")
    chunker.chunk(uk_service_agreement)  # prime the cache
    benchmark(chunker.chunk, uk_service_agreement)
