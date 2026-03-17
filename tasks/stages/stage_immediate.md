# Stage: Immediate — Block Release / Pre-Production Fixes

**Priority**: Must complete before any production deployment or v0.8.0 stable release.
**Estimated scope**: ~40 items across correctness bugs, test gaps, and EU completeness.

---

## 1. Critical Bugs

### 1.1 — [ ] Fix char_start/char_end offset mismatch when clauses are merged

**Explanation**: When multiple small clauses are merged into a single chunk by the clause-aware chunker, their contents are joined with `'\n'.join(c.content for c in group)`. However, clause contents already include trailing newlines from the structure parser. The join inserts an *extra* `\n` between each clause, meaning the merged content has characters that don't exist in the original document between `char_start` and `char_end`. Consequently, `text[chunk.char_start:chunk.char_end]` does NOT equal `chunk.content` for merged chunks.

**Rationale**: `char_start`/`char_end` are part of the public API contract. Any downstream system that uses them for document highlighting, span extraction, content reconstruction, or source attribution will get incorrect results. This is a silent data corruption bug — no error is raised, the offsets just point to the wrong text.

**Location**: `src/lexichunk/strategies/clause_aware.py` — `_group_to_chunk()` method, specifically the line that joins clause contents with `'\n'`. Also affects `_flush()` in `_split_oversized_clause()`.

**Pass criteria**:
- For every chunk produced by `LegalChunker.chunk(text)`, the invariant `text[chunk.char_start:chunk.char_end].strip() == chunk.content.strip()` holds (or a clearly documented relaxation of this invariant).
- A new test `test_char_offset_invariant` in `tests/test_char_offsets.py` verifies this across UK, US, and EU fixtures with both single-clause and merged-clause scenarios.
- The test runs on at least 5 different document sizes (1 clause, 5 clauses, 50 clauses, oversized clause requiring split, fallback chunker path).

---

### 1.2 — [ ] Fix char offset calculation in `_split_oversized_clause`

**Explanation**: When a single clause exceeds `max_chunk_size` and must be split at sentence boundaries, the code computes `char_start` for each sub-chunk using `sentence_char_start - len(group_text)`. This arithmetic is incorrect because `group_text` is the rejoined text (sentences joined with spaces), not the original document substring. The offset distance between joined text and original text diverges due to whitespace normalization, newline handling, and sentence stripping.

**Rationale**: Oversized clauses are common in real legal documents — a single definitions section can span 5+ pages. Every sub-chunk from such a clause will have wrong offsets, potentially pointing to entirely different parts of the document.

**Location**: `src/lexichunk/strategies/clause_aware.py` — `_split_oversized_clause()` method, the `_flush()` call and the `sentence_char_start` tracking logic.

**Pass criteria**:
- Create a test with a single clause containing 2000+ words (exceeding default `max_chunk_size=512`).
- Verify that each resulting sub-chunk's `char_start`/`char_end` correctly maps back to the original text.
- The fix must handle: leading/trailing whitespace in sentences, newlines within the clause, and sentence boundaries at different positions.

---

### 1.3 — [ ] Fix fallback chunker char offset calculation

**Explanation**: The fallback chunker (`FallbackChunker.chunk()`) constructs `char_start` from `window[0][1]` (first sentence offset) and `char_end` from `last_offset + len(last_sentence)`. However, sentences are stripped of whitespace during `_split_sentences()`, and the window content is joined with `" ".join(s for s, _ in window)`. This means `chunk.content` contains space-joined stripped sentences, while `char_start`/`char_end` point to spans in the original text that include the unstripped whitespace and original separators.

**Rationale**: The fallback path is triggered whenever no clause structure is detected — this includes plain text documents, badly formatted contracts, and EU preamble text. Offset correctness matters just as much here.

**Location**: `src/lexichunk/strategies/fallback.py` — `chunk()` method, lines 234-261.

**Pass criteria**:
- A test that feeds unstructured text (no clause headers) to `LegalChunker` and verifies `text[chunk.char_start:chunk.char_end]` contains the content of each chunk.
- Test includes multi-sentence, multi-paragraph input with varying whitespace.

---

## 2. Test Gaps — Offset Verification

### 2.1 — [ ] Create `tests/test_char_offsets.py` with offset invariant tests

**Explanation**: The entire test suite (650 tests) has zero tests verifying that `char_start`/`char_end` accurately map back to the original document text. This is a fundamental contract of the `LegalChunk` dataclass that has never been validated.

**Rationale**: Without offset tests, any refactoring of the chunking strategies can silently break offset correctness. This should be a CI-enforced invariant.

**Location**: New file `tests/test_char_offsets.py`.

**Pass criteria**:
- At least 15 tests covering:
  - Single clause (UK, US, EU) — offsets exact
  - Multiple clauses merged into one chunk — offsets span the full range
  - Oversized clause split into sub-chunks — each sub-chunk offset is within parent clause bounds
  - Fallback chunker — offsets map to original text
  - Empty/whitespace input — no offset errors
  - Documents with BOM, CRLF, null bytes (sanitized input) — offsets still correct after sanitization
  - Preamble clause — char_start=0, char_end covers preamble text
  - Schedule/Exhibit boundaries — offsets don't bleed across sections
- All tests assert: `chunk.content` is a substring of `text[chunk.char_start:chunk.char_end]` (allowing for whitespace normalization).

---

### 2.2 — [ ] Add merged-clause content correctness test

**Explanation**: When the clause-aware chunker merges small adjacent clauses, no test verifies that the merged content preserves all source text without duplication or loss.

**Rationale**: Content fidelity was raised to 99% in v0.2.0, but the fidelity tests only check that content appears *somewhere* in the output — they don't verify that merged chunks contain exactly the union of their source clauses' content, in order, without extra characters.

**Location**: Add to `tests/test_char_offsets.py` or `tests/test_chunker.py`.

**Pass criteria**:
- A test with 5 small clauses that will be merged into 1-2 chunks.
- Assert that the concatenation of all chunk contents equals the original text (modulo whitespace normalization).
- Assert no content is duplicated across chunks.

---

## 3. EU Jurisdiction Completeness

### 3.1 — [ ] Fix EU `_find_section_end` missing numbered paragraph detection

**Explanation**: The EU branch of `_find_section_end()` in `definitions.py` detects Chapter, Article, Section, and Annex headers as section boundaries — but does NOT detect numbered paragraphs (`1.`, `2.`, `3.`), which are level 2 in the EU hierarchy. This means when the definitions section finder looks for the end of a definitions section, it won't stop at the first numbered paragraph of the next article. The definitions section will be extracted too broadly, potentially including operative clause text.

**Rationale**: EU directives like the GDPR have definitions in `Article 4`, followed by `Article 5` which starts with `1. Personal data shall be...`. Without detecting `1.` as a boundary, Article 5's paragraphs would be included in the definitions section extraction.

**Location**: `src/lexichunk/parsers/definitions.py` — the `elif self._jurisdiction == Jurisdiction.EU:` branch in `_find_section_end()`, approximately line 264.

**Pass criteria**:
- Add `r"|^(\d+)\.\s"` to the EU next_header_re pattern with appropriate level mapping.
- A test that feeds GDPR-like text (Article 4 Definitions followed by Article 5 with numbered paragraphs) and verifies the definitions section ends before Article 5's paragraphs.

---

### 3.2 — [ ] Add EU legislative test fixture

**Explanation**: The SDK claims EU jurisdiction support but has zero production-realistic EU legislative text in test fixtures. All EU tests use synthetic inline text strings. A real GDPR/AI Act excerpt would exercise the full pipeline with authentic numbering, cross-references, defined terms, and hierarchy.

**Rationale**: Without a realistic fixture, we can't validate that the EU pipeline produces sensible results on actual EU legislation. The synthetic tests pass but may not reflect real-world patterns (e.g., GDPR Article 4 has 26 definitions in a specific format).

**Location**: New file `tests/fixtures/eu_gdpr_excerpt.txt` — a public domain excerpt from GDPR Articles 1-5 + selected definitions from Article 4.

**Pass criteria**:
- Fixture contains at least: 1 Chapter header, 4+ Articles, numbered paragraphs, alpha sub-points, 5+ defined terms in single-quote format, 3+ cross-references.
- At least 10 tests in `test_eu_jurisdiction.py` using this fixture.
- Tests verify: hierarchy detection, defined term extraction, cross-reference detection, clause type classification (DEFINITIONS identified), section detection (DEFINITIONS vs OPERATIVE).

---

### 3.3 — [ ] Fix EU recitals not detected as DocumentSection.RECITALS

**Explanation**: EU directives have a preamble block of numbered recitals (e.g., `(1) The protection of natural persons...`, `(2) The principles of...`). These are important for legislative interpretation. Currently, the structure parser's `_detect_document_section()` checks for keywords like "recital", "background", "whereas" — but EU recital blocks don't have a header line containing these words. They're just a sequence of numbered parenthetical paragraphs before the first Chapter/Article.

**Rationale**: Recitals are critical for understanding legislative intent in EU law. A RAG query about "why does the GDPR require consent?" should surface recital text. If recitals are classified as OPERATIVE, they get buried among article content.

**Location**: `src/lexichunk/parsers/structure.py` — `_detect_document_section()` method, and potentially the preamble detection logic.

**Pass criteria**:
- EU documents with numbered recitals before the first Article/Chapter are classified as `DocumentSection.RECITALS` (or at minimum `DocumentSection.PREAMBLE`).
- A test with GDPR-style preamble text (`(1) Whereas...`, `(2) The protection...`) verifies the section classification.

---

### 3.4 — [ ] Fix EU point vs paragraph numbering collision

**Explanation**: EU directives use `1.`, `2.`, `3.` for paragraphs within an article, AND `(1)`, `(2)`, `(3)` for sub-points within those paragraphs. The current `detect_level()` in `eu.py` treats `1.` as level 2 (paragraph). However, in context like `Article 6(1)`, the `(1)` is a parenthetical point, not a standalone paragraph. The cross-reference pattern `Article 6(1)(a)` expects this nesting, but the structure parser doesn't model the `(1)` level.

**Rationale**: GDPR Article 6 has 6 lettered points under paragraph 1: `Article 6(1)(a)` through `(f)`. If the structure parser can't distinguish paragraph `1.` from point `(1)`, the hierarchy for these clauses will be wrong, and cross-references like `Article 6(1)(a)` won't resolve correctly.

**Location**: `src/lexichunk/jurisdiction/eu.py` — `detect_level()` function. The `(1)`, `(2)` parenthetical numeric pattern is not currently detected (only `(a)` alpha and `(i)` roman are).

**Pass criteria**:
- Add a numeric parenthetical pattern: `r'^\((\d+)\)\s+\S'` → level 2.5 or a new level between paragraph and alpha.
- Or document that `(1)` is intentionally not detected as a separate hierarchy level, with rationale.
- Test: GDPR Article 6 excerpt with `1.` paragraph containing `(a)` through `(f)` sub-points — hierarchy must be correct.

---

## 4. Definitions Parser Fixes

### 4.1 — [ ] Tighten definitions section header matching

**Explanation**: `_find_definitions_section()` uses a regex that matches any clause header containing one of the `definitions_headers` strings (e.g., "definitions", "interpretation") as a substring. This is too broad — it matches "General Principles and Interpretation" or "Definitions of Key Performance Metrics" as the definitions section, even though these are not the formal definitions section.

**Rationale**: If a non-definitions section is incorrectly identified as the definitions section, all terms extracted from it get wrong `source_clause` values, and the real definitions section is treated as normal operative text (lower extraction priority).

**Location**: `src/lexichunk/parsers/definitions.py` — `_find_definitions_section()` method, specifically the `section_start_re` regex construction.

**Pass criteria**:
- The matching requires that the definitions header word appears as a primary/sole title, not as a qualifier in a longer title.
- Test: A document with both "1. Interpretation Guidelines" and "2. Definitions" correctly identifies clause 2 as the definitions section.
- Test: "Definitions of Key Metrics" does NOT match as a definitions section header (it's a business clause, not a legal definitions section).

---

### 4.2 — [ ] Fix `bisect_left` tuple comparison edge case

**Explanation**: `_nearest_clause_label()` uses `bisect.bisect_left(labels, (pos,))` where `labels` is a list of `(offset, label)` 2-tuples. This works because Python compares tuples lexicographically — the 1-tuple `(pos,)` is compared against the first element of each 2-tuple. However, if `pos` exactly equals an offset, Python tries to compare the missing second element of the 1-tuple against the `label` string, which raises `TypeError` in some Python versions or produces undefined ordering.

**Rationale**: While current test data doesn't trigger this (definition match positions never exactly equal clause label positions), it could happen in production documents where a definition starts on the exact same line as a clause label. This would be a crash bug.

**Location**: `src/lexichunk/parsers/definitions.py` — `_nearest_clause_label()` method, line using `bisect.bisect_left`.

**Pass criteria**:
- Replace with `bisect.bisect_right(labels, (pos,))` (which handles the boundary correctly) or use a key extraction: `offsets = [o for o, _ in labels]; idx = bisect.bisect_left(offsets, pos)`.
- Test: A definition that starts at the exact same character offset as a clause label does not crash and returns the correct nearest label.

---

### 4.3 — [ ] Add lowercase-initial defined term support

**Explanation**: All definition patterns require an uppercase initial letter: `[A-Z][A-Za-z\s\-]{1,60}`. However, UK contracts commonly define terms with a lowercase article: `"the Company"`, `"the Supplier"`, `"the Client"`. These are legitimate defined terms that are currently missed entirely.

**Rationale**: An estimated 5-8% of defined terms in UK contracts use lowercase-initial format. Missing them means downstream `defined_terms_used` on chunks will be incomplete, and any RAG query about "who is the Supplier?" won't match against the defined term.

**Location**: `src/lexichunk/parsers/definitions.py` — all definition regex patterns (`_DEFINITION_SINGLE`, `_DEFINITION_SINGLE_CURLY`, `_DEFINITION_SHALL_HAVE_MEANING`, `_DEFINITION_HEREINAFTER`, `_INLINE_PAREN_TERM`, `_PARENTHETICAL_BACKREF`), and the jurisdiction pattern dataclasses in `uk.py`, `us.py`, `eu.py`.

**Pass criteria**:
- Definition patterns also match `"the Company" means...` (lowercase article + uppercase noun).
- The `_is_valid_term()` filter still rejects pure stopwords like `"The"`, `"A"`.
- Test: `"the Supplier" means the party identified in Schedule 1` extracts `"the Supplier"` as a defined term.
- Test: `"the" means...` is still rejected.
- Negative test: No increase in false positives on existing fixtures.

---

### 4.4 — [ ] Handle hereinafter definition body extraction edge cases

**Explanation**: For `hereinafter referred to as "Term"` definitions, the code extracts preceding context by looking backward 200 characters and finding the last `.` as a sentence boundary. This is fragile: (1) URLs or abbreviations with periods truncate the body early, (2) 200 chars may be too small for complex definitions, (3) no handling of lists or multi-sentence contexts.

**Rationale**: Hereinafter definitions are common in preambles and recitals. Truncated definition bodies mean the RAG system has incomplete context for what the term refers to.

**Location**: `src/lexichunk/parsers/definitions.py` — the hereinafter handling block, approximately lines 435-458.

**Pass criteria**:
- Increase the lookback window to 500 chars.
- Use the abbreviation-aware sentence splitter (from fallback.py) instead of raw `.rfind(".")` to avoid abbreviation false splits.
- Test: `"ABC Corp., a Delaware LLC. (hereinafter referred to as "the Company")"` — body should include `"ABC Corp., a Delaware LLC."`, not truncate at `"LLC."`.
- Test: Long preamble sentence (300+ chars) is fully captured.

---

## 5. Cross-Reference Fixes

### 5.1 — [ ] Add Roman/Arabic numeral normalization for cross-ref resolution

**Explanation**: A chunk with identifier `"Article VII"` (Roman) and a reference to `"Article 7"` (Arabic) will NOT resolve because the normalizer doesn't convert between numeral systems. Similarly, `"Chapter III"` and `"Chapter 3"` won't match.

**Rationale**: Mixed Roman/Arabic references are common in US contracts (ARTICLE VII → Section 7.01) and EU legislation (Chapter III → Article 15). Resolution failure means `target_chunk_index` stays `None`, reducing the usefulness of cross-reference data.

**Location**: `src/lexchunk/parsers/references.py` — `_normalise_identifier()` method, and potentially `roman_to_int()` from `us.py`.

**Pass criteria**:
- The normalizer converts Roman numerals to Arabic for comparison purposes (or vice versa).
- Test: A reference to `"Article 7"` resolves to a chunk with identifier `"Article VII"`.
- Test: A reference to `"Chapter III"` resolves to a chunk with identifier `"Chapter 3"`.
- Existing resolution tests continue to pass.

---

## 6. Definition Cache

### 6.1 — [ ] Add max_cache_size parameter to LegalChunker

**Explanation**: The definition cache (`self._definition_cache: dict[str, dict[str, DefinedTerm]]`) grows unboundedly. Each unique document text adds an entry keyed by SHA-256 hash. For a long-running service chunking thousands of unique documents, this accumulates MB of cached definition dicts in memory with no eviction.

**Rationale**: A legal AI service processing 10,000 contracts/day would accumulate ~100MB+ of cached definitions within hours. Without eviction, this is a slow memory leak leading to OOM in production.

**Location**: `src/lexichunk/chunker.py` — `__init__()` (cache creation), `_run_pipeline()` (cache read/write), `clear_definition_cache()` (manual eviction).

**Pass criteria**:
- Add `max_cache_size: int = 128` parameter to `LegalChunker.__init__()`.
- When cache exceeds `max_cache_size`, evict the oldest entry (FIFO) or use `functools.lru_cache` semantics.
- `clear_definition_cache()` still works.
- Test: Process `max_cache_size + 10` unique documents, verify cache size never exceeds `max_cache_size`.
- Test: Cache hit still works for recently-seen documents.

---

## 7. Documentation / API Contract

### 7.1 — [ ] Document LegalChunk mutation semantics

**Explanation**: The enrichment pipeline mutates `LegalChunk` objects in-place across stages 3-7: setting `cross_references`, `clause_type`, `classification_confidence`, `context_header`, `defined_terms_used`, `defined_terms_context`, `cross_ref_total`, `cross_ref_resolved`. Callers receive these mutated objects from `chunk()`. If a caller later mutates a chunk (e.g., appending to `cross_references`), it could corrupt cached state if the same text is chunked again with caching enabled.

**Rationale**: Undocumented mutation semantics are a common source of bugs in consumer code. Adding a clear warning prevents misuse.

**Location**: `src/lexichunk/models.py` — `LegalChunk` class docstring. `src/lexichunk/chunker.py` — `chunk()` method docstring.

**Pass criteria**:
- LegalChunk docstring includes a note: "Mutable container fields (cross_references, defined_terms_used, defined_terms_context) are populated by the pipeline. Callers should treat returned chunks as read-only; mutations may affect cached state."
- `chunk()` docstring includes: "Returned chunks are fully enriched. The list and its elements should not be mutated if the chunker instance is reused with caching."

---

### 7.2 — [ ] Document pipeline stage invariants

**Explanation**: The 7-stage pipeline has implicit assumptions about chunk state at each stage boundary. These aren't documented anywhere, making it risky to reorder stages, add new stages, or debug intermediate state.

**Rationale**: Any future contributor modifying the pipeline needs to know what's guaranteed at each stage boundary. Without documentation, a stage reordering could silently produce wrong results.

**Location**: `src/lexichunk/chunker.py` — `_run_pipeline()` method, add comments before each stage block.

**Pass criteria**:
- Each stage block in `_run_pipeline()` has a comment documenting:
  - What fields are guaranteed populated on each chunk BEFORE this stage.
  - What fields this stage populates.
  - What fields remain unpopulated after this stage.
- Example: Before stage 3, chunks have `content`, `index`, `hierarchy`, `hierarchy_path`, `document_section`, `jurisdiction`, `char_start`, `char_end`, `token_count`. After stage 3, `cross_references` is populated (but `target_chunk_index` is `None`).
