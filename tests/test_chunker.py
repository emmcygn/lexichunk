"""End-to-end tests for LegalChunker."""

import pytest

from lexichunk import ClauseType, HierarchyNode, Jurisdiction, LegalChunk, LegalChunker
from lexichunk.strategies.fallback import FallbackChunker

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


def test_invalid_jurisdiction_raises_error():
    """Passing an unrecognised jurisdiction string must raise ValueError."""
    with pytest.raises(ValueError):
        LegalChunker(jurisdiction="french")


def test_jurisdiction_enum_accepted():
    """Passing a Jurisdiction enum value directly must be accepted."""
    chunker = LegalChunker(jurisdiction=Jurisdiction.UK)
    assert chunker._jurisdiction == Jurisdiction.UK


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


def test_fallback_preserves_legal_abbreviations():
    """Text containing 'U.S.C. § 1234' must NOT be split at periods in 'U.S.C.'.

    The fallback sentence splitter should recognise U.S.C. as a legal
    abbreviation and keep the entire phrase within a single chunk.
    """
    text = (
        "The statute at 18 U.S.C. § 1234 provides clear guidance on this matter. "
        "Violations may result in penalties under 28 U.S.C. § 5678 as amended. "
        "The court in F.3d. Reporter confirmed this interpretation last year."
    )
    chunker = FallbackChunker(jurisdiction=Jurisdiction.US)
    chunks = chunker.chunk(text)
    # All text should land in a single chunk since there are no real sentence
    # boundaries — every period is part of an abbreviation or the final stop.
    combined = " ".join(c.content for c in chunks)
    assert "18 U.S.C. § 1234" in combined, (
        "U.S.C. citation was broken across chunks"
    )
    assert "28 U.S.C. § 5678" in combined, (
        "Second U.S.C. citation was broken across chunks"
    )
    # The abbreviation periods must not cause extra chunks; all three
    # sentences should stay together given the default 512-token limit.
    assert len(chunks) == 1, (
        f"Expected 1 chunk (abbreviations should not split); got {len(chunks)}"
    )


def test_fallback_preserves_entity_abbreviations():
    """Entity abbreviations like 'Corp.' and 'LLC.' must not trigger a sentence split.

    'Acme Corp. LLC. entered into an agreement' should remain as one sentence
    rather than being split at each abbreviated period.
    """
    text = (
        "Acme Corp. LLC. entered into an agreement with BigCo Inc. "
        "for the provision of consulting services. "
        "The parties, including Newco Ltd. and its affiliates, "
        "agreed to the following terms."
    )
    chunker = FallbackChunker(jurisdiction=Jurisdiction.UK)
    chunks = chunker.chunk(text)
    combined = " ".join(c.content for c in chunks)
    # Verify abbreviations were not used as split points
    assert "Acme Corp. LLC." in combined, (
        "Corp./LLC. abbreviation was broken across chunks"
    )
    assert "BigCo Inc." in combined, (
        "Inc. abbreviation was broken across chunks"
    )
    assert "Newco Ltd." in combined, (
        "Ltd. abbreviation was broken across chunks"
    )
    # Short enough to fit in one chunk; abbreviation periods must not split it
    assert len(chunks) == 1, (
        f"Expected 1 chunk (entity abbreviations should not split); got {len(chunks)}"
    )


def test_fallback_splits_at_real_sentences():
    """Actual sentence boundaries must still be detected and used for splitting.

    When text has genuine sentence endings (period + space + uppercase) the
    fallback chunker should split there when the chunk size limit is reached.
    """
    # Build text with clear sentence boundaries that exceeds one chunk.
    # Each sentence is ~60 chars = 15 tokens.  With max_chunk_size=30 tokens
    # (120 chars) we should get multiple chunks.
    sentences = [
        "The parties hereby agree to the terms set forth in this agreement.",
        "Payment shall be made within thirty days of invoice receipt.",
        "Either party may terminate this agreement upon written notice.",
        "All disputes shall be resolved through binding arbitration.",
        "This agreement constitutes the entire understanding of the parties.",
    ]
    text = " ".join(sentences)
    chunker = FallbackChunker(jurisdiction=Jurisdiction.UK, max_chunk_size=30, min_chunk_size=10)
    chunks = chunker.chunk(text)
    assert len(chunks) >= 2, (
        f"Expected at least 2 chunks for long text with small max_chunk_size; "
        f"got {len(chunks)}"
    )
    # Every original sentence must appear in exactly one chunk (no loss).
    combined = " ".join(c.content for c in chunks)
    for sentence in sentences:
        assert sentence in combined, (
            f"Sentence not found in chunked output: {sentence!r}"
        )


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


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_invalid_jurisdiction_string_raises_value_error():
    """Passing an unsupported jurisdiction string raises ValueError."""
    with pytest.raises(ValueError):
        LegalChunker(jurisdiction="french")


def test_jurisdiction_enum_us_accepted():
    """Passing a Jurisdiction enum value directly works."""
    chunker = LegalChunker(jurisdiction=Jurisdiction.US)
    assert chunker._jurisdiction == Jurisdiction.US


def test_max_lt_min_chunk_size_raises_error():
    """max_chunk_size < min_chunk_size raises ValueError."""
    with pytest.raises(ValueError, match="max_chunk_size.*must be >= min_chunk_size"):
        LegalChunker(max_chunk_size=64, min_chunk_size=512)


# ---------------------------------------------------------------------------
# Non-default chunk size tests
# ---------------------------------------------------------------------------


def test_smaller_max_chunk_size_produces_more_chunks(uk_service_agreement):
    """Chunking with max_chunk_size=256 should produce more chunks than 512."""
    chunker_256 = LegalChunker(jurisdiction="uk", max_chunk_size=256)
    chunker_512 = LegalChunker(jurisdiction="uk", max_chunk_size=512)
    chunks_256 = chunker_256.chunk(uk_service_agreement)
    chunks_512 = chunker_512.chunk(uk_service_agreement)
    assert len(chunks_256) > len(chunks_512), (
        f"Expected max_chunk_size=256 to produce more chunks than 512; "
        f"got {len(chunks_256)} vs {len(chunks_512)}"
    )


def test_larger_min_chunk_size_merges_more(uk_service_agreement):
    """Chunking with min_chunk_size=128 should produce fewer or equal chunks than 64."""
    chunker_128 = LegalChunker(jurisdiction="uk", min_chunk_size=128)
    chunker_64 = LegalChunker(jurisdiction="uk", min_chunk_size=64)
    chunks_128 = chunker_128.chunk(uk_service_agreement)
    chunks_64 = chunker_64.chunk(uk_service_agreement)
    assert len(chunks_128) <= len(chunks_64), (
        f"Expected min_chunk_size=128 to produce fewer or equal chunks than 64; "
        f"got {len(chunks_128)} vs {len(chunks_64)}"
    )


def test_chars_per_token_configurable(uk_service_agreement):
    """chars_per_token=2 (smaller tokens = higher token estimates) produces more chunks."""
    chunker_default = LegalChunker(jurisdiction="uk", max_chunk_size=512)
    chunker_cpt2 = LegalChunker(jurisdiction="uk", max_chunk_size=512, chars_per_token=2)
    chunks_default = chunker_default.chunk(uk_service_agreement)
    chunks_cpt2 = chunker_cpt2.chunk(uk_service_agreement)
    assert len(chunks_cpt2) > len(chunks_default), (
        f"Expected chars_per_token=2 to produce more chunks than default; "
        f"got {len(chunks_cpt2)} vs {len(chunks_default)}"
    )


def test_max_chunk_size_respected_at_256(uk_service_agreement):
    """No chunk content should exceed 256 * 4 * 1.2 characters with max_chunk_size=256."""
    max_tokens = 256
    char_limit = max_tokens * 4 * 1.2  # 1228.8 characters
    chunker = LegalChunker(jurisdiction="uk", max_chunk_size=max_tokens)
    chunks = chunker.chunk(uk_service_agreement)
    for chunk in chunks:
        assert len(chunk.content) <= char_limit, (
            f"Chunk {chunk.index} exceeds character limit: "
            f"{len(chunk.content)} > {char_limit:.0f}"
        )


# ---------------------------------------------------------------------------
# Minimal and deeply-nested fixture tests
# ---------------------------------------------------------------------------


def test_single_clause_document():
    """A document with exactly one top-level clause produces exactly 1 chunk."""
    text = (
        "1. Governing Law\n\n"
        "This Agreement shall be governed by and construed in accordance with "
        "the laws of England and Wales."
    )
    chunker = LegalChunker(jurisdiction="uk")
    chunks = chunker.chunk(text)
    assert len(chunks) == 1, (
        f"Expected exactly 1 chunk for a single-clause document; got {len(chunks)}"
    )
    chunk = chunks[0]
    assert isinstance(chunk, LegalChunk)
    assert chunk.index == 0
    assert chunk.jurisdiction == Jurisdiction.UK
    assert chunk.hierarchy is not None
    assert chunk.hierarchy_path != ""
    assert "1" in chunk.hierarchy_path


def test_deeply_nested_hierarchy_uk():
    """A UK document with nested levels (1 > 1.1 > 1.1.1 > (a), (i)).

    Verifies hierarchy_path contains numbered levels and sub-clause siblings.
    The parser treats (a) and (i) as siblings under 1.1.1, not parent-child.
    """
    text = (
        "1. Obligations\n\n"
        "The Provider shall comply with all applicable obligations.\n\n"
        "1.1 Service Standards\n\n"
        "The Provider shall maintain the following service standards.\n\n"
        "1.1.1 Response Times\n\n"
        "The Provider shall respond to all requests within the timeframes set out below.\n\n"
        "(a) Priority Requests\n\n"
        "Priority requests shall be acknowledged within one Business Day.\n\n"
        "(i) Emergency escalation requests shall be acknowledged within four hours "
        "of receipt by the Provider and shall be resolved within twenty-four hours."
    )
    chunker = LegalChunker(
        jurisdiction="uk",
        include_context_header=True,
        min_chunk_size=1,
    )
    chunks = chunker.chunk(text)
    assert len(chunks) >= 3, "Expected at least 3 chunks from a nested document"

    # Verify numbered hierarchy levels are preserved
    paths = [c.hierarchy_path for c in chunks]
    assert any("1.1" in p for p in paths), f"Missing level-2 '1.1' in paths: {paths}"
    assert any("1.1.1" in p for p in paths), f"Missing level-3 '1.1.1' in paths: {paths}"

    # (a) and (i) should both appear as separate chunks
    assert any("(a)" in p for p in paths), f"Missing '(a)' in paths: {paths}"
    assert any("(i)" in p for p in paths), f"Missing '(i)' in paths: {paths}"

    # Every chunk should have a hierarchy node
    for chunk in chunks:
        assert chunk.hierarchy is not None


def test_deeply_nested_hierarchy_us():
    """A US document with Article > Section > (a), (i).

    Verifies hierarchy_path is built correctly for US-style numbering.
    The parser treats (a) and (i) as siblings under Section, not parent-child.
    """
    text = (
        "ARTICLE I\n"
        "DEFINITIONS\n\n"
        "Section 1.01. General Definitions.\n\n"
        "The following terms shall have the meanings set forth below.\n\n"
        "(a) Affiliate Definitions.\n\n"
        "The term Affiliate means any entity controlling or controlled by a Party.\n\n"
        "(i) A direct or indirect ownership interest of fifty percent or more "
        "of the voting securities of an entity shall constitute control for "
        "purposes of this definition."
    )
    chunker = LegalChunker(
        jurisdiction="us",
        include_context_header=True,
        min_chunk_size=1,
    )
    chunks = chunker.chunk(text)
    assert len(chunks) >= 2, "Expected at least 2 chunks from a US nested document"

    paths = [c.hierarchy_path for c in chunks]
    # Article-level should appear
    assert any("Article I" in p or "ARTICLE I" in p for p in paths), (
        f"Missing Article-level in paths: {paths}"
    )
    # Section 1.01 should appear
    assert any("1.01" in p for p in paths), f"Missing Section 1.01 in paths: {paths}"
    # Sub-clauses should appear as separate chunks
    assert any("(a)" in p for p in paths), f"Missing '(a)' in paths: {paths}"
    assert any("(i)" in p for p in paths), f"Missing '(i)' in paths: {paths}"


# ---------------------------------------------------------------------------
# Validation tests (S2)
# ---------------------------------------------------------------------------


def test_invalid_doc_type_raises_error():
    """Passing an unsupported doc_type raises ValueError."""
    with pytest.raises(ValueError, match="Unknown doc_type"):
        LegalChunker(doc_type="lawsuit")


def test_input_too_large_raises_error():
    """Input exceeding _MAX_INPUT_CHARS raises ValueError."""
    chunker = LegalChunker()
    large_text = "x" * (chunker._MAX_INPUT_CHARS + 1)
    with pytest.raises(ValueError, match="Input text too large"):
        chunker.chunk(large_text)


# ---------------------------------------------------------------------------
# token_count tests (S3)
# ---------------------------------------------------------------------------


def test_token_count_populated(uk_service_agreement):
    """Every chunk has a positive token_count after chunking."""
    chunker = LegalChunker(jurisdiction="uk")
    chunks = chunker.chunk(uk_service_agreement)
    for chunk in chunks:
        assert chunk.token_count > 0, (
            f"Chunk {chunk.index} has token_count={chunk.token_count}"
        )


# ---------------------------------------------------------------------------
# Content fidelity test (S6)
# ---------------------------------------------------------------------------


def test_content_fidelity_no_text_loss(uk_service_agreement):
    """Concatenated chunk content preserves the vast majority of the original.

    Verifies that at least 95% of non-trivial lines appear in the chunk
    output.  Some clause header lines may be absorbed into hierarchy
    metadata rather than chunk content — this is by design.
    """
    chunker = LegalChunker(jurisdiction="uk")
    chunks = chunker.chunk(uk_service_agreement)
    combined = " ".join(c.content for c in chunks)
    import re as _re

    def norm(s):
        return _re.sub(r'\s+', ' ', s).strip()

    combined_norm = norm(combined)

    lines = [
        line.strip() for line in uk_service_agreement.split("\n")
        if len(line.strip()) > 20
    ]
    found = sum(1 for line in lines if norm(line) in combined_norm)
    ratio = found / len(lines) if lines else 1.0
    # v0.2.0: ancestor headers are prepended to chunk content, so fidelity
    # should be ≥99%.
    assert ratio >= 0.99, (
        f"Too much text lost during chunking: {found}/{len(lines)} lines "
        f"preserved ({ratio:.0%}). Expected >= 99%."
    )


# ---------------------------------------------------------------------------
# Phase A: Ancestor header prepending tests (v0.2.0)
# ---------------------------------------------------------------------------


def test_ancestor_headers_in_chunk_content():
    """For a 3-level deep clause, ALL ancestor headers appear in chunk content
    in root→leaf order before the body text."""
    text = (
        "1. Obligations\n\n"
        "The Provider shall comply.\n\n"
        "1.1 Service Standards\n\n"
        "The Provider shall maintain standards.\n\n"
        "1.1.1 Response Times\n\n"
        "The Provider shall respond within the timeframes below.\n\n"
        "(a) Priority Requests\n\n"
        "Priority requests shall be acknowledged within one Business Day."
    )
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=1)
    chunks = chunker.chunk(text)

    # Find the chunk for (a)
    chunk_a = None
    for c in chunks:
        if c.hierarchy.identifier == "(a)":
            chunk_a = c
            break
    assert chunk_a is not None, "No chunk found with identifier (a)"

    # All ancestors must appear in content
    assert "1." in chunk_a.content or "1 " in chunk_a.content or "1\n" in chunk_a.content, (
        f"Top-level ancestor '1' not in content: {chunk_a.content!r}"
    )
    assert "1.1" in chunk_a.content, (
        f"Ancestor '1.1' not in content: {chunk_a.content!r}"
    )
    assert "1.1.1" in chunk_a.content, (
        f"Ancestor '1.1.1' not in content: {chunk_a.content!r}"
    )


def test_original_header_field_populated():
    """original_header is populated and matches the clause's own header."""
    text = (
        "1. Governing Law\n\n"
        "This Agreement shall be governed by the laws of England."
    )
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=1)
    chunks = chunker.chunk(text)
    assert len(chunks) >= 1
    # For preamble-less doc the first real clause should have original_header
    non_preamble = [c for c in chunks if c.hierarchy.level != -99]
    assert len(non_preamble) >= 1
    c = non_preamble[0]
    assert c.original_header != "", f"original_header is empty on chunk {c.index}"
    assert "1" in c.original_header


def test_per_chunk_identifier_in_content(uk_chunker, uk_service_agreement):
    """Every chunk's hierarchy identifier must appear in its content.

    Synthetic __part identifiers from sentence-splitting are excluded since
    the part suffix is a chunker artifact, not a document-level identifier.
    """
    chunks = uk_chunker.chunk(uk_service_agreement)
    for chunk in chunks:
        ident = chunk.hierarchy.identifier
        if ident == "preamble" or "__part" in ident:
            continue
        assert ident in chunk.content, (
            f"Chunk {chunk.index} identifier {ident!r} not found in content: "
            f"{chunk.content[:200]!r}"
        )


def test_ancestor_header_ordering():
    """Ancestor headers must appear in root→leaf order (not reversed)."""
    text = (
        "1. Obligations\n\n"
        "The Provider shall comply.\n\n"
        "1.1 Service Standards\n\n"
        "The Provider shall maintain standards.\n\n"
        "(a) Priority Requests\n\n"
        "Priority requests shall be acknowledged within one Business Day."
    )
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=1)
    chunks = chunker.chunk(text)

    chunk_a = next((c for c in chunks if c.hierarchy.identifier == "(a)"), None)
    assert chunk_a is not None

    # "1 Obligations" must appear before "1.1 Service Standards" which must
    # appear before "(a)" in content
    content = chunk_a.content
    pos_1 = content.find("1 Obligations")
    pos_11 = content.find("1.1 Service Standards")
    pos_a = content.find("(a)")
    assert pos_1 != -1, "Ancestor '1 Obligations' not found in content"
    assert pos_11 != -1, "Ancestor '1.1 Service Standards' not found in content"
    assert pos_1 < pos_11 < pos_a, (
        f"Headers not in root→leaf order: '1 Obligations' at {pos_1}, "
        f"'1.1 Service Standards' at {pos_11}, '(a)' at {pos_a}"
    )


def test_merged_chunks_carry_primary_ancestors():
    """When small clauses are merged, the primary clause's ancestors are prepended."""
    text = (
        "1. General\n\n"
        "The Provider shall comply.\n\n"
        "1.1 Terms\n\n"
        "Short clause.\n\n"
        "1.2 More Terms\n\n"
        "Another short clause."
    )
    # With a high min_chunk_size, 1.1 and 1.2 should merge
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=200)
    chunks = chunker.chunk(text)
    # The merged chunk should still contain the parent "1" identifier
    merged = [c for c in chunks if c.hierarchy.level != -99]
    for c in merged:
        assert "1" in c.content, (
            f"Merged chunk {c.index} missing ancestor '1' in content"
        )


def test_preamble_no_ancestor_headers():
    """Preamble chunks (level=-99) should NOT have ancestor headers prepended."""
    text = (
        "This Agreement is entered into on 1 January 2024.\n\n"
        "1. Definitions\n\n"
        "The following terms shall have the meanings set forth below."
    )
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=1)
    chunks = chunker.chunk(text)
    preamble_chunks = [c for c in chunks if c.hierarchy.level == -99]
    for c in preamble_chunks:
        # Preamble content should not start with any clause header
        assert c.original_header == "", (
            f"Preamble chunk has original_header: {c.original_header!r}"
        )


def test_token_count_includes_prepended_headers():
    """token_count must reflect the full content including prepended headers."""
    text = (
        "1. Obligations\n\n"
        "The Provider shall comply.\n\n"
        "1.1 Service Standards\n\n"
        "The Provider shall maintain service standards as set forth herein."
    )
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=1)
    chunks = chunker.chunk(text)
    for chunk in chunks:
        expected = max(1, len(chunk.content) // 4)
        assert chunk.token_count == expected, (
            f"Chunk {chunk.index} token_count {chunk.token_count} != "
            f"expected {expected} for content length {len(chunk.content)}"
        )


# ---------------------------------------------------------------------------
# Phase B: Adversarial stress tests (v0.2.0)
# ---------------------------------------------------------------------------


def test_deeply_nested_6_levels():
    """6-level deep hierarchy — all ancestors present, content not bloated."""
    text = (
        "1. Level One\n\nBody one.\n\n"
        "1.1 Level Two\n\nBody two.\n\n"
        "1.1.1 Level Three\n\nBody three.\n\n"
        "(a) Level Four\n\nBody four.\n\n"
        "(i) Level Five\n\nBody five.\n\n"
        "(A) Level Six\n\nBody six — the deepest clause."
    )
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=1)
    chunks = chunker.chunk(text)
    # Find deepest chunk
    deepest = max(chunks, key=lambda c: c.hierarchy.level)
    # Should contain identifiers from ancestor chain
    assert "1." in deepest.content or "1 " in deepest.content
    # Content shouldn't be unreasonably large
    assert len(deepest.content) < 2000, f"Content too large: {len(deepest.content)}"


def test_missing_parent_in_clause_map_no_crash():
    """If parent chain is broken (missing parent), chunker should not crash."""
    from lexichunk.models import DocumentSection
    from lexichunk.parsers.structure import ParsedClause
    from lexichunk.strategies.clause_aware import ClauseAwareChunker

    # Create a clause with a parent_identifier that doesn't exist in clause_map
    clause = ParsedClause(
        identifier="(a)",
        title="Orphan Clause",
        content="This clause has a broken parent reference.",
        level=3,
        parent_identifier="NONEXISTENT",
        document_section=DocumentSection.OPERATIVE,
        char_start=0,
        char_end=50,
        children=[],
    )
    chunker = ClauseAwareChunker(jurisdiction=Jurisdiction.UK, min_chunk_size=1)
    # Should not crash
    chunks = chunker.chunk([clause], "This clause has a broken parent reference.")
    assert len(chunks) >= 1


def test_clause_with_empty_title():
    """Clause with empty title — header should be identifier only, no trailing whitespace."""
    text = (
        "1.\n\n"
        "This clause has a number but no title text whatsoever."
    )
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=1)
    chunks = chunker.chunk(text)
    non_preamble = [c for c in chunks if c.hierarchy.level != -99]
    if non_preamble:
        c = non_preamble[0]
        # original_header should not have trailing whitespace
        assert c.original_header == c.original_header.strip(), (
            f"original_header has trailing whitespace: {c.original_header!r}"
        )


def test_single_clause_no_ancestors():
    """Single-clause document — no ancestors, no crash, content unchanged except own header."""
    text = "1. Entire Agreement\n\nThis constitutes the entire agreement."
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=1)
    chunks = chunker.chunk(text)
    non_preamble = [c for c in chunks if c.hierarchy.level != -99]
    assert len(non_preamble) >= 1
    c = non_preamble[0]
    assert "1" in c.content
    assert "entire agreement" in c.content.lower()


def test_unicode_in_titles():
    """Unicode characters in titles are preserved correctly."""
    text = (
        "1. Définitions\n\n"
        "Les termes suivants auront les significations indiquées ci-dessous.\n\n"
        "1.1 Affilié\n\n"
        "Le terme Affilié désigne toute entité contrôlée."
    )
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=1)
    chunks = chunker.chunk(text)
    # Find chunk for 1.1
    c11 = next((c for c in chunks if "1.1" in c.hierarchy.identifier), None)
    if c11:
        assert "Définitions" in c11.content or "1." in c11.content, (
            f"Parent header not in child content: {c11.content!r}"
        )
