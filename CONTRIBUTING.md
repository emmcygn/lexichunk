# Contributing

## Setup

Using [uv](https://docs.astral.sh/uv/) (recommended):

```bash
git clone https://github.com/emmcygn/lexichunk
cd lexichunk
uv venv
uv pip install -e ".[dev,all]"
```

Using plain `pip`:

```bash
git clone https://github.com/emmcygn/lexichunk
cd lexichunk
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,all]"
```

## Running the gates

Run these before opening a pull request — CI runs the same checks on Python
3.10 through 3.13, plus Windows on 3.12:

```bash
ruff check src/ tests/ examples/ benchmarks/
mypy src/lexichunk/
pytest --cov=lexichunk --cov-fail-under=92
pytest benchmarks --benchmark-disable
```

`ruff format` is **not** enforced — the tree is not currently formatted with
it, and reformatting everything would bury real changes in noise. Match the
style of the file you are editing.

## Property-based tests

`tests/test_properties.py` and `tests/test_invariants.py` use Hypothesis.
`tests/conftest.py` registers two derandomised profiles, so the same commit
generates the same examples everywhere:

- `dev` (default locally) — 500 ms per-example deadline;
- `ci` (used when `$CI` is set, or via `HYPOTHESIS_PROFILE=ci`) — 100 examples
  and a 2 s deadline, for cold shared runners.

To reproduce a CI failure locally, run `HYPOTHESIS_PROFILE=ci pytest ...`.

## Documentation is tested

`tests/test_readme_examples.py` executes every ```` ```python ```` block in
`README.md`. If you change the API, update the README in the same PR or that
test fails. A block that genuinely cannot run in CI needs an HTML comment
above it containing `lexichunk-doctest: skip` **and a stated reason**.

`tests/test_docstrings.py` requires a docstring on every name in
`lexichunk.__all__` and every public member of `LegalChunker`, and pins the
`LegalChunker` public surface — adding a public method means updating that
list and `CHANGELOG.md` deliberately.

## Updating snapshots

Some tests compare output against golden files in `tests/snapshots/*.json`.
If your change intentionally alters chunker output, regenerate them with:

```bash
pytest --update-snapshots
```

**Always review the resulting JSON diff and explain it in the PR** — a
snapshot update is only acceptable when the change is intentional and the
diff has been inspected line by line, not merely to make a failing test pass.
