# Architecture

## Pipeline Overview

`LegalChunker.chunk()` runs an 8-stage pipeline on plain-text legal documents.
Every stage is deterministic (no ML models) and uses only stdlib + `re`.

```
Input text (str)
  |
  v
[1] Structure Parsing        StructureParser
  |                           -> list[ParsedClause]
  v
[2] Chunking                  ClauseAwareChunker | FallbackChunker
  |                           -> list[LegalChunk]
  v
[3] Cross-Ref Detection       ReferenceDetector
  |                           -> populates chunk.cross_references
  v
[4] Clause Type Classification ClauseTypeClassifier
  |                           -> populates chunk.clause_type
  v
[5] Context Enrichment        ContextEnricher
  |                           -> populates chunk.context_header
  v
[6] Defined Terms             DefinitionsExtractor + _attach_defined_terms
  |                           -> populates chunk.defined_terms_*
  v
[7] Cross-Ref Resolution      resolve_references() (second pass)
  |                           -> resolves target_chunk_index
  v
[8] Stats & Metrics           Aggregate cross-ref stats
  |
  v
list[LegalChunk]
```

## Stage Details

### Stage 1: Structure Parsing

**Class**: `lexichunk.parsers.structure.StructureParser`

Scans the document line-by-line using jurisdiction-specific `detect_level()` functions. Each matching line starts a new `ParsedClause` with a level, identifier, and optional title. Non-matching text at the top of the document becomes a "preamble" clause. Children are nested by indentation level.

**Input**: Raw text (str)
**Output**: `list[ParsedClause]` in document order

### Stage 2: Chunking

**Class**: `lexichunk.strategies.clause_aware.ClauseAwareChunker` (primary) or `lexichunk.strategies.fallback.FallbackChunker` (when Stage 1 returns `[]`)

The clause-aware chunker respects clause boundaries. Clauses smaller than `min_chunk_size` are merged with neighbours; clauses exceeding `max_chunk_size` are split at sentence boundaries. Ancestor headers are prepended to maintain hierarchy context.

The fallback chunker uses sentence-level splitting with a legal-abbreviation-aware sentence boundary detector (handles "U.S.C.", "F.3d.", "Ltd.", etc.).

**Input**: `list[ParsedClause]` + original text
**Output**: `list[LegalChunk]`

### Stage 3: Cross-Reference Detection (First Pass)

**Class**: `lexichunk.parsers.references.ReferenceDetector`

Regex-based detection of legal cross-references ("Section 2.1", "Clause 5(a)", "Schedule 2", "Article III", etc.). Produces `CrossReference` objects with `raw_text` and `target_identifier`. Jurisdiction-specific patterns handle UK ("Clause", "Schedule") and US ("Section", "Article") conventions.

### Stage 4: Clause Type Classification

**Class**: `lexichunk.enrichment.clause_type.ClauseTypeClassifier`

Keyword-based scoring with 15 clause types (definitions, representations, warranties, etc.). Position-aware: end-of-document clause types (governing law, assignment, etc.) receive a bonus when they appear past the 75% mark. Produces `clause_type`, `classification_confidence`, and `secondary_clause_type`.

### Stage 5: Context Enrichment

**Class**: `lexichunk.enrichment.context.ContextEnricher`

Generates a Contextual Retrieval header for each chunk summarising its position in the document hierarchy, clause type, and document ID. This header improves retrieval accuracy when chunks are embedded.

### Stage 6: Defined Terms

**Class**: `lexichunk.parsers.definitions.DefinitionsExtractor`

Extracts defined terms from definition sections (quoted or formatted terms with "means", "refers to", etc.) and "hereinafter" inline definitions. Results are cached by SHA-256 content hash. Each chunk is then scanned for term usage, populating `defined_terms_used` and `defined_terms_context`.

### Stage 7: Cross-Reference Resolution (Second Pass)

**Function**: `lexichunk.parsers.references.resolve_references()`

Resolves `CrossReference.target_chunk_index` by matching `target_identifier` against chunk identifiers. Updates `cross_ref_total` and `cross_ref_resolved` on each chunk.

## Design Decisions

### Zero Dependencies

The core pipeline uses only Python stdlib and `re`. This keeps the install size minimal and avoids version conflicts in user environments. Optional integrations (LangChain, LlamaIndex) are extras.

### Protocol-Based Jurisdictions

`JurisdictionPatterns` is a `@runtime_checkable` Protocol, not an abstract class. Users add jurisdictions by creating any object with the required attributes and calling `register_jurisdiction()` — no inheritance needed.

### Two-Pass Cross-References

Cross-references are detected in Stage 3 (before chunking boundaries are final) and resolved in Stage 7 (after all chunks have identifiers). This two-pass design ensures resolution works even when a reference points forward in the document.

### Definition Cache

Definition extraction is SHA-256-keyed so repeated calls with the same document content skip re-extraction. The cache lives on the `LegalChunker` instance and can be cleared with `clear_definition_cache()`.

### Dataclass Immutability

Internal dataclasses (`ClassificationResult`, `PipelineMetrics`, `StageMetric`) use `frozen=True` with `MappingProxyType` and `tuple` for true immutability. The primary output type `LegalChunk` is a mutable dataclass — the pipeline populates its fields across stages. Callers should treat returned chunks as read-only; mutations may affect cached state.

## Observability

`chunk_with_metrics()` returns a `PipelineMetrics` object alongside the chunks, with per-stage wall-clock timing and item counts. Debug-level structured logging emits stage start/done messages when `logging.DEBUG` is configured.

```python
import logging
logging.basicConfig(level=logging.DEBUG)

chunker = LegalChunker(jurisdiction="uk")
chunks, metrics = chunker.chunk_with_metrics(text)
print(f"Total: {metrics.total_duration_ms:.1f}ms, {metrics.chunk_count} chunks")
for stage in metrics.stage_metrics:
    print(f"  {stage.name}: {stage.duration_ms:.1f}ms ({stage.item_count} items)")
```
