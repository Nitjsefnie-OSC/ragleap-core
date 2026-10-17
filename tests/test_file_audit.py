"""File tools: the autonomy log never stores file contents, and pausing file access removes the tools."""
import importlib.util
import pathlib

import pytest

from core import autonomy, file_access
from core.employees import actions

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sandbox_runner_fileaudit", ROOT / "sandbox" / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


class FakeCur:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        self.rows.append((sql, params))

    def close(self):
        pass


class FakeConn:
    def __init__(self):
        self.rows = []

    def cursor(self):
        return FakeCur(self.rows)

    def commit(self):
        pass

    def close(self):
        pass


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body

    def json(self):
        return self._b


def logged(monkeypatch, action_type, result, content="a.txt"):
    conn = FakeConn()
    monkeypatch.setattr(autonomy, "get_connection", lambda: conn)
    autonomy.log_autonomous_action(action_type, "files_read", "docs", content, result, approved=True, role="sales")
    return conn.rows[0][1]


def test_read_results_are_logged_without_file_contents(monkeypatch):
    out = file_access._format_read("docs", "a.txt", {"size": 9, "bytes_read": 9, "truncated": False,
                                                      "text": "TOPSECRET text"})
    assert "TOPSECRET" in out
    params = logged(monkeypatch, "read_file", out)
    assert "TOPSECRET" not in params[4]
    assert params[4].startswith("File read:")
    assert params[2] == "docs" and params[3] == "a.txt"


def test_list_results_keep_only_the_summary_line(monkeypatch):
    out = file_access._format_list("docs", "", {"entries": [{"name": "salaries.xlsx", "type": "file", "size": 5}],
                                                "truncated": False})
    params = logged(monkeypatch, "list_files", out, content=".")
    assert params[4] == "File list: 1 entries"
    assert "salaries" not in params[4]


def test_errors_and_other_tools_are_unchanged(monkeypatch):
    assert logged(monkeypatch, "read_file", "ERROR: action failed")[4] == "ERROR: action failed"
    assert logged(monkeypatch, "fetch_page", "Page: ok\nline two")[4] == "Page: ok\nline two"


def _grant():
    return {"name": "docs", "path": "/srv/example/docs", "mode": "read", "purpose": "use", "expires": None}


def _offer(monkeypatch):
    file_access._cache.update({"at": 0.0, "names": []})
    summary = runner.grants_summary()
    monkeypatch.setattr(file_access.requests, "get", lambda *a, **k: Resp(200, summary))
    return file_access.grant_names(), actions.available_tools()


def test_the_real_pause_flag_removes_the_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("FILE_TOOLS_ENABLED", "true")
    monkeypatch.setenv("SANDBOX_TOKEN", "t")
    monkeypatch.setenv("COMPUTER_CONTROL", "true")
    monkeypatch.setattr(runner, "GRANTS_FILE", str(tmp_path / "grants.json"))
    monkeypatch.setattr(runner, "active_grants", lambda now=None: [_grant()])
    names, tools = _offer(monkeypatch)
    assert names == ["docs"] and "list_files" in tools and "read_file" in tools
    (tmp_path / "DISABLED").write_text("paused\n")
    names, tools = _offer(monkeypatch)
    assert names == [] and "list_files" not in tools and "read_file" not in tools
    (tmp_path / "DISABLED").unlink()
    names, tools = _offer(monkeypatch)
    assert names == ["docs"] and "read_file" in tools


def test_a_paused_runner_refuses_a_call_that_is_already_in_flight(monkeypatch, tmp_path):
    monkeypatch.setenv("COMPUTER_CONTROL", "true")
    monkeypatch.setattr(runner, "GRANTS_FILE", str(tmp_path / "grants.json"))
    monkeypatch.setattr(runner, "active_grants", lambda now=None: [_grant()])
    (tmp_path / "DISABLED").write_text("paused\n")
    status, body = runner.file_op({"op": "read", "grant": "docs", "path": "a.txt"})
    assert status == 403 and "off" in body["error"]
