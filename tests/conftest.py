import pytest


@pytest.fixture(autouse=True)
def seed_legacy_test_author(monkeypatch):
    """Most historical tests use author id 1; public installs have no example account."""
    monkeypatch.setenv('MEDIA_ARCHIVE_TEST_SEED', '1')
