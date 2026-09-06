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

Run these before opening a pull request — CI runs the same checks:

```bash
ruff check src/ tests/ examples/ benchmarks/
mypy src/lexichunk/
pytest --cov=lexichunk --cov-fail-under=90
```

## Updating snapshots

Some tests compare output against golden files in `tests/snapshots/*.json`.
If your change intentionally alters chunker output, regenerate them with:

```bash
pytest --update-snapshots
```

**Always review the resulting JSON diff and explain it in the PR** — a
snapshot update is only acceptable when the change is intentional and the
diff has been inspected line by line, not merely to make a failing test pass.
