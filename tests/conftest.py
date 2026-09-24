"""Shared pytest fixtures for the harness test suite."""
import pytest

from clinical_safety import db


@pytest.fixture()
def database(tmp_path):
    return db.get_db(str(tmp_path / "test.db"))
