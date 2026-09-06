"""Characterization snapshot tests.

Freezes the *current* chunking behaviour (bugs included) for the five
fixtures under their natural (jurisdiction, doc_type) pairing at the default
sizes (512/64), so that later behaviour fixes are provable by diff against
these snapshots rather than by re-reading pipeline internals.

Regenerate after an intentional behaviour change with::

    pytest tests/test_snapshots.py --update-snapshots
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ._snapshot_support import (
    FIXTURE_CONFIGS,
    SNAPSHOTS_DIR,
    generate_snapshots,
)


def _chunks_path(fixture_name: str) -> Path:
    return SNAPSHOTS_DIR / f"{fixture_name}.json"


def _summary_path(fixture_name: str) -> Path:
    return SNAPSHOTS_DIR / f"{fixture_name}.summary.json"


def _write_json(path: Path, data: Any) -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_chunk_diff(
    actual: list[dict[str, Any]], expected: list[dict[str, Any]]
) -> str:
    """Return a human-readable description of the first difference found."""
    if len(actual) != len(expected):
        return (
            f"chunk count differs: actual={len(actual)} expected={len(expected)}"
        )
    for i, (a, e) in enumerate(zip(actual, expected)):
        for key in sorted(set(a) | set(e)):
            if a.get(key) != e.get(key):
                return (
                    f"first differing chunk index={i}, field={key!r}: "
                    f"actual={a.get(key)!r} expected={e.get(key)!r}"
                )
    return "lists compare unequal but no per-field difference was found"


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
def test_chunk_snapshot(
    fixture_name: str, jurisdiction: str, doc_type: str, request: pytest.FixtureRequest
) -> None:
    actual, _ = generate_snapshots(fixture_name, jurisdiction, doc_type)
    path = _chunks_path(fixture_name)

    if request.config.getoption("--update-snapshots"):
        _write_json(path, actual)
        return

    assert path.exists(), (
        f"Missing snapshot {path}. Run with --update-snapshots to create it."
    )
    expected = _read_json(path)
    assert actual == expected, _first_chunk_diff(actual, expected)


@pytest.mark.parametrize("fixture_name,jurisdiction,doc_type", FIXTURE_CONFIGS)
def test_summary_snapshot(
    fixture_name: str, jurisdiction: str, doc_type: str, request: pytest.FixtureRequest
) -> None:
    _, actual = generate_snapshots(fixture_name, jurisdiction, doc_type)
    path = _summary_path(fixture_name)

    if request.config.getoption("--update-snapshots"):
        _write_json(path, actual)
        return

    assert path.exists(), (
        f"Missing snapshot {path}. Run with --update-snapshots to create it."
    )
    expected = _read_json(path)
    assert actual == expected, (
        f"summary differs for {fixture_name}: actual={actual} expected={expected}"
    )
