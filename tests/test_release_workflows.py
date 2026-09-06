"""Guards on the release workflows themselves.

These are cheap, and each one pins a decision that is invisible at review
time but expensive to get wrong: a broken heredoc only fails at release, a
renamed job silently drops a branch-protection required check, and a publish
job that rebuilds its own artifact ships bits nobody integration-tested.
"""

from pathlib import Path
from textwrap import dedent

import pytest

_WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"


def _workflow(name: str) -> str:
    path = _WORKFLOWS / name
    if not path.exists():
        pytest.skip("GitHub workflows are not included in the source distribution")
    return path.read_text(encoding="utf-8")


def test_publish_version_check_embedded_python_compiles():
    workflow_path = _WORKFLOWS / "publish.yml"
    if not workflow_path.exists():
        pytest.skip("GitHub workflows are not included in the source distribution")

    workflow = workflow_path.read_text(encoding="utf-8")
    marker = "python - <<'PY'\n"
    embedded = workflow.split(marker, 1)[1].split("\n          PY", 1)[0]

    compile(dedent(embedded), str(workflow_path), "exec")


def test_publish_releases_the_artifact_integration_ci_verified():
    """The publish jobs download a built artifact; they never rebuild one.

    Rebuilding would ship a distribution that no integration job installed,
    imported or smoke-tested.
    """
    publish = _workflow("publish.yml")

    assert publish.count("actions/download-artifact@v8") == 2, (
        "both publish jobs must download the verified distributions"
    )
    assert "name: python-distributions" in publish
    assert "python -m build" not in publish, (
        "publish.yml must not rebuild the distribution it releases"
    )

    integrations = _workflow("integrations.yml")
    assert "actions/upload-artifact@v7" in integrations
    assert "name: python-distributions" in integrations
    assert "if-no-files-found: error" in integrations


def test_ci_preserves_the_protected_check_context_names():
    """Branch protection references `test (3.10)` and friends by literal name.

    Adding an `os` axis to the Linux matrix would rename those contexts, so
    Windows runs as its own job with its own fixed name instead.
    """
    ci = _workflow("ci.yml")

    assert "name: test (${{ matrix.python-version }})" in ci
    assert "runs-on: ubuntu-latest" in ci
    assert "test-windows:" in ci
    assert "name: test (3.12, windows-latest)" in ci
    # An `os` axis inside the Linux matrix is exactly what must not come back.
    matrix_block = ci.split("strategy:", 1)[1].split("steps:", 1)[0]
    assert "os:" not in matrix_block


def test_every_workflow_declares_least_privilege_permissions():
    for name in ("ci.yml", "integrations.yml", "publish.yml"):
        workflow = _workflow(name)
        assert "permissions:\n  contents: read" in workflow, name


def test_actions_are_pinned_to_maintained_majors():
    """Every third-party action runs on a runtime GitHub still supports.

    `actions/checkout@v4`, `setup-python@v5` and the v4 artifact actions all
    run on Node 20, which the runner now warns about. The bump to these
    majors moved them onto Node 24; a revert would reintroduce the warning
    and, once Node 20 is removed, a failing release.
    """
    expected = {
        "ci.yml": ("actions/checkout@v7", "actions/setup-python@v7"),
        "integrations.yml": (
            "actions/checkout@v7",
            "actions/setup-python@v7",
            "actions/upload-artifact@v7",
        ),
        "publish.yml": (
            "actions/checkout@v7",
            "actions/setup-python@v7",
            "actions/download-artifact@v8",
            # The PyPI publisher is released off a moving branch, not majors.
            "pypa/gh-action-pypi-publish@release/v1",
        ),
    }
    for name, pins in expected.items():
        workflow = _workflow(name)
        for pin in pins:
            assert pin in workflow, f"{name} must pin {pin}"
        for stale in (
            "actions/checkout@v4",
            "actions/setup-python@v5",
            "actions/upload-artifact@v4",
            "actions/download-artifact@v4",
        ):
            assert stale not in workflow, f"{name} still uses deprecated {stale}"


def test_coverage_gate_is_pinned_in_ci():
    ci = _workflow("ci.yml")
    assert ci.count("--cov-fail-under=88") == 2, (
        "both the Linux matrix and the Windows job must enforce the core gate "
        "(88% is what a dependency-free install measures; optional-dependency "
        "tests skip there)"
    )
    integrations = _workflow("integrations.yml")
    assert "--cov-fail-under=92" in integrations, (
        "the integrations job installs every extra and must enforce the full gate"
    )
