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

## Review (v0.1.0)

**Result**: 107/107 tests passing in 0.42s. Full pipeline verified end-to-end.

**Known rough edges** (post-MVP):
- `[\d.]+` in cross-reference patterns greedily captures trailing sentence periods (e.g. `3.2.` instead of `3.2`) — should use `[\d]+(?:\.[\d]+)*` in a future pass
- Same clause can appear in `cross_references` twice if matched by both the base pattern and an EXTENDED_PATTERNS contextual phrase — deduplication only drops exact `(raw_text, target_identifier)` duplicates
- Token counting is char/4 approximation — users needing exact counts can pass a custom counter in a future API extension
