# lexichunk

**Clause-aware legal document chunking for RAG pipelines.**

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/github/license/emmcygn/lexichunk)
![CI](https://img.shields.io/github/actions/workflow/status/emmcygn/lexichunk/ci.yml?label=tests)

**Status: public beta.** `0.9.0` is the first release on PyPI
(`pip install lexichunk`). The public API is settled enough to build on, but it
is not frozen; pin a version. See [CHANGELOG.md](CHANGELOG.md) for what changed
and why.

This branch prepares the `0.9.1` patch release. Its fixes are not available
from PyPI until the corresponding release is published.

The core package has **zero required dependencies**: pure Python, stdlib and
`re` only. The optional `llama-index` extra pulls a transitive NLTK version
covered by an open advisory; [SECURITY.md](SECURITY.md#optional-dependency-advisory)
records the advisory and the scoped assessment.

---

## The problem

General-purpose chunkers treat legal text like generic prose. On contracts and
terms and conditions this can produce five specific failure modes that degrade
RAG retrieval.

**Clause fragmentation.** A fixed 512-token window can split a limitation of
liability clause from its qualifying proviso. "The Seller shall not be
liable..." may land in one chunk while "...except in the case of fraud or
wilful misconduct" lands in the next. A query about liability scope can then
retrieve incomplete or misleading context.

**Orphaned cross-references.** A chunk containing "subject to the restrictions
set out in Clause 8.2" may have no connection to Clause 8.2's content. A
retriever that cannot follow the reference can provide an incomplete context
set.

**Lost defined terms.** A chunk may use "Material Adverse Effect" without
access to its negotiated definition from Section 1. A downstream model can
substitute a generic meaning rather than the contract-specific one.

**Destroyed hierarchy.** Section 7.2(a)(iii) can become a floating text
fragment with no indication it belongs to Article VII - Indemnification.
Retrieval may then confuse operative provisions and boilerplate.

**Cross-document contamination.** Without document-level metadata on every
chunk, retrievers can pull clauses from the wrong contract, because similar
agreements often share structural language.

---

## Positioning: after Docling, not instead of

lexichunk takes Unicode plain text in and returns structured chunks. It does
not open PDFs, DOCX or HTML files and it has no OCR, no layout model and no
table reconstruction. Callers must supply text from a trusted extraction or
OCR step, and should retain the original document for verification. Those are
hard problems that [Docling][docling],
[Unstructured][unstructured] and similar tools already solve well.

The intended pipeline is: **document converter → lexichunk → vector store**.
Convert the PDF or DOCX to text or Markdown with the tool of your choice, then
hand that text to lexichunk, which adds the legal structure a general-purpose
splitter throws away - clause hierarchy, defined terms, cross-references,
clause type, jurisdiction-aware numbering. If your documents are already plain
text or Markdown, you can skip the first step entirely.

[docling]: https://github.com/docling-project/docling
[unstructured]: https://github.com/Unstructured-IO/unstructured

---

## What it does not do

Read this before adopting it.

- **No PDF, DOCX or HTML parsing.** Input is a `str`. Use Docling,
  Unstructured or an equivalent converter upstream.
- **Statute and external references are detected but never resolved.**
  `section 123 of the Insolvency Act 1986` and `Regulation (EU) 2016/679`
  produce a `CrossReference` with `target_chunk_index=None` by design - they
  point outside the document, and lexichunk resolves references only against
  the chunks it produced. Filter on `target_chunk_index is None` to route them
  to an external citator.
- **Clause typing is a keyword classifier, not a model.** Unusual drafting,
  heavily defined-term-laden clauses and short cross-referencing clauses
  commonly come back as `UNKNOWN`. Extend it with `extra_clause_signals=`
  rather than expecting coverage of every house style.
- **`classification_confidence` is not a probability.** It is the winning
  clause type's relative dominance among the types that scored, scaled down
  when the absolute evidence is thin -
  `(best / total) * min(1.0, best / 4.0)`. It is comparable between chunks of
  the same document. It is not calibrated, so do not threshold it as if it
  were a model probability.
- **Offsets index the sanitised text, not your original string.**
  `char_start`/`char_end` refer to the text after BOM stripping, CRLF→LF
  normalisation and Unicode NFC normalisation. Call
  `LegalChunker.sanitize(text)` and slice *that* string, or pass
  `raw_offsets=True` and read `raw_char_start`/`raw_char_end`.
- **`chunk.content` is not `text[char_start:char_end]` by default.** It is
  that span with the ancestor headings prepended, so a retrieved `(b)` still
  says which clause it belongs to. Pass `include_ancestor_headers=False` if
  you need exact-slice equality. Removing the prefix frees chunk budget, so
  boundaries can change. `include_context_header` does *not* control this; it
  governs the separate `context_header` field.
- **Cross-reference resolution does not read the words around a reference.**
  "paragraph 2 of Schedule 2", written from the main body, resolves to
  top-level clause 2 rather than into the schedule.
- **Lettered sub-clauses are not resolution targets under their parent's
  number.** `clause 7.3(b)` is detected, and `target_identifier` is correct,
  but it resolves to clause 7.3 rather than to the `(b)` beneath it.
- **Some documents classify entirely as `UNKNOWN`** - two contracts in a
  150-contract CUAD sample, both short and unusually formatted. That is the
  classifier declining rather than misfiring;
  `PipelineMetrics.chunks_unclassified` makes it visible without iterating
  the chunks.
- **Ambiguous cross-references stay unresolved.** When two chunks are equally
  plausible targets and neither the document section nor the top-level
  ancestor breaks the tie, `target_chunk_index` stays `None`. A wrong pointer
  is worse than no pointer.
- **`token_count` is an estimate**, `len(content) // chars_per_token` with
  `chars_per_token=4` by default. It is not a tokenizer count; if you need
  exact budgeting, measure with your own tokenizer. `max_chunk_size` is
  enforced against that estimate as a hard cap: a run that offers no
  sentence, semicolon, enumerator, newline or word boundary inside the budget
  is cut mid-word, and that is logged once at `WARNING`.
- **Definitions are document-scoped heuristics.** `defined_terms_context`
  holds definitions detected in the supplied text - not authoritative
  meanings from legislation, case law, another agreement or an incorporated
  document. Repeated or unusually formatted definitions may need caller
  review.
- **Jurisdiction profiles are drafting-pattern heuristics**, not
  jurisdictional or legal validation. A successful parse does not establish
  that a document is valid, complete, enforceable, or correctly governed by
  the selected law.
- **Output is retrieval metadata, not legal advice.** Preserve and display
  source evidence, unresolved references and extraction provenance rather
  than presenting parsed output as legal validation.
- **No calibrated *retrieval* accuracy number yet.** Structural parse
  accuracy is measured against gold annotations - see
  [Measured accuracy](#measured-accuracy) - but end-to-end retrieval quality
  is not. The companion
  [legal-rag-eval][evalharness] harness reports the current honest position:
  on 5 fixtures and 22 queries lexichunk retrieves more annotated-relevant
  chunks than a 512-character `RecursiveCharacterTextSplitter`; the gap is
  largely explained by chunk size and is not significant against a
  size-matched baseline; and the structural metrics in that harness use
  lexichunk's own parse as ground truth, so they measure self-consistency
  rather than correctness. Treat those numbers as a regression harness, not
  as a benchmark result.

[evalharness]: https://github.com/emmcygn/legal-rag-eval

`examples/offline_evidence_retrieval.py` is a dependency-free, synthetic
lexical-selection example that returns a clause, its contract-defined terms
and the source offsets. It is deliberately narrow and is not a general legal
retriever or a relevance evaluation.

For evaluation scope, comparison criteria and production-readiness guidance,
see [Evaluating lexichunk](docs/adoption-guide.md).

---

## Measured accuracy

Two synthetic fixtures ship with gold annotations whose structure was
declared *before* the document text was generated from it, so the answer key
was never read back from the parser. Reproduce with
`python -m pytest tests/test_gold_fixtures.py -s`.

| | Simulated UK PDF extraction (26 KB) | Synthetic US MSA (22 KB) |
| --- | --- | --- |
| Heading recall / precision | 100% / 100% | 100% / 100% |
| Top-level boundary recall / precision | 100% / 100% | 100% / 100% |
| Chunks straddling two top-level clauses | 0 | 0 |
| Defined-term recall | 100% | 100% |
| Cross-reference recall | 100% | 100% |
| Cross-reference target precision | 94.8% | 100% |

Both fixtures are adversarial. The UK one is an agreement as a naive PDF text
extractor leaves it: a running header and footer every 45 lines, greedy
78-column hard wrapping that splits cross-references across line breaks, and a
soft-hyphenated word. The US one is a signed MSA whose ARTICLE titles sit on a
second heading line, whose exhibits come *after* the signature block, and
which says "survive execution" in an operative clause a long way before the
real execution block.

These are structural parse metrics, not retrieval metrics - see the bullet on
retrieval accuracy above.

Historical 0.9.0 throughput on 150 CUAD contracts (US SEC exhibits):
median 0.042 s per contract, worst case 0.84 s on a 292,000-character
co-development agreement.

### External benchmarks

The companion [legal-rag-eval](https://github.com/emmcygn/legal-rag-eval)
harness evaluates clause classification on LEDGAR and answer-span containment
on CUAD. Its [versioned external evaluation report](https://github.com/emmcygn/legal-rag-eval/blob/7fd1cce4884890030b6a7a8b061d54f7757360df/docs/external_evals.md)
records dataset revisions, SDK builds, label mappings, size-matched controls,
and reproduction commands. Run `make evals` from the harness checkout after
installing its evaluation dependencies; these runs download public datasets.

Those published measurements cover earlier SDK builds, including 0.9.0;
they do not establish accuracy for this unreleased 0.9.1 patch. The harness
pins an older SDK commit by default, so record and verify the installed SDK
version and source revision when comparing a new build.

The reported keyword classifier trails a supervised baseline, and its
confidence scores are not calibrated probabilities. Treat it as a coarse
filter and validate any routing threshold on your own data. A hook for your
own classifier is described under [Additional API](#additional-api).

---

## Installation

```bash
pip install lexichunk
```

Optional framework integrations:

```bash
pip install "lexichunk[langchain]"
pip install "lexichunk[llama-index]"
pip install "lexichunk[docling]"
pip install "lexichunk[all]"
```

Releases are published from a tagged commit through GitHub's trusted-publishing
flow; the wheel on PyPI is the artifact that passed the integrations workflow.
To install a specific release straight from the repository instead:

```bash
pip install "lexichunk @ git+https://github.com/emmcygn/lexichunk.git@v0.9.0"
```

To track a reviewed commit rather than a tag, clone, review, and record the
SHA with your deployment metadata:

```bash
git clone https://github.com/emmcygn/lexichunk
cd lexichunk
python -m pip install -e ".[dev,all]"
git rev-parse HEAD
```

Then pin `git+https://github.com/emmcygn/lexichunk.git@SHA` in your dependency
manager, replacing `SHA` with that commit.

**Release publishing:** `.github/workflows/publish.yml` runs CI and the
integration build, then publishes the *same verified artifact* to TestPyPI
or PyPI via `workflow_dispatch`, or to PyPI on a `v*` tag. PyPI trusted
publishing is configured for this repository. Maintainers using another
repository or publishing target must configure its matching trusted publisher
and GitHub environment before running the workflow.

---

## Quick start

```python
from lexichunk import LegalChunker

chunker = LegalChunker(
    jurisdiction="uk",           # "uk", "us", "eu", or a registered custom key
    doc_type="contract",         # or "terms_conditions"
    max_chunk_size=512,          # approximate tokens (1 token ~= 4 chars)
    min_chunk_size=64,           # merge clauses smaller than this
    include_definitions=True,    # attach relevant definitions to each chunk
    include_context_header=True, # Contextual Retrieval pattern headers
)

chunks = chunker.chunk(contract_text)

for chunk in chunks:
    print(chunk.content)
    print(chunk.clause_type)            # ClauseType.INDEMNIFICATION
    print(chunk.hierarchy_path)         # "Article VII > Section 7.2 > (a)"
    print(chunk.cross_references)       # [CrossReference(raw_text="Clause 5.2", ...)]
    print(chunk.defined_terms_used)     # ["Material Adverse Effect", "Losses"]
    print(chunk.defined_terms_context)  # {"Material Adverse Effect": "means any event..."}
    print(chunk.context_header)         # "[Document: Service Agreement] [Section: ...]"
```

---

## Output

`chunker.chunk()` returns a `list[LegalChunk]`. Each `LegalChunk` is a typed
dataclass with these fields:

| Field | Type | Description |
|---|---|---|
| `content` | `str` | The chunk text. May begin with synthesized ancestor header lines (see `original_header`). |
| `index` | `int` | Zero-based position among all chunks from this document. |
| `hierarchy` | `HierarchyNode` | Clause position: `level`, `identifier`, `title`, `parent`. |
| `hierarchy_path` | `str` | Human-readable path, e.g. `"Article VII > Section 7.2 > (a)"`. |
| `document_section` | `DocumentSection` | `PREAMBLE`, `RECITALS`, `DEFINITIONS`, `OPERATIVE`, `SCHEDULES` or `SIGNATURES`. |
| `clause_type` | `ClauseType` | One of 31 types - `INDEMNIFICATION`, `CONFIDENTIALITY`, `TERMINATION`, `SERVICES`, `INSURANCE`, `AUDIT`, `NON_SOLICITATION`, `ACCEPTABLE_USE`, … , `UNKNOWN`. |
| `jurisdiction` | `Jurisdiction \| str` | `UK`, `US`, `EU`, or the string key of a registered custom jurisdiction. |
| `cross_references` | `list[CrossReference]` | Every detected reference to another clause or instrument. |
| `defined_terms_used` | `list[str]` | Defined terms found in this chunk's text. |
| `defined_terms_context` | `dict[str, str]` | Maps each used defined term to its contract-specific definition. Empty unless `include_definitions=True`. |
| `classification_confidence` | `float` | Relative dominance of the winning clause type, saturation-scaled. Not a calibrated probability. |
| `secondary_clause_type` | `ClauseType \| None` | The keyword runner-up. After a hook override, the highest-scoring keyword type different from the hook's primary, or `None` if none exists. |
| `cross_ref_total` | `int` | Number of cross-references detected in this chunk. |
| `cross_ref_resolved` | `int` | How many of those resolved to a `target_chunk_index`. |
| `context_header` | `str` | Prepend to `content` before embedding (Contextual Retrieval pattern). Empty unless `include_context_header=True`. |
| `document_id` | `str \| None` | Propagated document identifier - set via `LegalChunker(document_id=...)` or `chunk(text, document_id=...)`. |
| `char_start` | `int` | Start offset of the clause body in the **sanitised** source text. |
| `char_end` | `int` | End offset of the clause body in the **sanitised** source text. |
| `token_count` | `int` | Approximate token count: `len(content) // chars_per_token`. |
| `original_header` | `str` | Ancestor header lines prepended to `content` for retrieval context. |

Nested types:

| Type | Fields |
|---|---|
| `HierarchyNode` | `level: int`, `identifier: str`, `title: str \| None`, `parent: str \| None` |
| `CrossReference` | `raw_text: str`, `target_identifier: str`, `target_chunk_index: int \| None`, `target_kind: str` |
| `DefinedTerm` | `term: str`, `definition: str`, `source_clause: str` |
| `BatchResult` | `results: list[list[LegalChunk]]`, `errors: list[BatchError]` |
| `BatchError` | `index: int`, `text_preview: str`, `error: str`, `error_type: str` |

`target_kind` is the kind of thing the reference points at - `"clause"`,
`"section"`, `"paragraph"`, `"schedule"`, `"exhibit"`, `"annex"`, `"chapter"`
or `"recital"` - so a reference to `Schedule 2` is not confused with a
main-body `clause 2`.

### Serialisation and enums

`ClauseType`, `Jurisdiction` and `DocumentSection` are `str` enums, so they
compare equal to their string form and `json.dumps` accepts them directly.
`LegalChunk` round-trips through `to_dict()` / `from_dict()`;
`HierarchyNode`, `CrossReference` and `DefinedTerm` each have `to_dict()`.

```python
import json

from lexichunk import LegalChunk, LegalChunker

chunks = LegalChunker(jurisdiction="uk").chunk(contract_text)
first = chunks[0]

assert first.clause_type == first.clause_type.value  # str enum
payload = json.dumps([c.to_dict() for c in chunks])  # JSON-safe

restored = [LegalChunk.from_dict(d) for d in json.loads(payload)]
assert restored[0].content == first.content
assert restored[0].hierarchy.identifier == first.hierarchy.identifier
```

### Fallback behaviour

When no clause structure is detected, a sentence-level fallback chunker runs
instead. Under that path `hierarchy_path` is a positional placeholder of the
form `chunk-N` rather than a real clause path.
`chunk_with_metrics(text)[1].fallback_used` reports whether the fallback was
taken for a given call.

---

## Supported documents

The core API accepts Unicode plain text only. The built-in jurisdiction
profiles recognise common structures in:

| Jurisdiction | Key | Document types |
|---|---|---|
| United Kingdom | `"uk"` | Commercial contracts (service, supply, employment, shareholder agreements), terms and conditions |
| United States | `"us"` | Contracts (MSAs, NDAs, SaaS terms, employment and service agreements), terms of service, privacy policies |
| European Union | `"eu"` | Regulations and directives (GDPR, DSA, DMA, AI Act, ePrivacy) - Chapter / Article / paragraph / Annex |

Pass `doc_type="contract"` or `doc_type="terms_conditions"`. Custom
jurisdictions are registered with `register_jurisdiction()` - see
[docs/extending.md](docs/extending.md).

These profiles are drafting-pattern heuristics, not jurisdictional or legal
validation. A successful parse does not establish that a document is valid,
complete, enforceable, or correctly governed by the selected law.

### Jurisdiction differences

| Feature | UK | US | EU |
|---|---|---|---|
| Top-level grouping | Clause (flat numbering) | Article (Roman numerals) | Chapter (Roman) / Article (Arabic) |
| Numbering | `1`, `1.1`, `1.1.1`, `(a)`, `(i)` | `Article I`, `Section 1.01`, `(a)`, `(i)` | `Chapter I`, `Article 1`, `1.`, `(a)` |
| Headers | Sentence case, minimal | ALL CAPS common | Mixed case |
| Defined terms location | "Definitions" clause | "Article I - Definitions" | "Article 4 - Definitions" |
| Schedules / exhibits | "Schedule 1" | "Exhibit A" or "Schedule 1" | "Annex I" |
| Boilerplate heading | "General" | "Miscellaneous" | "Final Provisions" |
| Cross-reference style | "Clause 5.2", "paragraph (a)" | "Section 5.2", "Section 5.2(a)" | "Article 6(1)(a)" |

---

## Batch processing

`chunk_batch()` chunks several documents in one call, optionally across
worker processes.

```python
from lexichunk import LegalChunker

chunker = LegalChunker(jurisdiction="uk")

results = chunker.chunk_batch(
    [contract_text, (contract_text, "doc-2"), contract_text],
    workers=1,
)

for doc_chunks in results.results:  # list[list[LegalChunk]], input order
    print(len(doc_chunks))

for error in results.errors:  # BatchError(index, text_preview, error, error_type)
    print(error.index, error.error_type, error.error)
```

- Each element is either a plain `str` or a `(text, document_id)` tuple.
- `texts` may be any iterable - list, tuple, generator, `dict.values()` - but
  **not** a bare `str`/`bytes` (which would be chunked character by
  character) and **not** a `Mapping` (iterating one yields its keys). Both
  raise `InputError`. Pass `chunk_batch([text])` for a single document, or
  `chunk_batch(mapping.items())` to use the keys as document ids.
- A document that fails is recorded in `results.errors` and does not halt the
  batch. That holds for a generator that raises partway through too: what it
  already yielded is chunked, and the failure is one `BatchError`.
- `workers` defaults to `min(cpu_count(), len(texts))`. With `workers=1`, or a
  batch of two or fewer documents, processing is serial.
- If the process pool cannot start, `chunk_batch()` logs a `WARNING` and falls
  back to serial execution rather than raising.
- Custom (non-built-in) jurisdictions cannot be used with `workers > 1` -
  custom registrations cannot be pickled to child processes. Use `workers=1`.

**On Windows and macOS**, `workers > 1` requires the call to be guarded,
because both platforms use the `spawn` start method and re-import the
entry-point module in every worker:

```python
from lexichunk import LegalChunker

def main() -> None:
    chunker = LegalChunker(jurisdiction="uk")
    results = chunker.chunk_batch(documents, workers=4)
    print(len(results.results))

if __name__ == "__main__":
    main()
```

---

## LangChain integration

Requires the `langchain` extra - see [Installation](#installation)
(`python -m pip install -e ".[langchain]"` from a source checkout).

`LegalTextSplitter` subclasses `langchain_core.documents.BaseDocumentTransformer`.
It is an adapter, not a drop-in `TextSplitter`: `split_text()` returns
`Document` objects rather than `list[str]`, because the legal metadata on each
chunk is the point. That difference is deliberate.

```python
from lexichunk.integrations.langchain import LegalTextSplitter

splitter = LegalTextSplitter(
    jurisdiction="uk",
    doc_type="contract",
    max_chunk_size=512,
)

# list[langchain_core.documents.Document]
documents = splitter.split_text(contract_text)

# Several texts at once, with optional per-text metadata merged in
documents = splitter.create_documents(
    [text_1, text_2, text_3],
    metadatas=[{"source": "doc1.pdf"}, {"source": "doc2.pdf"}, {"source": "doc3.pdf"}],
)

for doc in documents:
    print(doc.page_content)
    print(doc.metadata["clause_type"])       # "confidentiality"
    print(doc.metadata["hierarchy_path"])    # "7 > 7.1"
    print(doc.metadata["defined_terms_used"])
    print(doc.metadata["context_header"])
    print(doc.metadata["cross_references"])  # list of dicts

# Contextual Retrieval: embed the header with the content.
texts_to_embed = [
    doc.metadata["context_header"] + "\n\n" + doc.page_content
    for doc in documents
]

# Already have Document objects from a loader? split_documents() chunks each
# one and preserves the caller's metadata; lexichunk's own keys win on
# collision (or set metadata_prefix= so they cannot collide at all).
chunked = splitter.split_documents(loaded_documents)

# transform_documents() is the BaseDocumentTransformer alias for the same call.
chunked = splitter.transform_documents(loaded_documents)
```

Output `Document.id` is unique across a `split_documents()` call even when
several input documents share the same `source` - the usual
one-`Document`-per-page loader pattern - so a vector store's upsert cannot
silently drop chunks.

Other constructor options: `document_id=`, `include_defined_terms_context=`
(adds the full definition text to metadata), `flatten_metadata=` (JSON-encodes
non-scalar values for stores that only accept scalars), and
`metadata_prefix=`.

---

## LlamaIndex integration

Requires the `llama-index` extra - see [Installation](#installation)
(`python -m pip install -e ".[llama-index]"` from a source checkout).

```python
from llama_index.core.schema import Document

from lexichunk.integrations.llama_index import LegalNodeParser

parser = LegalNodeParser(
    jurisdiction="us",
    doc_type="contract",
    max_chunk_size=512,
)

# From plain text
nodes = parser.get_nodes_from_text(contract_text)

# From LlamaIndex Document objects
nodes = parser.get_nodes_from_documents([Document(text=contract_text)])

for node in nodes:
    print(node.text)
    print(node.metadata["clause_type"])
    print(node.metadata["hierarchy_path"])
    print(node.metadata["defined_terms_used"])
```

`LegalNodeParser` subclasses `NodeParser`, so nodes participate in the rest of
the LlamaIndex ecosystem:

- `NodeRelationship.SOURCE` / `PREVIOUS` / `NEXT` and `ref_doc_id` are set on
  every `TextNode`, for provenance tracing and windowed retrieval.
- Structural metadata keys (`char_start`/`char_end`, counts, cross-references)
  are excluded from embedding and LLM text by default via
  `excluded_embed_metadata_keys`, while `clause_type`, `jurisdiction`,
  `document_section`, `hierarchy_path`, `context_header` and
  `defined_terms_used` are deliberately kept.
- Node ids are deterministic. A `Document` with no caller-supplied `id_`
  arrives carrying a fresh `uuid4`; using it would change `node_id` and the
  embed text on every run and duplicate every vector on re-ingestion, so the
  identifier is derived from a hash of the document's content instead. A
  caller-chosen `id_` always wins.
- `start_char_idx`/`end_char_idx` are lexichunk's own offsets into the
  sanitised text and cover the clause body only, so `node.text` is not
  guaranteed to be a literal substring of the source document.

Building an index from those nodes is the ordinary LlamaIndex flow - it needs
an embedding model and an LLM, so it is not exercised by this repository's
tests:

<!-- lexichunk-doctest: skip (needs a live embedding model and LLM) -->

```python
from llama_index.core import VectorStoreIndex

index = VectorStoreIndex(nodes)
response = index.as_query_engine().query("What are the indemnification obligations?")
```

Tested against langchain-core 1.6.2 and llama-index-core 0.14.24.

---

## Ingestion: reuse the structure your converter already found

`chunk()` detects headings from the text itself. When an upstream converter
has already recovered the document's structure from its layout, hand
lexichunk that structure instead - it is better than anything line-based can
recover from flattened text.

<!-- lexichunk-doctest: skip (needs the optional `docling` converter and a PDF on disk) -->

```python
from docling.document_converter import DocumentConverter

from lexichunk import LegalChunker
from lexichunk.ingestion import from_docling

result = DocumentConverter().convert("msa.pdf")
chunks = LegalChunker(jurisdiction="uk").chunk_documents(
    from_docling(result.document, jurisdiction="uk")
)
```

`chunk_documents()` runs the whole pipeline *except* heading detection.
Markdown needs no extra dependency at all:

```python
from lexichunk import LegalChunker
from lexichunk.ingestion import from_markdown

markdown = """# Services Agreement

## 1. Definitions

"Services" means the services described in Schedule 1.

## 2. Supply of the Services

The Supplier shall provide the Services in accordance with clause 1.
"""

chunks = LegalChunker(jurisdiction="uk").chunk_documents(
    from_markdown(markdown, jurisdiction="uk")
)
print(chunks[0].hierarchy_path)
```

| Adapter | Takes | Install |
| --- | --- | --- |
| `from_docling` | a `DoclingDocument` | the `docling` extra |
| `from_unstructured` | `unstructured` elements | nothing extra - duck-typed |
| `from_markdown` | a Markdown string | nothing extra |

lexichunk still has zero mandatory dependencies: importing
`lexichunk.ingestion` never imports `docling_core` or `unstructured`.

See [docs/ingestion.md](docs/ingestion.md) and
[examples/docling_pipeline.py](examples/docling_pipeline.py).

### Offsets into your original string

`char_start`/`char_end` index the sanitised text. Pass `raw_offsets=True` to
also get `raw_char_start`/`raw_char_end`, which index the exact string you
passed in:

```python
from lexichunk import LegalChunker

chunker = LegalChunker(jurisdiction="uk")
chunks = chunker.chunk(contract_text, raw_offsets=True)

for chunk in chunks[:3]:
    print(contract_text[chunk.raw_char_start : chunk.raw_char_end][:60])
```

Raw spans cover the original characters contributing to each sanitised span.
If a chunk splits a Unicode sequence that normalises to multiple characters,
its raw span covers the whole sequence. Adjacent raw spans may then overlap,
and sanitising a raw slice may return more text than that individual chunk.
Use sanitised offsets for exact chunk boundaries and raw offsets for source
highlighting; do not concatenate raw slices to reconstruct the document.


---

## Architecture

lexichunk runs an eight-stage pipeline on every document:

```
Raw Text -> sanitize (BOM, CRLF, NFC)
    |
    v
1. Structure Parser     Detect clauses, numbering, hierarchy (UK/US/EU)
    |
2. Clause Chunker       Split at clause boundaries, merge/split on size
    |                   (fallback: sentence-level splitting if no structure)
    |
3. Cross-ref Detection  Detect references (first pass, unresolved)
    |
4. Clause Classifier    Keyword scoring -> 31 clause types + confidence
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
  list[LegalChunk]
```

**Structure parser** uses jurisdiction-specific regexes to detect clause
boundaries and build a `HierarchyNode` tree, behind a heading-plausibility
gate that rejects lines which only look like headings (postal addresses,
currency amounts, dates, list items). Falls back to sentence-level splitting
when nothing is detected.

**Clause chunker** splits at detected boundaries. Undersized clauses merge
only with an adjacent sibling under the same parent - the hierarchy is never
crossed to satisfy `min_chunk_size`. Oversized clauses are split with a
cascading strategy (sentence → semicolon → enumerator → newline → word
window) that enforces `max_chunk_size` as a hard cap.

**Cross-reference detection and resolution** run in two passes: detect first,
then resolve `target_chunk_index` once every chunk exists.

**Clause classifier** scores each chunk with keyword signals, weighted by
phrase length and with position-aware bonuses. There are 31 `ClauseType`
members; 29 carry signals, while `PREAMBLE` is assigned structurally and
`UNKNOWN` is the fallback when nothing scores.

**Term extractor** scans the definitions section for `"[Term]" means`,
`'the Company' means`, hereinafter constructions and inline parenthetical
definitions, then attaches the relevant terms to each chunk. A term redefined
for a schedule is scoped to that schedule.

**Context enricher** generates the Contextual Retrieval header for each chunk.

**Stats and metrics** aggregate cross-reference resolution statistics
(`cross_ref_resolution_rate`, `cross_ref_stats`). See
[docs/architecture.md](docs/architecture.md) for per-stage timings via
`chunk_with_metrics()` and for measured throughput.

---

## Additional API

```python
from lexichunk import DefinedTerm, HierarchyNode, LegalChunker

chunker = LegalChunker(jurisdiction="uk")

# Extract all defined terms without chunking
terms: dict[str, DefinedTerm] = chunker.get_defined_terms(contract_text)
for name, term in terms.items():
    print(f"{term.term} (defined in {term.source_clause}): {term.definition[:80]}")

# Inspect parsed structure before chunking
nodes: list[HierarchyNode] = chunker.parse_structure(contract_text)
for node in nodes:
    print(f"{'  ' * node.level}{node.identifier}: {node.title}")

# Per-stage timings and pipeline facts
chunks, metrics = chunker.chunk_with_metrics(contract_text)
print(metrics.total_duration_ms, metrics.chunk_count, metrics.fallback_used)
for stage in metrics.stage_metrics:
    print(stage.name, stage.duration_ms, stage.item_count)

# Structure quality - is the parse trustworthy for this document?
print(metrics.clause_count, metrics.top_level_clause_count)
print(metrics.chunks_spanning_multiple_top_level_clauses)  # should be 0
print(metrics.heading_candidates_rejected)
print(metrics.chunks_unclassified)  # == chunk_count means no clause metadata

# Lazy iteration, and the exact string the offsets index into
sanitised = LegalChunker.sanitize(contract_text)
for chunk in chunker.chunk_iter(contract_text):
    assert 0 <= chunk.char_start <= chunk.char_end <= len(sanitised)
    print(sanitised[chunk.char_start:chunk.char_end][:60])

# Cross-reference resolution stats for the most recent call
print(chunker.cross_ref_resolution_rate)
print(chunker.cross_ref_stats)
```

---

## Testing and quality

CI enforces 92% statement coverage on the integrations job and 88% on the
dependency-free core job, where optional-dependency tests skip. Test counts
depend on the installed extras; each run reports its executed and skipped tests.

- **Snapshot tests** (`tests/test_snapshots.py`) pin the full chunk output for
  seven fixtures - a UK service agreement, UK terms and conditions, a US MSA,
  US terms of service, a GDPR excerpt, a PDF-extracted UK agreement and a
  signed US MSA with exhibits - against golden JSON in `tests/snapshots/`.
  Any behaviour change shows up as a reviewable diff. Regenerate with
  `pytest --update-snapshots`, then read the diff.
- **Gold-fixture accuracy** (`tests/test_gold_fixtures.py`) scores the parse
  against hand-built annotations declared before the fixture text was
  generated from them - see [Measured accuracy](#measured-accuracy).
  `-s` prints the table.
- **Invariant suite** (`tests/test_invariants.py`) asserts cross-cutting
  properties that no single stage owns: offsets stay inside the sanitised
  text and never overlap, `max_chunk_size` is a hard cap, every
  `target_chunk_index` is a valid index, chunks are index-ordered.
- **Property-based tests** (`tests/test_properties.py`) drive the pipeline
  with Hypothesis-generated text. CI runs them under a derandomised profile
  with a fixed deadline, so a CI failure reproduces locally.
- **Adversarial suites** (`tests/test_adversarial_*.py`,
  `tests/test_g7_adversarial_fixes.py`) capture bugs found by deliberately
  hostile review passes - each test is a regression pin for a real defect.
- **ReDoS audit** (`tests/test_redos_audit.py`) drives every regex in the
  package with pathological inputs.
- **Heading regression** (`tests/test_heading_regression.py`) is a
  table-driven set of realistic headings that must be detected and
  heading-shaped lines that must not be;
  `tests/test_heading_shapes.py` pins the per-line `detect_level` shapes
  underneath that gate.
- **Ingestion and offset suites** (`tests/test_ingestion.py`,
  `tests/test_chunk_documents.py`, `tests/test_offset_map.py`) cover the
  externally-parsed-structure path and the raw-offset back-map.
- **Random invariants** (`tests/test_random_invariants.py`) re-check the
  cross-cutting invariants over Hypothesis-generated whole documents.
- **README examples** (`tests/test_readme_examples.py`) executes every Python
  block in this file, so the documentation cannot drift from the API.
- **Benchmarks** (`benchmarks/`) run in CI with `--benchmark-disable` so they
  stay executable; measured numbers are recorded in
  [docs/architecture.md](docs/architecture.md).

Gates, all run in CI on Python 3.10–3.13 (plus Windows on 3.12):

```bash
ruff check src/ tests/ examples/ benchmarks/
mypy src/lexichunk/
pytest --cov=lexichunk --cov-fail-under=92
```

---

## Contributing and security

Issues and pull requests are welcome. Please open an issue before submitting
large changes. [CONTRIBUTING.md](CONTRIBUTING.md) covers setup, the CI gates
and the snapshot-update rule. To report a vulnerability, follow
[SECURITY.md](SECURITY.md) rather than opening a public issue.

```bash
git clone https://github.com/emmcygn/lexichunk
cd lexichunk
pip install -e ".[dev,all]"
pytest
```

---

## License

MIT - see [LICENSE](LICENSE).
