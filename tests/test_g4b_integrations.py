"""Tests for work package G4b: build_metadata enrichment, BaseDocumentTransformer-based
LangChain splitter (split_documents, transform_documents), and NodeParser-based LlamaIndex
parser (relationships, deterministic ids, lean embed metadata).
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

from lexichunk.chunker import LegalChunker
from lexichunk.integrations.langchain import _LANGCHAIN_AVAILABLE
from lexichunk.integrations.llama_index import _LLAMA_INDEX_AVAILABLE
from lexichunk.models import ClauseType, CrossReference, LegalChunk
from lexichunk.utils import build_metadata

langchain_required = pytest.mark.skipif(
    not _LANGCHAIN_AVAILABLE,
    reason="langchain-core not installed",
)
llama_index_required = pytest.mark.skipif(
    not _LLAMA_INDEX_AVAILABLE,
    reason="llama-index-core not installed",
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SAMPLE_UK = """1. Definitions

"Services" means the software services described in Schedule 1.

"Fees" means the amounts payable by the Client under this Agreement.

2. Payment

2.1 The Client shall pay the Fees within 30 days of invoice, subject to Clause 3.

3. Termination

3.1 Either party may terminate this Agreement on 30 days written notice.
"""


def _fixture_jurisdiction(name: str) -> str:
    if name.startswith("uk_"):
        return "uk"
    if name.startswith("us_"):
        return "us"
    if name.startswith("eu_"):
        return "eu"
    raise ValueError(f"cannot infer jurisdiction from fixture name {name!r}")


def _all_fixture_chunks() -> list[LegalChunk]:
    """Chunk every fixture file with definitions/context-header enrichment enabled."""
    chunks: list[LegalChunk] = []
    for path in sorted(FIXTURES_DIR.glob("*.txt")):
        jurisdiction = _fixture_jurisdiction(path.name)
        chunker = LegalChunker(
            jurisdiction=jurisdiction,
            include_definitions=True,
            include_context_header=True,
        )
        text = path.read_text(encoding="utf-8")
        chunks.extend(chunker.chunk(text, document_id=path.stem))
    return chunks


ALL_FIXTURE_CHUNKS = _all_fixture_chunks()


# ---------------------------------------------------------------------------
# build_metadata
# ---------------------------------------------------------------------------


class TestBuildMetadata:
    def _one_chunk(self) -> LegalChunk:
        chunker = LegalChunker(jurisdiction="uk", include_definitions=True, include_context_header=True)
        return chunker.chunk(SAMPLE_UK, document_id="doc-1")[0]

    def test_scalar_fields_present_by_default(self):
        chunk = self._one_chunk()
        metadata = build_metadata(chunk)
        expected_scalar_keys = {
            "clause_type",
            "jurisdiction",
            "document_section",
            "hierarchy_path",
            "hierarchy_identifier",
            "hierarchy_level",
            "context_header",
            "char_start",
            "char_end",
            "chunk_index",
            "document_id",
            "classification_confidence",
            "secondary_clause_type",
            "cross_ref_total",
            "cross_ref_resolved",
            "token_count",
            "original_header",
        }
        assert expected_scalar_keys.issubset(metadata.keys())
        assert isinstance(metadata["classification_confidence"], float)
        assert metadata["secondary_clause_type"] is None or isinstance(metadata["secondary_clause_type"], str)
        assert isinstance(metadata["cross_ref_total"], int)
        assert isinstance(metadata["cross_ref_resolved"], int)
        assert isinstance(metadata["token_count"], int)
        assert isinstance(metadata["original_header"], str)

    def test_defined_terms_context_omitted_by_default(self):
        chunk = self._one_chunk()
        metadata = build_metadata(chunk)
        assert "defined_terms_context" not in metadata

    def test_defined_terms_context_included_when_flagged(self):
        chunk = self._one_chunk()
        metadata = build_metadata(chunk, include_defined_terms_context=True)
        assert "defined_terms_context" in metadata
        assert isinstance(metadata["defined_terms_context"], dict)

    def test_cross_references_are_cross_reference_to_dict(self):
        chunk = LegalChunker(jurisdiction="uk", max_chunk_size=2048, min_chunk_size=10).chunk(
            """1. Definitions

"Confidential Information" means any information disclosed by either party.

2. Termination

2.1 Either party may terminate this Agreement on 30 days written notice, subject to Clause 1.
"""
        )[1]
        metadata = build_metadata(chunk)
        assert isinstance(metadata["cross_references"], list)
        for ref, expected in zip(chunk.cross_references, metadata["cross_references"]):
            assert expected == ref.to_dict()

    def test_secondary_clause_type_is_value_or_none(self):
        chunk = self._one_chunk()
        chunk = copy.deepcopy(chunk)
        chunk.secondary_clause_type = ClauseType.PAYMENT
        metadata = build_metadata(chunk)
        assert metadata["secondary_clause_type"] == "payment"

        chunk.secondary_clause_type = None
        metadata = build_metadata(chunk)
        assert metadata["secondary_clause_type"] is None

    def test_flatten_json_encodes_non_scalar_values(self):
        chunk = self._one_chunk()
        chunk = copy.deepcopy(chunk)
        chunk.cross_references = [CrossReference(raw_text="clause 3", target_identifier="3", target_chunk_index=2)]
        metadata = build_metadata(chunk, include_defined_terms_context=True, flatten=True)
        assert isinstance(metadata["cross_references"], str)
        assert json.loads(metadata["cross_references"]) == [
            {"raw_text": "clause 3", "target_identifier": "3", "target_chunk_index": 2, "target_kind": "clause"}
        ]
        assert isinstance(metadata["defined_terms_used"], str)
        assert isinstance(metadata["defined_terms_context"], str)
        # scalars remain scalars
        assert isinstance(metadata["clause_type"], str)
        assert isinstance(metadata["char_start"], int)

    def test_flatten_false_keeps_native_types(self):
        chunk = self._one_chunk()
        metadata = build_metadata(chunk, flatten=False)
        assert isinstance(metadata["cross_references"], list)
        assert isinstance(metadata["defined_terms_used"], list)

    @pytest.mark.parametrize("chunk", ALL_FIXTURE_CHUNKS, ids=lambda c: f"{c.document_id}-{c.index}")
    def test_every_fixture_chunk_metadata_is_json_serialisable(self, chunk):
        for include_ctx in (False, True):
            for flatten in (False, True):
                metadata = build_metadata(
                    chunk, include_defined_terms_context=include_ctx, flatten=flatten
                )
                json.dumps(metadata)  # must not raise

    def test_every_fixture_chunk_covers_all_clause_types_smoke(self):
        # Sanity: fixtures actually produced a nontrivial number of chunks.
        assert len(ALL_FIXTURE_CHUNKS) > 20


# ---------------------------------------------------------------------------
# LangChain — split_documents / transform_documents / metadata handling
# ---------------------------------------------------------------------------


@langchain_required
class TestLangChainSplitDocuments:
    def _splitter(self, **kwargs):
        from lexichunk.integrations.langchain import LegalTextSplitter

        return LegalTextSplitter(jurisdiction="uk", max_chunk_size=2048, min_chunk_size=10, **kwargs)

    def test_is_base_document_transformer_subclass(self):
        from langchain_core.documents import BaseDocumentTransformer

        from lexichunk.integrations.langchain import LegalTextSplitter

        assert issubclass(LegalTextSplitter, BaseDocumentTransformer)
        assert isinstance(self._splitter(), BaseDocumentTransformer)

    def test_split_documents_preserves_caller_metadata(self):
        from langchain_core.documents import Document

        splitter = self._splitter()
        doc = Document(page_content=SAMPLE_UK, metadata={"source": "contractA.txt", "custom": "keep-me"})
        out = splitter.split_documents([doc])
        assert len(out) > 0
        for d in out:
            assert d.metadata["custom"] == "keep-me"
            assert d.metadata["source"] == "contractA.txt"
            assert "clause_type" in d.metadata

    def test_split_documents_lexichunk_wins_on_collision(self):
        from langchain_core.documents import Document

        splitter = self._splitter()
        # caller metadata collides with a lexichunk-produced key
        doc = Document(page_content=SAMPLE_UK, metadata={"source": "contractA.txt", "clause_type": "caller-value"})
        out = splitter.split_documents([doc])
        for d in out:
            assert d.metadata["clause_type"] != "caller-value"
            assert d.metadata["clause_type"] in {ct.value for ct in ClauseType}

    def test_split_documents_metadata_prefix_namespaces_lexichunk_keys(self):
        from langchain_core.documents import Document

        splitter = self._splitter(metadata_prefix="lexichunk_")
        doc = Document(page_content=SAMPLE_UK, metadata={"clause_type": "caller-value"})
        out = splitter.split_documents([doc])
        for d in out:
            assert d.metadata["clause_type"] == "caller-value"  # caller key untouched
            assert "lexichunk_clause_type" in d.metadata
            assert d.metadata["lexichunk_clause_type"] in {ct.value for ct in ClauseType}

    def test_split_documents_deepcopies_caller_metadata(self):
        from langchain_core.documents import Document

        splitter = self._splitter()
        doc = Document(page_content=SAMPLE_UK, metadata={"tags": ["a", "b"]})
        out = splitter.split_documents([doc])
        assert len(out) > 1
        out[0].metadata["tags"].append("mutated")
        assert out[1].metadata["tags"] == ["a", "b"], "mutating one output's metadata leaked into another"

    @pytest.mark.parametrize(
        "metadata,expected_id_prefix",
        [
            ({}, None),
            ({"document_id": "from-metadata"}, "from-metadata"),
            ({"source": "from-source.txt"}, "from-source.txt"),
            ({"document_id": "from-metadata", "source": "from-source.txt"}, "from-metadata"),
        ],
    )
    def test_document_id_resolution_order_metadata(self, metadata, expected_id_prefix):
        from langchain_core.documents import Document

        splitter = self._splitter()
        doc = Document(page_content=SAMPLE_UK, metadata=dict(metadata))
        out = splitter.split_documents([doc])
        if expected_id_prefix is None:
            assert out[0].id is None
        else:
            assert out[0].id == f"{expected_id_prefix}:0"

    def test_document_id_attribute_wins_over_metadata(self):
        from langchain_core.documents import Document

        splitter = self._splitter()
        doc = Document(
            id="from-doc-id",
            page_content=SAMPLE_UK,
            metadata={"document_id": "from-metadata", "source": "from-source.txt"},
        )
        out = splitter.split_documents([doc])
        assert out[0].id == "from-doc-id:0"

    def test_constructor_document_id_is_fallback(self):
        from langchain_core.documents import Document

        splitter = self._splitter(document_id="ctor-default")
        doc = Document(page_content=SAMPLE_UK, metadata={})
        out = splitter.split_documents([doc])
        assert out[0].id == "ctor-default:0"

    def test_transform_documents_is_alias_for_split_documents(self):
        from langchain_core.documents import Document

        splitter = self._splitter()
        doc = Document(page_content=SAMPLE_UK, metadata={"source": "x"})
        via_split = splitter.split_documents([doc])
        via_transform = splitter.transform_documents([doc])
        assert len(via_split) == len(via_transform)
        assert [d.page_content for d in via_split] == [d.page_content for d in via_transform]

    def test_create_documents_metadatas_length_mismatch_raises(self):
        splitter = self._splitter()
        with pytest.raises(ValueError):
            splitter.create_documents([SAMPLE_UK, SAMPLE_UK], metadatas=[{"a": 1}])

    def test_create_documents_metadatas_merged_lexichunk_wins(self):
        splitter = self._splitter()
        docs = splitter.create_documents([SAMPLE_UK], metadatas=[{"clause_type": "caller-value", "extra": "kept"}])
        assert len(docs) > 0
        for d in docs:
            assert d.metadata["extra"] == "kept"
            assert d.metadata["clause_type"] in {ct.value for ct in ClauseType}

    def test_split_text_all_metadata_json_serialisable(self):
        splitter = self._splitter(include_defined_terms_context=True)
        docs = splitter.split_text(SAMPLE_UK)
        for d in docs:
            json.dumps(d.metadata)

    def test_flatten_metadata_option(self):
        splitter = self._splitter(flatten_metadata=True)
        docs = splitter.split_text(SAMPLE_UK)
        for d in docs:
            assert isinstance(d.metadata["cross_references"], str)
            assert isinstance(d.metadata["defined_terms_used"], str)


# ---------------------------------------------------------------------------
# LlamaIndex — relationships, deterministic ids, offsets, excluded keys
# ---------------------------------------------------------------------------


@llama_index_required
class TestLlamaIndexNodeParser:
    def _parser(self, **kwargs):
        from lexichunk.integrations.llama_index import LegalNodeParser

        return LegalNodeParser(jurisdiction="uk", max_chunk_size=2048, min_chunk_size=10, **kwargs)

    def test_is_node_parser_subclass(self):
        from llama_index.core.node_parser import NodeParser

        from lexichunk.integrations.llama_index import LegalNodeParser

        assert issubclass(LegalNodeParser, NodeParser)
        assert isinstance(self._parser(), NodeParser)

    def test_source_relationship_and_ref_doc_id(self):
        from llama_index.core.schema import Document, NodeRelationship

        parser = self._parser()
        doc = Document(text=SAMPLE_UK, doc_id="doc-1")
        nodes = parser.get_nodes_from_documents([doc])
        assert len(nodes) > 1
        for node in nodes:
            assert NodeRelationship.SOURCE in node.relationships
            assert node.ref_doc_id == "doc-1"

    def test_prev_next_relationships(self):
        from llama_index.core.schema import Document, NodeRelationship

        parser = self._parser()
        doc = Document(text=SAMPLE_UK, doc_id="doc-1")
        nodes = parser.get_nodes_from_documents([doc])
        assert len(nodes) >= 3
        assert NodeRelationship.PREVIOUS not in nodes[0].relationships
        assert NodeRelationship.NEXT in nodes[0].relationships
        assert NodeRelationship.PREVIOUS in nodes[1].relationships
        assert NodeRelationship.NEXT in nodes[1].relationships
        assert NodeRelationship.PREVIOUS in nodes[-1].relationships
        assert NodeRelationship.NEXT not in nodes[-1].relationships

    def test_node_ids_deterministic_across_runs(self):
        from llama_index.core.schema import Document

        parser = self._parser()
        doc_a = Document(text=SAMPLE_UK, doc_id="doc-1")
        doc_b = Document(text=SAMPLE_UK, doc_id="doc-1")
        nodes_a = parser.get_nodes_from_documents([doc_a])
        nodes_b = parser.get_nodes_from_documents([doc_b])
        assert [n.node_id for n in nodes_a] == [n.node_id for n in nodes_b]
        # sanity: ids are not all identical to each other (real hash, not constant)
        assert len({n.node_id for n in nodes_a}) == len(nodes_a)

    def test_node_ids_differ_for_different_documents(self):
        from llama_index.core.schema import Document

        parser = self._parser()
        nodes_a = parser.get_nodes_from_documents([Document(text=SAMPLE_UK, doc_id="doc-1")])
        nodes_b = parser.get_nodes_from_documents([Document(text=SAMPLE_UK, doc_id="doc-2")])
        assert [n.node_id for n in nodes_a] != [n.node_id for n in nodes_b]

    def test_offsets_survive_postprocessing(self):
        from llama_index.core.schema import Document

        parser = self._parser()
        doc = Document(text=SAMPLE_UK, doc_id="doc-1")
        nodes = parser.get_nodes_from_documents([doc])
        # Recompute expected offsets directly from the chunker to compare.
        chunks = LegalChunker(jurisdiction="uk", max_chunk_size=2048, min_chunk_size=10).chunk(
            SAMPLE_UK, document_id="doc-1"
        )
        assert len(nodes) == len(chunks)
        for node, chunk in zip(nodes, chunks):
            assert node.start_char_idx == chunk.char_start
            assert node.end_char_idx == chunk.char_end

    def test_source_document_metadata_merged(self):
        from llama_index.core.schema import Document

        parser = self._parser()
        doc = Document(text=SAMPLE_UK, doc_id="doc-1", metadata={"source": "contractA.txt", "custom": "keep-me"})
        nodes = parser.get_nodes_from_documents([doc])
        for node in nodes:
            assert node.metadata["source"] == "contractA.txt"
            assert node.metadata["custom"] == "keep-me"
            assert "clause_type" in node.metadata

    def test_default_excluded_metadata_keys_applied(self):
        from llama_index.core.schema import Document

        parser = self._parser()
        doc = Document(text=SAMPLE_UK, doc_id="doc-1")
        nodes = parser.get_nodes_from_documents([doc])
        expected_structural = {
            "char_start",
            "char_end",
            "chunk_index",
            "cross_references",
            "cross_ref_total",
            "cross_ref_resolved",
            "hierarchy_level",
            "token_count",
            "original_header",
            "classification_confidence",
            "secondary_clause_type",
            "document_id",
        }
        for node in nodes:
            assert expected_structural.issubset(set(node.excluded_embed_metadata_keys))
            assert expected_structural.issubset(set(node.excluded_llm_metadata_keys))
            # semantically useful keys are deliberately kept
            for kept in ("clause_type", "jurisdiction", "document_section", "hierarchy_path"):
                assert kept not in node.excluded_embed_metadata_keys

    def test_excluded_embed_metadata_keys_union_with_source_document(self):
        from llama_index.core.schema import Document

        parser = self._parser()
        doc = Document(
            text=SAMPLE_UK,
            doc_id="doc-1",
            excluded_embed_metadata_keys=["custom_secret"],
            metadata={"custom_secret": "value"},
        )
        nodes = parser.get_nodes_from_documents([doc])
        for node in nodes:
            assert "custom_secret" in node.excluded_embed_metadata_keys
            assert "char_start" in node.excluded_embed_metadata_keys

    def test_custom_excluded_embed_metadata_keys_constructor_override(self):
        from llama_index.core.schema import Document

        parser = self._parser(excluded_embed_metadata_keys=["char_start"])
        doc = Document(text=SAMPLE_UK, doc_id="doc-1")
        nodes = parser.get_nodes_from_documents([doc])
        for node in nodes:
            assert "char_start" in node.excluded_embed_metadata_keys
            # keys outside the custom override set are no longer auto-excluded
            assert "cross_references" not in node.excluded_embed_metadata_keys

    def test_get_nodes_from_text_convenience(self):
        parser = self._parser()
        nodes = parser.get_nodes_from_text(SAMPLE_UK)
        assert len(nodes) > 0
        assert all(isinstance(n.text, str) and n.text for n in nodes)

    def test_empty_text_returns_empty(self):
        parser = self._parser()
        assert parser.get_nodes_from_text("") == []

    def test_all_node_metadata_json_serialisable(self):
        from llama_index.core.schema import Document

        parser = self._parser(include_defined_terms_context=True)
        doc = Document(text=SAMPLE_UK, doc_id="doc-1")
        nodes = parser.get_nodes_from_documents([doc])
        for node in nodes:
            json.dumps(node.metadata)

    def test_flatten_metadata_option(self):
        from llama_index.core.schema import Document

        parser = self._parser(flatten_metadata=True)
        doc = Document(text=SAMPLE_UK, doc_id="doc-1")
        nodes = parser.get_nodes_from_documents([doc])
        for node in nodes:
            assert isinstance(node.metadata["cross_references"], str)


# ---------------------------------------------------------------------------
# Import-safety: simulate the framework being uninstalled entirely
# ---------------------------------------------------------------------------


def _reload_without_module(module_name: str, blocked_prefixes: tuple[str, ...], monkeypatch):
    """Reload module_name after making every import of blocked_prefixes fail."""
    real_import = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked_prefixes):
            raise ImportError(f"simulated missing dependency: {name}")
        return real_import(name, *args, **kwargs)

    # Remove any already-imported submodules of the blocked packages so the
    # reload is forced to go through builtins.__import__ again.
    for mod_name in list(sys.modules):
        if any(mod_name == prefix or mod_name.startswith(prefix + ".") for prefix in blocked_prefixes):
            monkeypatch.delitem(sys.modules, mod_name, raising=False)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr("builtins.__import__", _make_blocking_import(blocked_prefixes))

    module = sys.modules[module_name]
    return importlib.reload(module)


def _make_blocking_import(blocked_prefixes):
    import builtins

    real_import = builtins.__import__

    def blocking_import(name, globals=None, locals=None, fromlist=(), level=0):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked_prefixes):
            raise ImportError(f"simulated missing dependency: {name}")
        return real_import(name, globals, locals, fromlist, level)

    return blocking_import


@langchain_required
def test_langchain_module_import_safe_without_langchain(monkeypatch):
    """The langchain integration module must still import (and expose the class)
    when langchain-core is not installed, and raise a helpful ImportError only
    when the class is actually instantiated.
    """
    import lexichunk.integrations.langchain as lc_module

    module = _reload_without_module("lexichunk.integrations.langchain", ("langchain_core",), monkeypatch)
    try:
        assert module._LANGCHAIN_AVAILABLE is False
        assert hasattr(module, "LegalTextSplitter")
        with pytest.raises(ImportError, match="langchain-core"):
            module.LegalTextSplitter(jurisdiction="uk")
    finally:
        monkeypatch.undo()
        importlib.reload(lc_module)
        assert lc_module._LANGCHAIN_AVAILABLE is True


@llama_index_required
def test_llama_index_module_import_safe_without_llama_index(monkeypatch):
    """The llama_index integration module must still import (and expose the class)
    when llama-index-core is not installed, and raise a helpful ImportError only
    when the class is actually instantiated.
    """
    import lexichunk.integrations.llama_index as li_module

    module = _reload_without_module("lexichunk.integrations.llama_index", ("llama_index",), monkeypatch)
    try:
        assert module._LLAMA_INDEX_AVAILABLE is False
        assert hasattr(module, "LegalNodeParser")
        with pytest.raises(ImportError, match="llama-index-core"):
            module.LegalNodeParser(jurisdiction="uk")
    finally:
        monkeypatch.undo()
        importlib.reload(li_module)
        assert li_module._LLAMA_INDEX_AVAILABLE is True
