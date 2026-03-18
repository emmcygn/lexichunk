# Stage: Short-Term — v0.9.0 Hardening

**Priority**: Complete before expanding to new customers or document types.
**Estimated scope**: ~30 items across structure detection, definitions, cross-references, classification, and abbreviations.

---

## 1. UK Structure Detection Expansion

### 1.1 — [ ] Add Part numbering detection for UK jurisdiction

**Explanation**: Modern UK contracts frequently use a Part structure above clause numbering: `PART 1 — GENERAL`, `Part 2 — Services`, `PART THREE`. The current UK `detect_level()` does not detect Part headers at all. Any text under a Part header is attributed to whatever clause boundary was last detected, causing content to bleed across structural boundaries.

**Rationale**: UK public sector contracts, construction contracts (JCT, NEC), property leases, and long-form commercial agreements routinely use Parts. A 200-page English law SPA with 5 Parts would produce chunks with scrambled hierarchy.

**Location**: `src/lexichunk/jurisdiction/uk.py` — `detect_level()` function. Add a new pattern before the Schedule check: `r'^(?:PART|Part)\s+(\d+|[A-Z]+|[IVXLC]+)'`.

**Pass criteria**:
- `detect_level("PART 1 — GENERAL")` returns `(-1, "Part 1")` or a new level above top-level clauses.
- `detect_level("Part 2")` returns the same level.
- `detect_level("PART THREE")` returns `(-1, "Part THREE")` (text numeral).
- Negative: `detect_level("The parties agree")` still returns `None`.
- E2E test: A document with `PART 1 > 1. Definitions > 1.1 Term` produces correct hierarchy path.

---

### 1.2 — [ ] Add Appendix/Annex detection for UK jurisdiction

**Explanation**: UK `detect_level()` detects `Schedule` but not `Appendix` or `Annex`. These are common attachment labels in UK contracts, particularly ISDA master agreements (Appendix), construction contracts (Annex), and government procurement (Annex).

**Rationale**: Text under an Appendix or Annex heading currently flows into the parent clause or becomes a fallback chunk. This misattributes substantial content.

**Location**: `src/lexichunk/jurisdiction/uk.py` — `detect_level()`, add patterns for `Appendix` and `Annex` at the same level as Schedule (-1).

**Pass criteria**:
- `detect_level("Appendix A — Fee Schedule")` returns `(-1, "Appendix A — Fee Schedule")`.
- `detect_level("Annex 1")` returns `(-1, "Annex 1")`.
- `UKPatterns` dataclass gains `appendix` and `annex` compiled patterns (for consistency, even if unused by the core pipeline).
- `_detect_document_section()` in `structure.py` classifies these as `DocumentSection.SCHEDULES`.

---

### 1.3 — [ ] Add dual-marker subclause detection for UK

**Explanation**: Some UK contracts use hybrid numbering: `1.2.1(a)(i)` — a three-level numeric clause with alpha and roman sub-points inline. The current parser detects `1.2.1` as level 2, then on the next line detects `(a)` as level 3. But when `(a)` appears on the *same line* as `1.2.1`, it's not detected as a separate clause — it's part of the 1.2.1 content.

**Rationale**: This is a formatting-dependent edge case. Some drafters put sub-points on the same line as their parent clause; others put them on new lines. Both should be handled.

**Location**: `src/lexichunk/jurisdiction/uk.py` — `detect_level()`. Also affects `src/lexichunk/parsers/structure.py` — the line-by-line parsing loop.

**Pass criteria**:
- A clause `1.2.1(a) the first condition` is detected as level 3 `(a)` under parent `1.2.1`, not as level 2 `1.2.1`.
- OR: Document that inline sub-points are intentionally treated as body text of the parent clause, with rationale for why this is acceptable.
- Test: Both formats (same-line and new-line sub-points) produce chunks with correct hierarchy.

---

## 2. US Structure Detection Expansion

### 2.1 — [ ] Add capital letter subclause detection for US

**Explanation**: US financial documents (credit agreements, indentures, bond prospectuses) frequently use capital letter sub-points: `(A)`, `(B)`, `(C)` and capital Roman numerals: `(I)`, `(II)`, `(III)`. The current US `detect_level()` only matches lowercase: `r'^\(([a-z])\)\s+'` and `r'^\(([ivxlc]+)\)\s+'`. Capital letter sub-points are invisible to the parser.

**Rationale**: A $500M credit facility agreement might have 30+ capital-letter sub-points across its conditions and covenants sections. All of them would be treated as body text instead of separate clause boundaries, producing oversized chunks with lost hierarchy.

**Location**: `src/lexichunk/jurisdiction/us.py` — `detect_level()`, add patterns for `(A)`, `(B)`, `(I)`, `(II)`.

**Pass criteria**:
- `detect_level("(A) the Borrower shall maintain")` returns `(3, "(A)")`.
- `detect_level("(III) the aggregate amount")` returns `(4, "(III)")`.
- Negative: `detect_level("(ABC) not a real clause")` returns `None` (only single letters, not multi-letter).
- Negative: `detect_level("(a) lowercase still works")` still returns `(3, "(a)")` — no regression.
- E2E test: A US credit agreement excerpt with capital sub-points chunks correctly.

---

### 2.2 — [ ] Tighten ALL-CAPS header detection for US

**Explanation**: The US `detect_level()` detects any line that is entirely uppercase letters and spaces (≥2 chars) as a level-0 clause header. This is too broad — it catches in-line titles within sections (e.g., `CONFIDENTIALITY OBLIGATIONS` appearing as a sub-heading within a Section) as top-level clauses, fragmenting the document.

**Rationale**: False positive clause detection creates too many small chunks, breaks hierarchy, and produces misleading `hierarchy_path` values. A document with 50 sub-headings would produce 50 spurious top-level clauses.

**Location**: `src/lexichunk/jurisdiction/us.py` — `detect_level()`, the ALL-CAPS detection block at lines 152-158.

**Pass criteria**:
- Add a minimum length threshold (e.g., ≥4 characters) to reduce single-word false positives.
- Add a heuristic: only match ALL-CAPS lines that are preceded by a blank line or are the first non-blank line in the document.
- OR: Add a configurable flag to enable/disable ALL-CAPS detection.
- Test: `"REPRESENTATIONS AND WARRANTIES"` preceded by blank line → detected.
- Test: `"CONFIDENTIAL"` appearing mid-paragraph → NOT detected.
- Existing tests continue to pass.

---

### 2.3 — [ ] Add US sub-section numbering support (5.1.1, 5.1.2)

**Explanation**: Some US agreements use numbered sub-sections: `Section 5.1 Obligations`, then `5.1.1 Party A shall...`, `5.1.2 Party B shall...`. The US `detect_level()` doesn't detect `5.1.1` as a clause boundary because it's not in the expected pattern set (ARTICLE, Section, (a), (i)).

**Rationale**: These become body text of the parent Section, producing oversized chunks. Common in M&A agreements and technology licensing contracts.

**Location**: `src/lexichunk/jurisdiction/us.py` — `detect_level()`, add numeric sub-section pattern similar to UK's `subsection_3` and `subsection_2`.

**Pass criteria**:
- `detect_level("5.1.1 Party A shall maintain")` returns a level below Section (e.g., level 2).
- `detect_level("5.1.2 Party B shall provide")` returns the same level.
- This doesn't conflict with the existing Section pattern (`Section 1.01`).
- E2E test with nested US sub-sections.

---

## 3. Definitions Parser Expansion

### 3.1 — [ ] Add list-style definition extraction

**Explanation**: Financial and regulatory contracts often define terms in a numbered list format:
```
The following definitions apply:
1. "Affiliate" means any entity...
2. "Business Day" means any day...
```
The current extractor expects `"Term" means definition_body` on the same line/paragraph. Numbered-list definitions where the number prefix comes before the quoted term are not captured.

**Rationale**: A 20-page financial regulatory document might have 40% of its definitions in list format. Missing them breaks downstream term-usage detection.

**Location**: `src/lexichunk/parsers/definitions.py` — `_extract_definitions_from_text()`, add a new pattern for numbered list definitions.

**Pass criteria**:
- A new regex pattern matches: `r'^\d+\.\s+["\u201c\'\u2018]([A-Z][A-Za-z\s\-]{1,60})["\u201d\'\u2019]\s+(?:means|shall mean|has the meaning)'`.
- Test: A definitions section with 5 numbered definitions extracts all 5 terms.
- Test: Doesn't false-positive on numbered operative clauses that happen to contain a quoted word.

---

### 3.2 — [ ] Add exotic definition verb support

**Explanation**: The current definition patterns match: `means`, `shall mean`, `has the meaning`, `is defined as`, `refers to`. Real contracts also use: `is as provided in`, `is given by`, `is that set out in`, `shall be construed as`, `includes`, `shall include`. These are missed.

**Rationale**: ~10% of definitions in specialized contracts (banking, insurance) use non-standard verbs. Missing them creates gaps in the defined terms index.

**Location**: `src/lexichunk/parsers/definitions.py` — all definition regex patterns, and jurisdiction pattern dataclasses.

**Pass criteria**:
- Definition patterns also match: `"Term" shall be construed as...`, `"Term" includes...`, `"Term" is given by...`.
- Test: At least 3 new verb patterns are captured.
- Negative: `"The meaning of life"` does NOT trigger a false positive (the word "meaning" alone shouldn't match).

---

### 3.3 — [ ] Improve definition body extraction for long definitions

**Explanation**: `_extract_definition_body()` stops at: (1) next definition match, (2) two blank lines, (3) blank line + clause header. For multi-page definitions (common in GDPR Article 4, ISDA definitions), a stray blank line within the definition body causes premature truncation.

**Rationale**: GDPR Article 4 definitions can be 100+ words. ISDA master agreement definitions can span paragraphs. Premature truncation means the RAG system has incomplete definition context.

**Location**: `src/lexichunk/parsers/definitions.py` — `_extract_definition_body()` method.

**Pass criteria**:
- A single blank line within a definition body does NOT truncate extraction — only TWO consecutive blank lines or a blank line followed by a clause header.
- Test: A 200-word definition with one internal blank line is fully extracted.
- Test: A definition followed by two blank lines then a new clause correctly stops at the blank lines.
- Regression: Existing definition extraction tests continue to pass.

---

## 4. Cross-Reference Detection Expansion

### 4.1 — [ ] Add range reference detection

**Explanation**: Legal documents frequently reference ranges: `"Sections 3.1 through 3.5"`, `"Articles II–IV"`, `"Clauses 5 to 8"`. The current detector doesn't recognize range patterns — it would only capture `"Sections 3.1"` and miss `"3.5"`, or capture nothing for `"Articles II–IV"`.

**Rationale**: Range references are common in boilerplate clauses ("Subject to Sections 3.1 through 3.5, the Borrower shall..."). Missing the end of the range means incomplete cross-reference data.

**Location**: `src/lexichunk/parsers/references.py` — add a new extended pattern for range references.

**Pass criteria**:
- A new pattern matches: `"Sections 3.1 through 3.5"`, `"Articles II–IV"`, `"Clauses 5 to 8"`, `"Sections 2.1-2.5"`.
- Each reference in the range is emitted as a separate `CrossReference` object.
- Test: `"Sections 3.1 through 3.5"` produces 5 cross-references (3.1, 3.2, 3.3, 3.4, 3.5).
- Test: `"Articles II–IV"` produces 3 cross-references (II, III, IV).

---

### 4.2 — [ ] Add cross-document reference detection

**Explanation**: Multi-document transactions (M&A, financing) constantly reference other documents: `"as defined in the Credit Agreement"`, `"pursuant to the Loan Documents"`, `"subject to the terms of the Security Agreement"`. The current detector only finds intra-document references (Section X, Clause Y).

**Rationale**: For multi-document RAG pipelines, cross-document references are essential for linking related chunks across different files. Missing them means the RAG system can't connect a term defined in one document with its usage in another.

**Location**: `src/lexichunk/parsers/references.py` — add a new `EXTENDED_PATTERNS` entry for cross-document references.

**Pass criteria**:
- A new pattern matches: `"as defined in the Credit Agreement"`, `"pursuant to the [Document Name]"`.
- Cross-document references are flagged with a distinct attribute (e.g., `is_cross_document=True`) or use a special `target_identifier` format.
- Test: `"as defined in the Credit Agreement Section 2.1"` produces a cross-reference with document context.
- Test: `"pursuant to the terms of this Agreement"` is NOT flagged as cross-document (it's self-referential).

---

## 5. Clause Type Classification Expansion

### 5.1 — [ ] Add banking/finance clause type signals

**Explanation**: The 27 clause types cover general commercial contracts but miss specialized banking/finance types. A credit facility agreement has clauses for: financial covenants, security interest, pricing mechanics, loan facility, conditions to drawdown, events of default, commitment fees. These are currently classified as COVENANTS, CONDITIONS, or UNKNOWN.

**Rationale**: A bank deploying lexichunk on its loan document database would see ~30% of clauses classified as UNKNOWN or misclassified. This degrades RAG accuracy for financial-specific queries.

**Location**: `src/lexichunk/enrichment/clause_type.py` — `CLAUSE_SIGNALS` dict. `src/lexichunk/models.py` — `ClauseType` enum.

**Pass criteria**:
- Add at least: `FINANCIAL_COVENANTS`, `EVENTS_OF_DEFAULT`, `SECURITY_INTEREST` to `ClauseType`.
- Add corresponding keyword signals (e.g., FINANCIAL_COVENANTS: `["financial covenant", "leverage ratio", "debt service coverage", "interest coverage", "net worth", "ebitda"]`).
- Test: A credit agreement excerpt with financial covenants is classified correctly.
- Existing classification tests continue to pass (no signal pollution).

---

### 5.2 — [ ] Add insurance clause type signals

**Explanation**: Insurance contracts have specialized clauses: claims procedure, coverage/scope, exclusions, conditions precedent to coverage, subrogation, deductible/excess. These are currently classified as CONDITIONS, COVENANTS, or UNKNOWN.

**Rationale**: Insurance tech companies using lexichunk would see poor clause type accuracy. Claims handling queries ("what's the claims procedure?") would miss relevant chunks.

**Location**: Same as 5.1.

**Pass criteria**:
- Add at least: `CLAIMS_PROCEDURE`, `COVERAGE`, `EXCLUSIONS` to `ClauseType`.
- Add corresponding signals.
- Test: An insurance policy excerpt classifies correctly.

---

### 5.3 — [ ] Add employment clause type signals

**Explanation**: Employment agreements have specialized clauses: non-compete, non-solicitation, garden leave, vesting schedule, severance, restrictive covenants, IP assignment (employment-specific). These overlap with general contract types but have distinct signals.

**Rationale**: HR tech / employment law platforms using lexichunk would benefit from distinguishing employment-specific clause types.

**Location**: Same as 5.1.

**Pass criteria**:
- Add at least: `NON_COMPETE`, `NON_SOLICITATION` to `ClauseType`.
- Add signals (e.g., NON_COMPETE: `["non-compete", "non-competition", "restrictive covenant", "competitive activity", "garden leave"]`).
- Test: An employment agreement excerpt classifies correctly.

---

### 5.4 — [ ] Strengthen DATA_PROTECTION classification signals

**Explanation**: The DATA_PROTECTION signals (`"personal data"`, `"data protection"`, `"gdpr"`, `"privacy"`, etc.) are often outweighed by other clause types in mixed clauses. A GDPR compliance clause that also mentions indemnification will be classified as INDEMNIFICATION because `"indemnify"` scores higher than `"personal data"`.

**Rationale**: ~20% of modern commercial contracts have GDPR/privacy clauses. Misclassifying them as INDEMNIFICATION means privacy-related queries miss relevant chunks.

**Location**: `src/lexichunk/enrichment/clause_type.py` — `CLAUSE_SIGNALS[ClauseType.DATA_PROTECTION]`.

**Pass criteria**:
- Add more signals: `"data processing agreement"`, `"dpa"`, `"standard contractual clauses"`, `"scc"`, `"data transfer"`, `"data breach"`, `"data protection impact"`, `"dpia"`, `"legitimate interest"`, `"consent"` (in data context).
- Add higher-weight multi-word phrases: `"general data protection regulation"` (5 words = score 5).
- Test: A clause mentioning both `"indemnify"` and `"personal data"` + `"data controller"` + `"gdpr"` is classified as DATA_PROTECTION.

---

## 6. Abbreviation Expansion

### 6.1 — [ ] Add EU-specific legal abbreviations

**Explanation**: The abbreviation list is comprehensive for US and UK case law but has zero EU-specific entries. EU legal documents reference: `O.J.` (Official Journal), `ECJ`/`CJEU` (courts), `Dir.` (Directive), `Reg.` (Regulation), `Art.` (Article — abbreviated form).

**Rationale**: A GDPR citation like `"See O.J. L 119, 4.5.2016"` would incorrectly split at the period after `O.J`, breaking the sentence boundary.

**Location**: `src/lexichunk/strategies/fallback.py` — `DEFAULT_ABBREVIATIONS` tuple.

**Pass criteria**:
- Add: `"O.J"`, `"Dir"`, `"Reg"`, `"Art"`, `"CJEU"`, `"ECJ"`, `"AG"` (Advocate General), `"OJ"`.
- Test: `"See O.J. L 119 for the full text. The next sentence starts here."` splits into 2 sentences (not 3).

---

### 6.2 — [ ] Add UK court abbreviations

**Explanation**: UK court citations use: `Ch. D` (Chancery Division), `Q.B.` (Queen's Bench), `C.A.` (Court of Appeal), `K.B.` (King's Bench), `H.L.` (House of Lords), `S.C.` (Supreme Court — but this conflicts with US state).

**Rationale**: UK contracts with case law citations would have false sentence splits at these abbreviations.

**Location**: Same as 6.1.

**Pass criteria**:
- Add: `"Ch"` (already present? check), `"Q.B"`, `"K.B"`, `"C.A"`, `"H.L"`, `"W.L.R"` (Weekly Law Reports), `"A.C"` (Appeal Cases), `"All E.R"` (All England Reports).
- Test: `"See Smith v Jones [2020] Q.B. 123. The court held..."` splits at the second period, not the first.

---

### 6.3 — [ ] Add financial/banking domain abbreviations

**Explanation**: Financial documents reference benchmarks, regulatory bodies, and legal constructs with period-containing abbreviations: `LIBOR`, `SOFR`, `SONIA`, `EBITDA`, `N.A.` (National Association — already present), `F.D.I.C.`, `S.E.C.`, `O.C.C.`.

**Rationale**: Credit agreements and financial regulatory filings use these extensively. False splits degrade chunk quality.

**Location**: Same as 6.1.

**Pass criteria**:
- Add: `"F.D.I.C"`, `"S.E.C"`, `"O.C.C"`, `"FINRA"` (no period, but add for completeness), `"N.Y.S.E"`.
- Test: `"The S.E.C. requires disclosure. The next sentence..."` splits correctly.

---

## 7. Test Fixtures

### 7.1 — [ ] Add financial document test fixture

**Explanation**: The test suite has zero financial document fixtures. Credit agreements, indentures, and loan documents have distinct structure (ARTICLE/Section/sub-section with financial covenants, conditions to closing, events of default) that differs from the current UK/US service agreement fixtures.

**Rationale**: Financial documents are among the most valuable use cases for legal RAG. Without testing, we can't validate that the pipeline handles them correctly.

**Location**: New file `tests/fixtures/us_credit_agreement.txt`.

**Pass criteria**:
- Contains: ARTICLE headers (Roman), Section headers (1.01 format), capital-letter sub-points, financial covenant text, events of default clause, pricing mechanics.
- At least 200 lines of realistic content.
- At least 5 tests using this fixture covering hierarchy, clause types, cross-refs, defined terms.

---

### 7.2 — [ ] Add poorly-formatted document test fixture

**Explanation**: All existing fixtures are clean, well-formatted modern documents. Real-world legal documents include: OCR artifacts, mixed tab/space indentation, inconsistent numbering, missing blank lines between clauses, double-spaced text, unusual quote characters.

**Rationale**: The fallback chunker is supposed to handle unrecognized formats, but it's never tested with realistically messy input.

**Location**: New file `tests/fixtures/messy_contract.txt`.

**Pass criteria**:
- Contains: inconsistent indentation, mixed numbering styles, missing blank lines, double-spacing, unusual quote characters (backticks, angle quotes), OCR-like artifacts (broken words, ligature issues).
- At least 5 tests verifying graceful degradation: chunks produced, no crashes, reasonable content preservation.

---

### 7.3 — [ ] Add schedule-only document fixture

**Explanation**: Some documents are pure schedules/annexes with internal structure (e.g., a pricing schedule, a list of properties, a service level description). These have no operative clauses, no preamble, and no traditional article/section structure. No test covers this case.

**Rationale**: Schedules attached to master agreements are chunked independently in many RAG pipelines. If the pipeline can't handle a schedule-only document, those chunks are lost or malformed.

**Location**: New file `tests/fixtures/schedule_only.txt`.

**Pass criteria**:
- Contains: Schedule header, tabular-like content, numbered items within the schedule, no Article/Section structure.
- Test: Pipeline produces chunks without crashing.
- Test: `document_section` is `SCHEDULES` for all chunks.
