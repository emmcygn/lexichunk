"""Shared pytest fixtures and the Hypothesis profiles for lexichunk tests."""

import os
from datetime import timedelta
from pathlib import Path

import pytest

from lexichunk.jurisdiction import registered_jurisdictions, unregister_jurisdiction

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Hypothesis profiles
#
# Both profiles are derandomised, so a property-based failure reproduces
# exactly: the same commit generates the same examples on a laptop and on a
# CI runner, and a red build can be re-run locally without hunting for a seed.
# The default 200ms per-example deadline is too tight for a cold, shared CI
# runner (a first call pays for regex compilation), so the ``ci`` profile
# raises it rather than letting the suite flake.
#
# Select explicitly with ``pytest -p hypothesis --hypothesis-profile=ci`` or
# via ``HYPOTHESIS_PROFILE``; otherwise ``ci`` is used when ``$CI`` is set.
# ---------------------------------------------------------------------------
try:
    from hypothesis import HealthCheck, settings
except ImportError:  # pragma: no cover - hypothesis is a dev dependency
    pass
else:
    settings.register_profile(
        "dev",
        derandomize=True,
        deadline=timedelta(milliseconds=500),
        print_blob=True,
    )
    settings.register_profile(
        "ci",
        derandomize=True,
        deadline=timedelta(seconds=2),
        max_examples=100,
        print_blob=True,
        suppress_health_check=[HealthCheck.too_slow],
    )
    settings.load_profile(
        os.environ.get("HYPOTHESIS_PROFILE") or ("ci" if os.environ.get("CI") else "dev")
    )


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
