"""Benchmark fixtures — reuses test fixture files."""

from __future__ import annotations

from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


@pytest.fixture(scope="session")
def uk_service_agreement() -> str:
    return (_FIXTURES_DIR / "uk_service_agreement.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def us_msa() -> str:
    return (_FIXTURES_DIR / "us_msa.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def uk_terms_conditions() -> str:
    return (_FIXTURES_DIR / "uk_terms_conditions.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def us_terms_of_service() -> str:
    return (_FIXTURES_DIR / "us_terms_of_service.txt").read_text(encoding="utf-8")
