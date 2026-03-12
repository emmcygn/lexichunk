"""End-to-end tests for LegalChunker."""

import pytest

from lexichunk import LegalChunker, LegalChunk, HierarchyNode, ClauseType, Jurisdiction


# ---------------------------------------------------------------------------
# Fixtures / shared helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def uk_chunker():
    return LegalChunker(
        jurisdiction="uk",
        doc_type="contract",
        include_definitions=True,
        include_context_header=True,
    )


@pytest.fixture
def us_chunker():
    return LegalChunker(
        jurisdiction="us",
        doc_type="contract",
        include_definitions=True,
        include_context_header=True,
    )


@pytest.fixture
def uk_chunks(uk_chunker, uk_service_agreement):
    return uk_chunker.chunk(uk_service_agreement)


@pytest.fixture
def us_chunks(us_chunker, us_msa):
    return us_chunker.chunk(us_msa)


# ---------------------------------------------------------------------------
# Basic smoke tests
# ---------------------------------------------------------------------------


def test_chunk_uk_contract_returns_chunks(uk_chunker, uk_service_agreement):
    """Chunking the UK fixture returns a non-empty list of LegalChunk."""
    chunks = uk_chunker.chunk(uk_service_agreement)
    assert isinstance(chunks, list)
    assert len(chunks) > 0
    for chunk in chunks:
        assert isinstance(chunk, LegalChunk)


def test_chunk_us_contract_returns_chunks(us_chunker, us_msa):
    """Chunking the US fixture returns a non-empty list of LegalChunk."""
    chunks = us_chunker.chunk(us_msa)
    assert isinstance(chunks, list)
    assert len(chunks) > 0
    for chunk in chunks:
        assert isinstance(chunk, LegalChunk)


# ---------------------------------------------------------------------------
# Metadata completeness tests
# ---------------------------------------------------------------------------


def test_all_chunks_have_hierarchy_path(uk_chunks):
    """Every chunk produced from the UK fixture has a non-empty hierarchy_path."""
    assert len(uk_chunks) > 0
    for chunk in uk_chunks:
        assert chunk.hierarchy_path, (
            f"Chunk index {chunk.index} has an empty hierarchy_path"
        )


def test_all_chunks_have_clause_type(uk_chunks):
    """Every chunk has a ClauseType that is not None."""
    assert len(uk_chunks) > 0
    for chunk in uk_chunks:
        assert chunk.clause_type is not None, (
            f"Chunk index {chunk.index} has clause_type=None"
        )
        assert isinstance(chunk.clause_type, ClauseType)


def test_all_chunks_have_jurisdiction(uk_chunks):
    """Every chunk produced from the UK fixture carries Jurisdiction.UK."""
    assert len(uk_chunks) > 0
    for chunk in uk_chunks:
        assert chunk.jurisdiction == Jurisdiction.UK, (
            f"Chunk index {chunk.index} has jurisdiction={chunk.jurisdiction!r}"
        )


# ---------------------------------------------------------------------------
# Context header tests
# ---------------------------------------------------------------------------


def test_context_headers_populated(uk_chunker, uk_service_agreement):
    """With include_context_header=True every chunk has a non-empty context_header."""
    chunker = LegalChunker(jurisdiction="uk", include_context_header=True)
    chunks = chunker.chunk(uk_service_agreement)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.context_header, (
            f"Chunk index {chunk.index} has an empty context_header"
        )


def test_context_headers_contain_jurisdiction(uk_chunker, uk_service_agreement):
    """Context headers from the UK fixture must contain 'UK'."""
    chunker = LegalChunker(jurisdiction="uk", include_context_header=True)
    chunks = chunker.chunk(uk_service_agreement)
    assert len(chunks) > 0
    for chunk in chunks:
        assert "UK" in chunk.context_header, (
            f"'UK' not found in context_header: {chunk.context_header!r}"
        )


def test_context_headers_contain_us_jurisdiction(us_chunker, us_msa):
    """Context headers from the US fixture must contain 'US'."""
    chunker = LegalChunker(jurisdiction="us", include_context_header=True)
    chunks = chunker.chunk(us_msa)
    assert len(chunks) > 0
    for chunk in chunks:
        assert "US" in chunk.context_header, (
            f"'US' not found in context_header: {chunk.context_header!r}"
        )


# ---------------------------------------------------------------------------
# Defined terms attachment tests
# ---------------------------------------------------------------------------


def test_defined_terms_attached(uk_service_agreement):
    """With include_definitions=True at least one chunk has defined_terms_used non-empty.

    The UK fixture defines 'Services', 'Fees', 'Affiliate' etc., all of which
    appear in operative clauses, so at least one chunk should reference them.
    """
    chunker = LegalChunker(jurisdiction="uk", include_definitions=True)
    chunks = chunker.chunk(uk_service_agreement)
    chunks_with_terms = [c for c in chunks if c.defined_terms_used]
    assert len(chunks_with_terms) > 0, (
        "Expected at least one chunk with defined_terms_used non-empty"
    )


# ---------------------------------------------------------------------------
# Cross-reference tests
# ---------------------------------------------------------------------------


def test_cross_references_detected(uk_service_agreement):
    """At least one chunk from the UK fixture should have cross_references populated.

    The UK fixture contains many references to clauses and schedules.
    """
    chunker = LegalChunker(jurisdiction="uk")
    chunks = chunker.chunk(uk_service_agreement)
    chunks_with_refs = [c for c in chunks if c.cross_references]
    assert len(chunks_with_refs) > 0, (
        "Expected at least one chunk with cross_references; none found"
    )


# ---------------------------------------------------------------------------
# Size constraints
# ---------------------------------------------------------------------------


def test_no_chunk_exceeds_max_size(uk_service_agreement):
    """No chunk's character count should exceed max_chunk_size * 4 * 1.2.

    1 token ≈ 4 characters; 20% tolerance for chunker approximation.
    """
    max_tokens = 512
    char_limit = max_tokens * 4 * 1.2  # 2457.6 characters
    chunker = LegalChunker(jurisdiction="uk", max_chunk_size=max_tokens)
    chunks = chunker.chunk(uk_service_agreement)
    for chunk in chunks:
        assert len(chunk.content) <= char_limit, (
            f"Chunk {chunk.index} exceeds character limit: "
            f"{len(chunk.content)} > {char_limit:.0f}"
        )


# ---------------------------------------------------------------------------
# Index sequencing
# ---------------------------------------------------------------------------


def test_chunk_indices_sequential(uk_chunks):
    """Chunk indices must be 0, 1, 2, … n-1 without gaps or duplicates."""
    assert len(uk_chunks) > 0
    indices = [c.index for c in uk_chunks]
    assert indices == list(range(len(uk_chunks))), (
        f"Indices are not sequential: {indices[:20]}"
    )


# ---------------------------------------------------------------------------
# document_id propagation
# ---------------------------------------------------------------------------


def test_document_id_propagated(uk_service_agreement):
    """document_id passed to chunk() must appear on every returned chunk."""
    chunker = LegalChunker(jurisdiction="uk")
    doc_id = "TEST-001"
    chunks = chunker.chunk(uk_service_agreement, document_id=doc_id)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.document_id == doc_id, (
            f"Chunk {chunk.index} has document_id={chunk.document_id!r}; expected {doc_id!r}"
        )


def test_document_id_from_init(uk_service_agreement):
    """document_id set on LegalChunker.__init__ propagates when chunk() is called."""
    doc_id = "INIT-DOC"
    chunker = LegalChunker(jurisdiction="uk", document_id=doc_id)
    chunks = chunker.chunk(uk_service_agreement)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.document_id == doc_id


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_text_returns_empty(uk_chunker):
    """chunk('') must return an empty list."""
    result = uk_chunker.chunk("")
    assert result == []


def test_whitespace_only_returns_empty(uk_chunker):
    """chunk with only whitespace must return an empty list."""
    result = uk_chunker.chunk("   \n\n\t  ")
    assert result == []


def test_plain_text_fallback():
    """Chunking plain text with no legal structure still returns a non-empty list.

    The FallbackChunker is used when no headers are detected.
    """
    text = (
        "This is a plain paragraph with no legal structure markers. "
        "It contains enough text to form at least one chunk. "
        "The quick brown fox jumps over the lazy dog. "
        "Pack my box with five dozen liquor jugs. "
        "How valiantly did thou fight, brave warrior of the northern lands."
    )
    chunker = LegalChunker(jurisdiction="uk")
    chunks = chunker.chunk(text)
    assert len(chunks) > 0


# ---------------------------------------------------------------------------
# Additional public-method tests
# ---------------------------------------------------------------------------


def test_get_defined_terms(uk_chunker, uk_service_agreement):
    """get_defined_terms() on the UK fixture returns a dict with at least 5 terms."""
    terms = uk_chunker.get_defined_terms(uk_service_agreement)
    assert isinstance(terms, dict)
    assert len(terms) >= 5, (
        f"Expected at least 5 defined terms; got {len(terms)}: {list(terms.keys())}"
    )


def test_parse_structure(uk_chunker, uk_service_agreement):
    """parse_structure() returns a list of HierarchyNode objects."""
    nodes = uk_chunker.parse_structure(uk_service_agreement)
    assert isinstance(nodes, list)
    assert len(nodes) > 0
    for node in nodes:
        assert isinstance(node, HierarchyNode)


def test_parse_structure_us(us_chunker, us_msa):
    """parse_structure() on US fixture includes Article-level nodes (level 0)."""
    nodes = us_chunker.parse_structure(us_msa)
    article_nodes = [n for n in nodes if n.level == 0]
    assert len(article_nodes) > 0, (
        f"Expected Article-level nodes; found levels: {sorted({n.level for n in nodes})}"
    )


# ---------------------------------------------------------------------------
# Context header disabled
# ---------------------------------------------------------------------------


def test_context_headers_empty_when_disabled(uk_service_agreement):
    """With include_context_header=False, context_header should remain empty on all chunks."""
    chunker = LegalChunker(jurisdiction="uk", include_context_header=False)
    chunks = chunker.chunk(uk_service_agreement)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.context_header == "", (
            f"Expected empty context_header when disabled; "
            f"got {chunk.context_header!r} on chunk {chunk.index}"
        )
