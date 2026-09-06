"""Shared helpers for characterization snapshot and invariant tests.

Not a test module itself (leading underscore keeps it out of pytest
collection) — imported by ``test_snapshots.py`` and ``test_invariants.py``
so both use exactly the same (fixture, config) pairs and chunk projection.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from lexichunk import LegalChunker
from lexichunk.metrics import PipelineMetrics
from lexichunk.models import LegalChunk

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"

# (fixture_name, jurisdiction, doc_type) — the "natural" pairing for each
# fixture, per the Phase 0 spec.
FIXTURE_CONFIGS: list[tuple[str, str, str]] = [
    ("uk_service_agreement", "uk", "contract"),
    ("uk_terms_conditions", "uk", "terms_conditions"),
    ("us_msa", "us", "contract"),
    ("us_terms_of_service", "us", "terms_conditions"),
    ("eu_gdpr_excerpt", "eu", "contract"),
    # Generated fixtures with hand-built gold annotations; see
    # tests/test_gold_fixtures.py and tests/fixtures/generators/.
    ("uk_pdf_extracted_agreement", "uk", "contract"),
    ("us_msa_signed_with_exhibits", "us", "contract"),
]

DEFAULT_MAX_CHUNK_SIZE = 512
DEFAULT_MIN_CHUNK_SIZE = 64


def load_fixture(name: str) -> str:
    """Read a fixture file's raw text by its base name (no extension)."""
    return (FIXTURES_DIR / f"{name}.txt").read_text(encoding="utf-8")


def make_chunker(jurisdiction: str, doc_type: str) -> LegalChunker:
    """Build a LegalChunker with the default sizes used by the snapshots."""
    return LegalChunker(
        jurisdiction=jurisdiction,
        doc_type=doc_type,
        max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
        min_chunk_size=DEFAULT_MIN_CHUNK_SIZE,
    )


def chunk_to_snapshot_dict(chunk: LegalChunk) -> dict[str, Any]:
    """Project a LegalChunk onto the reduced, line-diffable snapshot schema."""
    return {
        "index": chunk.index,
        "hierarchy_path": chunk.hierarchy_path,
        "document_section": chunk.document_section.value,
        "clause_type": chunk.clause_type.value,
        "classification_confidence": round(chunk.classification_confidence, 3),
        "secondary_clause_type": (
            chunk.secondary_clause_type.value
            if chunk.secondary_clause_type is not None
            else None
        ),
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "token_count": chunk.token_count,
        "content_sha256": hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
        "content_head": repr(chunk.content[:80]),
        "original_header": chunk.original_header,
        "cross_references": [
            {
                "raw_text": ref.raw_text,
                "target_identifier": ref.target_identifier,
                "target_chunk_index": ref.target_chunk_index,
            }
            for ref in chunk.cross_references
        ],
        "defined_terms_used": sorted(chunk.defined_terms_used),
        "context_header": chunk.context_header,
    }


def fixture_summary_dict(metrics: PipelineMetrics) -> dict[str, Any]:
    """Project PipelineMetrics onto the compact per-fixture summary schema."""
    return {
        "chunk_count": metrics.chunk_count,
        "cross_ref_total": metrics.cross_ref_total,
        "cross_ref_resolved": metrics.cross_ref_resolved,
        "defined_term_count": metrics.defined_term_count,
        "fallback_used": metrics.fallback_used,
    }


def generate_snapshots(
    fixture_name: str, jurisdiction: str, doc_type: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the pipeline and return (per-chunk snapshot list, summary dict)."""
    text = load_fixture(fixture_name)
    chunker = make_chunker(jurisdiction, doc_type)
    chunks, metrics = chunker.chunk_with_metrics(text)
    chunk_snapshot = [chunk_to_snapshot_dict(c) for c in chunks]
    summary_snapshot = fixture_summary_dict(metrics)
    return chunk_snapshot, summary_snapshot
