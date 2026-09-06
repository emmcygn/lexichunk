"""``include_ancestor_headers=False`` makes ``content`` exactly the span.

By default ``chunk.content`` is the chunk's span with its ancestor headings
prepended, so ``content != sanitized[char_start:char_end]``. That default is
deliberate — a retrieved ``(b)`` that does not say which clause it belongs to
is much less useful — but it is a trap for anything that trusts the offsets
and the text together: highlighting a passage in the source, mapping an
answer span back to a page, de-duplicating against the original. A CUAD
evaluation measured the prefix on 51% of chunks (1,244 of 2,422) across 60
real contracts, and on 43% of contracts at least one chunk carried it.

``include_context_header`` does not turn this off — that flag governs the
separate ``context_header`` field. ``include_ancestor_headers=False`` does,
and these tests pin the exact-equality invariant it promises.
"""

from __future__ import annotations

import pytest

from lexichunk import LegalChunker

from ._snapshot_support import FIXTURE_CONFIGS, load_fixture

_SIZE_GRID = [(512, 64), (128, 0), (2048, 0)]


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
@pytest.mark.parametrize("max_size,min_size", _SIZE_GRID)
def test_content_is_exactly_the_span(
    fixture_name: str,
    jurisdiction: str,
    doc_type: str,
    max_size: int,
    min_size: int,
) -> None:
    text = load_fixture(fixture_name)
    sanitised = LegalChunker.sanitize(text)
    chunker = LegalChunker(
        jurisdiction=jurisdiction,
        doc_type=doc_type,
        max_chunk_size=max_size,
        min_chunk_size=min_size,
        include_ancestor_headers=False,
    )
    chunks = chunker.chunk(text)
    assert chunks, f"{fixture_name} produced no chunks"
    for chunk in chunks:
        assert chunk.content == sanitised[chunk.char_start : chunk.char_end], (
            f"{fixture_name}[{max_size}/{min_size}] chunk {chunk.index} "
            f"({chunk.hierarchy_path}) is not its own span"
        )
        assert chunk.original_header == ""


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
def test_the_default_still_prepends_ancestor_headers(
    fixture_name: str, jurisdiction: str, doc_type: str
) -> None:
    """The default is unchanged, and the span is always a suffix of content."""
    text = load_fixture(fixture_name)
    sanitised = LegalChunker.sanitize(text)
    chunks = LegalChunker(jurisdiction=jurisdiction, doc_type=doc_type).chunk(text)
    for chunk in chunks:
        span = sanitised[chunk.char_start : chunk.char_end]
        assert chunk.content.endswith(span), (
            f"{fixture_name} chunk {chunk.index}: span is not a suffix of content"
        )


def test_roomy_budget_keeps_offsets_identical_with_and_without_the_prefix() -> None:
    """The US MSA keeps its boundaries when both modes have a 2048-token budget.

    This fixture does not approach the cap in either mode, so changing what is
    prepended does not require any positional boundary to move.
    """
    text = load_fixture("us_msa")
    common = dict(jurisdiction="us", doc_type="contract", max_chunk_size=2048)
    with_headers = LegalChunker(**common, include_ancestor_headers=True).chunk(text)
    without = LegalChunker(**common, include_ancestor_headers=False).chunk(text)
    assert [(c.char_start, c.char_end) for c in with_headers] == [
        (c.char_start, c.char_end) for c in without
    ]


def test_include_context_header_does_not_control_the_prefix() -> None:
    """The two flags are independent; the issue report conflated them."""
    text = load_fixture("us_msa")
    chunker = LegalChunker(
        jurisdiction="us", include_context_header=False, max_chunk_size=2048
    )
    sanitised = LegalChunker.sanitize(text)
    prefixed = [
        c
        for c in chunker.chunk(text)
        if c.content != sanitised[c.char_start : c.char_end]
    ]
    assert prefixed, "expected include_context_header=False to leave the prefix on"
    assert all(c.context_header == "" for c in chunker.chunk(text))


def test_the_reported_reproducer_no_longer_shows_a_prefix() -> None:
    """Issue 2's own reproducer, with the new flag set."""
    filler = " ".join(["The parties acknowledge and agree that this applies."] * 6)
    text = (
        "Exhibit 99.1\n\n"
        "COOPERATION AGREEMENT\n\n"
        "This Agreement is made as of January 1, 2020. " + filler + "\n\n"
        "(a) The Board shall appoint the designee promptly. " + filler + "\n\n"
        "(b) The designee shall comply with all policies. " + filler + "\n"
    )
    chunker = LegalChunker(
        jurisdiction="us",
        max_chunk_size=512,
        include_context_header=False,
        include_ancestor_headers=False,
    )
    sanitised = LegalChunker.sanitize(text)
    for chunk in chunker.chunk(text):
        assert chunk.content == sanitised[chunk.char_start : chunk.char_end]


def test_include_ancestor_headers_must_be_a_bool() -> None:
    from lexichunk.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError):
        LegalChunker(jurisdiction="uk", include_ancestor_headers="yes")  # type: ignore[arg-type]
