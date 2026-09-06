# Changelog

All notable changes to lexichunk are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.9.0] — Unreleased

First planned PyPI release. This section aggregates work landing across
several concurrent branches ahead of the release.

### Breaking
- `chunk_batch()` now rejects a bare `str` passed as `texts` (raises
  `TypeError`/`ConfigurationError` instead of silently iterating the string
  character-by-character). Pass a `list` — `[text]` for a single document.
- `LegalTextSplitter.split_text()` continues to return LangChain `Document`
  objects rather than `str`; this is called out explicitly in the README as
  intentional, not an oversight, since it differs from the base
  `TextSplitter.split_text()` signature.
- `ClauseType` and `Jurisdiction` (and other public enums) are now
  string-valued (`str` mixin) rather than plain `Enum` members — equality
  against their string form (e.g. `chunk.clause_type == "indemnification"`)
  now holds, but code relying on `repr()` output or strict `type(x) is Enum`
  identity checks should be reviewed.
- `register_jurisdiction()` raises by default when re-registering an
  existing jurisdiction key; pass `override=True` to replace an existing
  registration explicitly (previously, re-registration silently replaced
  the existing entry).

### Added
- `LegalChunk.to_dict()` / `LegalChunk.from_dict()` for JSON-safe
  round-tripping of chunk data (e.g. for caching or cross-process transfer).
- `tests/snapshots/*.json` golden-file snapshots and a `pytest --update-snapshots`
  flag for regenerating them (see `CONTRIBUTING.md` — review the diff before committing).
- `tests/test_invariants.py` — cross-cutting invariant tests that run
  independently of any single stage's unit tests.
- `LegalTextSplitter.split_documents()` and `.transform_documents()` for
  chunking already-loaded LangChain `Document` objects, preserving caller
  metadata (lexichunk's own metadata keys win on collision); `create_documents()`
  now accepts a parallel `metadatas=` list.
- `LegalNodeParser` now subclasses LlamaIndex's `NodeParser` and sets
  node `relationships`/`ref_doc_id`; structural metadata keys are excluded
  from embedding text via `excluded_embed_metadata_keys` by default.
- `register_jurisdiction(..., override=True)`, `unregister_jurisdiction()`,
  and `registered_jurisdictions()` for inspecting and managing the
  jurisdiction registry at runtime.
- `LegalChunker.sanitize(text)` — public method exposing the same
  BOM-stripping/CRLF-normalization/NFC-normalization step used internally,
  so callers can compute offsets against the exact string the pipeline uses.
- `LegalChunker.jurisdiction` property for reading back the configured
  jurisdiction.
- A heading-plausibility gate in structure parsing, to reduce false-positive
  clause detection on lines that only superficially resemble a heading.
- Hierarchy-aware merge: undersized clauses now merge only with an adjacent
  sibling within the same parent — hierarchy is never crossed to satisfy
  `min_chunk_size`.
- `max_chunk_size` is now enforced as a hard cap via a cascading splitter
  (sentence → semicolon → enumerator → newline → word window), with a
  single warning logged if an indivisible run still exceeds the cap.
- `chunk_batch()` falls back to serial execution (with a `WARNING` log)
  when the process pool cannot be started, instead of raising.
- Four commercial `ClauseType` members — `SERVICES`, `INSURANCE`, `AUDIT`
  and `NON_SOLICITATION` — bringing the classifier to 31 clause types.
  `secondary_clause_type` semantics are unchanged.
- Container headings written over two lines (`ARTICLE I` above `DEFINITIONS`,
  `Chapter I` above `General provisions`) now adopt the second line as the
  clause title, so `hierarchy_path` reads `Article I — Definitions`.  The
  line stays in the body text and no offsets change.
- Descendants of a Schedule / Exhibit / Annex (or of a Recitals or
  Definitions block) now inherit that container's `DocumentSection`, so
  `SCHEDULE 1 > 1 — Overview` is `SCHEDULES` and `1 — Definitions > 1.1` is
  `DEFINITIONS` rather than `OPERATIVE`.  A descendant with a section of its
  own keeps it.  This also lets cross-reference resolution tell a main-body
  `clause 3` from a Schedule's paragraph 3.
- Chunks whose entire body was a heading line (`Article I`, `Chapter I`,
  `SCHEDULE 1 — SERVICES DESCRIPTION`) are folded into the child clause they
  announce, as long as the result fits `max_chunk_size`.  The absorbed
  heading's identifier is recorded, so `Schedule 1` / `Article I` references
  still resolve to the merged chunk.
- Packaging/CI: Python 3.13 classifier and CI matrix entry, `windows-latest`
  CI coverage (Python 3.12), `examples` extra
  (`langchain-text-splitters`, `langchain-community`, `langchain-openai`),
  upper version bounds on `langchain-core` and `llama-index-core`,
  `MANIFEST.in`, a dedicated `integrations.yml` CI workflow that builds and
  smoke-tests the published wheel/sdist, `dependabot.yml`, `SECURITY.md`,
  and `CONTRIBUTING.md`.

### Fixed
- Cross-references to a sub-clause that was merged into a larger chunk
  (`clause 2.7`, `clause 3.4(b)`) now resolve: the clause-aware path hands the
  absorbed identifiers to the resolver instead of dropping them.
- A merged chunk no longer registers its own identifier twice, which made it
  look ambiguous with itself and left its references unresolved.
- The pieces of an over-sized clause keep the clause's own identifier —
  `hierarchy`, `hierarchy_path`, `original_header` and `context_header` no
  longer expose the internal `.__part<n>` suffix.  Uniqueness comes from the
  internal `uid`, and a reference to the clause resolves to the piece where it
  starts.
- `(i)` roman-numeral sub-clause identifiers no longer misdetected/mis-normalized
  during cross-reference resolution.
- EU `Chapter`-level sections are no longer misclassified into
  `DocumentSection.SCHEDULES`.
- `examples/` now passes `ruff check` (previously 7 lint errors — unnecessary
  f-string prefixes and an unused local variable); CI now lints
  `src/ tests/ examples/ benchmarks/` instead of `src/ tests/` only.

## [0.8.0b1] — 2026-03-17

### Added
- EU Directives jurisdiction (`Jurisdiction.EU` / `"eu"`) — supports GDPR, DSA, DMA, AI Act, ePrivacy structure (Chapter/Article/Section/paragraph/Annex)
- GDPR test fixture (`tests/fixtures/eu_gdpr_excerpt.txt`) with 10 fixture-based tests
- ReDoS security audit — 28 tests verifying all regex patterns resist catastrophic backtracking with pathological inputs
- Coverage enforcement in CI — `--cov-fail-under=90` gate (currently 97%)
- PyPI publish workflow (`.github/workflows/publish.yml`) — automated release on tag push via OIDC trusted publisher
- Character offset invariant tests (`tests/test_char_offsets.py`) — 16 tests covering all chunking paths
- Lowercase-initial defined term support (`"the Company" means...`)
- Roman/Arabic numeral normalization for cross-reference resolution
- `max_cache_size` parameter on `LegalChunker` (default 128, FIFO eviction)
- Pipeline stage invariant documentation in `_run_pipeline()`

### Fixed
- Critical: `_split_oversized_clause` produced negative `char_start` values — rewrote offset tracking
- `bisect_left` tuple comparison edge case in `_nearest_clause_label` — replaced with flat-list `bisect_right`
- EU `_find_section_end` missing numbered paragraph boundary detection
- Definitions section header matching too broad — added word boundary constraints
- Hereinafter definition lookback window increased from 200 to 500 chars

### Changed
- Version bumped to 0.8.0b1 (Beta status)
- Development Status classifier upgraded from Alpha to Beta
- CI now runs `pytest --cov` with 90% minimum coverage gate

## [0.7.0] — 2026-03-14

### Added
- `PipelineMetrics` and `StageMetric` frozen dataclasses for pipeline observability
- `LegalChunker.chunk_with_metrics()` — returns `(chunks, metrics)` with per-stage wall-clock timing
- Per-stage structured logging at DEBUG level (stage start/done with item counts and timing)
- Developer documentation: `docs/architecture.md` (pipeline design) and `docs/extending.md` (custom jurisdictions, clause signals)
- This changelog

### Changed
- Internal pipeline logic extracted into `_run_pipeline()` shared by `chunk()` and `chunk_with_metrics()`
- `chunk()` behaviour is unchanged — zero overhead when metrics are not requested

## [0.6.0] — 2026-03-14

### Added
- Classification confidence scoring (`classification_confidence`, `secondary_clause_type` on `LegalChunk`)
- `ClassificationResult` frozen dataclass with `MappingProxyType` scores
- Position-aware clause type scoring (+1.5 bonus for end-of-document types past 75%)
- `ClauseTypeClassifier.classify_detailed()` public method
- "Hereinafter" inline definition extraction with preceding-context support
- Cross-reference resolution stats (`cross_ref_total`, `cross_ref_resolved` per chunk)
- `LegalChunker.cross_ref_resolution_rate` and `cross_ref_stats` properties

## [0.5.0] — 2026-03-14

### Added
- SHA-256-keyed definition extraction cache (`enable_definition_cache` param)
- `LegalChunker.clear_definition_cache()` method
- `chunk_iter()` generator wrapper
- `chunk_batch()` with serial and parallel (`ProcessPoolExecutor`) paths
- `BatchResult` and `BatchError` dataclasses
- Platform-aware worker cap (Windows: max 61)
- Performance benchmarks (`benchmarks/`)

## [0.4.0] — 2026-03-14

### Added
- `JurisdictionPatterns` `@runtime_checkable` Protocol
- Jurisdiction registry: `register_jurisdiction()` for custom jurisdictions
- `extra_clause_signals` parameter on `LegalChunker` for custom classification keywords
- `_merge_signals()` helper — never mutates built-in `CLAUSE_SIGNALS`

## [0.3.0] — 2026-03-14

### Added
- Exception hierarchy: `LexichunkError` -> `ConfigurationError`, `ParsingError`, `InputError`
- Input sanitization: BOM stripping, CRLF normalization, null byte removal, NFC normalization
- Expanded legal abbreviation support (~110 abbreviations across 7 categories)
- `extra_abbreviations` parameter on `FallbackChunker` and `LegalChunker`
- Hypothesis property-based tests

## [0.2.0] — 2026-03-14

### Added
- `original_header` field on `LegalChunk`
- Ancestor header prepending for hierarchy context
- Content fidelity raised from 85% to 99%

### Fixed
- `_split_oversized_clause()` no longer drops parent content when children exist

## [0.1.0] — 2026-03-14

### Added
- Initial release
- 8-stage pipeline: structure parsing, chunking, cross-reference detection, clause type classification, context enrichment, defined terms, cross-reference resolution
- UK and US jurisdiction support
- `LegalChunker` public API with `chunk()`, `get_defined_terms()`, `parse_structure()`
- LangChain (`LegalTextSplitter`) and LlamaIndex (`LegalNodeParser`) integrations
- 107 tests
