from datetime import datetime, timedelta, timezone

import pytest

from ragleap_memory import InvalidEntryError, NotFoundError
from ragleap_security import LimitError, Scope, SecretStr

A = Scope("acme")


def test_add_returns_entry_with_safe_defaults(store):
    e = store.add(A, "hello world")
    assert e.scope == A and e.kind == "fact" and e.trust == "untrusted" and e.importance == 0.5
    assert len(e.id) == 32 and e.superseded_by is None and e.derived_from == () and e.metadata == {}
    assert store.get(A, e.id) == e


def test_explicit_trust_kind_source_importance_metadata(store):
    e = store.add(A, "x y", kind="summary", source="agent:planner", trust="owner", importance=1, metadata={"k": [1, 2]})
    assert (e.kind, e.source, e.trust, e.importance, e.metadata) == ("summary", "agent:planner", "owner", 1, {"k": [1, 2]})


@pytest.mark.parametrize("bad", ["", "   ", None, 5, b"bytes"])
def test_bad_text_refused(store, bad):
    with pytest.raises(InvalidEntryError):
        store.add(A, bad)


def test_text_size_limit_counts_bytes_and_boundary(store):
    store.add(A, "a" * 8192)  # positive control: exactly at the limit
    with pytest.raises(LimitError):
        store.add(A, "a" * 8193)
    with pytest.raises(LimitError):
        store.add(A, "é" * 4097)  # 8194 bytes


@pytest.mark.parametrize("field,value", [("kind", "note"), ("trust", "admin"), ("source", ""), ("source", "a b"),
                                         ("source", "-x"), ("importance", -0.1), ("importance", 1.1),
                                         ("importance", True), ("importance", "high"), ("importance", None)])
def test_bad_fields_refused(store, field, value):
    with pytest.raises(InvalidEntryError):
        store.add(A, "text", **{field: value})


@pytest.mark.parametrize("scope", ["tenant=acme", None, {"tenant": "acme"}, 5])
def test_scope_must_be_a_scope(store, scope):
    with pytest.raises(Exception) as e:
        store.add(scope, "text")
    assert type(e.value).__name__ == "ScopeError"
    assert store.count(A) == 0


def test_metadata_rules(store):
    for bad in ([1], "x", 5):
        with pytest.raises(InvalidEntryError):
            store.add(A, "t", metadata=bad)
    with pytest.raises(InvalidEntryError):
        store.add(A, "t", metadata={"k": SecretStr("abcdefgh")})  # not JSON serializable
    with pytest.raises(InvalidEntryError):
        store.add(A, "t", metadata={"k": object()})
    with pytest.raises(LimitError):
        store.add(A, "t", metadata={"k": "x" * 5000})
    deep = cur = {}
    for _ in range(20):
        cur["n"] = {}
        cur = cur["n"]
    with pytest.raises(LimitError):
        store.add(A, "t", metadata=deep)
    store.add(A, "t", metadata={"k": "x" * 4000})  # positive control under the size limit


def test_expires_at_must_be_aware(store):
    with pytest.raises(InvalidEntryError):
        store.add(A, "t", expires_at=datetime.now())
    with pytest.raises(InvalidEntryError):
        store.add(A, "t", expires_at="2030-01-01")
    e = store.add(A, "t", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    assert e.expires_at.endswith("+00:00")


def test_derived_from_rules(store):
    parent = store.add(A, "parent fact")
    child = store.add(A, "summary of parent", kind="summary", derived_from=[parent.id])
    assert child.derived_from == (parent.id,)
    for bad in (["nothex"], [parent.id, parent.id], ["0" * 32], [5]):
        with pytest.raises((InvalidEntryError, NotFoundError)):
            store.add(A, "x", derived_from=bad)
    with pytest.raises(InvalidEntryError):
        store.add(A, "x", derived_from=["%032x" % i for i in range(101)])


def test_derived_from_cannot_point_into_another_tenant(store):
    other = store.add(Scope("other"), "their secret")
    with pytest.raises(NotFoundError):
        store.add(A, "link to theirs", derived_from=[other.id])
    assert store.count(A) == 0
