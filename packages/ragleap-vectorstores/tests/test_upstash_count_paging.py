"""Mock-based tests for UpstashBackend.list_documents() chunk counting: no Upstash account needed (the live tests in
test_upstash_backend.py skip without credentials). The index is replaced by a fake whose range() pages like the real
one: at most `limit` vectors per call and a next_cursor until the prefix scan is finished."""
import types

import pytest

pytest.importorskip("upstash_vector")

from ragleap_vectorstores.upstash_backend import UpstashBackend  # noqa: E402


class FakeIndex:
    """Holds vector ids; range() filters by prefix and returns at most `limit` per call."""

    def __init__(self, ids, loop_forever=False):
        self.ids = list(ids)
        self.calls = []
        self.loop_forever = loop_forever

    def range(self, cursor="", limit=1, prefix=None, namespace="", **kwargs):
        self.calls.append({"cursor": cursor, "limit": limit, "prefix": prefix, "namespace": namespace})
        matching = [i for i in self.ids if prefix is None or i.startswith(prefix)]
        start = int(cursor or 0)
        page = matching[start:start + limit]
        if self.loop_forever:
            return types.SimpleNamespace(next_cursor="7", vectors=[types.SimpleNamespace(id=i) for i in page])
        end = start + len(page)
        next_cursor = str(end) if end < len(matching) else ""
        return types.SimpleNamespace(next_cursor=next_cursor, vectors=[types.SimpleNamespace(id=i) for i in page])


def make_backend(tmp_path, ids, **fake_kwargs):
    backend = UpstashBackend(
        url="https://example.upstash.io", token="example-token", namespace="ns1",
        registry_path=str(tmp_path / "registry.sqlite3"),
    )
    backend._index = FakeIndex(ids, **fake_kwargs)
    return backend


def counts(backend):
    return {d["document_id"]: d["chunk_count"] for d in backend.list_documents(limit=10, offset=0)}


def test_document_with_more_than_one_page_of_chunks_is_counted_fully(tmp_path):
    ids = ["big:%d" % i for i in range(2500)] + ["other:0", "other:1"]
    backend = make_backend(tmp_path, ids)
    backend.insert_document("big", "big.txt", {})
    backend.insert_document("other", "other.txt", {})
    assert counts(backend) == {"big": 2500, "other": 2}


def test_small_and_empty_documents_still_count_correctly(tmp_path):
    backend = make_backend(tmp_path, ["a:0", "a:1", "a:2"])
    backend.insert_document("a", "a.txt", {})
    backend.insert_document("empty", "e.txt", {})
    assert counts(backend) == {"a": 3, "empty": 0}


def test_every_page_is_requested_with_the_cursor_prefix_and_namespace(tmp_path):
    backend = make_backend(tmp_path, ["big:%d" % i for i in range(2001)])
    backend.insert_document("big", "big.txt", {})
    assert counts(backend) == {"big": 2001}
    calls = backend._index.calls
    assert [c["cursor"] for c in calls] == ["", "1000", "2000"]
    assert all(c["prefix"] == "big:" and c["namespace"] == "ns1" and c["limit"] == 1000 for c in calls)


def test_a_server_that_repeats_the_same_cursor_does_not_loop_forever(tmp_path):
    backend = make_backend(tmp_path, ["d:%d" % i for i in range(10)], loop_forever=True)
    backend.insert_document("d", "d.txt", {})
    assert counts(backend)["d"] >= 10
    assert len(backend._index.calls) <= 3
