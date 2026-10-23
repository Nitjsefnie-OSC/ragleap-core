import pytest

from ragleap_memory import NotFoundError
from ragleap_security import Scope

A, B = Scope("acme"), Scope("globex")
WORD = "quarterly forecast"


@pytest.fixture
def two(store):
    a = store.add(A, f"acme {WORD}")
    b = store.add(B, f"globex {WORD}")
    return store, a, b


def test_search_never_crosses_tenants(two):
    store, a, b = two
    assert [h.entry.id for h in store.search(A, WORD)] == [a.id]
    assert [h.entry.id for h in store.search(B, WORD)] == [b.id]


def test_get_across_tenants_looks_like_missing(two):
    store, a, b = two
    with pytest.raises(NotFoundError) as e1:
        store.get(A, b.id)
    with pytest.raises(NotFoundError) as e2:
        store.get(A, "0" * 32)
    assert str(e1.value) == str(e2.value)


def test_count_export_are_per_tenant(two):
    store, a, b = two
    assert store.count(A) == 1 and store.count(B) == 1
    assert [d["id"] for d in store.export(A)] == [a.id]
    assert Scope("nobody").key and store.count(Scope("nobody")) == 0 and store.export(Scope("nobody")) == []


def test_forget_cannot_delete_another_tenants_entry(two):
    store, a, b = two
    assert store.forget(A, [b.id]) == 0
    assert store.count(B) == 1
    assert store.forget(A, [a.id, b.id]) == 1  # only its own
    assert store.count(A) == 0 and store.count(B) == 1


def test_supersede_cannot_touch_another_tenants_entry(two):
    store, a, b = two
    with pytest.raises(NotFoundError):
        store.supersede(A, b.id, "overwritten")
    assert store.get(B, b.id).superseded_by is None
    assert store.count(B) == 1


def test_erase_and_sweep_stay_inside_the_tenant(two):
    store, a, b = two
    assert store.erase(A) == 1
    assert store.count(A) == 0 and store.count(B) == 1
    assert store.sweep_expired(A) == 0
    assert [h.entry.id for h in store.search(B, WORD)] == [b.id]


def test_narrow_scope_sees_only_its_own_subject(store):
    alice, bob = Scope("acme", "alice"), Scope("acme", "bob")
    ea = store.add(alice, f"alice {WORD}")
    eb = store.add(bob, f"bob {WORD}")
    assert [h.entry.id for h in store.search(alice, WORD)] == [ea.id]
    assert [h.entry.id for h in store.search(bob, WORD)] == [eb.id]
    with pytest.raises(NotFoundError):
        store.get(alice, eb.id)
    assert store.forget(alice, [eb.id]) == 0
    assert store.erase(alice) == 1 and store.count(bob) == 1


def test_tenant_wide_scope_sees_every_subject_in_its_tenant(store):
    ea = store.add(Scope("acme", "alice"), f"alice {WORD}")
    eb = store.add(Scope("acme", "bob"), f"bob {WORD}")
    et = store.add(A, f"tenant-level {WORD}")
    other = store.add(B, f"other {WORD}")
    got = {h.entry.id for h in store.search(A, WORD, k=10)}
    assert got == {ea.id, eb.id, et.id} and other.id not in got  # positive control plus isolation


def test_subject_scope_does_not_see_tenant_level_entries(store):
    tenant_level = store.add(A, f"tenant-level {WORD}")
    alice = Scope("acme", "alice")
    assert store.search(alice, WORD) == []
    with pytest.raises(NotFoundError):
        store.get(alice, tenant_level.id)


def test_agent_and_session_parts_narrow_too(store):
    s1 = Scope("acme", "alice", "bot", "s1")
    s2 = Scope("acme", "alice", "bot", "s2")
    e1 = store.add(s1, f"first {WORD}")
    e2 = store.add(s2, f"second {WORD}")
    assert [h.entry.id for h in store.search(s1, WORD)] == [e1.id]
    assert {h.entry.id for h in store.search(Scope("acme", "alice", "bot"), WORD)} == {e1.id, e2.id}
    assert store.search(Scope("acme", "alice", "other-bot"), WORD) == []


def test_search_query_cannot_escape_the_scope(two):
    store, a, b = two
    for q in ['forecast" OR tenant:globex', "tenant:globex forecast", "forecast NOT acme", "* forecast", 'a" OR "b',
              "forecast AND (globex OR acme)", "NEAR(forecast quarterly)", "text: forecast"]:
        ids = {h.entry.id for h in store.search(A, q, k=10)}
        assert b.id not in ids, q
