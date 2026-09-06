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

Generates a Contextual Retrieval header for each chunk summarising its position in the document hierarchy, clause type, and document ID. It is meant to be prepended to the chunk text before embedding, so the vector carries the document-level context the chunk itself no longer states. lexichunk does not measure the retrieval effect of doing this; the README links the evaluation harness and describes what it does and does not establish.

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

Internal dataclasses (`ClassificationResult`, `PipelineMetrics`, `StageMetric`) use `frozen=True` with `MappingProxyType` and `tuple` for true immutability. The primary output type `LegalChunk` is a mutable dataclass — the pipeline populates its fields across stages. Its container fields are per-instance and hold no reference to the definition cache, so mutating a returned chunk cannot corrupt cached state; but derived metadata such as `cross_ref_total` is computed once at the end of the run, so editing one field in place will not update the others. Prefer `dataclasses.replace()` or `to_dict()`/`from_dict()`.

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

## Logging and observability

lexichunk's root logger (`logging.getLogger("lexichunk")`) has a `NullHandler`
installed by default, so the library is silent unless the host application
configures logging.

- **DEBUG** — per-stage progress: stage start/done, item counts, timing. Safe
  to enable in development; verbose in production.
- **INFO** — one message only: `chunk_batch()` capping the worker count to
  the Windows `ProcessPoolExecutor` limit of 61 handles. The call still does
  what was asked, just with fewer workers, so this is not a warning.
- **WARNING** — emitted only when behaviour deviates from what the caller
  asked for, not for routine operation. There are four: `chunk_batch()`
  falling back to serial execution because the process pool could not start,
  `chunk_batch()` recording that its input iterable raised partway through,
  an indivisible run still exceeding `max_chunk_size` after every splitting
  strategy was exhausted, and `register_jurisdiction()` overriding an
  existing custom key.

No ERROR-level records are emitted: a failure the caller must know about is
raised, not logged.

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

## Performance baseline

`benchmarks/` measures the pipeline against the shipped fixtures. The suite is
run in CI with `pytest benchmarks --benchmark-disable`, which executes every
benchmark body exactly once without timing it — enough to keep the benchmarks
from rotting, without spending CI minutes on numbers that a shared runner
cannot measure reliably.

Reproduce the timings locally with:

```bash
pytest benchmarks --benchmark-enable --benchmark-columns=min,mean,stddev,rounds
```

Baseline recorded on 2026-09-06 — Python 3.11.9, Windows 11, AMD Zen 4
(16 logical cores). These are wall-clock milliseconds for one call; treat them
as an order-of-magnitude reference and a regression tripwire, not a
cross-machine benchmark.

| Benchmark | Input | Min | Mean | StdDev |
|---|---|---|---|---|
| `chunk()` UK terms and conditions | 16,948 chars | 10.6 ms | 11.6 ms | 0.8 ms |
| `chunk()` US MSA | 25,346 chars | 16.5 ms | 17.2 ms | 0.6 ms |
| `chunk()` UK service agreement | 25,187 chars | 18.0 ms | 19.9 ms | 2.0 ms |
| `chunk()` US terms of service | 25,743 chars | 19.2 ms | 24.3 ms | 2.7 ms |
| `chunk_batch()` serial, 3 docs | 75,720 chars | 67.7 ms | 71.9 ms | 5.3 ms |
| `chunk_batch()` parallel, 2 workers, 3 docs | 75,720 chars | 434.3 ms | 482.6 ms | 36.0 ms |
| Definition cache miss (fresh chunker per round) | 25,187 chars | 102.6 ms | 108.6 ms | 5.4 ms |
| Definition cache hit (primed chunker) | 25,187 chars | 18.6 ms | 24.0 ms | 2.7 ms |

Two of these deserve comment, because the naive reading of each is wrong.

**Parallel is slower than serial here, and that is expected.** Three documents
of ~25 KB each take about 70 ms in total; starting two `spawn` worker
processes on Windows costs several hundred milliseconds of interpreter
startup and pickling before any work happens. `workers > 1` only pays for
itself on batches large enough to amortise that — hundreds of documents, or
documents an order of magnitude larger. `chunk_batch()` already refuses to go
parallel for two documents or fewer for this reason; the crossover point for
your corpus is worth measuring rather than assuming.

**The cache-miss benchmark is not a like-for-like comparison.** It constructs
a new `LegalChunker` on every round, so it measures construction plus a full
uncached run; the hit benchmark reuses a primed instance. The difference
between the two is therefore an upper bound on what the definition cache
saves, not a measurement of it.
