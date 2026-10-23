from datetime import datetime, timedelta, timezone

import pytest

from ragleap_memory import InvalidEntryError
from ragleap_security import LimitError, Scope

A = Scope("acme")


def test_relevance_order_and_scores(store):
    best = store.add(A, "invoice invoice invoice payment terms")
    ok = store.add(A, "the invoice was sent on Monday with many other words around it")
    store.add(A, "completely unrelated gardening note")
    hits = store.search(A, "invoice")
    assert [h.entry.id for h in hits] == [best.id, ok.id]
    assert hits[0].score >= hits[1].score > 0


def test_any_word_may_match_and_unmatched_returns_nothing(store):
    e = store.add(A, "alpha beta gamma")
    assert [h.entry.id for h in store.search(A, "zzz gamma qqq")] == [e.id]
    assert store.search(A, "zzz qqq") == []


@pytest.mark.parametrize("q", ["", "   ", "!!! ???", '"""', "(", ")", "AND", "OR", "NOT", "*", "^", "-", ":"])
def test_odd_queries_do_not_error(store, q):
    store.add(A, "alpha beta")
    store.search(A, q)


def test_query_limits_and_types(store):
    with pytest.raises(LimitError):
        store.search(A, "x" * 1001)
    with pytest.raises(InvalidEntryError):
        store.search(A, 5)
    store.search(A, "x " * 500)  # positive control: exactly 1000 bytes, 32-token cap applies


@pytest.mark.parametrize("k", [0, -1, True, 1.5, "3", None])
def test_bad_k_refused(store, k):
    with pytest.raises(InvalidEntryError):
        store.search(A, "x", k=k)


def test_k_limits_results_and_is_capped(store):
    for i in range(5):
        store.add(A, f"common word {i}")
    assert len(store.search(A, "common", k=2)) == 2
    assert len(store.search(A, "common", k=10_000)) == 5  # under the store's cap of 50


def test_store_wide_result_cap_applies_even_when_k_is_larger():
    from ragleap_memory import SQLiteStore
    s = SQLiteStore(max_results=3)
    for i in range(6):
        s.add(A, f"common word {i}")
    assert len(s.search(A, "common", k=100)) == 3


def test_kinds_filter(store):
    f = store.add(A, "shared topic", kind="fact")
    s = store.add(A, "shared topic", kind="summary")
    assert {h.entry.id for h in store.search(A, "topic")} == {f.id, s.id}
    assert [h.entry.id for h in store.search(A, "topic", kinds=["summary"])] == [s.id]
    for bad in ([], ["note"], ["fact", "note"]):
        with pytest.raises(InvalidEntryError):
            store.search(A, "topic", kinds=bad)


def test_min_trust_filter(store):
    u = store.add(A, "shared topic", trust="untrusted")
    m = store.add(A, "shared topic", trust="model")
    o = store.add(A, "shared topic", trust="owner")
    assert {h.entry.id for h in store.search(A, "topic")} == {u.id, m.id, o.id}
    assert {h.entry.id for h in store.search(A, "topic", min_trust="model")} == {m.id, o.id}
    assert [h.entry.id for h in store.search(A, "topic", min_trust="owner")] == [o.id]
    with pytest.raises(InvalidEntryError):
        store.search(A, "topic", min_trust="root")


def test_search_results_carry_their_trust_label(store):
    store.add(A, "labelled entry", trust="model")
    assert store.search(A, "labelled")[0].entry.trust == "model"


def test_expired_entries_are_hidden_unless_asked(store):
    now = [datetime(2030, 1, 1, tzinfo=timezone.utc)]
    from ragleap_memory import SQLiteStore
    s = SQLiteStore(clock=lambda: now[0])
    e = s.add(A, "short lived note", expires_at=now[0] + timedelta(hours=1))
    assert [h.entry.id for h in s.search(A, "note")] == [e.id]
    now[0] += timedelta(hours=1)  # exactly at the expiry instant: expired
    assert s.search(A, "note") == []
    assert [h.entry.id for h in s.search(A, "note", include_expired=True)] == [e.id]


def test_superseded_entries_are_hidden_unless_asked(store):
    old = store.add(A, "price is ten")
    new = store.supersede(A, old.id, "price is twelve")
    assert [h.entry.id for h in store.search(A, "price")] == [new.id]
    assert {h.entry.id for h in store.search(A, "price", include_superseded=True)} == {old.id, new.id}


@pytest.mark.parametrize("text,query", [
    ("café au lait", "cafe"), ("Zürich Straße", "zurich"), ("नमस्ते दुनिया", "दुनिया"),
    ("வணக்கம் உலகம்", "உலகம்"), ("مرحبا بالعالم", "بالعالم"), ("你好 世界", "世界"),
])
def test_non_english_text_is_searchable(store, text, query):
    e = store.add(A, text)
    assert [h.entry.id for h in store.search(A, query)] == [e.id]
