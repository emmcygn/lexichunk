## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## Why

<!-- The problem, not the patch. What was wrong, or what could not be done before? -->

## Checklist

- [ ] `ruff check src/ tests/ examples/ benchmarks/` passes
- [ ] `mypy src/lexichunk/` passes
- [ ] `pytest --cov=lexichunk --cov-fail-under=92` passes
- [ ] `CHANGELOG.md` updated under the unreleased section (user-visible changes only)
- [ ] New behaviour has a test; a bug fix has a regression test that fails without the fix

## Snapshot diffs

`tests/snapshots/*.json` pins the full chunk output for five fixture
documents. If this PR changes any of them:

- [ ] The snapshot change is **intentional**, not a way to make a failing test pass.
- [ ] I regenerated them with `pytest --update-snapshots` and read the resulting diff.
- [ ] I have explained below what changed and why the new output is correct.

<!-- If snapshots changed, describe the diff here. If they did not, say "no snapshot changes". -->
