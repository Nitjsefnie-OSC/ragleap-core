import pytest

from ragleap_memory import SQLiteStore


@pytest.fixture
def store():
    s = SQLiteStore()
    yield s
    s.close()
