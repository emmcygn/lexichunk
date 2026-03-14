# Changelog

All notable changes to lexichunk are documented in this file.

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
