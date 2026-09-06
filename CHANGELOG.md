# Changelog

All notable changes to lexichunk are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.9.0] — 2026-09-06

First tagged release of the source-distributed public beta. lexichunk is not
published on PyPI; install it from git, pinned to `v0.9.0` or to a reviewed
commit SHA. Everything before this version was source-only too, so the
"Breaking" entries below describe changes against `0.8.0b1` as installed from
git, not against a published package.

### Breaking
- `chunk_batch()` rejects a bare `str`, `bytes` or `bytearray` passed as
  `texts`, raising `InputError` instead of silently iterating the string
  character-by-character. Any other iterable — list, tuple, generator,
  `dict.values()` — is still accepted. Pass `chunk_batch([text])` for a
  single document.
- `chunk_batch()` also rejects a `Mapping`. Iterating one yields its *keys*,
  so `chunk_batch({"doc1": text1})` used to chunk the string `"doc1"` and
  never look at the document, returning a normal-looking `BatchResult` with
  `errors == []`. Pass `mapping.values()`, or `mapping.items()` to use the
  keys as document ids.
- `ClauseType`, `Jurisdiction` and `DocumentSection` are now string-valued
  (`str` mixin) rather than plain `Enum` members. Equality against their
  string form (`chunk.clause_type == "indemnification"`) now holds, and
  `json.dumps` accepts them directly — but code relying on `repr()` output
  or on `type(x) is Enum` identity checks should be reviewed.
- `register_jurisdiction()` raises `ConfigurationError` by default when
  re-registering an existing jurisdiction key; pass `override=True` to
  replace an existing registration explicitly. Previously, re-registration
  silently replaced the existing entry.
- `LegalTextSplitter.split_text()` returns LangChain `Document` objects
  rather than `str`. This differs from the base `TextSplitter.split_text()`
  signature and is deliberate — the metadata is the point of the library —
  and is now documented as such in the README rather than left implicit.
- The maximum input size (`_MAX_INPUT_CHARS`, 10,000,000 characters) is now
  checked against the *raw* input, before sanitisation. Input that used to
  slip past the guard because it sanitised down below the limit (for
  example a multi-megabyte run of BOM characters) now raises `InputError`.

### Added
- `LegalChunk.to_dict()` / `LegalChunk.from_dict()` for JSON-safe
  round-tripping of chunk data (caching, cross-process transfer). `to_dict()`
  is also defined on `HierarchyNode`, `CrossReference` and `DefinedTerm`.
- `CrossReference.target_kind` — the kind of thing a reference points at
  (`"clause"`, `"section"`, `"paragraph"`, `"schedule"`, `"exhibit"`,
  `"annex"`, `"chapter"`, `"recital"`, …), so a `Schedule 2` reference is no
  longer confused with a main-body `clause 2`. Also emitted in the
  integrations' flattened cross-reference metadata.
- `tests/snapshots/*.json` golden-file snapshots for every fixture and a
  `pytest --update-snapshots` flag for regenerating them (see
  `CONTRIBUTING.md` — review the diff before committing).
- `tests/test_invariants.py` — cross-cutting, Hypothesis-backed invariant
  tests that run independently of any single stage's unit tests.
- `tests/test_readme_examples.py` executes every Python block in `README.md`,
  so documented code cannot drift from the API; `tests/test_docstrings.py`
  requires a docstring on every public export and pins the `LegalChunker`
  public surface; `tests/test_heading_regression.py` is a flat, table-driven
  set of 25 realistic headings that must be detected and the heading-shaped
  lines (postal addresses, currency amounts, dates, durations,
  table-of-contents entries) that must not be; and
  `tests/test_heading_shapes.py` pins the per-line `detect_level` shapes
  underneath that gate, US bare-decimal headings in particular.
- Two derandomised Hypothesis profiles in `tests/conftest.py` (`dev` and
  `ci`), so a property-based failure reproduces from the same commit on any
  machine. CI selects `ci` via `HYPOTHESIS_PROFILE`.
- `LegalTextSplitter.split_documents()` and `.transform_documents()` for
  chunking already-loaded LangChain `Document` objects, preserving caller
  metadata (lexichunk's own keys win on collision); `create_documents()` now
  accepts a parallel `metadatas=` list, and `LegalTextSplitter` gained
  `include_defined_terms_context`, `flatten_metadata` and `metadata_prefix`
  options.
- `LegalNodeParser` now subclasses LlamaIndex's `NodeParser`, so nodes carry
  `relationships` (`SOURCE`/`PREVIOUS`/`NEXT`) and `ref_doc_id`; structural
  metadata keys are excluded from embedding and LLM text via
  `excluded_embed_metadata_keys` by default.
- `register_jurisdiction(..., override=True)`, `unregister_jurisdiction()`
  and `registered_jurisdictions()` for inspecting and managing the
  jurisdiction registry at runtime.
- `LegalChunker.sanitize(text)` — a static method exposing the same BOM
  stripping, CRLF→LF and Unicode NFC normalisation the pipeline applies
  internally, so callers can slice the exact string `char_start`/`char_end`
  index into.
- `LegalChunker.jurisdiction` property for reading back the configured
  jurisdiction.
- A heading-plausibility gate in structure parsing, so lines that only
  superficially resemble a heading (postal addresses, currency amounts,
  dates, list items) no longer open a new clause.
- Per-jurisdiction section roles and roman/alpha identifier disambiguation
  in the structure parser, plus header-coverage accounting so body text is
  not silently dropped between detected headers.
- Hierarchy-aware merge: undersized clauses merge only with an adjacent
  sibling under the same parent — the hierarchy is never crossed to satisfy
  `min_chunk_size`.
- `max_chunk_size` is enforced as a hard cap via a cascading splitter
  (sentence → semicolon → enumerator → newline → word window → character
  window), shared by the clause-aware and fallback paths, with a single
  `WARNING` logged when a run offers no boundary inside the budget and the
  cut therefore lands mid-word.
- `chunk_batch()` falls back to serial execution (with a `WARNING` log) when
  the process pool cannot be started, instead of raising; a generator that
  raises partway through is recorded as one `BatchError` at the index it
  stopped on rather than propagating out of the call.
- Four commercial `ClauseType` members — `SERVICES`, `INSURANCE`, `AUDIT`
  and `NON_SOLICITATION` — bringing the classifier to 31 clause types.
  `secondary_clause_type` semantics are unchanged.
- `classification_confidence` is now saturation-scaled:
  `(best_score / total_score) * min(1.0, best_score / 4.0)`, so a clause
  whose winning type has thin absolute evidence no longer reports high
  confidence just because nothing else scored.
- The definition cache is a thread-safe LRU (`OrderedDict` under a
  `threading.Lock`, least-recently-used eviction) rather than an unguarded
  FIFO dict.
- Container headings written over two lines (`ARTICLE I` above `DEFINITIONS`,
  `Chapter I` above `General provisions`) adopt the second line as the clause
  title, so `hierarchy_path` reads `Article I — Definitions`. The line stays
  in the body text and no offsets change.
- Descendants of a Schedule / Exhibit / Annex (or of a Recitals or
  Definitions block) inherit that container's `DocumentSection`, so
  `SCHEDULE 1 > 1 — Overview` is `SCHEDULES` and `1 — Definitions > 1.1` is
  `DEFINITIONS` rather than `OPERATIVE`. A descendant with a section of its
  own keeps it. This also lets cross-reference resolution tell a main-body
  `clause 3` from a Schedule's paragraph 3.
- Chunks whose entire body was a heading line (`Article I`, `Chapter I`,
  `SCHEDULE 1 — SERVICES DESCRIPTION`) are folded into the child clause they
  announce, as long as the result fits `max_chunk_size`. The absorbed
  heading's identifier is recorded, so `Schedule 1` / `Article I` references
  still resolve to the merged chunk.
- A term redefined for a schedule ("For the purposes of this Schedule 2
  only, 'Services' means …") is now scoped to that container: chunks inside
  the schedule get the local definition, main-body chunks keep the
  document-wide one.
- EU pinpoint references (`Article 6(1)(a)`), reference ranges, and a
  prefix index for faster cross-reference resolution.
- Packaging/CI: Python 3.13 classifier and CI matrix entry, `windows-latest`
  CI coverage (Python 3.12), an `examples` extra
  (`langchain-text-splitters`, `langchain-community`, `langchain-openai`),
  upper version bounds on `langchain-core` and `llama-index-core`,
  `MANIFEST.in`, a dedicated `integrations.yml` workflow that builds and
  smoke-tests the wheel and sdist, `dependabot.yml`, `SECURITY.md`,
  `CONTRIBUTING.md`, `CODEOWNERS`, issue and pull-request templates, and a
  `--cov-fail-under=92` coverage gate.
- Installation guidance for a package that is not on PyPI: pin the `v0.9.0`
  tag or an exact reviewed commit SHA. Security reporting scope,
  optional-dependency scope (including the NLTK advisory that reaches the
  `llama-index` extra transitively), an adoption guide
  (`docs/adoption-guide.md`) and a fully offline source-evidence retrieval
  example (`examples/offline_evidence_retrieval.py`, covered by
  `tests/test_offline_example.py`) are documented.
- Release CI preserves the protected Linux check contexts `test (3.10)`,
  `test (3.11)` and `test (3.12)` by running Windows as its own job rather
  than as an extra matrix axis, and the publish workflow now releases only
  the wheel and source distribution already built and verified by the
  integrations workflow, downloaded as an artifact instead of rebuilt.
  `tests/test_release_workflows.py` compiles the version-check job's embedded
  Python so a broken heredoc fails CI rather than the release.

- `LegalChunker(include_ancestor_headers=...)`. Controls what `chunk.content`
  holds. Default `True` keeps the previous behaviour — the chunk's span with
  its ancestor headings prepended. With `False`, `content` is exactly
  `sanitized_text[char_start:char_end]` and `original_header` is empty, which
  is what you want when the offsets drive highlighting or answer-span
  mapping. Chunk boundaries are identical either way.
- `PipelineMetrics.chunks_unclassified` — chunks whose `clause_type` is
  `UNKNOWN`. A few are normal; `chunks_unclassified == chunk_count` means the
  document carries no clause metadata at all.
- `LegalChunker.chunk_documents()` — runs the pipeline on structure supplied
  by an external parser (Docling, `unstructured`, a DOCX outline), skipping
  lexichunk's own line-based heading detection.
- `lexichunk.ingestion` — `from_docling`, `from_unstructured`,
  `from_markdown`. Adapters onto `chunk_documents()`. No new mandatory
  dependencies; importing the package never imports `docling_core` or
  `unstructured`.
- Raw-offset back-map: `LegalChunker.sanitize_with_map()`, the `OffsetMap`
  type, and `chunk(..., raw_offsets=True)`, which populates `raw_char_start` /
  `raw_char_end` on every chunk so offsets can be mapped back to the text you
  passed in rather than the sanitised text.
- Structure-quality metrics on `PipelineMetrics`: `clause_count`,
  `top_level_clause_count`, `chunks_spanning_multiple_top_level_clauses`,
  `chunks_with_multiple_clauses`, `chunks_below_min`,
  `heading_candidates_rejected`.
- `classification_hook` / `classification_hook_threshold` — call your own
  classifier only for chunks the keyword scorer was unsure about.
- Two gold-annotated fixtures with parser-independent answer keys:
  `uk_pdf_extracted_agreement` (a UK agreement as a naive PDF text extractor
  leaves it — running headers and footers, 78-column hard wrapping,
  cross-references split across line breaks, a soft-hyphenated word) and
  `us_msa_signed_with_exhibits` (a signed US MSA with two-line ARTICLE titles
  and exhibits after the signature block), plus `docs/ingestion.md` and
  `tests/test_gold_fixtures.py`.

### Fixed
- `DefinitionsExtractor` now uses the jurisdiction registry's `detect_level`
  for clause-boundary detection instead of three hardcoded UK/US/EU regexes.
  A jurisdiction registered through the public `register_jurisdiction()` API
  previously had its term patterns honoured but its clause boundaries
  silently resolved with US-style rules, so a definition body ran on to the
  end of the document. A boundary-heading heuristic also stops an inline
  lowercase continuation ("…disclosed under\nClause 2 excluding…") from
  ending a definition.
- `ReferenceDetector.resolve()` re-derives a reference's container kind from
  its raw text when `target_kind` is still the default `"clause"`. A
  `CrossReference` built by hand — by an SDK integrator feeding references
  from an external extractor — and passed straight to `resolve()` used to
  match a main-body `clause 1` for `"Schedule 1"` and report
  `target_kind="clause"`. Bare identifiers (`"Article VII"`) are unaffected.
- `FallbackChunker` splits a sentence longer than `max_chunk_size` at word
  boundaries before assembling chunks, preserving exact character offsets. A
  run-on sentence with no internal punctuation — plausible in OCR'd or
  poorly formatted text — used to be emitted whole, violating the
  `max_chunk_size` hard cap. A single indivisible word over the budget is
  still emitted as-is.
- Cross-references to a sub-clause that was merged into a larger chunk
  (`clause 2.7`, `clause 3.4(b)`) now resolve: the clause-aware path hands
  the absorbed identifiers to the resolver instead of dropping them.
- A merged chunk no longer registers its own identifier twice, which made it
  look ambiguous with itself and left its references unresolved.
- The pieces of an over-sized clause keep the clause's own identifier —
  `hierarchy`, `hierarchy_path`, `original_header` and `context_header` no
  longer expose the internal `.__part<n>` suffix. Uniqueness comes from the
  internal `uid`, and a reference to the clause resolves to the piece where
  it starts.
- `(i)` roman-numeral sub-clause identifiers are no longer misdetected or
  mis-normalised during cross-reference resolution.
- A dash between two references is only treated as a range operator when
  there is evidence for it, so `Clause 5 - Payment` is no longer read as the
  range `Clause 5` to `Payment`.
- EU `Chapter`-level sections are no longer misclassified into
  `DocumentSection.SCHEDULES`; document-section keyword classification is
  anchored to the heading rather than matched anywhere in the body.
- The heading-plausibility gate no longer swallows real clause headings.
- The UK `next_header_re` Schedule branch was missing a capture group, so
  Schedule boundaries were mis-detected.
- Structure parsing derives line offsets from the same splitter `parse()`
  uses, so `char_start`/`char_end` cannot drift from the parsed lines.
- Definition extraction: the defined-term character class was widened and
  opening quotes anchored (so `"Level 2 Data"` is found), a definition body
  is bounded at the next entry marker — including a US/EU-style
  `Section 1.2` / `Article II` marker — or at an ALL-CAPS operative heading,
  so neighbouring entries no longer leak into the previous definition.
- `LegalChunk.from_dict()` validates every container field instead of
  trusting the input shape.
- The definition cache key tolerates unpaired surrogates instead of raising
  `UnicodeEncodeError`, and registry names are type-checked.
- `LegalTextSplitter.split_documents()` ids are unique across the whole
  call. `chunk.index` restarts at 0 for each input `Document`, so under the
  common one-`Document`-per-page loader pattern every page shares
  `metadata["source"]` and `f"{document_id}:{chunk.index}"` collided —
  a vector store's `add_documents` upsert then kept only the last chunk per
  id and silently dropped the rest.
- `LegalNodeParser` derives a stable document identifier from content when
  the caller supplied none. LlamaIndex fills an unnamed `Document.id_` with
  a fresh `uuid4`, which made the context header, embed text and `node_id`
  differ on every run and duplicated every vector on re-ingestion.
- `examples/` now passes `ruff check` (previously 7 errors — unnecessary
  f-string prefixes and an unused local); CI lints
  `src/ tests/ examples/ benchmarks/` instead of `src/ tests/` only.
- **`jurisdiction="us"` now recognises bare-decimal headings**
  (`1. Definitions.` / `1.1` / `1.1.1`), the dominant US commercial drafting
  style. Previously the `us` profile required a literal `Section` or `ARTICLE`
  marker, so on a 150-contract CUAD sample it recovered five or more top-level
  clauses in 14% of contracts against 31% for `uk` on the *same* US filings —
  the profile named for the jurisdiction was the worse choice for it, and
  anyone passing `us` silently got fixed-size splitting.
- **`max_chunk_size` is now a hard cap on every path.** A run offering no
  split point — an OCR'd table, a base64 blob, a 2,485-character line — was
  emitted whole, up to 2.4x over the limit (1,220 tokens against a configured
  512). The cascading splitter gains a final character-window level, and the
  fallback path now uses the same splitter as the clause-aware path instead of
  treating a sentence as indivisible. When a run offers no boundary of any
  kind inside the budget the cut lands mid-word, and that is logged once at
  `WARNING`.
- **Consecutive chunks tile the document on the fallback path.** Sentences
  were stripped before their offsets were recorded, so the whitespace between
  two sentences belonged to neither chunk and consecutive spans were one
  character apart.
- **Wrapped sentences are no longer read as headings.** A heading candidate
  must now open a block — the previous line blank, ending a sentence, or
  itself a heading. Text hard-wrapped out of a PDF put `Schedule 2.`,
  `Section 2.04.` and `7.2. Continued use ...` at the head of a line, each the
  tail of a sentence; believing one re-parents the rest of the document under
  a clause that is not there.
- **Letter-named attachments resolve.** `Exhibit A` and `Schedule B` are now
  detected as cross-references under `us`. Previously only digits and Roman
  numerals were accepted, so `Exhibit C` resolved (C is a Roman numeral) while
  `Exhibit A`, `B` and `D` did not.

### Performance
- **Definition-body extraction is linear in the document again.** For each
  definition it searched from that definition to the end of the text, once per
  stop pattern, with around fourteen patterns — O(definitions x length). On
  the worst CUAD contract (291,873 characters, 414 definitions) chunking took
  20.2 s against a 0.042 s corpus median. Bounding each search to the best
  boundary found so far takes that to **0.84 s**, with byte-identical output
  on every fixture and both CUAD contracts. A second contract went 0.70 s to
  0.08 s. The registry-driven blank-line-then-header stop condition is bounded
  the same way.

### Changed
- `chunk.content` is documented, prominently, as **not** being
  `sanitized_text[char_start:char_end]` by default. It never was — measured on
  60 real CUAD contracts, 51% of chunks carry a prepended ancestor heading —
  but the contract was stated nowhere, and `include_context_header=False` does
  not change it (that flag governs the separate `context_header` field). See
  the `LegalChunk` docstring and `docs/architecture.md`.
- The `us_msa` snapshot gains two chunks (48 to 50) and three resolved
  cross-references (71 to 74). Bare-decimal heading recognition now finds the
  numbered clauses inside `EXHIBIT A`, so the exhibit's body is split into its
  own clauses instead of one flat chunk, and the letter-named `Exhibit A`
  references resolve to it.

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
