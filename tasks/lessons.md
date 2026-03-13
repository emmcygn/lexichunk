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
