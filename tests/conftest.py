"""Shared pytest fixtures for lexichunk tests."""

from pathlib import Path

import pytest

from lexichunk.jurisdiction import registered_jurisdictions, unregister_jurisdiction

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _jurisdiction_registry_snapshot():
    """Snapshot the jurisdiction registry before each test; unregister
    anything new left behind afterwards.

    This never restores state by reading the (possibly mutated) registry —
    it only removes keys that did not exist before the test ran, via the
    public :func:`~lexichunk.jurisdiction.unregister_jurisdiction`. A test
    that overwrites a *built-in* key (via ``override=True``) is responsible
    for restoring it itself, since built-ins cannot be unregistered and the
    snapshot diff is empty for a key that already existed.
    """
    before = set(registered_jurisdictions())
    yield
    after = set(registered_jurisdictions())
    for key in after - before:
        unregister_jurisdiction(key)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--update-snapshots`` CLI option.

    When passed, ``tests/test_snapshots.py`` rewrites the on-disk snapshot
    files under ``tests/snapshots/`` instead of asserting against them.
    """
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Rewrite tests/snapshots/*.json instead of asserting against them.",
    )


@pytest.fixture
def uk_service_agreement():
    return (FIXTURES_DIR / "uk_service_agreement.txt").read_text(encoding="utf-8")


@pytest.fixture
def us_msa():
    return (FIXTURES_DIR / "us_msa.txt").read_text(encoding="utf-8")


@pytest.fixture
def uk_terms_conditions():
    return (FIXTURES_DIR / "uk_terms_conditions.txt").read_text(encoding="utf-8")


@pytest.fixture
def us_terms_of_service():
    return (FIXTURES_DIR / "us_terms_of_service.txt").read_text(encoding="utf-8")


@pytest.fixture
def eu_gdpr_excerpt():
    return (FIXTURES_DIR / "eu_gdpr_excerpt.txt").read_text(encoding="utf-8")
