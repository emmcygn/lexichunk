"""Release metadata stays consistent across the source checkout."""

import re
from pathlib import Path

import pytest

import lexichunk

ROOT = Path(__file__).parents[1]


def test_package_version_matches_latest_changelog_entry():
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', metadata, re.MULTILINE)
    latest = re.search(r"^## \[([^\]]+)\]", changelog, re.MULTILINE)
    assert version is not None
    assert latest is not None
    assert version.group(1) == lexichunk.__version__ == latest.group(1)


def test_security_policy_acknowledges_pypi_distribution():
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "not yet published" not in policy
    assert "https://pypi.org/project/lexichunk/" in policy


@pytest.mark.parametrize(
    "filename,obsolete_claim",
    [
        ("README.md", "git install above is the only supported route"),
        ("CHANGELOG.md", "Installation guidance for a package that is not on PyPI"),
        ("README.md", "offsets and chunk boundaries are\n  identical either way"),
    ],
)
def test_release_docs_do_not_repeat_superseded_claims(filename, obsolete_claim):
    assert obsolete_claim not in (ROOT / filename).read_text(encoding="utf-8")
