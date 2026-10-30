"""Fixtures compartidas de biomech-pipelines."""

from __future__ import annotations

from pathlib import Path

import pytest

from biomech_pipelines.anonymize import Anonymizer

SALT = "test-salt-with-more-than-16-characters"


@pytest.fixture()
def anonymizer() -> Anonymizer:
    return Anonymizer(SALT)


@pytest.fixture()
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
