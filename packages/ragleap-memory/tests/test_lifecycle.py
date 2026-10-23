import os
from datetime import datetime, timedelta, timezone

import pytest

from ragleap_memory import InvalidEntryError, NotFoundError, SQLiteStore
from ragleap_security import Scope

A = Scope("acme")


def test_supersede_links_old_and_new(store):
    old = store.add(A, "owner phone is 111", kind="fact", trust="owner", importance=0.9)
    new = store.supersede(A, old.id, "owner phone is 222", trust="owner")
    assert new.derived_from == (old.id,) and new.kind == "fact" and new.importance == 0.9 and new.scope == A
    assert store.get(A, old.id).superseded_by == new.id and store.get(A, new.id).superseded_by is None


def test_supersede_overrides_and_keeps_the_old_entrys_scope(store):
    old = store.add(Scope("acme", "alice"), "likes tea")
    new = store.supersede(A, old.id, "likes coffee", kind="summary", importance=0.2)  # tenant-wide scope may do it
    assert new.scope == Scope("acme", "alice") and new.kind == "summary" and new.importance == 0.2


def test_narrower_scope_cannot_supersede_a_wider_entry(store):
    wide = store.add(A, "tenant-level fact")
    with pytest.raises(NotFoundError):
        store.supersede(Scope("acme", "alice"), wide.id, "changed")


def test_cannot_supersede_twice_or_with_bad_input(store):
    old = store.add(A, "v1")
    store.supersede(A, old.id, "v2")
    with pytest.raises(InvalidEntryError):
        store.supersede(A, old.id, "v3")
    cur = store.add(A, "w1")
    with pytest.raises(InvalidEntryError):
        store.supersede(A, cur.id, "")
    assert store.get(A, cur.id).superseded_by is None and store.count(A) == 3  # nothing half-written
    with pytest.raises(NotFoundError):
        store.supersede(A, "0" * 32, "x")


def test_forget_counts_and_removes_from_search(store):
    a, b = store.add(A, "remove me"), store.add(A, "keep me")
    assert store.forget(A, [a.id]) == 1 and store.forget(A, [a.id]) == 0 and store.forget(A, []) == 0
    assert store.search(A, "remove") == [] and [h.entry.id for h in store.search(A, "keep")] == [b.id]
    for bad in (["nothex"], [5], ["0" * 32] * 1001):
        with pytest.raises(InvalidEntryError):
            store.forget(A, bad)


def test_export_includes_everything_visible(store):
    old = store.add(A, "old fact")
    new = store.supersede(A, old.id, "new fact")
    gone = store.add(A, "expired", expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    ids = {d["id"] for d in store.export(A)}
    assert ids == {old.id, new.id, gone.id}
    d = next(x for x in store.export(A) if x["id"] == old.id)
    assert d["scope"] == "tenant=acme" and d["superseded_by"] == new.id and d["text"] == "old fact"


def test_sweep_expired_deletes_only_expired_in_scope(store):
    now = datetime.now(timezone.utc)
    s = SQLiteStore(clock=lambda: now)
    s.add(A, "stale", expires_at=now - timedelta(seconds=1))
    live = s.add(A, "fresh", expires_at=now + timedelta(days=1))
    forever = s.add(A, "forever")
    other_stale = s.add(Scope("globex"), "other stale", expires_at=now - timedelta(days=1))
    assert s.sweep_expired(A) == 1
    assert {d["id"] for d in s.export(A)} == {live.id, forever.id}
    assert s.count(Scope("globex")) == 1 and s.get(Scope("globex"), other_stale.id)


def test_erase_removes_text_from_the_file(tmp_path):
    marker = "zyxwvmarkerqq"
    path = tmp_path / "mem.db"
    s = SQLiteStore(path)
    for i in range(3):
        s.add(A, f"keep this {i} and {marker} entry")
    keep = s.add(Scope("globex"), "other tenant stays visible")

    def raw():
        return b"".join(open(str(path) + ext, "rb").read() for ext in ("", "-wal") if os.path.exists(str(path) + ext))

    s.compact()
    assert marker.encode() in raw()  # positive control: the text really is in the file
    assert s.erase(A) == 3
    assert marker.encode() not in raw()
    assert [h.entry.id for h in s.search(Scope("globex"), "tenant")] == [keep.id]


def test_forget_alone_may_leave_traces_until_compact(tmp_path):
    # Documented limitation: forget() removes entries from queries at once, but the text can stay in
    # the file's search index until compact() or erase() runs.
    marker = "qwertymarkerzz"
    path = tmp_path / "mem.db"
    s = SQLiteStore(path)
    e = s.add(A, f"entry with {marker}")
    s.forget(A, [e.id])
    s.compact()
    raw = b"".join(open(str(path) + ext, "rb").read() for ext in ("", "-wal") if os.path.exists(str(path) + ext))
    assert marker.encode() not in raw
