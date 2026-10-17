"""Dashboard Files tab: /file-grants shows switches and grant names only, never host paths. No Docker or database."""
import pathlib
import re

import pytest

from core import file_access

STATIC = pathlib.Path(__file__).resolve().parent.parent / "core" / "office_static"


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body

    def json(self):
        return self._b


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("SANDBOX_TOKEN", "t")


def test_without_a_token_nothing_is_asked(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not call the runner")
    monkeypatch.setattr(file_access.requests, "get", boom)
    out = file_access.overview()
    assert out == {"tools_enabled": False, "runner": "not_configured", "computer_control": False, "grants": []}


def test_grants_are_listed_by_name_without_any_host_path(token, monkeypatch):
    reply = {"enabled": True, "grants": [
        {"name": "docs", "mode": "read", "purpose": "use", "expires": None, "path": "/srv/secret/docs"},
        {"name": "Bad Name", "mode": "read", "purpose": "use", "expires": None},
        {"name": "reports", "mode": "weird", "purpose": "odd", "expires": "2026-12-01T00:00:00+00:00"},
        "junk"]}
    monkeypatch.setattr(file_access.requests, "get", lambda *a, **k: Resp(200, reply))
    out = file_access.overview()
    assert out["runner"] == "ok" and out["computer_control"] is True
    assert [g["name"] for g in out["grants"]] == ["docs", "reports"]
    assert out["grants"][1]["mode"] == "read" and out["grants"][1]["purpose"] == "use"
    assert "/srv/secret" not in str(out) and "path" not in out["grants"][0]


def test_paused_runner_shows_no_grants_and_control_off(token, monkeypatch):
    monkeypatch.setattr(file_access.requests, "get", lambda *a, **k: Resp(200, {"enabled": False, "grants": []}))
    out = file_access.overview()
    assert out["runner"] == "ok" and out["computer_control"] is False and out["grants"] == []


def test_runner_errors_and_outages(token, monkeypatch):
    monkeypatch.setattr(file_access.requests, "get", lambda *a, **k: Resp(401, {}))
    assert file_access.overview()["runner"] == "error"

    def down(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(file_access.requests, "get", down)
    assert file_access.overview()["runner"] == "unreachable"


def test_tools_flag_is_reported(token, monkeypatch):
    monkeypatch.setattr(file_access.requests, "get", lambda *a, **k: Resp(200, {"enabled": True, "grants": []}))
    assert file_access.overview()["tools_enabled"] is False
    monkeypatch.setenv("FILE_TOOLS_ENABLED", "true")
    assert file_access.overview()["tools_enabled"] is True


def test_the_page_has_the_files_tab_and_no_add_control():
    js = (STATIC / "app.js").read_text()
    assert '["files", "Files"]' in js and "/file-grants" in js
    block = js.split("// ---- Files tab", 1)[1].split("// ---- Proactive tab", 1)[0]
    assert "api(" not in block and not re.search(r"\b(POST|PUT|PATCH|DELETE)\b", block)


def test_the_route_needs_the_key(monkeypatch):
    from fastapi.testclient import TestClient
    from core import api
    monkeypatch.setattr(api, "RAGLEAP_API_KEY", "k-test")
    c = TestClient(api.app)
    assert c.get("/file-grants").status_code == 401
    assert c.get("/file-grants", headers={"x-api-key": "wrong"}).status_code == 401
    r = c.get("/file-grants", headers={"x-api-key": "k-test"})
    assert r.status_code == 200 and r.json()["grants"] == [] and "runner" in r.json()
