"""Tests for ContextEnricher and context header generation."""

from lexichunk.enrichment.context import (
    ContextEnricher,
    build_embedded_text,
    generate_context_header,
)
from lexichunk.models import ClauseType, DocumentSection, HierarchyNode, Jurisdiction, LegalChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(**overrides) -> LegalChunk:
    """Create a minimal LegalChunk with sensible defaults."""
    defaults = dict(
        content="The Supplier shall provide the services described herein.",
        index=0,
        hierarchy=HierarchyNode(level=1, identifier="1.1", title="Services", parent=None),
        hierarchy_path="1 — Obligations > 1.1 — Services",
        document_section=DocumentSection.OPERATIVE,
        clause_type=ClauseType.COVENANTS,
        jurisdiction=Jurisdiction.UK,
    )
    defaults.update(overrides)
    return LegalChunk(**defaults)


# ---------------------------------------------------------------------------
# generate_context_header tests
# ---------------------------------------------------------------------------


def test_context_header_contains_hierarchy():
    """Context header includes the chunk's hierarchy_path."""
    chunk = _make_chunk(hierarchy_path="Article IV — Confidentiality")
    header = generate_context_header(chunk)
    assert "Article IV" in header


def test_context_header_contains_document_id():
    """Context header includes document_id when set."""
    chunk = _make_chunk(document_id="NDA-2024")
    header = generate_context_header(chunk)
    assert "[Document: NDA-2024]" in header


def test_context_header_omits_document_id_when_none():
    """Context header omits [Document: ...] when document_id is None."""
    chunk = _make_chunk(document_id=None)
    header = generate_context_header(chunk)
    assert "[Document:" not in header


def test_context_header_contains_clause_type():
    """Context header includes the formatted clause type."""
    chunk = _make_chunk(clause_type=ClauseType.CONFIDENTIALITY)
    header = generate_context_header(chunk)
    assert "Confidentiality" in header


def test_context_header_contains_jurisdiction():
    """Context header includes the jurisdiction."""
    chunk = _make_chunk(jurisdiction=Jurisdiction.US)
    header = generate_context_header(chunk)
    assert "US" in header


# ---------------------------------------------------------------------------
# build_embedded_text tests
# ---------------------------------------------------------------------------


def test_build_embedded_text_prepends_header():
    """build_embedded_text prepends context_header to content."""
    chunk = _make_chunk()
    chunk.context_header = "[Section: 1.1] [Type: Covenants] [Jurisdiction: UK]"
    result = build_embedded_text(chunk)
    assert result.startswith(chunk.context_header)
    assert chunk.content in result


def test_build_embedded_text_without_header():
    """build_embedded_text returns plain content when header is empty."""
    chunk = _make_chunk()
    chunk.context_header = ""
    result = build_embedded_text(chunk)
    assert result == chunk.content


# ---------------------------------------------------------------------------
# ContextEnricher tests
# ---------------------------------------------------------------------------


def test_enrich_all_populates_headers():
    """enrich_all sets a non-empty context_header on every chunk."""
    chunks = [_make_chunk(index=i) for i in range(3)]
    enricher = ContextEnricher()
    enricher.enrich_all(chunks)
    for chunk in chunks:
        assert chunk.context_header != "", (
            f"Chunk {chunk.index} has empty context_header after enrich_all"
        )


def test_enrich_single_chunk():
    """enrich() populates context_header and returns the same chunk."""
    chunk = _make_chunk()
    enricher = ContextEnricher()
    result = enricher.enrich(chunk)
    assert result is chunk
    assert chunk.context_header != ""
