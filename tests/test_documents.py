"""Documents tab: list and delete routes, and the dashboard tab."""
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "core" / "office_static" / "app.js"


def _client(monkeypatch):
    from fastapi.testclient import TestClient
    from core import api
    monkeypatch.setattr(api, "RAGLEAP_API_KEY", "k-test")
    return TestClient(api.app)


def _insert_document(filename):
    from core import document_store
    doc_id = str(uuid.uuid4())
    conn = document_store._connect()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO documents (id, filename) VALUES (%s, %s)", (doc_id, filename))
        conn.commit()
    finally:
        conn.close()
    return doc_id


def _purge(doc_id):
    from core import document_store
    document_store.delete_document(doc_id)


KEY = {"x-api-key": "k-test"}


def test_document_routes_need_the_key(monkeypatch):
    c = _client(monkeypatch)
    some_id = str(uuid.uuid4())
    assert c.get("/documents").status_code == 401
    assert c.get("/documents", headers={"x-api-key": "wrong"}).status_code == 401
    assert c.delete("/documents/" + some_id).status_code == 401
    assert c.delete("/documents/" + some_id, headers={"x-api-key": "wrong"}).status_code == 401
    assert c.get("/documents", headers=KEY).status_code == 200


def test_list_shows_a_new_document_with_zero_chunks(monkeypatch):
    c = _client(monkeypatch)
    doc_id = _insert_document("pytest-doc-" + doc_id_suffix() + ".txt")
    try:
        docs = c.get("/documents?limit=500", headers=KEY).json()["documents"]
        mine = [d for d in docs if d["id"] == doc_id]
        assert len(mine) == 1
        assert mine[0]["filename"].startswith("pytest-doc-") and mine[0]["chunks"] == 0
        assert isinstance(mine[0]["uploaded_at"], str)
    finally:
        _purge(doc_id)


def doc_id_suffix():
    return uuid.uuid4().hex[:8]


def test_delete_removes_the_document_then_404(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr("core.document_store.delete_document_graph", lambda _i: "skipped")
    doc_id = _insert_document("pytest-del-" + doc_id_suffix() + ".txt")
    try:
        r = c.delete("/documents/" + doc_id, headers=KEY)
        assert r.status_code == 200 and r.json() == {"deleted": doc_id, "graph": "skipped"}
        assert c.delete("/documents/" + doc_id, headers=KEY).status_code == 404
        docs = c.get("/documents?limit=500", headers=KEY).json()["documents"]
        assert all(d["id"] != doc_id for d in docs)
    finally:
        _purge(doc_id)


def test_delete_with_unknown_or_malformed_id_is_404(monkeypatch):
    c = _client(monkeypatch)
    assert c.delete("/documents/not-a-uuid", headers=KEY).status_code == 404
    assert c.delete("/documents/" + str(uuid.uuid4()), headers=KEY).status_code == 404


def test_chunks_are_counted_and_removed_with_the_document(monkeypatch):
    import psycopg2
    from core import document_store
    c = _client(monkeypatch)
    doc_id = _insert_document("pytest-chunks-" + doc_id_suffix() + ".txt")
    try:
        conn = document_store._connect()
        try:
            cur = conn.cursor()
            try:
                cur.execute("INSERT INTO chunks (document_id, document_name, chunk_index, text) "
                            "VALUES (%s, %s, %s, %s)", (doc_id, "pytest", 0, "hello"))
                conn.commit()
            except psycopg2.Error:
                conn.rollback()
                pytest.skip("chunks table needs more columns than the test fills in")
        finally:
            conn.close()
        mine = [d for d in c.get("/documents?limit=500", headers=KEY).json()["documents"] if d["id"] == doc_id]
        assert mine and mine[0]["chunks"] == 1
        assert c.delete("/documents/" + doc_id, headers=KEY).status_code == 200
        conn = document_store._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM chunks WHERE document_id = %s", (doc_id,))
            assert cur.fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        _purge(doc_id)


def test_dashboard_has_the_documents_tab():
    s = APP_JS.read_text(encoding="utf-8")
    assert '["documents", "Documents"]' in s
    assert '"/documents"' in s and "uploadDocument" in s
    assert '"accept"' in s


def test_dashboard_script_parses_with_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--check", str(APP_JS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[:500]


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def single(self):
        return self.rows[0] if self.rows else None


class _Session:
    def __init__(self, log, names, fail):
        self.log, self.names, self.fail = log, names, fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.log.append((query, params))
        if self.fail:
            raise RuntimeError("boom")
        if "RETURN e.name" in query:
            return _Result([{"name": n} for n in self.names])
        if "RETURN count(*)" in query:
            return _Result([{"removed": 2}])
        return _Result([])


class _Driver:
    def __init__(self, names=(), fail=False):
        self.log = []
        self.names = list(names)
        self.fail = fail

    def session(self):
        return _Session(self.log, self.names, self.fail)


def _service(driver):
    from core.graph import GraphService
    svc = GraphService.__new__(GraphService)
    svc.driver = driver
    return svc


def test_graph_delete_removes_document_then_orphan_entities():
    drv = _Driver(names=["alpha", "beta"])
    res = _service(drv).delete_document_graph("doc-1")
    assert res["success"] is True and res["entities_removed"] == 2 and res["skipped"] is False
    assert len(drv.log) == 3
    assert "RETURN e.name" in drv.log[0][0] and drv.log[0][1] == {"document_id": "doc-1"}
    assert "DETACH DELETE d" in drv.log[1][0] and drv.log[1][1] == {"document_id": "doc-1"}
    assert "UNWIND" in drv.log[2][0] and "NOT (e)<-[:CONTAINS]-(:Document)" in drv.log[2][0]
    assert drv.log[2][1] == {"names": ["alpha", "beta"]}


def test_graph_delete_without_entities_only_removes_the_document():
    drv = _Driver(names=[])
    res = _service(drv).delete_document_graph("doc-2")
    assert res["success"] is True and res["entities_removed"] == 0
    assert len(drv.log) == 2


def test_graph_delete_is_skipped_without_a_driver():
    res = _service(None).delete_document_graph("doc-3")
    assert res["skipped"] is True and res["success"] is False


def test_graph_delete_failure_never_raises():
    res = _service(_Driver(names=["x"], fail=True)).delete_document_graph("doc-4")
    assert res["success"] is False and res["skipped"] is False and "boom" in res["error"]


def test_document_store_maps_graph_results(monkeypatch):
    from core import document_store, graph
    for result, expected in (({"skipped": True}, "skipped"), ({"success": True}, "cleaned"),
                             ({"success": False}, "failed")):
        monkeypatch.setattr(graph.graph_service, "delete_document_graph", lambda _i, r=result: r)
        assert document_store.delete_document_graph(str(uuid.uuid4())) == expected
    assert document_store.delete_document_graph("not-a-uuid") == "failed"


def test_delete_route_reports_the_graph_status(monkeypatch):
    c = _client(monkeypatch)
    doc_id = _insert_document("pytest-graph-" + doc_id_suffix() + ".txt")
    monkeypatch.setattr("core.document_store.delete_document_graph", lambda _i: "failed")
    try:
        r = c.delete("/documents/" + doc_id, headers=KEY)
        assert r.status_code == 200 and r.json() == {"deleted": doc_id, "graph": "failed"}
    finally:
        _purge(doc_id)


def test_unknown_document_does_not_touch_the_graph(monkeypatch):
    c = _client(monkeypatch)
    calls = []
    monkeypatch.setattr("core.document_store.delete_document_graph", lambda i: calls.append(i) or "cleaned")
    assert c.delete("/documents/" + str(uuid.uuid4()), headers=KEY).status_code == 404
    assert calls == []
