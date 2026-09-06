# lexichunk

**Intelligent legal document chunking for RAG pipelines.**

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/github/license/emmcygn/lexichunk)
![CI](https://img.shields.io/github/actions/workflow/status/emmcygn/lexichunk/ci.yml?label=tests)

**Status: Beta.** lexichunk is not yet on PyPI — the first PyPI release is
planned as `0.9.0`. Install from source until then (see below).

---

## The Problem

General-purpose chunkers treat legal text like generic prose. On contracts and terms & conditions, this produces five specific failure modes that degrade RAG retrieval quality.

**Clause fragmentation.** A 512-token window splits a limitation of liability clause from its qualifying proviso. "The Seller shall not be liable..." lands in one chunk while "...except in the case of fraud or wilful misconduct" lands in the next. Any query about liability scope retrieves an incomplete and potentially misleading answer.

**Orphaned cross-references.** A chunk containing "subject to the restrictions set out in Clause 8.2" has no connection to Clause 8.2's content. The retriever cannot follow the reference, so the LLM reasons from an incomplete picture.

**Lost defined terms.** A chunk uses "Material Adverse Effect" without access to its negotiated 200-word definition from Section 1. The LLM substitutes a generic definition rather than the contract-specific one — a silent hallucination.

**Destroyed hierarchy.** Section 7.2(a)(iii) becomes a floating text fragment with no indication it belongs to Article VII — Indemnification. Retrieval cannot distinguish operative provisions from boilerplate.

**Cross-document contamination.** Without document-level metadata on every chunk, retrievers pull clauses from the wrong contract. All NDAs look structurally similar; retrieval mismatch follows.

---

## Installation

```bash
pip install lexichunk
```

This will work once `0.9.0` is published to PyPI. Until then, install
from source:

```bash
git clone https://github.com/emmcygn/lexichunk
cd lexichunk
pip install -e .
```

Optional framework integrations:

```bash
pip install lexichunk[langchain]      # LangChain TextSplitter integration
pip install lexichunk[llama-index]    # LlamaIndex NodeParser integration
pip install lexichunk[all]            # Both integrations
pip install lexichunk[examples]       # Extra deps used by examples/ (FAISS demo, etc.)
```

(Substitute `pip install -e ".[langchain]"` etc. when installing from source.)

---

## Quick Start

```python
from lexichunk import LegalChunker

chunker = LegalChunker(
    jurisdiction="uk",          # "uk", "us", or "eu" (or a registered custom key)
    doc_type="contract",        # or "terms_conditions"
    max_chunk_size=512,         # tokens (approximate, 1 token ~= 4 chars)
    min_chunk_size=64,          # merge clauses smaller than this
    include_definitions=True,   # attach relevant definitions to each chunk
    include_context_header=True # Contextual Retrieval pattern headers
)

chunks = chunker.chunk(contract_text)

for chunk in chunks:
    print(chunk.content)
    print(chunk.clause_type)            # ClauseType.INDEMNIFICATION
    print(chunk.hierarchy_path)         # "Article VII > Section 7.2 > (a)"
    print(chunk.cross_references)       # [CrossReference(raw_text="Section 2.1", ...)]
    print(chunk.defined_terms_used)     # ["Material Adverse Effect", "Losses"]
    print(chunk.defined_terms_context)  # {"Material Adverse Effect": "means any event..."}
    print(chunk.context_header)         # "[Document: Service Agreement] [Section: ...]"
```

---

## Output

Every call to `chunker.chunk()` returns a `list[LegalChunk]`. Each `LegalChunk` is a typed dataclass:

| Field | Type | Description |
|---|---|---|
| `content` | `str` | The chunk text. |
| `index` | `int` | Zero-based position among all chunks from this document. |
| `hierarchy` | `HierarchyNode` | Clause position: `level`, `identifier`, `title`, `parent`. |
| `hierarchy_path` | `str` | Human-readable path, e.g. `"Article VII > Section 7.2 > (a)"`. |
| `document_section` | `DocumentSection` | High-level section: `PREAMBLE`, `DEFINITIONS`, `OPERATIVE`, `SCHEDULES`, `SIGNATURES`. |
| `clause_type` | `ClauseType` | Classified type: `INDEMNIFICATION`, `CONFIDENTIALITY`, `TERMINATION`, `ACCEPTABLE_USE`, `USER_RESTRICTIONS`, `ACCOUNT_SECURITY`, etc. (27 types). |
| `classification_confidence` | `float` | Relative dominance of the winning clause type among the types that scored — not a calibrated probability. |
| `secondary_clause_type` | `ClauseType \| None` | The runner-up clause type, or `None` when fewer than two types scored. |
| `jurisdiction` | `Jurisdiction` | `UK`, `US`, or `EU`. |
| `cross_references` | `list[CrossReference]` | Every detected reference to another clause. Each has `raw_text`, `target_identifier`, and `target_chunk_index` (resolved after chunking where possible). |
| `cross_ref_total` | `int` | Number of cross-references detected in this chunk. |
| `cross_ref_resolved` | `int` | Number of those cross-references that were resolved to a `target_chunk_index`. |
| `defined_terms_used` | `list[str]` | Capitalised defined terms found in this chunk's text. |
| `defined_terms_context` | `dict[str, str]` | Maps each used defined term to its full contract-specific definition. |
| `context_header` | `str` | Prepend this to `content` before embedding (Contextual Retrieval pattern). Example: `"[Document: Service Agreement] [Section: Article VII — Indemnification > Section 7.2(a)] [Type: Indemnification] [Jurisdiction: US]"`. |
| `token_count` | `int` | Approximate token count: `len(content) // chars_per_token`. Not a real tokenizer count. |
| `original_header` | `str` | Ancestor header lines prepended to `content` for retrieval context. |
| `document_id` | `str \| None` | Propagated document identifier — set via `LegalChunker(document_id=...)`. |
| `char_start` | `int` | Start character offset in the source text. |
| `char_end` | `int` | End character offset in the source text. |

Offsets (`char_start`/`char_end`) are relative to the **sanitised** text —
after BOM stripping, CRLF→LF normalization, and Unicode NFC normalization —
not necessarily the raw string you passed in. Call `LegalChunker.sanitize(text)`
to get the exact string the offsets index into.

Under the fallback chunker (used when no clause structure is detected),
`hierarchy_path` is a positional placeholder of the form `chunk-N` rather
than a real clause path. `chunk_with_metrics(text)[1].fallback_used` reports
whether the fallback path was taken for a given call.

---

## Supported Document Types

| Jurisdiction | Document Types |
|---|---|
| United Kingdom | Commercial contracts (service agreements, supply agreements, employment contracts, shareholder agreements), terms and conditions |
| United States | Contracts (MSAs, NDAs, SaaS terms, employment agreements, service agreements), terms of service, privacy policies |
| European Union | Regulations and directives (GDPR, DSA, DMA, AI Act) — structure follows Chapter / Article / paragraph / Annex |

Pass `doc_type="contract"` or `doc_type="terms_conditions"` to the chunker.

---

## Jurisdiction Differences

lexichunk applies jurisdiction-specific structural rules. The three built-in jurisdictions differ in numbering, header style, and cross-reference language.

| Feature | UK Convention | US Convention | EU Directives |
|---|---|---|---|
| Top-level grouping | Clause (flat numbering) | Article (Roman numerals) | Chapter (Roman) / Article (Arabic) |
| Numbering | `1`, `1.1`, `1.1.1`, `(a)`, `(i)` | `Article I`, `Section 1.01`, `(a)`, `(i)` | `Chapter I`, `Article 1`, `1.`, `(a)` |
| Headers | Sentence case, minimal | ALL CAPS common | Mixed case |
| Defined terms location | "Definitions" clause | "Article I — Definitions" | "Article 4 — Definitions" |
| Schedules/Exhibits | "Schedule 1" | "Exhibit A" or "Schedule 1" | "Annex I" |
| Boilerplate heading | "General" | "Miscellaneous" | "Final Provisions" |
| Cross-reference style | "Clause 5.2" or "paragraph (a)" | "Section 5.2" or "Section 5.2(a)" | "Article 6(1)(a)" |

Select the jurisdiction at construction time with `jurisdiction="uk"`, `jurisdiction="us"`, or `jurisdiction="eu"`. Custom jurisdictions can be registered via `register_jurisdiction()`.

---

## Batch processing

`LegalChunker.chunk_batch()` chunks multiple documents in one call, with
optional multi-process parallelism:

```python
results = chunker.chunk_batch(
    [contract_text_1, (contract_text_2, "doc-2"), contract_text_3],
    workers=4,
)

for doc_chunks in results.results:  # list[list[LegalChunk]], input order
    print(doc_chunks)

for error in results.errors:  # BatchError(index, text_preview, error, error_type)
    print(error.index, error.error)
```

- Each element is either a plain `str` or a `(text, document_id)` tuple.
  `texts` itself must be a `list` — passing a bare `str` as `texts` is
  rejected, since a string is iterable and would otherwise be silently
  chunked character-by-character.
- `workers` defaults to `min(cpu_count(), len(texts))`. With `workers=1`, or
  a batch of two or fewer documents, processing is serial (no subprocess
  overhead).
- **On Windows and macOS**, using `workers > 1` requires the call to be
  guarded by `if __name__ == "__main__":` in the calling script, because
  both platforms use the `spawn` process-start method, which re-imports
  the entry-point module in each worker.

  ```python
  if __name__ == "__main__":
      results = chunker.chunk_batch(documents, workers=4)
  ```

- If the process pool cannot be started (e.g. the platform or sandbox
  disallows subprocess creation), `chunk_batch()` falls back to serial
  execution and logs a `WARNING` rather than raising — batch processing
  always completes, just without parallelism in that environment.
- Custom (non-built-in) jurisdictions cannot be used with `workers > 1`,
  since custom registrations cannot be pickled to child processes; use
  `workers=1` for custom jurisdictions.

---

## LangChain Integration

Requires `pip install lexichunk[langchain]`.

```python
from lexichunk.integrations.langchain import LegalTextSplitter

splitter = LegalTextSplitter(
    jurisdiction="uk",
    doc_type="contract",
    max_chunk_size=512,
)

# Returns List[langchain_core.documents.Document]
documents = splitter.split_text(contract_text)

# Split multiple documents at once
documents = splitter.create_documents([text_1, text_2, text_3])

# Rich metadata is preserved on every Document
for doc in documents:
    print(doc.page_content)
    print(doc.metadata["clause_type"])       # e.g. "confidentiality"
    print(doc.metadata["hierarchy_path"])    # e.g. "7 > 7.1"
    print(doc.metadata["defined_terms_used"])
    print(doc.metadata["context_header"])
    print(doc.metadata["cross_references"])  # list of dicts

# Contextual Retrieval: prepend context_header before embedding
texts_to_embed = [
    doc.metadata["context_header"] + "\n\n" + doc.page_content
    for doc in documents
]

# Already have langchain_core Document objects (e.g. from a loader)?
# split_documents() chunks each one and preserves the caller's existing
# metadata on the resulting chunks — lexichunk's own metadata keys
# (clause_type, hierarchy_path, etc.) win on key collision.
chunked_documents = splitter.split_documents(loaded_documents)

# transform_documents() is the LangChain-standard alias for the same
# operation, for compatibility with pipelines that call it by that name.
chunked_documents = splitter.transform_documents(loaded_documents)

# create_documents() also accepts a parallel metadatas= list, merged the
# same way as split_documents() above.
documents = splitter.create_documents(
    [text_1, text_2, text_3],
    metadatas=[{"source": "doc1.pdf"}, {"source": "doc2.pdf"}, {"source": "doc3.pdf"}],
)
```

Note: `split_text()` deliberately returns `Document` objects rather than
plain strings — every chunk carries its clause type, hierarchy path, and
other lexichunk metadata, which would be lost if it returned `list[str]`.
This differs from the base LangChain `TextSplitter.split_text()` contract by
design.

---

## LlamaIndex Integration

Requires `pip install lexichunk[llama-index]`.

```python
from llama_index.core.schema import Document
from lexichunk.integrations.llama_index import LegalNodeParser

parser = LegalNodeParser(
    jurisdiction="us",
    doc_type="contract",
    max_chunk_size=512,
)

# Parse from plain text
nodes = parser.get_nodes_from_text(contract_text)

# Parse from LlamaIndex Document objects
llama_docs = [Document(text=contract_text)]
nodes = parser.get_nodes_from_documents(llama_docs)

# Rich metadata is on every TextNode
for node in nodes:
    print(node.text)
    print(node.metadata["clause_type"])
    print(node.metadata["hierarchy_path"])
    print(node.metadata["defined_terms_used"])

# Build a VectorStoreIndex from the nodes
from llama_index.core import VectorStoreIndex
index = VectorStoreIndex(nodes)
query_engine = index.as_query_engine()
response = query_engine.query("What are the indemnification obligations?")
```

`LegalNodeParser` subclasses LlamaIndex's `NodeParser`, so nodes participate
correctly in the rest of the LlamaIndex ecosystem:

- **Relationships** (`PREVIOUS`/`NEXT`/`SOURCE`) and `ref_doc_id` are set on
  every `TextNode`, matching what `get_nodes_from_documents()` callers
  expect for source tracing and windowed retrieval.
- Structural metadata keys (e.g. `hierarchy_path`, `document_section`,
  `char_start`/`char_end`) are excluded from the embedding text by default
  via `excluded_embed_metadata_keys`, so they do not pollute the vector
  embedding while remaining available for filtering and display.

Tested against langchain-core 1.6.2 and llama-index-core 0.14.24.

---

## Architecture

lexichunk runs an eight-stage pipeline on every document:

```
Raw Text → sanitize (BOM, CRLF, NFC)
    |
    v
1. Structure Parser     Detect clauses, numbering, hierarchy (UK/US/EU)
    |
2. Clause Chunker       Split at clause boundaries, merge/split on size
    |                   (fallback: sentence-level splitting if no structure)
    |
3. Cross-ref Detection  Detect references (first pass, unresolved)
    |
4. Clause Classifier    Keyword scoring → 27 clause types + confidence
    |
5. Context Enricher     Generate Contextual Retrieval headers
    |
6. Term Extractor       Extract defined terms, attach to chunks
    |
7. Cross-ref Resolution Resolve target_chunk_index (second pass)
    |
8. Stats & Metrics      Aggregate cross-ref stats for the completed call
    |
    v
  List[LegalChunk]
```

**Structure Parser** uses jurisdiction-specific regex patterns (UK, US, EU) to detect clause boundaries and build a `HierarchyNode` tree. Falls back to sentence-level splitting for documents with no detected structure.

**Clause Chunker** splits at detected boundaries. Merges undersized clauses with an adjacent sibling where the hierarchy allows (hierarchy is never crossed to satisfy `min_chunk_size`); splits oversized clauses using a cascading strategy (sentence → semicolon → enumerator → newline → word window) that enforces `max_chunk_size` as a hard cap.

**Cross-ref Detection & Resolution** runs in two passes: first detects references, then resolves `target_chunk_index` after all chunks are created.

**Clause Classifier** scores each chunk against 27 clause types using keyword signals with phrase-length weighting and position-aware bonuses.

**Term Extractor** scans the definitions section for patterns like `"[Term]" means`, `'the Company' means`, hereinafter, and inline parenthetical definitions. Attaches relevant terms to each chunk.

**Context Enricher** generates a header string for each chunk following the Contextual Retrieval pattern.

**Stats & Metrics** aggregates cross-reference resolution stats (`cross_ref_resolution_rate`, `cross_ref_stats`) for the call that just completed; see [docs/architecture.md](docs/architecture.md) for per-stage timing via `chunk_with_metrics()`.

Zero mandatory dependencies — the core uses stdlib and `re` only.

---

## Additional API

```python
# Extract all defined terms without chunking
terms: dict[str, DefinedTerm] = chunker.get_defined_terms(text)
for name, term in terms.items():
    print(f"{term.term} (defined in {term.source_clause}): {term.definition[:80]}...")

# Inspect parsed structure before chunking
nodes: list[HierarchyNode] = chunker.parse_structure(text)
for node in nodes:
    print(f"{'  ' * node.level}{node.identifier}: {node.title}")
```

---

## Contributing

Issues and pull requests are welcome. Please open an issue before submitting large changes. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the CI gates (`ruff`/`mypy`/`pytest`), and the snapshot-update workflow.

```bash
git clone https://github.com/emmcygn/lexichunk
cd lexichunk
pip install -e ".[dev]"
pytest
```

---

## License

MIT — see [LICENSE](LICENSE).
