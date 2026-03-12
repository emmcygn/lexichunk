# PRD: lexchunk — Legal Document Chunking SDK

## 1. Overview

`lexchunk` is a Python SDK for intelligent text chunking optimised for legal documents in RAG (Retrieval Augmented Generation) pipelines. It addresses the systematic failure of general-purpose chunking strategies on contracts, terms and conditions, and other legal documents by preserving legal structure, clause relationships, defined terms, and cross-references.

**Target users**: Developers building legal AI products, legal tech engineers, RAG pipeline developers working with legal corpora.

**Distribution**: PyPI package (`pip install lexchunk`), MIT licence, GitHub repo with documentation and examples.

---

## 2. Problem Statement

### Why existing chunkers fail on legal documents

Every major open-source chunking tool (LangChain's RecursiveCharacterTextSplitter, LlamaIndex's SentenceSplitter, Chonkie, Unstructured.io) treats legal text like generic prose. This causes five specific failure modes:

1. **Clause fragmentation**: A 512-token window splits a limitation of liability clause from its qualifying proviso. The chunk containing "The Seller shall not be liable..." is separated from "...except in the case of fraud or wilful misconduct."

2. **Orphaned cross-references**: A chunk containing "subject to the restrictions set out in Clause 8.2" has no connection to Clause 8.2's content. The retriever cannot follow the reference.

3. **Lost defined terms**: A chunk uses "Material Adverse Effect" without access to its negotiated 200-word definition from Section 1. The LLM hallucinates a generic definition instead of using the contract-specific one.

4. **Destroyed hierarchy**: Section 7.2(a)(iii) becomes a floating text fragment with no indication it's a sub-sub-clause of Article VII — Indemnification. Retrieval cannot distinguish boilerplate from operative provisions.

5. **Cross-document contamination**: All NDAs look structurally similar. Without document-level metadata in each chunk, retrievers pull clauses from the wrong contract entirely (Document-Level Retrieval Mismatch).

### Evidence

- Fixed-size character chunking scores below 0.244 nDCG@5 on legal corpora vs ~0.59 for content-aware methods (arXiv 2603.06976, March 2026)
- LegalBench-RAG benchmark (arXiv 2408.10343) demonstrates significant retrieval quality degradation from chunking strategy choice on legal documents
- Summary-Augmented Chunking (NLLP 2025) found that prepending document context to chunks reduces Document-Level Retrieval Mismatch on legal datasets
- Anthropic's Contextual Retrieval showed 35% reduction in top-20 retrieval failure by adding chunk-specific context

---

## 3. Target Documents

### United States (top 2 by volume)
1. **Contracts**: Service agreements, MSAs, NDAs, employment agreements, SaaS terms. Hundreds of millions executed annually across 33.2M active businesses.
2. **Terms of Service / Privacy Policies**: Every consumer-facing business publishes these. Dense, clause-heavy, frequently queried by compliance teams.

### United Kingdom (top 2 by volume)
1. **Commercial contracts**: Service agreements, supply agreements, employment contracts, shareholder agreements. Companies House registers 5.4M active companies with mandatory filings.
2. **Terms and conditions**: Consumer and B2B terms. UK Consumer Rights Act 2015 makes these heavily scrutinised.

### Structural differences between UK and US contracts

| Feature | UK Convention | US Convention |
|---------|---------------|---------------|
| Top-level grouping | Clause (flat) | Article (Roman numerals) |
| Numbering | 1, 1.1, 1.1.1, (a), (i) | Article I, Section 1.01, (a), (i) |
| Headers | Sentence case, minimal | ALL CAPS common |
| Defined terms | Capitalised, often in "Definitions" clause | Capitalised, often in "Article I — Definitions" |
| Schedules/Exhibits | "Schedule 1" | "Exhibit A" or "Schedule 1" |
| Boilerplate location | End, under "General" | End, under "Miscellaneous" |
| Cross-ref style | "Clause 5.2" or "paragraph (a)" | "Section 5.2" or "Section 5.2(a)" |

---

## 4. Solution Architecture

### Design Principles
- **Zero-dependency core**: stdlib + regex only. No torch, no transformers, no spacy.
- **Pipeline architecture**: Parse → Detect Structure → Chunk → Enrich → Output. Each stage is independent and composable.
- **Config-driven jurisdiction**: UK/US rules selected via parameter, not inferred.
- **Structured output**: Every chunk is a typed dataclass with content, metadata, hierarchy, and cross-references.
- **Framework-agnostic**: Works standalone. LangChain and LlamaIndex integrations are optional extras.

### Pipeline Stages

```
Raw Text
    │
    ▼
┌─────────────────┐
│ Structure Parser │  Detect sections, clauses, numbering, hierarchy
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Term Extractor  │  Parse definitions section, build term → definition map
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Clause Chunker   │  Split at clause boundaries, respect hierarchy, merge/split oversized
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Metadata Enricher│  Tag clause type, detect cross-refs, attach defined terms, add hierarchy path
└────────┬────────┘
         │
         ▼
  List[LegalChunk]
```

---

## 5. Data Models

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class Jurisdiction(Enum):
    UK = "uk"
    US = "us"

class ClauseType(Enum):
    DEFINITIONS = "definitions"
    REPRESENTATIONS = "representations"
    WARRANTIES = "warranties"
    COVENANTS = "covenants"
    CONDITIONS = "conditions"
    INDEMNIFICATION = "indemnification"
    TERMINATION = "termination"
    CONFIDENTIALITY = "confidentiality"
    GOVERNING_LAW = "governing_law"
    FORCE_MAJEURE = "force_majeure"
    ASSIGNMENT = "assignment"
    AMENDMENT = "amendment"
    NOTICES = "notices"
    ENTIRE_AGREEMENT = "entire_agreement"
    SEVERABILITY = "severability"
    LIMITATION_OF_LIABILITY = "limitation_of_liability"
    PAYMENT = "payment"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    DATA_PROTECTION = "data_protection"
    DISPUTE_RESOLUTION = "dispute_resolution"
    BOILERPLATE = "boilerplate"
    PREAMBLE = "preamble"
    RECITALS = "recitals"
    UNKNOWN = "unknown"

class DocumentSection(Enum):
    PREAMBLE = "preamble"
    RECITALS = "recitals"
    DEFINITIONS = "definitions"
    OPERATIVE = "operative"
    SCHEDULES = "schedules"
    SIGNATURES = "signatures"

@dataclass
class CrossReference:
    """A detected reference to another section/clause."""
    raw_text: str               # e.g., "Section 2.1" or "Clause 5(a)"
    target_identifier: str      # e.g., "2.1" or "5(a)"
    target_chunk_index: Optional[int] = None  # resolved after chunking

@dataclass
class DefinedTerm:
    """A capitalised term with its contract-specific definition."""
    term: str                   # e.g., "Material Adverse Effect"
    definition: str             # The full definition text
    source_clause: str          # e.g., "1.1" — where it was defined

@dataclass
class HierarchyNode:
    """Position in the document's clause hierarchy."""
    level: int                  # 0 = top-level article/clause, 1 = section, 2 = subsection, etc.
    identifier: str             # e.g., "Article VII", "7.2", "7.2(a)"
    title: Optional[str] = None # e.g., "Indemnification"
    parent: Optional[str] = None # identifier of parent node

@dataclass
class LegalChunk:
    """A single chunk of legal text with full metadata."""
    content: str
    index: int
    
    # Structure
    hierarchy: HierarchyNode
    hierarchy_path: str         # e.g., "Article VII > Section 7.2 > (a)"
    document_section: DocumentSection
    
    # Legal metadata
    clause_type: ClauseType
    jurisdiction: Jurisdiction
    
    # Cross-references and terms
    cross_references: list[CrossReference] = field(default_factory=list)
    defined_terms_used: list[str] = field(default_factory=list)
    defined_terms_context: dict[str, str] = field(default_factory=dict)  # term → definition, for terms used in this chunk
    
    # Retrieval helpers
    context_header: str = ""    # Prepended context for embedding (Contextual Retrieval pattern)
    document_id: Optional[str] = None
    char_start: int = 0
    char_end: int = 0
```

---

## 6. Public API

### Primary Interface

```python
from lexchunk import LegalChunker

# Basic usage
chunker = LegalChunker(
    jurisdiction="uk",          # or "us"
    doc_type="contract",        # or "terms_conditions"
    max_chunk_size=512,         # tokens (approximate)
    min_chunk_size=64,          # tokens — merge smaller clauses
    include_definitions=True,   # attach relevant definitions to each chunk
    include_context_header=True # prepend hierarchy path as context (Contextual Retrieval)
)

chunks: list[LegalChunk] = chunker.chunk(text)

# Access chunk data
for chunk in chunks:
    print(chunk.content)
    print(chunk.clause_type)         # ClauseType.INDEMNIFICATION
    print(chunk.hierarchy_path)      # "Article VII > Section 7.2 > (a)"
    print(chunk.cross_references)    # [CrossReference(raw_text="Section 2.1", ...)]
    print(chunk.defined_terms_used)  # ["Material Adverse Effect", "Losses"]
    print(chunk.defined_terms_context)  # {"Material Adverse Effect": "means any event..."}
    print(chunk.context_header)      # "Contract > Indemnification > Section 7.2(a)"
```

### Definitions Access

```python
# Get all defined terms from the document
terms: dict[str, DefinedTerm] = chunker.get_defined_terms(text)
```

### Structure Access

```python
# Get the parsed document structure (useful for debugging/visualisation)
structure = chunker.parse_structure(text)
# Returns tree of HierarchyNode objects
```

### Framework Integrations (optional extras)

```python
# LangChain integration
from lexchunk.integrations.langchain import LegalTextSplitter

splitter = LegalTextSplitter(jurisdiction="uk", doc_type="contract")
documents = splitter.split_text(text)
# Returns List[Document] with metadata populated

# LlamaIndex integration
from lexchunk.integrations.llama_index import LegalNodeParser

parser = LegalNodeParser(jurisdiction="us", doc_type="contract")
nodes = parser.get_nodes_from_documents(documents)
# Returns List[TextNode] with metadata populated
```

---

## 7. Chunking Algorithm

### Step 1: Structure Detection

Detect section boundaries using jurisdiction-specific regex patterns.

**UK patterns:**
```
^\d+\.?\s+[A-Z]           # "1. Definitions" or "1 Definitions"
^\d+\.\d+\.?\s+            # "1.1 " or "1.1. "
^\d+\.\d+\.\d+\.?\s+       # "1.1.1 "
^\([a-z]\)\s+               # "(a) "
^\([ivx]+\)\s+              # "(i) ", "(ii) ", "(iv) "
^Schedule\s+\d+             # "Schedule 1"
```

**US patterns:**
```
^ARTICLE\s+[IVXLC]+        # "ARTICLE I" (Roman numerals, ALL CAPS)
^Article\s+[IVXLC]+        # "Article I" (Title case variant)
^Section\s+\d+\.\d+        # "Section 1.01"
^SECTION\s+\d+\.\d+        # "SECTION 1.01"
^\([a-z]\)\s+               # "(a) "
^\([ivx]+\)\s+              # "(i) "
^Exhibit\s+[A-Z]            # "Exhibit A"
^Schedule\s+\d+             # "Schedule 1"
```

### Step 2: Defined Terms Extraction

Scan for definition patterns:
```
"[A-Z][a-zA-Z\s]+" means       # "Material Adverse Effect" means
"[A-Z][a-zA-Z\s]+" shall mean  # "Losses" shall mean
"[A-Z][a-zA-Z\s]+" has the meaning  # "Affiliate" has the meaning
```

Build term→definition dictionary. Track which clause each term is defined in.

### Step 3: Clause-Level Chunking

1. Split text at detected clause boundaries
2. For each clause:
   - If under `min_chunk_size` → merge with next sibling clause
   - If over `max_chunk_size` → split at sub-clause boundaries
   - If still over after sub-clause split → split at sentence boundaries within the clause
3. Preserve parent hierarchy context on every chunk

### Step 4: Cross-Reference Detection

Scan each chunk for reference patterns:
```
(?:Section|Clause|Article|Paragraph|Schedule|Exhibit)\s+[\d.()a-zA-Z]+
(?:as defined in|pursuant to|subject to|in accordance with|set forth in|described in)\s+(?:Section|Clause|Article)...
```

Resolve references to chunk indices where possible (second pass after chunking).

### Step 5: Metadata Enrichment

Classify each chunk's clause type using keyword matching:

| Clause Type | Signal Keywords |
|-------------|----------------|
| DEFINITIONS | "means", "shall mean", "has the meaning", "defined as" |
| INDEMNIFICATION | "indemnify", "hold harmless", "losses", "damages" |
| TERMINATION | "terminate", "termination", "expiry", "expiration" |
| CONFIDENTIALITY | "confidential", "non-disclosure", "proprietary" |
| LIMITATION_OF_LIABILITY | "limit of liability", "aggregate liability", "shall not exceed", "in no event" |
| GOVERNING_LAW | "governed by", "governing law", "jurisdiction", "courts of" |
| FORCE_MAJEURE | "force majeure", "act of God", "beyond reasonable control" |
| PAYMENT | "payment", "invoice", "fee", "price", "consideration" |
| DATA_PROTECTION | "personal data", "data protection", "GDPR", "privacy" |
| REPRESENTATIONS | "represents", "represents and warrants" |
| WARRANTIES | "warrants", "warranty", "warranted" |
| INTELLECTUAL_PROPERTY | "intellectual property", "IP rights", "licence", "license" |
| ASSIGNMENT | "assign", "assignment", "transfer" |
| NOTICES | "notices", "notice shall be", "written notice" |
| ENTIRE_AGREEMENT | "entire agreement", "whole agreement", "supersedes" |
| SEVERABILITY | "severability", "invalid or unenforceable", "severable" |
| DISPUTE_RESOLUTION | "arbitration", "mediation", "dispute resolution" |
| AMENDMENT | "amendment", "variation", "modification" |

### Step 6: Context Header Generation

For each chunk, generate a context header following the Contextual Retrieval pattern:

```
"[Document: Service Agreement] [Section: Article VII — Indemnification > Section 7.2(a)] [Type: Indemnification] [Jurisdiction: US]"
```

This is stored in `context_header` and can be prepended to `content` before embedding.

---

## 8. Package Structure

```
lexchunk/
├── pyproject.toml
├── README.md
├── LICENSE                     # MIT
├── src/
│   └── lexchunk/
│       ├── __init__.py         # Public API exports
│       ├── chunker.py          # LegalChunker class
│       ├── models.py           # Dataclasses (LegalChunk, etc.)
│       ├── parsers/
│       │   ├── __init__.py
│       │   ├── structure.py    # Section/clause boundary detection
│       │   ├── definitions.py  # Defined terms extraction
│       │   └── references.py   # Cross-reference detection
│       ├── enrichment/
│       │   ├── __init__.py
│       │   ├── clause_type.py  # Clause type classification
│       │   └── context.py      # Context header generation
│       ├── strategies/
│       │   ├── __init__.py
│       │   ├── clause_aware.py # Primary chunking strategy
│       │   └── fallback.py     # Graceful degradation for unrecognised formats
│       ├── integrations/
│       │   ├── __init__.py
│       │   ├── langchain.py    # LangChain TextSplitter subclass
│       │   └── llama_index.py  # LlamaIndex NodeParser subclass
│       └── jurisdiction/
│           ├── __init__.py
│           ├── uk.py           # UK numbering patterns + conventions
│           └── us.py           # US numbering patterns + conventions
├── tests/
│   ├── test_chunker.py
│   ├── test_structure_parser.py
│   ├── test_definitions.py
│   ├── test_references.py
│   ├── test_clause_types.py
│   ├── test_integrations.py
│   └── fixtures/
│       ├── uk_service_agreement.txt
│       ├── us_msa.txt
│       ├── uk_terms_conditions.txt
│       └── us_terms_of_service.txt
└── examples/
    ├── basic_usage.py
    ├── langchain_rag.py
    └── compare_chunkers.py     # Side-by-side vs RecursiveCharacterTextSplitter
```

---

## 9. Success Criteria

### Must Have (MVP — end of 6-hour sprint)
- [ ] Core chunking works on UK and US contracts
- [ ] Clause boundaries respected (no mid-clause splits)
- [ ] Hierarchy path populated on every chunk
- [ ] Defined terms extracted and attached to relevant chunks
- [ ] Cross-references detected (resolution is best-effort)
- [ ] Clause type classification via keyword matching
- [ ] Context headers generated
- [ ] Installable via pip (pyproject.toml configured)
- [ ] README with usage examples
- [ ] At least 20 tests passing

### Should Have (if time permits)
- [ ] LangChain TextSplitter integration
- [ ] LlamaIndex NodeParser integration
- [ ] `compare_chunkers.py` example showing improvement over naive chunking
- [ ] Terms and conditions doc type (separate parsing logic)

### Won't Have (v1)
- PDF/DOCX parsing (text input only)
- ML-based classification (regex/heuristic only)
- Web UI or CLI
- Legislation/case law document types
- Benchmarking against LegalBench-RAG (future blog post)

---

## 10. 6-Hour Sprint Plan

| Hour | Focus | Deliverable |
|------|-------|-------------|
| 1 | Scaffold + models | `pyproject.toml`, `models.py`, package structure, test fixtures |
| 2 | Structure parser | `parsers/structure.py` — UK + US clause detection, hierarchy building |
| 3 | Chunker core | `strategies/clause_aware.py` — clause-level splitting, merge/split logic |
| 4 | Terms + refs | `parsers/definitions.py`, `parsers/references.py` — extraction and detection |
| 5 | Enrichment + context | `enrichment/clause_type.py`, `enrichment/context.py` — metadata tagging |
| 6 | Package + test + docs | Integrations, `README.md`, test suite, pyproject.toml finalisation |

### Key Risk: Regex pattern coverage
The biggest risk is regex patterns not covering enough real-world formatting variations. Mitigation: start with the 5 most common patterns per jurisdiction, test against real contract text in fixtures, and build a `fallback.py` strategy that gracefully degrades to sentence-level splitting when structure detection fails.

---

## 11. Future Roadmap (post-MVP)

1. **Legislation support**: UK Acts of Parliament, US federal statutes — different structure entirely
2. **Case law support**: Rhetorical role segmentation (facts, issues, reasoning, holding)
3. **ML-enhanced classification**: Fine-tuned classifier for clause types (replace keyword matching)
4. **LegalBench-RAG benchmarking**: Publish results comparing lexchunk vs baseline chunkers
5. **White paper**: Technical write-up of the approach, failure modes, and benchmark results
6. **Philippines legal conventions**: Leveraging the author's jurisdictional expertise
7. **Graph-based cross-reference resolution**: Build a reference graph across all chunks for multi-hop retrieval
