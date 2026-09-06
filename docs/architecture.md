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

A container heading written over two lines (`ARTICLE I` above `DEFINITIONS`, `Chapter I` above `General provisions`) adopts the second line as its title when that line is short, is not itself a detected heading, and does not end like a sentence; an ALL-CAPS line is re-cased. The line is only read — it stays in the clause's body text and no character offset changes.

`document_section` is classified per clause and then inherited: a clause that would otherwise be `OPERATIVE` takes the section of its nearest enclosing `SCHEDULES`, `RECITALS` or `DEFINITIONS` ancestor, so `SCHEDULE 1 > 1 — Overview` is `SCHEDULES` and `1 — Definitions > 1.1` is `DEFINITIONS`. A descendant with a section of its own (a `Definitions` paragraph inside a Schedule) keeps it.

**Input**: Raw text (str)
**Output**: `list[ParsedClause]` in document order

### Stage 2: Chunking

**Class**: `lexichunk.strategies.clause_aware.ClauseAwareChunker` (primary) or `lexichunk.strategies.fallback.FallbackChunker` (when Stage 1 finds no clause structure — either returns `[]` or only a preamble clause)

The clause-aware chunker respects clause boundaries. Clauses smaller than `min_chunk_size` are merged with an adjacent sibling where the hierarchy allows; hierarchy is never crossed to satisfy `min_chunk_size` (a clause is never merged into a sibling's subtree, or across a parent boundary, purely to hit the minimum). `max_chunk_size` is enforced as a hard cap: an oversized clause is run through a cascading splitter that tries, in order, sentence boundaries, then semicolons, then enumerated sub-items (`(a)`, `(i)`, etc.), then newlines, and finally a word window — falling through to the next strategy only when the current one cannot produce pieces under the cap. A single warning is logged if an indivisible run (e.g. one unbroken word or number) still exceeds `max_chunk_size` after all strategies are exhausted. Ancestor headers are prepended to maintain hierarchy context.

Finally, a group whose whole body is heading lines (`Article I`, `Chapter I`, `SCHEDULE 1 — SERVICES DESCRIPTION`) is folded into the group that starts with its first child, whatever their levels, provided the result still fits `max_chunk_size`. Such a chunk retrieves nothing on its own and displaces the clause it announces. The merged chunk is labelled by the child, starts at the heading's `char_start`, and carries the heading text in its body rather than as a prepended ancestor header; the absorbed identifier is recorded so `Schedule 1` and `Article I` references still resolve to it.

The fallback chunker uses sentence-level splitting with a legal-abbreviation-aware sentence boundary detector (handles "U.S.C.", "F.3d.", "Ltd.", etc.).

**Input**: `list[ParsedClause]` + original text
**Output**: `list[LegalChunk]`

### Stage 3: Cross-Reference Detection (First Pass)

**Class**: `lexichunk.parsers.references.ReferenceDetector`

Regex-based detection of legal cross-references ("Section 2.1", "Clause 5(a)", "Schedule 2", "Article III", "Article 6(1)(a)", etc.). Produces `CrossReference` objects with `raw_text` and `target_identifier`. Jurisdiction-specific patterns handle UK ("Clause", "Schedule"), US ("Section", "Article", "Exhibit"), and EU ("Article", "Chapter", "Annex", "Recital") conventions.

### Stage 4: Clause Type Classification

**Class**: `lexichunk.enrichment.clause_type.ClauseTypeClassifier`

Keyword-based scoring with 31 clause types (definitions, representations, warranties, indemnification, data protection, etc.). Position-aware: end-of-document clause types (governing law, assignment, etc.) receive a bonus when they appear past the 75% mark. Produces `clause_type`, `classification_confidence`, and `secondary_clause_type`.

### Stage 5: Context Enrichment

**Class**: `lexichunk.enrichment.context.ContextEnricher`

Generates a Contextual Retrieval header for each chunk summarising its position in the document hierarchy, clause type, and document ID. This header improves retrieval accuracy when chunks are embedded.

### Stage 6: Defined Terms

**Class**: `lexichunk.parsers.definitions.DefinitionsExtractor`

Extracts defined terms from definition sections (quoted or formatted terms with "means", "refers to", etc.) and "hereinafter" inline definitions. Results are cached by SHA-256 content hash. Each chunk is then scanned for term usage, populating `defined_terms_used` and `defined_terms_context`.

**Scoping of redefined terms.** A term may be defined more than once — the main body defines it, and a schedule then redefines it for its own purposes (`For the purposes of this Schedule 2 only, "Services" means the managed hosting services...`). The definition attached to a chunk is the one from the **nearest enclosing container**: if the schedule the chunk sits in defines the term itself, that schedule-local definition wins; otherwise the main-body definition is used. Definitions inside a container never leak outward, so a chunk in the main body is unaffected by a schedule's redefinition. The per-container pass runs only when the document actually has schedule containers and at least one defined term.

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

### Structure-quality metrics

Timings tell you the pipeline ran. These fields tell you whether it
*understood this contract* — the question that actually matters when you point
lexichunk at a new corpus and cannot eyeball 4,000 documents.

| Field | Meaning | How to read it |
| --- | --- | --- |
| `clause_count` | `ParsedClause` objects from Stage 1, including the synthetic preamble. | Near-zero on a document you expect to be structured means the extraction layer, not the contract, changed. |
| `top_level_clause_count` | Root structural units — parsed clauses with no parent (preamble, each top-level clause, each Schedule/Article). | The document's own outline size. Compare `chunk_count` against it. |
| `chunks_spanning_multiple_top_level_clauses` | Chunks whose `[char_start, char_end)` overlaps more than one root unit. | **0 by design.** The clause-aware chunker never merges two container-level groups, so anything else is an over-merge putting two unrelated clauses behind one embedding. Assert on it in CI. |
| `chunks_with_multiple_clauses` | Chunks that gathered more than one *distinct* clause identifier. | Informational. Sub-clause grouping is how `min_chunk_size` is honoured without crossing hierarchy. The pieces of one over-sized clause are not counted — they share an identifier. |
| `chunks_below_min` | Chunks under `min_chunk_size` tokens. | Expected to be non-zero: `min_chunk_size` is a preference, hierarchy is a fact. A short, structurally isolated clause is emitted short rather than folded into a neighbour. |
| `heading_candidates_rejected` | Lines `detect_level` proposed as headings that the plausibility gate then vetoed. | Table-of-contents entries, running headers, wrapped ALL-CAPS paragraphs, fee-schedule list items. A jump against a comparable document points at the extraction layer. |
| `chunks_unclassified` | Chunks whose `clause_type` is `UNKNOWN` — the classifier declining rather than guessing. | Some are normal (a signature block, a fee table). `chunks_unclassified == chunk_count` is the one worth alerting on: the document carries *no* clause metadata at all. A CUAD evaluation saw that on 2 of 150 contracts, both short and unusually formatted. Read it next to `fallback_used`. |
| `fallback_used` | The sentence-level `FallbackChunker` ran because Stage 1 found no structure. | On a numbered contract this means detection failed outright. |

```python
chunks, metrics = chunker.chunk_with_metrics(text)

assert metrics.chunks_spanning_multiple_top_level_clauses == 0
print(
    f"{metrics.clause_count} clauses "
    f"({metrics.top_level_clause_count} top-level) -> "
    f"{metrics.chunk_count} chunks; "
    f"{metrics.chunks_with_multiple_clauses} grouped, "
    f"{metrics.chunks_below_min} short, "
    f"{metrics.heading_candidates_rejected} heading candidates rejected, "
    f"{metrics.chunks_unclassified} unclassified"
)
```

Reference values for the bundled fixtures at the default 512/64 sizes:

| Fixture | clauses | top-level | chunks | spanning | grouped | below min | rejected | unclassified |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `uk_service_agreement` | 113 | 11 | 51 | 0 | 32 | 4 | 1 | 1 |
| `uk_terms_conditions` | 71 | 11 | 32 | 0 | 21 | 2 | 1 | 0 |
| `us_msa` | 74 | 12 | 50 | 0 | 17 | 2 | 14 | 0 |
| `us_terms_of_service` | 80 | 12 | 48 | 0 | 17 | 0 | 6 | 1 |
| `eu_gdpr_excerpt` | 37 | 3 | 10 | 0 | 8 | 1 | 2 | 1 |

## Logging and observability

lexichunk's root logger (`logging.getLogger("lexichunk")`) has a `NullHandler`
installed by default, so the library is silent unless the host application
configures logging.

- **DEBUG** — per-stage progress: stage start/done, item counts, timing. Safe
  to enable in development; verbose in production.
- **WARNING** — emitted only when behaviour deviates from what the caller
  asked for, not for routine operation. Examples: `chunk_batch()` falling
  back to serial execution because the process pool could not start, the
  worker count being capped to the platform limit, and a jurisdiction
  being re-registered over an existing key (overriding a previous
  registration).

No other levels are used internally; there is no INFO-level chatter to filter out.

## Thread safety

A single `LegalChunker` instance is safe to share across threads for
`chunk()` and `chunk_iter()` — these methods do not mutate shared instance
state that would race between concurrent calls beyond the definition cache,
which is itself safe for concurrent reads/writes.

The `cross_ref_resolution_rate` and `cross_ref_stats` properties reflect the
**last completed call** on that instance — they are convenience accumulators,
not per-call results, so reading them from one thread while another thread is
mid-`chunk()` call is racy. When you need statistics tied to a specific call
(e.g. from concurrent callers), use `chunk_with_metrics()` and read the
returned `PipelineMetrics` object instead of the instance-level properties.

## `content` and the offsets: what a chunk actually holds

`char_start` and `char_end` mark a clause's own text in the **sanitised**
document. `content` is that slice **with the ancestor headings prepended**:

```
char_start ────────────────────────────────► char_end
              │ Section 4.2 Payment terms. Customer shall pay ...
              ▼
content = "ARTICLE IV — Fees\nSection 4.2\n" + sanitized[char_start:char_end]
          └──────── prepended, outside the span ────────┘
```

So by default `content != sanitized_text[char_start:char_end]`. This is
deliberate — a retrieved `(b)` that does not say which clause it belongs to
is much harder to use — but it is a trap for anything that trusts both
fields at once. Measured on 60 real CUAD contracts, 51% of chunks (1,244 of
2,422) carried such a prefix, on 43% of contracts.

Two exits:

| You want | Use |
|---|---|
| `content` to be exactly the span | `LegalChunker(include_ancestor_headers=False)` |
| the heading context, and the literal span occasionally | keep the default, slice the source yourself |

With `include_ancestor_headers=False`, `content ==
sanitized_text[char_start:char_end]` exactly and `original_header` is empty.
Chunk **boundaries do not move** when you flip the flag — only what is
prepended at each boundary changes — so nothing positional needs re-deriving.
The prefix also stops counting against `max_chunk_size`, which is why the
flag is honoured in the size accounting and not merely at the point the
strings are joined.

`include_context_header` does **not** control any of this. That flag governs
the separate `context_header` field (`[Section: ...] [Type: ...]
[Jurisdiction: ...]`), which is never part of `content`.

Finally, the offsets index the *sanitised* text, not the raw text passed in.
For offsets into the raw input, pass `raw_offsets=True` and read
`raw_char_start` / `raw_char_end`.
