"""Shared pytest fixtures for lexichunk tests."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
