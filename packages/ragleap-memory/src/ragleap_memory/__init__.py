"""ragleap-memory: durable, tenant-scoped long-term memory for LLM applications.

Needs SQLite with FTS5. Not independently audited. See docs/threat-model.md."""
from ragleap_memory.model import (KINDS, TRUSTS, InvalidEntryError, MemoryEntry, MemoryStoreError, NotFoundError,
                                  SearchHit)
from ragleap_memory.sqlite_store import SCHEMA_VERSION, SQLiteStore

__version__ = "0.1.0"

__all__ = [
    "InvalidEntryError", "KINDS", "MemoryEntry", "MemoryStoreError", "NotFoundError", "SCHEMA_VERSION",
    "SQLiteStore", "SearchHit", "TRUSTS", "__version__",
]
