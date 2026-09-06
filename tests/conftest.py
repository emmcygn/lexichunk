"""Shared pytest fixtures for lexichunk tests."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
