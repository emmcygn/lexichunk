# Sprint Lessons

## L001 — Subagents need tool permissions pre-configured

**Pattern**: Launched 3 background agents in Wave 1 before the user had a `.claude/settings.json`. All three were blocked on Write/Bash and returned errors, causing a full wave delay.

**Rule**: On any new project, write `.claude/settings.json` with `permissions.allow` covering Bash, Write, Edit, Read, Grep, Glob BEFORE launching subagents. Do this in the main context — the subagent can't write its own permissions file.

**Check**: Does `.claude/settings.json` exist and include Write + Bash? If not, create it first.

---

## L002 — Write .gitignore before `git add -A` on new repos

**Pattern**: Created `.gitignore` after first `git add -A`. This caused `__pycache__/` and `*.egg-info/` to be committed in the initial commit, requiring a cleanup follow-up commit.

**Rule**: On `git init`, the order is always:
1. `git init`
2. Write `.gitignore`
3. `git add -A`
4. `git commit`

Never reverse steps 2 and 3.

---

## L003 — No co-author attribution on commits for this user

**Pattern**: User explicitly does not want `Co-Authored-By: Claude` in commit messages.

**Rule**: Never include the Co-Authored-By trailer. The `.claude/settings.json` `attribution` block handles it automatically, but don't add it manually either.

---

## L004 — Subagent write blocks: fall back to main context immediately

**Pattern**: When a subagent is blocked on Write permissions, don't retry the same subagent or try workarounds. Write the files directly in the main context instead.

**Rule**: If a subagent fails due to tool denial, handle it in the main context and inform the user of the root cause so they can fix the permissions for next time.

---

## L005 — Flat clause lists: children have independent content

**Pattern**: `_split_oversized_clause()` returned child clauses as the split pieces for an oversized parent. But the structure parser gives each clause its own independent content — children's content is NOT a subset of the parent's. This silently dropped the parent's body text (e.g. all definition entries in clause 1.1), causing 13% content loss.

**Rule**: In a flat-list architecture where each `ParsedClause` owns only its own text, never substitute children for the parent during splitting. Children are already in the flat list and will be processed by the main loop. Split the parent's own content via sentence boundaries instead.

**Check**: When debugging content fidelity, compare the parent clause's `content` against its children's `content` — if they don't overlap, children can't serve as splits.

---

## L006 — Test-first abbreviation tests need two real boundaries

**Pattern**: Wrote abbreviation tests where each test text had only ONE potential split point — the abbreviation itself. When the abbreviation was correctly suppressed, the entire text became one sentence, causing the `assert len(s) == 2` to fail. The test was flawed, not the implementation.

**Rule**: When testing that an abbreviation does NOT cause a false split, the test text must contain at least ONE real sentence boundary after the abbreviation. Structure: `"Prefix abbrev. Continuation text with enough words. Real second sentence starts here."`

**Check**: Count the number of `[.!?] [A-Z]` patterns in your test text — subtract abbreviation positions. The remainder must be ≥ 1 for a 2-sentence expectation.

---

## L007 — Validate lower bounds on chunk size params, not just relative ordering

**Pattern**: `max_chunk_size=0, min_chunk_size=0` passed validation because `0 >= 0` satisfied the `max >= min` check. But `max_chunk_size=0` is nonsensical — no chunk can be 0 tokens. Adversarial testing caught this.

**Rule**: Always validate absolute lower bounds on numeric config params, not just relative constraints. `max_chunk_size >= 1` and `min_chunk_size >= 0` are the sensible minimums.

**Check**: After writing relative validation (`max >= min`), ask: "What's the smallest valid value for each parameter independently?"

---

## L008 — Adversarial tests: distinguish test bugs from code bugs

**Pattern**: In v0.4.0 adversarial testing, 2 of 3 "failures" were test logic errors, not code bugs:
1. Empty string signal `""` has `len("".split()) == 0`, so it scores 0 — correct behavior (not a wildcard match), but the test expected it to win.
2. Text contained "fee" (a built-in PAYMENT signal) which caused PAYMENT classification regardless of extras — the test didn't isolate the custom signal properly.

**Rule**: When writing adversarial tests, use keywords with zero overlap to built-in signals (e.g. `xylophonic_obligation`, `zorgblatt`). Before asserting a result, trace the scoring logic manually: what signals match? What weights accumulate? If a built-in signal in the text matches, the test isn't isolating the feature.

**Check**: grep your test text against `CLAUSE_SIGNALS` values before assuming the test is correct.

---

## L009 — Validate batch input types eagerly, not lazily

**Pattern**: `chunk_batch([None, 42, ("a","b","c")])` crashed with cryptic `AttributeError`/`ValueError` inside the processing loop because input types were never validated upfront. The errors were either uncaught (3-tuple unpack ValueError outside try/except) or produced confusing messages ("NoneType has no attribute 'replace'").

**Rule**: Validate all batch inputs before processing begins. Collect type/arity errors into `BatchError` early, insert placeholders, and skip those indices during processing. Never let invalid input reach the processing loop where the error message loses context.

**Check**: After writing a batch API, feed it `[None, 42, ("a","b","c"), ""]` and verify every case produces a clear error or correct empty result.

---

## L010 — Frozen dataclass with mutable fields: forward ALL init state

**Pattern**: `_ChunkerConfig` captured all `LegalChunker.__init__` params except `document_id`. Parallel workers created fresh `LegalChunker` instances without the init-level `document_id`, so chunks lost their document identifier silently. No test caught it because all batch tests used per-doc tuple IDs.

**Rule**: When creating a config snapshot for child processes, enumerate EVERY `__init__` parameter of the source class. Diff the config fields against `__init__` params before calling it done. Especially watch for optional params with `None` defaults — they're easy to forget.

**Check**: `set(inspect.signature(LegalChunker.__init__).parameters) - {'self'}` should be a subset of `_ChunkerConfig` fields.

---

## L011 — Platform-specific limits in ProcessPoolExecutor

**Pattern**: `ProcessPoolExecutor(max_workers=100)` on Windows raises `ValueError: max_workers must be <= 61` due to a Windows-specific limit. Tests passed locally but would fail on CI or user machines with different core counts.

**Rule**: Cap `max_workers` to `min(requested, 61)` on `sys.platform == "win32"`. Always test with worker counts that exceed platform limits.

**Check**: After writing any ProcessPoolExecutor usage, test with `workers=100` and verify no crash.

---

## L012 — Frozen dataclasses with mutable container fields

**Pattern**: `ClassificationResult` was `@dataclass(frozen=True)` with `scores: dict[...]`. The frozen decorator prevents attribute reassignment but does NOT prevent mutation of the dict itself. External code could do `result.scores[key] = value` freely, violating the immutability contract.

**Rule**: When a frozen dataclass has a container field (dict, list, set), wrap it in a read-only view: `MappingProxyType` for dicts, `tuple()` for lists. Verify with a test that attempts mutation and expects `TypeError`.

**Check**: For every frozen dataclass, grep for `dict[`, `list[`, `set[` fields. Each one needs either a read-only wrapper or a documented reason why mutation is acceptable.

---

## L013 — Regex IGNORECASE leaks into all character classes

**Pattern**: `_DEFINITION_HEREINAFTER` used `re.IGNORECASE` to make the keyword "hereinafter" case-insensitive. But the flag applied to the entire pattern, making `[A-Z]` in the term capture group also match lowercase — inconsistent with every other definition pattern that enforces uppercase initials.

**Rule**: When a regex needs case-insensitivity for only PART of the pattern, use inline `(?i:...)` around the case-insensitive portion instead of the global `re.IGNORECASE` flag. Always verify character classes still enforce their intended restrictions.

**Check**: After writing a regex with `re.IGNORECASE`, audit every `[A-Z]`, `[a-z]`, or `[A-Za-z]` class in the pattern. Ask: "Should this class be case-sensitive? If yes, use inline `(?i:...)` instead of the global flag."

---

## L014 — Adversarial review must be a separate step, not part of implementation

**Pattern**: In v0.6.0, adversarial tests were written alongside the feature as part of the same implementation pass. All 4 bugs were missed because the tests were confirmatory ("does my code do what I intended?") rather than adversarial ("how can a consumer break or misuse this?"). The v0.5.0 audit worked precisely because it was a separate role switch after implementation.

**Rule**: NEVER write `test_adversarial_v*.py` during implementation. Complete all implementation + happy-path tests first. Then explicitly switch roles: "I am now a staff engineer trying to break this." The role switch forces outside-in thinking (consumer perspective) instead of inside-out (author perspective).

**Adversarial questions to ask from the consumer perspective:**
1. What can a caller DO with returned objects? (mutation, type abuse)
2. What does the documentation PROMISE vs what the code DOES? (docstring drift)
3. What flags/options affect MORE than their intended target? (regex flags, config leaks)
4. What conventions does the codebase ALREADY follow that new code SHOULD match? (log levels, naming)

**Check**: If you're writing adversarial tests in the same tool call or message as implementation code, STOP. Ship the implementation, run existing tests, then start a fresh adversarial pass.

---

## L015 — Docstrings are contracts, not comments — re-verify after logic changes

**Pattern**: `ClassificationResult.scores` docstring said "Raw per-clause-type scores" but the implementation mutates scores with position boost before storing. The docstring was written at creation time and never updated when the function body changed.

**Rule**: After modifying function logic (especially adding a transformation step), re-read the docstring and verify every claim still holds. Treat docstrings as assertions that need updating when behavior changes.

**Check**: After editing a function body, re-read its docstring line by line. For each factual claim, ask: "Is this still true after my change?"
