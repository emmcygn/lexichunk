# Stage: Medium-Term — v1.0 Production Maturity

**Priority**: Complete before declaring v1.0 stable. These items expand coverage for specialized use cases and harden the system for diverse production workloads.
**Estimated scope**: ~25 items across advanced features, domain packs, architecture improvements, and international support.

---

## 1. Domain-Specific Clause Type Packs

### 1.1 — [ ] Create pluggable clause type pack architecture

**Explanation**: The current `CLAUSE_SIGNALS` dict is a monolithic table of 27 clause types. Adding banking, insurance, employment, and other domain-specific types to this table would bloat it for users who don't need them, and risk signal pollution (banking keywords appearing in insurance document classification).

**Rationale**: Different customers chunk different document types. A bank doesn't need insurance signals; an insurance company doesn't need banking signals. A pack-based architecture lets users opt into domain-specific classification without carrying irrelevant signal weight.

**Location**: `src/lexichunk/enrichment/clause_type.py` — new pack loading mechanism. Could leverage the existing `extra_clause_signals` parameter on `LegalChunker`.

**Pass criteria**:
- Design decision documented: either (a) packs are loaded via `extra_clause_signals` (already works, just needs curated signal dicts), or (b) a new `clause_type_packs: list[str]` parameter on `LegalChunker` that loads named packs.
- At least one pack implemented as a reference: `lexichunk.packs.banking` or similar.
- Packs can be composed: `packs=["banking", "insurance"]` merges signals.
- Test: Loading a pack doesn't affect classification of documents outside that domain.

---

### 1.2 — [ ] Create banking/finance clause type pack

**Explanation**: Credit facility agreements, indentures, bond prospectuses, and loan documents have specialized clause types not covered by the base 27: Financial Covenants, Events of Default, Conditions to Drawdown/Closing, Security Interest, Pricing Mechanics, Commitment Fees, Mandatory Prepayment, Representations (financial-specific), Waterfall/Priority of Payments.

**Rationale**: Banking/finance is one of the highest-value use cases for legal AI. Accurate clause classification enables queries like "show me all financial covenant breaches" or "what are the events of default?".

**Location**: New file `src/lexichunk/packs/banking.py` or a curated dict in documentation/examples.

**Pass criteria**:
- At least 8 new clause types with 5+ signals each.
- A credit agreement fixture (from stage_short_term 7.1) classifies at least 80% of clauses correctly with the pack loaded.
- Pack signals don't interfere with base classification when loaded on non-financial documents.

---

### 1.3 — [ ] Create insurance clause type pack

**Explanation**: Insurance policies (general liability, professional indemnity, D&O, cyber) have specialized clauses: Insuring Agreement, Coverage/Scope, Exclusions, Conditions Precedent to Coverage, Claims Procedure/Notification, Subrogation, Deductible/Excess, Aggregate Limits, Extensions, Endorsements.

**Rationale**: Insurtech companies need accurate classification to power claims analysis, coverage comparison, and policy review tools.

**Location**: Same architecture as 1.2.

**Pass criteria**:
- At least 6 new clause types with 5+ signals each.
- An insurance policy excerpt classifies correctly.
- No false positives on non-insurance documents.

---

### 1.4 — [ ] Create employment clause type pack

**Explanation**: Employment agreements have: Non-Compete/Non-Competition, Non-Solicitation, Garden Leave, IP Assignment (employment-specific), Restrictive Covenants, Probation Period, Notice Period, Severance/Termination Benefits, Vesting Schedule, Bonus/Commission, Benefits, Working Hours.

**Rationale**: HR tech platforms need to distinguish employment-specific clause types for compliance review and contract comparison.

**Location**: Same architecture as 1.2.

**Pass criteria**:
- At least 6 new clause types.
- An employment agreement excerpt classifies correctly.

---

## 2. Advanced Definition Extraction

### 2.1 — [ ] Add formatting-aware definition extraction (bold/italic)

**Explanation**: Many legal documents define terms using formatting instead of (or in addition to) quotation marks: **Company** means..., *Affiliate* means..., or even COMPANY means... (all-caps). The current extractor relies entirely on quote characters (`"`, `'`, `\u201c`, `\u201d`, `\u2018`, `\u2019`) and misses all formatting-based definitions.

**Rationale**: An estimated 25-35% of legal documents use formatting-based definitions, especially legacy documents, government contracts, and documents converted from PDF/Word where quote characters were lost during OCR.

**Location**: `src/lexichunk/parsers/definitions.py` — add new pattern(s) for unquoted capitalised terms followed by definition verbs.

**Pass criteria**:
- A new pattern matches: `Company means the entity...` (no quotes, capitalised word + "means").
- Pattern requires: (a) the term is capitalised, (b) followed by a definition verb, (c) the term is 2-60 characters.
- The pattern has higher false-positive risk, so it should only be used as a fallback when quote-based patterns find fewer than expected terms.
- OR: Make it opt-in via a `detect_unquoted_definitions: bool = False` parameter.
- Test: `"Company means XYZ Corp."` extracts `"Company"`.
- Test: `"The company means business."` does NOT extract (lowercase).
- Test: `"Nothing means everything"` does NOT extract ("Nothing" is in `_SKIP_TERMS`).

---

### 2.2 — [ ] Add schedule-based definition extraction

**Explanation**: Some contracts define terms in a Schedule rather than in the body: "Schedule 1 — Definitions". The `_find_definitions_section()` method searches for a clause header containing "definitions" — but if definitions are in a Schedule, the Schedule is detected at level -1 and may be handled differently.

**Rationale**: Construction contracts (NEC, JCT) and government procurement contracts frequently put definitions in Schedule 1. Missing these means 100% of defined terms in that document type are lost.

**Location**: `src/lexichunk/parsers/definitions.py` — `_find_definitions_section()` should also search Schedule/Annex headers.

**Pass criteria**:
- A document with `"Schedule 1 — Definitions"` correctly identifies the Schedule as the definitions section.
- Terms are extracted from the Schedule content.
- The `source_clause` reflects the Schedule identifier.
- Test: A document with definitions only in Schedule 1 (not in the body) extracts all terms.

---

## 3. Cross-Reference Resolution Improvements

### 3.1 — [ ] Improve partial match resolution scoring

**Explanation**: When a reference to `"Section 4"` can't find an exact chunk match, the partial matcher finds the first child chunk whose identifier starts with `"4."`. This is greedy — it always picks the first child in document order, regardless of semantic relevance. A better approach would score candidates by proximity to the reference location.

**Rationale**: In a document where Section 4 has sub-sections 4.1-4.10, a reference to "Section 4" from Section 7 should ideally resolve to the parent (4) not the first child (4.1). But since there's no chunk for the parent (its content was distributed to children), picking the first child is a reasonable heuristic. The improvement is to prefer the child that contains the most representative content.

**Location**: `src/lexichunk/parsers/references.py` — `_partial_match()` method.

**Pass criteria**:
- Document the current behavior (first child wins) and why it's acceptable.
- OR: Add proximity scoring (prefer the child closest to the reference source).
- Test: Reference from Section 7 to "Section 4" resolves to the first sub-section of 4.

---

### 3.2 — [ ] Add EU-style cross-reference patterns

**Explanation**: EU legislation uses distinctive reference patterns not covered by the current detector: `"Article 6(1), point (a)"`, `"the first subparagraph of Article 5(1)"`, `"in accordance with the procedure referred to in Article 93(2)"`. The current patterns match `"Article 6(1)(a)"` but not the textual variants.

**Rationale**: EU legislative text is heavily cross-referenced. Missing EU-specific patterns means the cross-reference data for EU documents is substantially incomplete.

**Location**: `src/lexichunk/parsers/references.py` — add EU-specific entries to `EXTENDED_PATTERNS`.

**Pass criteria**:
- New patterns match: `"Article 6(1), point (a)"`, `"the first subparagraph of Article 5(1)"`, `"paragraph 2 of Article 12"`.
- Test: GDPR-style cross-references are detected.
- Existing UK/US patterns unaffected.

---

## 4. Architecture Improvements

### 4.1 — [ ] Add chunk content hash for deduplication

**Explanation**: The pipeline can produce chunks with identical content when the same text appears in multiple contexts (e.g., a boilerplate clause copied across schedules). Currently there's no mechanism to detect or flag duplicate chunks.

**Rationale**: Duplicate chunks in a RAG index waste storage and can skew retrieval results (the same text appears multiple times with different metadata). A content hash enables downstream deduplication.

**Location**: `src/lexichunk/models.py` — add `content_hash: str` field to `LegalChunk`. `src/lexichunk/chunker.py` — populate with SHA-256 of normalized content.

**Pass criteria**:
- Each `LegalChunk` has a `content_hash` field (SHA-256 hex digest of lowercased, whitespace-normalized content).
- Two chunks with identical content have the same hash.
- Two chunks with different content have different hashes.
- Test: Duplicate detection works.
- Backward compatible: `content_hash` has a default value of `""` for deserialization of old chunks.

---

### 4.2 — [ ] Add thread safety documentation and guards

**Explanation**: `LegalChunker` instances maintain mutable state: `_definition_cache`, `_last_cross_ref_stats`. If a single `LegalChunker` instance is used concurrently from multiple threads (e.g., in a web server), these shared mutable objects could cause race conditions.

**Rationale**: Production deployments typically share a single chunker instance across request handlers. Without thread safety, concurrent requests could corrupt the definition cache or produce wrong cross-ref stats.

**Location**: `src/lexichunk/chunker.py` — `__init__()`, `_run_pipeline()`, `clear_definition_cache()`.

**Pass criteria**:
- Option A: Add `threading.Lock` guards around cache read/write and stats update.
- Option B: Document that `LegalChunker` is NOT thread-safe and users must create one instance per thread.
- Test (if Option A): Concurrent `chunk()` calls from 4 threads produce correct results without data corruption.

---

### 4.3 — [ ] Add pipeline stage hook mechanism

**Explanation**: Users may want to inject custom processing between pipeline stages (e.g., custom NER extraction after structure parsing, custom metadata after classification). Currently the only extension point is `extra_clause_signals`.

**Rationale**: Power users (legal AI teams) need extensibility beyond clause type signals. A hook mechanism would let them add custom enrichment without forking the library.

**Location**: `src/lexichunk/chunker.py` — `_run_pipeline()`.

**Pass criteria**:
- Design a callback mechanism: `on_after_stage(stage_name: str, chunks: list[LegalChunk]) -> list[LegalChunk]`.
- Add `stage_hooks: dict[str, Callable] | None` parameter to `LegalChunker.__init__()`.
- Hooks are called after each named stage with the current chunk list.
- Test: A hook that adds a custom metadata field to each chunk works correctly.
- Test: A hook that filters chunks reduces the output.
- Hooks are optional — default is `None` (no hooks, zero overhead).

---

## 5. International / Multi-Language Support

### 5.1 — [ ] Add language detection utility

**Explanation**: The SDK assumes English-language documents. EU directives exist in 24 official languages. Some contracts are bilingual (English + local language). Processing a French or German document with English regex patterns would produce garbage results.

**Rationale**: Graceful degradation is better than silent failure. If the SDK can detect that a document is non-English, it can fall back to the sentence-level chunker or raise a clear warning.

**Location**: New utility in `src/lexichunk/utils.py` — a lightweight language detection heuristic (no external dependencies).

**Pass criteria**:
- A function `detect_language(text: str) -> str` that returns an ISO 639-1 code (`"en"`, `"fr"`, `"de"`, etc.).
- Uses a simple heuristic: check for presence of common English function words ("the", "and", "of", "shall", "means") vs. other languages.
- `LegalChunker` logs a warning if detected language is not English.
- No new dependencies — heuristic only.
- Test: English text returns `"en"`. French text returns `"fr"`. Mixed text returns `"en"` (majority language).

---

### 5.2 — [ ] Add multi-language abbreviation sets

**Explanation**: EU documents in French use `art.` (article), `al.` (alinéa), `J.O.` (Journal Officiel). German uses `Art.` (Artikel), `Abs.` (Absatz), `Nr.` (Nummer). These would cause false sentence splits with the English-only abbreviation list.

**Rationale**: If/when non-English support is added, abbreviation handling must be language-aware.

**Location**: `src/lexichunk/strategies/fallback.py` — parameterize abbreviation list by language.

**Pass criteria**:
- `DEFAULT_ABBREVIATIONS` is renamed to `EN_ABBREVIATIONS`.
- New `FR_ABBREVIATIONS`, `DE_ABBREVIATIONS` tuples added.
- `FallbackChunker` accepts a `language: str = "en"` parameter.
- Test: French abbreviations don't cause false splits in French text.

---

## 6. Signature / Execution Page Detection

### 6.1 — [ ] Improve signature section detection

**Explanation**: Current signature markers are limited to traditional phrases: `"in witness whereof"`, `"executed by"`, `"signed by"`, etc. Modern contracts increasingly use: `"E-SIGNATURE"`, `"DocuSign"`, `"Signed electronically by"`, `"SIGNATURE PAGE FOLLOWS"`. US notarial blocks use: `"STATE OF ___"`, `"COUNTY OF ___"`, `"NOTARY PUBLIC"`.

**Rationale**: If signature sections aren't detected, they become OPERATIVE chunks, polluting retrieval results with non-substantive content.

**Location**: `src/lexichunk/jurisdiction/uk.py`, `us.py`, `eu.py` — `signature_markers` tuples. `src/lexichunk/parsers/structure.py` — `_detect_document_section()`.

**Pass criteria**:
- Add: `"e-signature"`, `"docusign"`, `"signed electronically"`, `"signature page"`, `"execution page"`, `"notary public"`, `"state of"` (in signature context).
- Test: A document ending with `"SIGNATURE PAGE\n\nBy: ___________\nName:\nTitle:"` classifies the final section as SIGNATURES.
- Negative: `"The state of the economy"` does NOT trigger SIGNATURES classification.

---

### 6.2 — [ ] Detect cover pages / execution pages at document start

**Explanation**: Many contracts have a cover page or execution page at the beginning: `"This Agreement is entered into as of [date] by and between: [Party A] and [Party B]"`. This is currently classified as PREAMBLE (which is correct). However, some documents have a formal cover page with minimal text (`"MASTER SERVICES AGREEMENT"` + party names + date) that should be distinguished from substantive preamble text.

**Rationale**: For document metadata extraction (parties, date, agreement type), cover page text is highly valuable. For substantive legal analysis, it's noise. Distinguishing them improves downstream filtering.

**Location**: `src/lexichunk/parsers/structure.py` — enhance preamble detection.

**Pass criteria**:
- Short preamble text (< 200 chars) before the first clause is tagged with a metadata flag or a distinct identifier.
- OR: Document that this is out of scope for v1.0 and preamble handling is sufficient.

---

## 7. Schedule / Exhibit Internal Structure

### 7.1 — [ ] Parse internal structure within Schedules and Exhibits

**Explanation**: Schedules often contain their own internal hierarchy: numbered items, tables, sub-headings. The current pipeline detects the Schedule boundary but treats everything inside as a single blob of text. A pricing schedule with 20 line items becomes one oversized chunk.

**Rationale**: Schedules contain some of the most queried content in contracts (pricing, SLAs, permitted uses, property descriptions). Breaking them into meaningful sub-chunks enables precise retrieval.

**Location**: `src/lexichunk/strategies/clause_aware.py` — handle Schedule-level clauses differently, or recursively parse their internal structure.

**Pass criteria**:
- A Schedule with numbered items (`1.`, `2.`, `3.`) produces separate chunks for each item.
- A Schedule with sub-headings produces chunks per sub-heading.
- The `hierarchy_path` includes the Schedule identifier: `"Schedule 1 > 1. Software Development"`.
- Test: A pricing schedule with 5 items produces 5 chunks.
- Test: A schedule with no internal structure produces 1 chunk (no over-splitting).

---

## 8. Performance & Resilience

### 8.1 — [ ] Add pipeline-level timeout guard

**Explanation**: While the ReDoS audit (v0.8.0) verified that individual regex patterns don't hang, there's no guard against the *overall pipeline* taking too long on pathologically complex documents (e.g., a 10MB document with 50,000 clause headers that causes O(n²) behavior in the structure parser or cross-reference resolver).

**Rationale**: Production services need SLA guarantees. A single document that takes 60 seconds to chunk can block a request queue.

**Location**: `src/lexichunk/chunker.py` — `_run_pipeline()` or `chunk()`.

**Pass criteria**:
- Add `timeout_seconds: float | None = None` parameter to `LegalChunker.__init__()`.
- If processing exceeds the timeout, raise a new `TimeoutError` (or `InputError`) with a descriptive message.
- Implementation: check elapsed time between stages (not per-regex, which would add overhead).
- Test: A large document with `timeout_seconds=0.001` raises the timeout error.
- Default: `None` (no timeout, backward compatible).

---

### 8.2 — [ ] Add structured error reporting for partial pipeline failures

**Explanation**: If the definitions extractor fails on one document in a batch, the entire document is recorded as a `BatchError`. But there's no mechanism for partial success — a document that chunks correctly but fails during definition extraction still loses all its chunks.

**Rationale**: Graceful degradation is critical in production. A document should still produce chunks even if one enrichment stage fails.

**Location**: `src/lexichunk/chunker.py` — `_run_pipeline()` error handling per stage.

**Pass criteria**:
- Each pipeline stage is wrapped in a try/except.
- If a non-critical stage (definitions, cross-refs, classification, context) fails, the pipeline continues with partially-enriched chunks.
- A warning is logged with the stage name and error.
- `PipelineMetrics` gains a `warnings: list[str]` field for partial failures.
- Test: A document where the definitions extractor raises still produces chunks with `clause_type` and `cross_references` populated.
