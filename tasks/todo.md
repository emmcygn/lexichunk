# lexichunk — Sprint Todo

## Wave 1: Foundation ✅
- [x] Project scaffold: directory tree, `__init__` files
- [x] `pyproject.toml` — PyPI config, optional extras for langchain/llama-index
- [x] `src/lexichunk/models.py` — all dataclasses + enums from PRD
- [x] `src/lexichunk/jurisdiction/uk.py` — UK regex patterns + conventions
- [x] `src/lexichunk/jurisdiction/us.py` — US regex patterns + conventions
- [x] `tests/fixtures/` — 4 realistic legal text samples (UK contract, US MSA, UK T&Cs, US ToS)

## Wave 2: Parsers ✅
- [x] `src/lexichunk/parsers/structure.py` — section/clause boundary detection, hierarchy building
- [x] `src/lexichunk/parsers/definitions.py` — defined terms extraction
- [x] `src/lexichunk/parsers/references.py` — cross-reference detection

## Wave 3: Strategies + Enrichment ✅
- [x] `src/lexichunk/strategies/clause_aware.py` — primary chunking: split at clause boundaries, merge/split oversized
- [x] `src/lexichunk/strategies/fallback.py` — graceful degradation to sentence-level splitting
- [x] `src/lexichunk/enrichment/clause_type.py` — keyword-based clause type classification
- [x] `src/lexichunk/enrichment/context.py` — context header generation

## Wave 4: Core Chunker ✅
- [x] `src/lexichunk/chunker.py` — LegalChunker class, public API

## Wave 5: Integrations + Tests + Docs ✅
- [x] `src/lexichunk/integrations/langchain.py` — LegalTextSplitter
- [x] `src/lexichunk/integrations/llama_index.py` — LegalNodeParser
- [x] `tests/test_chunker.py`
- [x] `tests/test_structure_parser.py`
- [x] `tests/test_definitions.py`
- [x] `tests/test_references.py`
- [x] `tests/test_clause_types.py`
- [x] `tests/conftest.py`
- [x] `README.md`
- [x] `examples/basic_usage.py`
- [x] `examples/langchain_rag.py`
- [x] `examples/compare_chunkers.py`

## Milestone 0.2.0 — Fidelity ✅
- [x] Add `original_header` field to `LegalChunk` model
- [x] Prepend ancestor headers to chunk content in `_group_to_chunk()`
- [x] Fix `_split_oversized_clause()` dropping parent content when children exist
- [x] Raise fidelity threshold from 85% → 99%
- [x] Add 14 new tests (8 Phase A + 6 Phase B adversarial)
- [x] Add mypy to CI and dev deps
- [x] Fix 4 mypy type errors across source files
- [x] Bump version to 0.2.0

**Result**: 223/223 tests passing. ruff clean. mypy 0 errors. Content fidelity ≥99%.

## Milestone 0.3.0 — Robustness ✅
- [x] Create `src/lexichunk/exceptions.py` — LexichunkError → ConfigurationError, ParsingError, InputError (dual-inherits ValueError)
- [x] Migrate 8 raise sites in chunker.py, jurisdiction/__init__.py, jurisdiction/us.py
- [x] Export exceptions from `__init__.py`
- [x] Add `_sanitize_input()` to chunker.py — BOM, CRLF, null, NFC
- [x] Wire sanitization into `chunk()`, `get_defined_terms()`, `parse_structure()`
- [x] Expand abbreviations 31→~110 in fallback.py (7 categories + procedural rules)
- [x] Add `_compile_abbreviations()` helper, instance-level `_abbrev_pattern`
- [x] Add `extra_abbreviations` param to FallbackChunker and LegalChunker
- [x] Add `max_chunk_size >= 1` and `min_chunk_size >= 0` validation
- [x] Write `tests/test_exceptions.py` — 21 tests (hierarchy, backward compat, raise sites, adversarial)
- [x] Write `tests/test_sanitization.py` — 16 tests (BOM, CRLF, null, NFC, identity, all public methods, adversarial)
- [x] Write `tests/test_abbreviations.py` — 35 tests (7 categories positive, negative boundaries, extra_abbreviations, adversarial)
- [x] Write `tests/test_properties.py` — 6 hypothesis property tests (data loss, indices, idempotent, config, bounds)
- [x] Add `hypothesis>=6.0` to dev deps
- [x] Version bump to 0.3.0
- [x] Full verification: pytest 301/301, ruff clean, mypy 0 errors

**Result**: 301/301 tests passing. ruff clean. mypy 0 errors. All adversarial stress tests pass.

## Milestone 0.4.0 — Extensibility ✅
- [x] Add `JurisdictionPatterns` @runtime_checkable Protocol to `models.py` (6 attrs: cross_ref, definition, definition_curly, definitions_headers, boilerplate_headers, signature_markers)
- [x] Add jurisdiction registry in `jurisdiction/__init__.py` — `_JURISDICTION_REGISTRY` dict, `register_jurisdiction()`, `DetectLevelFn` type alias
- [x] Refactor `get_patterns()` / `get_detect_level()` to accept `Jurisdiction | str`, look up registry
- [x] Widen `LegalChunk.jurisdiction: Jurisdiction | str`
- [x] Widen `jurisdiction` param type on all pipeline constructors (StructureParser, DefinitionsExtractor, ReferenceDetector, resolve_references, ClauseAwareChunker, FallbackChunker)
- [x] Guard `.value` access with `isinstance(Enum)` in `context.py`, `utils.py`, `chunker.py`
- [x] Add `extra_clause_signals: dict[ClauseType, list[str]] | None` param to `LegalChunker`
- [x] Thread `extra_clause_signals` to `ClauseTypeClassifier(extra_signals=...)`
- [x] Add `_merge_signals()` helper — creates merged copy, never mutates `CLAUSE_SIGNALS`
- [x] Update `_score()` to accept optional `signals` dict param
- [x] Export `JurisdictionPatterns`, `register_jurisdiction` from `__init__.py`
- [x] Version bump to 0.4.0 in `__init__.py` and `pyproject.toml`
- [x] Write `tests/test_jurisdiction_registry.py` — 12 tests (protocol conformance, register/retrieve, overwrite, invalid registration, backward compat, E2E)
- [x] Write `tests/test_extra_clause_signals.py` — 10 tests (extra signal triggers, existing signals work, multiple types, None/empty dict, LegalChunker integration)
- [x] Write `tests/test_adversarial_extensibility.py` — 40 tests (registry abuse, protocol edge cases, full pipeline custom jurisdiction, extra signals adversarial, combined extensibility, state leak isolation, serialization, definitions with custom jurisdiction)
- [x] Full verification: pytest 363/363 (1 pre-existing deselected), ruff clean, mypy 0 errors

**Result**: 363/363 tests passing. ruff clean. mypy 0 errors. 40 adversarial tests confirm no state leaks, no CLAUSE_SIGNALS mutation, full pipeline works with custom jurisdictions.

## Milestone 0.5.0 — Performance ✅
- [x] Add `enable_definition_cache: bool = True` param to `LegalChunker.__init__`
- [x] Add SHA-256 content-hash keyed definition cache (BOM/CRLF-invariant)
- [x] Add `clear_definition_cache()` method
- [x] Add `chunk_iter()` generator wrapper over `chunk()`
- [x] Add `BatchResult` / `BatchError` dataclasses to `models.py`
- [x] Add `chunk_batch()` with serial path (error collection, tuple/str input)
- [x] Add `chunk_batch()` parallel path with `ProcessPoolExecutor`
- [x] Add `_ChunkerConfig` frozen dataclass for worker pickling (includes `document_id`)
- [x] Add `_chunk_single()` module-level worker function
- [x] Add input validation in `chunk_batch()` — None, non-string, wrong-arity tuples caught as errors
- [x] Cap workers to platform limit (Windows: 61)
- [x] Custom jurisdiction + `workers>1` raises `ConfigurationError`
- [x] Serial fallback for ≤2 docs regardless of workers setting
- [x] Add `pytest-benchmark>=4.0` to dev deps, benchmark marker config
- [x] Write `tests/test_definition_cache.py` — 6 tests
- [x] Write `tests/test_chunk_iter.py` — 4 tests
- [x] Write `tests/test_batch.py` — 12 tests (serial + parallel + error handling)
- [x] Write `tests/test_adversarial_v050.py` — 36 adversarial tests (cache mutation, input validation, doc_id forwarding, ordering, thread safety, worker edge cases)
- [x] Write `benchmarks/conftest.py` + `benchmarks/test_perf_chunk.py` — 8 benchmarks
- [x] Export `BatchResult`, `BatchError` from `__init__.py`
- [x] Version bump to 0.5.0 in `__init__.py` and `pyproject.toml`
- [x] Full verification: pytest 421/421 (1 pre-existing failure), ruff clean, mypy 0 errors

**Result**: 421 tests passing (58 new). ruff clean. mypy 0 errors. 36 adversarial tests pass. 8 benchmarks run. Bugs found and fixed during adversarial audit: (1) None/non-string batch input crashed, (2) 3-tuple unpacking crashed, (3) workers>61 crashed on Windows, (4) document_id not forwarded to parallel workers.

## Milestone 0.6.0 — Accuracy ✅
- [x] Add `classification_confidence`, `secondary_clause_type`, `cross_ref_total`, `cross_ref_resolved` to LegalChunk (backward-compatible defaults)
- [x] Create `ClassificationResult` frozen dataclass with `MappingProxyType` scores
- [x] Implement `_classify_detailed()` with confidence formula (best_score / sum)
- [x] Add position-aware scoring: +1.5 bonus for 7 end-of-doc types when position > 0.75
- [x] Add `ClauseTypeClassifier.classify_detailed()` public method
- [x] Update `classify_all()` to populate confidence + secondary type with relative_position
- [x] Cache `_merged_signals` in classifier `__init__`
- [x] Add `_DEFINITION_HEREINAFTER` regex with inline `(?i:...)` for keyword, `[A-Z]` for term
- [x] Implement preceding-context extraction (~200 chars to last sentence boundary) for hereinafter
- [x] Update `resolve_references()` to set `cross_ref_total` / `cross_ref_resolved` per chunk
- [x] Add `LegalChunker.cross_ref_resolution_rate` and `cross_ref_stats` properties
- [x] Export `ClassificationResult` from `__init__.py`
- [x] Version bump to 0.6.0
- [x] Write `tests/test_classification_confidence.py` — 16 tests
- [x] Write `tests/test_position_scoring.py` — 12 tests
- [x] Write `tests/test_crossref_stats.py` — 10 tests
- [x] Write `tests/test_adversarial_v060.py` — 16 tests (separate pass)
- [x] Extend `tests/test_definitions.py` — 11 new hereinafter tests
- [x] Full verification: pytest 497/497 (1 pre-existing deselected), ruff clean, mypy 0 errors

**Result**: 497 tests passing (76 new). ruff clean. mypy 0 errors. Adversarial review (separate pass) caught and fixed 4 bugs: (1) mutable scores dict in frozen ClassificationResult → MappingProxyType, (2) docstring "Raw scores" but values included position boost → corrected, (3) re.IGNORECASE leaked into [A-Z] term capture → inline (?i:...), (4) logger.info vs codebase convention of logger.debug → fixed.

**Process improvement**: Added mandatory "Adversarial Review" workflow step to CLAUDE.md (section 5). Added "Code-Level Invariants" section. Lessons L012–L015 added to tasks/lessons.md.

## Review (v0.1.0)

**Result**: 107/107 tests passing in 0.42s. Full pipeline verified end-to-end.

**Known rough edges** (post-MVP):
- `[\d.]+` in cross-reference patterns greedily captures trailing sentence periods (e.g. `3.2.` instead of `3.2`) — should use `[\d]+(?:\.[\d]+)*` in a future pass
- Same clause can appear in `cross_references` twice if matched by both the base pattern and an EXTENDED_PATTERNS contextual phrase — deduplication only drops exact `(raw_text, target_identifier)` duplicates
- Token counting is char/4 approximation — users needing exact counts can pass a custom counter in a future API extension
