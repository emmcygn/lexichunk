"""Integration tests for LegalTextSplitter (LangChain) and LegalNodeParser (LlamaIndex)."""

from __future__ import annotations

import unittest.mock as mock

import pytest

from lexichunk.integrations.langchain import _LANGCHAIN_AVAILABLE
from lexichunk.integrations.llama_index import _LLAMA_INDEX_AVAILABLE
from lexichunk.models import ClauseType, DocumentSection, Jurisdiction

# ---------------------------------------------------------------------------
# Conditional skip markers
# ---------------------------------------------------------------------------

langchain_required = pytest.mark.skipif(
    not _LANGCHAIN_AVAILABLE,
    reason="langchain-core not installed",
)
llama_index_required = pytest.mark.skipif(
    not _LLAMA_INDEX_AVAILABLE,
    reason="llama-index-core not installed",
)

# ---------------------------------------------------------------------------
# Shared sample text
# ---------------------------------------------------------------------------

SAMPLE_UK = """1. Definitions

"Services" means the software services described in Schedule 1.

"Fees" means the amounts payable by the Client under this Agreement.

2. Payment

2.1 The Client shall pay the Fees within 30 days of invoice, subject to Clause 3.

3. Termination

3.1 Either party may terminate this Agreement on 30 days written notice.
"""

EXPECTED_METADATA_KEYS = {
    "clause_type",
    "jurisdiction",
    "document_section",
    "hierarchy_path",
    "hierarchy_identifier",
    "hierarchy_level",
    "cross_references",
    "defined_terms_used",
    "context_header",
    "char_start",
    "char_end",
    "chunk_index",
    "document_id",
}

# ---------------------------------------------------------------------------
# Always-run import-error tests (no optional deps required)
# ---------------------------------------------------------------------------


def test_langchain_import_error_without_dependency():
    """LegalTextSplitter raises ImportError when _LANGCHAIN_AVAILABLE is False."""
    with mock.patch("lexichunk.integrations.langchain._LANGCHAIN_AVAILABLE", False):
        from lexichunk.integrations.langchain import LegalTextSplitter

        with pytest.raises(ImportError, match="langchain-core"):
            LegalTextSplitter(jurisdiction="uk")


def test_llama_index_import_error_without_dependency():
    """LegalNodeParser raises ImportError when _LLAMA_INDEX_AVAILABLE is False."""
    with mock.patch("lexichunk.integrations.llama_index._LLAMA_INDEX_AVAILABLE", False):
        from lexichunk.integrations.llama_index import LegalNodeParser

        with pytest.raises(ImportError, match="llama-index-core"):
            LegalNodeParser(jurisdiction="uk")


# ---------------------------------------------------------------------------
# LangChain tests
# ---------------------------------------------------------------------------


@pytest.fixture
def langchain_splitter():
    from lexichunk.integrations.langchain import LegalTextSplitter

    return LegalTextSplitter(
        jurisdiction="uk",
        doc_type="contract",
        max_chunk_size=512,
        min_chunk_size=64,
        include_definitions=True,
        include_context_header=True,
    )


@pytest.fixture
def langchain_docs(langchain_splitter):
    return langchain_splitter.split_text(SAMPLE_UK)


@langchain_required
def test_langchain_split_text_returns_list(langchain_splitter):
    """split_text returns a list."""
    result = langchain_splitter.split_text(SAMPLE_UK)
    assert isinstance(result, list)


@langchain_required
def test_langchain_documents_are_nonempty(langchain_docs):
    """split_text on SAMPLE_UK yields at least one Document."""
    assert len(langchain_docs) > 0


@langchain_required
def test_langchain_document_has_page_content(langchain_docs):
    """Every Document has a non-empty page_content string."""
    assert len(langchain_docs) > 0
    for doc in langchain_docs:
        assert isinstance(doc.page_content, str)
        assert len(doc.page_content) > 0


@langchain_required
def test_langchain_metadata_keys_present(langchain_docs):
    """The first Document's metadata contains all 13 expected keys with correct types."""
    assert len(langchain_docs) > 0
    metadata_keys = set(langchain_docs[0].metadata.keys())
    assert EXPECTED_METADATA_KEYS.issubset(metadata_keys), (
        f"Missing keys: {EXPECTED_METADATA_KEYS - metadata_keys}"
    )
    # Verify value types and validity on every document
    valid_clause_types = {ct.value for ct in ClauseType}
    valid_doc_sections = {ds.value for ds in DocumentSection}
    valid_jurisdictions = {j.value for j in Jurisdiction}
    for doc in langchain_docs:
        m = doc.metadata
        assert isinstance(m["hierarchy_level"], int), (
            f"hierarchy_level should be int, got {type(m['hierarchy_level'])}"
        )
        assert m["hierarchy_level"] >= 0
        assert m["clause_type"] in valid_clause_types, (
            f"clause_type '{m['clause_type']}' not in ClauseType enum"
        )
        assert m["document_section"] in valid_doc_sections, (
            f"document_section '{m['document_section']}' not in DocumentSection enum"
        )
        assert m["jurisdiction"] in valid_jurisdictions, (
            f"jurisdiction '{m['jurisdiction']}' not in Jurisdiction enum"
        )
        assert isinstance(m["hierarchy_path"], str)
        assert isinstance(m["hierarchy_identifier"], str)
        assert isinstance(m["context_header"], str)
        assert isinstance(m["chunk_index"], int)
        assert isinstance(m["char_start"], int)
        assert isinstance(m["char_end"], int)


@langchain_required
def test_langchain_metadata_clause_type_is_string(langchain_docs):
    """doc.metadata['clause_type'] is a str on every Document."""
    assert len(langchain_docs) > 0
    for doc in langchain_docs:
        assert isinstance(doc.metadata["clause_type"], str)


@langchain_required
def test_langchain_metadata_jurisdiction_value(langchain_docs):
    """doc.metadata['jurisdiction'] equals 'uk' on every Document."""
    assert len(langchain_docs) > 0
    for doc in langchain_docs:
        assert doc.metadata["jurisdiction"] == "uk"


@langchain_required
def test_langchain_metadata_chunk_index_sequential(langchain_docs):
    """chunk_index values are 0, 1, 2, … n-1 without gaps."""
    assert len(langchain_docs) > 0
    indices = [doc.metadata["chunk_index"] for doc in langchain_docs]
    assert indices == list(range(len(langchain_docs))), (
        f"chunk_index sequence is not sequential: {indices}"
    )


@langchain_required
def test_langchain_metadata_char_offsets(langchain_docs):
    """char_start >= 0 and char_end > char_start on every Document."""
    assert len(langchain_docs) > 0
    for doc in langchain_docs:
        assert doc.metadata["char_start"] >= 0, (
            f"char_start is negative: {doc.metadata['char_start']}"
        )
        assert doc.metadata["char_end"] > doc.metadata["char_start"], (
            f"char_end ({doc.metadata['char_end']}) is not greater than "
            f"char_start ({doc.metadata['char_start']})"
        )


@langchain_required
def test_langchain_create_documents_two_texts(langchain_splitter):
    """create_documents([text, text]) returns twice as many docs as split_text(text)."""
    single = langchain_splitter.split_text(SAMPLE_UK)
    combined = langchain_splitter.create_documents([SAMPLE_UK, SAMPLE_UK])
    assert len(combined) == 2 * len(single)


@langchain_required
def test_langchain_empty_text_returns_empty(langchain_splitter):
    """split_text('') returns an empty list."""
    result = langchain_splitter.split_text("")
    assert result == []


@langchain_required
def test_langchain_cross_references_is_list(langchain_docs):
    """doc.metadata['cross_references'] is a list on every Document."""
    assert len(langchain_docs) > 0
    for doc in langchain_docs:
        assert isinstance(doc.metadata["cross_references"], list)


@langchain_required
def test_langchain_defined_terms_used_is_list(langchain_docs):
    """doc.metadata['defined_terms_used'] is a list on every Document."""
    assert len(langchain_docs) > 0
    for doc in langchain_docs:
        assert isinstance(doc.metadata["defined_terms_used"], list)


@langchain_required
def test_langchain_metadata_values_correct():
    """Chunk a known small text and verify specific metadata values match expectations."""
    from lexichunk.integrations.langchain import LegalTextSplitter

    splitter = LegalTextSplitter(
        jurisdiction="uk",
        doc_type="contract",
        max_chunk_size=2048,
        min_chunk_size=10,
        include_definitions=True,
        include_context_header=True,
    )

    text = """1. Definitions

"Confidential Information" means any information disclosed by either party.

2. Termination

2.1 Either party may terminate this Agreement on 30 days written notice, subject to Clause 1.
"""
    docs = splitter.split_text(text)
    assert len(docs) >= 2, f"Expected at least 2 chunks, got {len(docs)}"

    # --- First chunk: Definitions section ---
    defs_doc = docs[0]
    m = defs_doc.metadata
    assert m["clause_type"] == "definitions", (
        f"First chunk clause_type should be 'definitions', got '{m['clause_type']}'"
    )
    assert m["jurisdiction"] == "uk"
    assert m["document_section"] in {ds.value for ds in DocumentSection}
    assert m["hierarchy_level"] >= 0
    assert isinstance(m["hierarchy_identifier"], str)
    assert len(m["hierarchy_identifier"]) > 0
    assert m["chunk_index"] == 0
    assert m["char_start"] == 0
    assert m["char_end"] > m["char_start"]
    assert isinstance(m["cross_references"], list)
    assert isinstance(m["defined_terms_used"], list)

    # --- Second chunk: Termination section ---
    term_doc = docs[1]
    m2 = term_doc.metadata
    assert m2["clause_type"] == "termination", (
        f"Second chunk clause_type should be 'termination', got '{m2['clause_type']}'"
    )
    assert m2["jurisdiction"] == "uk"
    assert m2["chunk_index"] == 1
    assert m2["char_start"] >= defs_doc.metadata["char_end"] or m2["char_start"] >= 0
    assert m2["char_end"] > m2["char_start"]
    assert m2["hierarchy_level"] >= 0

    # Cross-reference to Clause 1 should be detected in the termination chunk
    assert isinstance(m2["cross_references"], list)
    if len(m2["cross_references"]) > 0:
        xref = m2["cross_references"][0]
        assert "raw_text" in xref
        assert "target_identifier" in xref
        assert "target_chunk_index" in xref

    # Verify sequential chunk indices across all docs
    for i, doc in enumerate(docs):
        assert doc.metadata["chunk_index"] == i


# ---------------------------------------------------------------------------
# LlamaIndex tests
# ---------------------------------------------------------------------------


@pytest.fixture
def llama_parser():
    from lexichunk.integrations.llama_index import LegalNodeParser

    return LegalNodeParser(jurisdiction="uk")


@pytest.fixture
def llama_nodes(llama_parser):
    return llama_parser.get_nodes_from_text(SAMPLE_UK)


@llama_index_required
def test_llama_index_get_nodes_from_text_returns_list(llama_parser):
    """get_nodes_from_text returns a list."""
    result = llama_parser.get_nodes_from_text(SAMPLE_UK)
    assert isinstance(result, list)


@llama_index_required
def test_llama_index_nodes_are_nonempty(llama_nodes):
    """get_nodes_from_text on SAMPLE_UK yields at least one TextNode."""
    assert len(llama_nodes) > 0


@llama_index_required
def test_llama_index_node_has_text(llama_nodes):
    """Every TextNode has a non-empty .text string."""
    assert len(llama_nodes) > 0
    for node in llama_nodes:
        assert isinstance(node.text, str)
        assert len(node.text) > 0


@llama_index_required
def test_llama_index_metadata_keys_present(llama_nodes):
    """The first TextNode's metadata contains all 13 expected keys with correct types."""
    assert len(llama_nodes) > 0
    metadata_keys = set(llama_nodes[0].metadata.keys())
    assert EXPECTED_METADATA_KEYS.issubset(metadata_keys), (
        f"Missing keys: {EXPECTED_METADATA_KEYS - metadata_keys}"
    )
    # Verify value types and validity on every node
    valid_clause_types = {ct.value for ct in ClauseType}
    valid_doc_sections = {ds.value for ds in DocumentSection}
    valid_jurisdictions = {j.value for j in Jurisdiction}
    for node in llama_nodes:
        m = node.metadata
        assert isinstance(m["hierarchy_level"], int), (
            f"hierarchy_level should be int, got {type(m['hierarchy_level'])}"
        )
        assert m["hierarchy_level"] >= 0
        assert m["clause_type"] in valid_clause_types, (
            f"clause_type '{m['clause_type']}' not in ClauseType enum"
        )
        assert m["document_section"] in valid_doc_sections, (
            f"document_section '{m['document_section']}' not in DocumentSection enum"
        )
        assert m["jurisdiction"] in valid_jurisdictions, (
            f"jurisdiction '{m['jurisdiction']}' not in Jurisdiction enum"
        )
        assert isinstance(m["hierarchy_path"], str)
        assert isinstance(m["hierarchy_identifier"], str)
        assert isinstance(m["context_header"], str)
        assert isinstance(m["chunk_index"], int)
        assert isinstance(m["char_start"], int)
        assert isinstance(m["char_end"], int)


@llama_index_required
def test_llama_index_metadata_jurisdiction_value(llama_nodes):
    """node.metadata['jurisdiction'] equals 'uk' on every TextNode."""
    assert len(llama_nodes) > 0
    for node in llama_nodes:
        assert node.metadata["jurisdiction"] == "uk"


@llama_index_required
def test_llama_index_get_nodes_from_documents(llama_parser):
    """get_nodes_from_documents accepts a mock document with a .text attribute."""

    class _MockDocument:
        text = SAMPLE_UK

    nodes = llama_parser.get_nodes_from_documents([_MockDocument()])
    assert isinstance(nodes, list)
    assert len(nodes) > 0


@llama_index_required
def test_llama_index_get_nodes_from_documents_bad_object(llama_parser):
    """get_nodes_from_documents raises AttributeError for an incompatible object."""

    class _BadDocument:
        pass

    with pytest.raises(AttributeError):
        llama_parser.get_nodes_from_documents([_BadDocument()])


@llama_index_required
def test_llama_index_empty_text_returns_empty(llama_parser):
    """get_nodes_from_text('') returns an empty list."""
    result = llama_parser.get_nodes_from_text("")
    assert result == []


@llama_index_required
def test_llama_index_metadata_values_correct():
    """Chunk a known small text and verify specific metadata values match expectations."""
    from lexichunk.integrations.llama_index import LegalNodeParser

    parser = LegalNodeParser(
        jurisdiction="uk",
        doc_type="contract",
        max_chunk_size=2048,
        min_chunk_size=10,
        include_definitions=True,
        include_context_header=True,
    )

    text = """1. Definitions

"Confidential Information" means any information disclosed by either party.

2. Termination

2.1 Either party may terminate this Agreement on 30 days written notice, subject to Clause 1.
"""
    nodes = parser.get_nodes_from_text(text)
    assert len(nodes) >= 2, f"Expected at least 2 nodes, got {len(nodes)}"

    # --- First node: Definitions section ---
    defs_node = nodes[0]
    m = defs_node.metadata
    assert m["clause_type"] == "definitions", (
        f"First node clause_type should be 'definitions', got '{m['clause_type']}'"
    )
    assert m["jurisdiction"] == "uk"
    assert m["document_section"] in {ds.value for ds in DocumentSection}
    assert m["hierarchy_level"] >= 0
    assert isinstance(m["hierarchy_identifier"], str)
    assert len(m["hierarchy_identifier"]) > 0
    assert m["chunk_index"] == 0
    assert m["char_start"] == 0
    assert m["char_end"] > m["char_start"]
    assert isinstance(m["cross_references"], list)
    assert isinstance(m["defined_terms_used"], list)

    # --- Second node: Termination section ---
    term_node = nodes[1]
    m2 = term_node.metadata
    assert m2["clause_type"] == "termination", (
        f"Second node clause_type should be 'termination', got '{m2['clause_type']}'"
    )
    assert m2["jurisdiction"] == "uk"
    assert m2["chunk_index"] == 1
    assert m2["char_start"] >= defs_node.metadata["char_end"] or m2["char_start"] >= 0
    assert m2["char_end"] > m2["char_start"]
    assert m2["hierarchy_level"] >= 0

    # Cross-reference to Clause 1 should be detected in the termination node
    assert isinstance(m2["cross_references"], list)
    if len(m2["cross_references"]) > 0:
        xref = m2["cross_references"][0]
        assert "raw_text" in xref
        assert "target_identifier" in xref
        assert "target_chunk_index" in xref

    # Verify sequential chunk indices across all nodes
    for i, node in enumerate(nodes):
        assert node.metadata["chunk_index"] == i
