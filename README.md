# lexichunk

**Intelligent legal document chunking for RAG pipelines.**

![PyPI version](https://img.shields.io/badge/pypi-v0.1.0-blue)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

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

Optional framework integrations:

```bash
pip install lexichunk[langchain]      # LangChain TextSplitter integration
pip install lexichunk[llama-index]    # LlamaIndex NodeParser integration
pip install lexichunk[all]            # Both integrations
```

---

## Quick Start

```python
from lexichunk import LegalChunker

chunker = LegalChunker(
    jurisdiction="uk",          # or "us"
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
| `clause_type` | `ClauseType` | Classified type: `INDEMNIFICATION`, `CONFIDENTIALITY`, `TERMINATION`, etc. (24 types). |
| `jurisdiction` | `Jurisdiction` | `UK` or `US`. |
| `cross_references` | `list[CrossReference]` | Every detected reference to another clause. Each has `raw_text`, `target_identifier`, and `target_chunk_index` (resolved after chunking where possible). |
| `defined_terms_used` | `list[str]` | Capitalised defined terms found in this chunk's text. |
| `defined_terms_context` | `dict[str, str]` | Maps each used defined term to its full contract-specific definition. |
| `context_header` | `str` | Prepend this to `content` before embedding (Contextual Retrieval pattern). Example: `"[Document: Service Agreement] [Section: Article VII — Indemnification > Section 7.2(a)] [Type: Indemnification] [Jurisdiction: US]"`. |
| `document_id` | `str \| None` | Propagated document identifier — set via `LegalChunker(document_id=...)`. |
| `char_start` | `int` | Start character offset in the source text. |
| `char_end` | `int` | End character offset in the source text. |

---

## Supported Document Types

| Jurisdiction | Document Types |
|---|---|
| United Kingdom | Commercial contracts (service agreements, supply agreements, employment contracts, shareholder agreements), terms and conditions |
| United States | Contracts (MSAs, NDAs, SaaS terms, employment agreements, service agreements), terms of service, privacy policies |

Pass `doc_type="contract"` or `doc_type="terms_conditions"` to the chunker.

---

## Jurisdiction Differences

lexichunk applies jurisdiction-specific structural rules. The two conventions differ in numbering, header style, and cross-reference language.

| Feature | UK Convention | US Convention |
|---|---|---|
| Top-level grouping | Clause (flat numbering) | Article (Roman numerals) |
| Numbering | `1`, `1.1`, `1.1.1`, `(a)`, `(i)` | `Article I`, `Section 1.01`, `(a)`, `(i)` |
| Headers | Sentence case, minimal | ALL CAPS common |
| Defined terms location | "Definitions" clause | "Article I — Definitions" |
| Schedules/Exhibits | "Schedule 1" | "Exhibit A" or "Schedule 1" |
| Boilerplate heading | "General" | "Miscellaneous" |
| Cross-reference style | "Clause 5.2" or "paragraph (a)" | "Section 5.2" or "Section 5.2(a)" |

Select the jurisdiction at construction time with `jurisdiction="uk"` or `jurisdiction="us"`. The chunker uses the appropriate regex patterns for boundary detection and cross-reference resolution.

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
```

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

---

## Architecture

lexichunk runs a four-stage pipeline on every document:

```
Raw Text
    |
    v
+------------------+
| Structure Parser |  Detect clauses, sections, numbering, hierarchy
+--------+---------+
         |
         v
+------------------+
|  Term Extractor  |  Parse definitions section, build term -> definition map
+--------+---------+
         |
         v
+------------------+
|  Clause Chunker  |  Split at clause boundaries, merge/split on size limits
+--------+---------+
         |
         v
+------------------+
| Metadata Enricher|  Clause type, cross-refs, defined terms, context header
+--------+---------+
         |
         v
  List[LegalChunk]
```

**Structure Parser** uses jurisdiction-specific regex patterns to detect clause boundaries and build a `HierarchyNode` tree. Falls back to sentence-level splitting for unrecognised formats.

**Term Extractor** scans the definitions section for patterns like `"[Term]" means`, `"[Term]" shall mean`, and `"[Term]" has the meaning`. Builds a term-to-definition dictionary keyed by capitalised term.

**Clause Chunker** splits at detected boundaries. Merges undersized clauses with their siblings; splits oversized clauses at sub-clause boundaries then at sentence boundaries.

**Metadata Enricher** runs four enrichment passes: keyword-based clause type classification (24 types), cross-reference detection and resolution, defined term attachment (scans each chunk for known terms), and context header generation following the Contextual Retrieval pattern.

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

Issues and pull requests are welcome. Please open an issue before submitting large changes.

```bash
git clone https://github.com/lexichunk/lexichunk
cd lexichunk
pip install -e ".[dev]"
pytest
```

---

## License

MIT — see [LICENSE](LICENSE).
