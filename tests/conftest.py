"""Shared pytest fixtures for lexichunk tests."""

from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

from lexichunk.jurisdiction import registered_jurisdictions, unregister_jurisdiction

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------
#
# A property test that draws different examples on every run is a test whose
# failures cannot be reproduced and whose passes mean less than they look
# like they do: CI goes green because today's seed missed the bug. Both
# knobs below exist for that.
#
# ``derandomize`` seeds generation from the test itself, so a given commit
# always draws the same examples on every machine and every run. ``database``
# is disabled because the local ``.hypothesis`` directory otherwise replays
# previously-failing examples first — helpful when debugging interactively,
# but it means two checkouts of the same commit run different tests.
#
# ``settings(...)`` decorators on individual tests inherit anything they do
# not set, so a module asking for ``max_examples=30`` still gets determinism
# from here.
settings.register_profile(
    "lexichunk",
    derandomize=True,
    database=None,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
settings.load_profile("lexichunk")


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
