from __future__ import annotations

import pytest

from lexichunk import LegalChunker
from lexichunk.documents import SourceSpanIndex, build_document
from lexichunk.ingestion import from_docling, from_markdown
from lexichunk.models import DocumentSection, Section


def test_source_span_index_old_signature_uses_identity_body_maps() -> None:
    source_spans = SourceSpanIndex(
        body_starts=[2],
        body_ends=[6],
        block_starts=[0],
        source_starts=[10],
        source_ends=[14],
    )

    assert source_spans(3, 5) == (11, 13)


def test_markdown_crlf_source_span_covers_original_body() -> None:
    raw = "Alpha\r\nBeta\r\nGamma"

    (chunk,) = LegalChunker(
        min_chunk_size=0,
        include_ancestor_headers=False,
    ).chunk_documents(from_markdown(raw))

    assert chunk.content == "Alpha\nBeta\nGamma"
    assert (chunk.raw_char_start, chunk.raw_char_end) == (0, len(raw))
    assert raw[chunk.raw_char_start : chunk.raw_char_end] == raw


def test_markdown_heading_only_source_span_covers_original_heading() -> None:
    raw = "# 1. Definitions\n"

    (chunk,) = LegalChunker(
        min_chunk_size=0,
        include_ancestor_headers=False,
    ).chunk_documents(from_markdown(raw))

    assert chunk.content == "1 Definitions\n"
    assert (chunk.raw_char_start, chunk.raw_char_end) == (0, 16)
    assert raw[chunk.raw_char_start : chunk.raw_char_end] == "# 1. Definitions"


def test_markdown_crlf_source_span_maps_a_mid_body_chunk() -> None:
    raw = "Alpha\r\nBeta\r\nGamma"
    chunks = LegalChunker(
        min_chunk_size=0,
        max_chunk_size=4,
        chars_per_token=1,
        include_ancestor_headers=False,
    ).chunk_documents(from_markdown(raw))

    beta_chunk = next(chunk for chunk in chunks if chunk.content == "Beta")

    assert (beta_chunk.raw_char_start, beta_chunk.raw_char_end) == (7, 11)
    assert raw[beta_chunk.raw_char_start : beta_chunk.raw_char_end] == "Beta"


def test_markdown_crlf_partial_body_chunk_skips_leading_blank_line() -> None:
    raw = "# 1. Clause\r\n\r\nAlpha\r\n"
    chunks = LegalChunker(
        min_chunk_size=0,
        max_chunk_size=5,
        chars_per_token=1,
        include_ancestor_headers=False,
    ).chunk_documents(from_markdown(raw))

    alpha_chunk = next(chunk for chunk in chunks if chunk.content == "Alpha")

    assert (alpha_chunk.raw_char_start, alpha_chunk.raw_char_end) == (15, 20)
    assert raw[alpha_chunk.raw_char_start : alpha_chunk.raw_char_end] == "Alpha"


def test_markdown_source_spans_reset_for_each_section() -> None:
    raw = "# 1. First\r\nAlpha\r\nBeta\r\n# 2. Second\r\nGamma\r\nDelta\r\n"

    chunks = LegalChunker(
        min_chunk_size=0,
        include_ancestor_headers=False,
    ).chunk_documents(from_markdown(raw))

    assert [raw[chunk.raw_char_start : chunk.raw_char_end] for chunk in chunks] == [
        "Alpha\r\nBeta",
        "Gamma\r\nDelta",
    ]


def test_raw_offsets_cover_a_reordered_nfc_run_when_split() -> None:
    raw = "1. Clause\na\u0315\u0300z"
    chunks = LegalChunker(
        min_chunk_size=0,
        max_chunk_size=1,
        chars_per_token=1,
        include_ancestor_headers=False,
    ).chunk(raw, raw_offsets=True)

    normalized_run_chunks = [chunk for chunk in chunks if chunk.content in {"\u00e0", "\u0315"}]

    assert [chunk.content for chunk in normalized_run_chunks] == ["\u00e0", "\u0315"]
    assert [(chunk.raw_char_start, chunk.raw_char_end) for chunk in normalized_run_chunks] == [
        (10, 13),
        (10, 13),
    ]
    assert all(
        raw[chunk.raw_char_start : chunk.raw_char_end] == "a\u0315\u0300"
        for chunk in normalized_run_chunks
    )


def test_markdown_source_span_covers_a_reordered_nfc_run() -> None:
    raw = "# 1. Clause\nprefix a\u0315\u0300z suffix\n"
    chunks = LegalChunker(
        min_chunk_size=0,
        max_chunk_size=1,
        chars_per_token=1,
        include_ancestor_headers=False,
    ).chunk_documents(from_markdown(raw))

    normalized_run_chunks = [chunk for chunk in chunks if chunk.content in {"\u00e0", "\u0315"}]

    assert [chunk.content for chunk in normalized_run_chunks] == ["\u00e0", "\u0315"]
    assert [(chunk.raw_char_start, chunk.raw_char_end) for chunk in normalized_run_chunks] == [
        (19, 22),
        (19, 22),
    ]


def test_markdown_fence_requires_sufficient_bare_closing_delimiter() -> None:
    raw = (
        "# 1. Clause\n\n"
        "````python\n"
        "```\n"
        "# NOT A HEADING\n"
        "```` still code\n"
        "# ALSO NOT A HEADING\n"
        "````\n"
    )

    sections = from_markdown(raw)

    assert len(sections) == 1
    assert "# NOT A HEADING" in sections[0].text
    assert "# ALSO NOT A HEADING" in sections[0].text


def test_docling_table_preserves_equal_cells_but_deduplicates_merged_cells() -> None:
    docling_types = pytest.importorskip("docling_core.types.doc")
    docling_document_types = pytest.importorskip("docling_core.types.doc.document")

    document = docling_types.DoclingDocument(name="duplicate-table-cells")
    document.add_heading(text="1. Answers", level=1)
    document.add_table(
        data=docling_document_types.TableData(
            num_rows=2,
            num_cols=2,
            table_cells=[
                docling_document_types.TableCell(
                    text="Yes",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                ),
                docling_document_types.TableCell(
                    text="Yes",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                ),
                docling_document_types.TableCell(
                    text="Agreed",
                    start_row_offset_idx=1,
                    end_row_offset_idx=2,
                    start_col_offset_idx=0,
                    end_col_offset_idx=2,
                ),
            ],
        )
    )

    (section,) = from_docling(document)

    assert section.text.splitlines() == ["Yes | Yes", "Agreed"]


def test_build_document_custom_sanitizer_disables_source_spans() -> None:
    def classify(
        identifier: str,
        title: str,
        level: int,
    ) -> DocumentSection:
        return DocumentSection.OPERATIVE

    def remove_spaces(text: str) -> str:
        return text.replace(" ", "")

    reconstructed, clauses, source_spans = build_document(
        [
            Section(
                identifier="preamble",
                title=None,
                text="a b",
                level=-99,
                char_start=10,
                char_end=13,
            )
        ],
        classify,
        remove_spaces,
    )

    assert reconstructed == "ab\n"
    assert clauses[0].content == "ab\n"
    assert source_spans is None
