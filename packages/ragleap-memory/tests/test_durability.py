import os
import sqlite3
import stat
import threading

import pytest

from ragleap_memory import MemoryStoreError, NotFoundError, SQLiteStore
from ragleap_security import AuditError, AuditLog, Scope

A = Scope("acme")


def test_data_survives_reopen(tmp_path):
    p = tmp_path / "mem.db"
    s = SQLiteStore(p)
    e = s.add(A, "remember this across restarts", trust="owner", metadata={"k": 1})
    s.close()
    s2 = SQLiteStore(p)
    assert s2.get(A, e.id) == e
    assert [h.entry.id for h in s2.search(A, "restarts")] == [e.id]


def test_database_file_is_private(tmp_path):
    p = tmp_path / "mem.db"
    SQLiteStore(p).add(A, "x y")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_newer_schema_is_refused(tmp_path):
    p = tmp_path / "mem.db"
    SQLiteStore(p).close()
    c = sqlite3.connect(p)
    c.execute("PRAGMA user_version = 99")
    c.commit()
    c.close()
    with pytest.raises(MemoryStoreError):
        SQLiteStore(p)


def test_threads_can_add_concurrently(tmp_path):
    s = SQLiteStore(tmp_path / "mem.db")

    def work(n):
        for i in range(25):
            s.add(Scope("acme", f"u{n}"), f"note {n} {i}")

    ts = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert s.count(A) == 200
    for n in range(8):
        assert s.count(Scope("acme", f"u{n}")) == 25


def test_a_failed_write_leaves_nothing_behind(store):
    parent = store.add(A, "parent")
    with pytest.raises(NotFoundError):
        store.add(A, "child", derived_from=[parent.id, "0" * 32])  # second id does not exist
    assert store.count(A) == 1


def test_audit_log_records_operations_without_text(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    s = SQLiteStore(audit=audit)
    e = s.add(A, "top secret plan", trust="owner")
    n = s.supersede(A, e.id, "revised secret plan", trust="owner")
    s.export(A)
    s.forget(A, [n.id])
    s.sweep_expired(A)
    s.erase(A)
    raw = open(audit.path).read()
    assert "secret plan" not in raw
    events = [__import__("json").loads(l)["event"] for l in raw.splitlines()]
    assert events == ["memory.add", "memory.supersede", "memory.export", "memory.forget", "memory.sweep", "memory.erase"]
    assert audit.verify().ok and all(__import__("json").loads(l)["scope"] == "tenant=acme" for l in raw.splitlines())


def test_a_failing_audit_log_blocks_the_write(tmp_path):
    class Broken:
        def append(self, *a, **k):
            raise AuditError("disk full")

    s = SQLiteStore(audit=Broken())
    with pytest.raises(AuditError):
        s.add(A, "must not be stored unaudited")
    assert s.count(A) == 0


def test_a_failing_audit_log_blocks_erase_and_forget(tmp_path):
    s = SQLiteStore()
    e = s.add(A, "stays")

    class Broken:
        def append(self, *a, **k):
            raise AuditError("disk full")

    s._audit = Broken()
    with pytest.raises(AuditError):
        s.forget(A, [e.id])
    with pytest.raises(AuditError):
        s.erase(A)
    assert s.count(A) == 1
