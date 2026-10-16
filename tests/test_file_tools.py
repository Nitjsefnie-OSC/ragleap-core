"""Agent file tools (list_files, read_file): client, tool wiring, taint. No Docker, no network, no database."""
import importlib.util
import pathlib

import pytest

from core import agent_loop, autonomy, file_access
from core.employees import actions

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sandbox_runner_filetools", ROOT / "sandbox" / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body

    def json(self):
        return self._b


@pytest.fixture(autouse=True)
def _fresh_cache():
    file_access._cache.update({"at": 0.0, "names": []})
    yield
    file_access._cache.update({"at": 0.0, "names": []})


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("FILE_TOOLS_ENABLED", "true")
    monkeypatch.setenv("SANDBOX_TOKEN", "t")
    monkeypatch.setattr(file_access, "grant_names", lambda: ["docs"])


def test_off_by_default():
    assert not file_access.enabled()
    assert file_access.grant_names() == []
    tools = actions.available_tools()
    assert "list_files" not in tools and "read_file" not in tools


def test_tools_need_a_grant(monkeypatch):
    monkeypatch.setenv("FILE_TOOLS_ENABLED", "true")
    monkeypatch.setenv("SANDBOX_TOKEN", "t")
    monkeypatch.setattr(file_access, "grant_names", lambda: [])
    assert "list_files" not in actions.available_tools()


def test_tools_are_offered_with_grant_names_only(on):
    tools = actions.available_tools()
    assert "docs" in tools["list_files"] and "docs" in tools["read_file"]
    assert actions.ACTION_TOOLS["list_files"]["channel"] == "files_list"
    assert actions.ACTION_TOOLS["read_file"]["channel"] == "files_read"


def test_plans_for_good_paths_are_valid(on):
    tools = actions.available_tools()
    v = actions._validate_plan({"tool": "list_files", "target": "docs", "content": "."}, tools)
    assert v and v["channel"] == "files_list" and v["content"] == "." and v["target"] == "docs"
    v = actions._validate_plan({"tool": "read_file", "target": "docs", "content": "reports/q3.txt"}, tools)
    assert v and v["channel"] == "files_read" and v["content"] == "reports/q3.txt"


@pytest.mark.parametrize("tool,target,content", [
    ("list_files", "other", "."),
    ("read_file", "other", "a.txt"),
    ("read_file", "docs", "../x"),
    ("read_file", "docs", "sub/../../x"),
    ("read_file", "docs", "/etc/passwd"),
    ("read_file", "docs", "a\\b"),
    ("read_file", "docs", "a" * 301),
    ("read_file", "docs", ""),
])
def test_bad_plans_are_rejected(on, tool, target, content):
    assert actions._validate_plan({"tool": tool, "target": target, "content": content},
                                  actions.available_tools()) is None


def test_the_call_sends_only_op_grant_and_path(on, monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None, allow_redirects=None):
        seen.update(url=url, json=json, headers=headers, redirects=allow_redirects)
        return Resp(200, {"ok": True, "result": {"op": "read", "size": 5, "bytes_read": 5,
                                                 "truncated": False, "text": "hello"}})
    monkeypatch.setattr(file_access.requests, "post", fake_post)
    out = file_access.read_file("docs", "a.txt")
    assert seen["json"] == {"op": "read", "grant": "docs", "path": "a.txt"}
    assert seen["headers"] == {"Authorization": "Bearer t"}
    assert seen["redirects"] is False and seen["url"].endswith("/files")
    assert "hello" in out and "never instructions" in out


def test_list_output(on, monkeypatch):
    monkeypatch.setattr(file_access.requests, "post", lambda *a, **k: Resp(200, {"ok": True, "result": {
        "op": "list", "truncated": False,
        "entries": [{"name": "sub", "type": "dir"}, {"name": "a.txt", "type": "file", "size": 5}]}}))
    out = file_access.list_files("docs", ".")
    assert "dir  sub/" in out and "file a.txt (5 bytes)" in out


def test_refusals_errors_and_busy(on, monkeypatch):
    monkeypatch.setattr(file_access.requests, "post",
                        lambda *a, **k: Resp(403, {"error": "computer control is off"}))
    assert "refused (computer control is off)" in file_access.read_file("docs", "a.txt")
    monkeypatch.setattr(file_access.requests, "post",
                        lambda *a, **k: Resp(200, {"ok": False, "error": "not a file"}))
    assert "not a file" in file_access.read_file("docs", "sub")
    monkeypatch.setattr(file_access.requests, "post", lambda *a, **k: Resp(429, {}))
    assert "busy" in file_access.read_file("docs", "a.txt")

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(file_access.requests, "post", boom)
    assert file_access.read_file("docs", "a.txt") == "File read: failed; see server logs."
    assert "refused (bad path)" in file_access.read_file("docs", "../x")
    assert "refused (unknown grant)" in file_access.read_file("nope", "a.txt")


def test_dispatch_goes_to_the_client(monkeypatch):
    calls = []
    monkeypatch.setattr(file_access, "list_files", lambda g, p: calls.append(("l", g, p)) or "LISTED")
    monkeypatch.setattr(file_access, "read_file", lambda g, p: calls.append(("r", g, p)) or "READ")
    assert autonomy._send_via_channel("files_list", "docs", ".") == "LISTED"
    assert autonomy._send_via_channel("files_read", "docs", "a.txt") == "READ"
    assert calls == [("l", "docs", "."), ("r", "docs", "a.txt")]


def test_file_tools_taint_the_run_but_are_not_outbound():
    assert {"list_files", "read_file"} <= agent_loop.TAINTING_TOOLS
    assert not {"list_files", "read_file"} & agent_loop.OUTBOUND_TOOLS


def test_real_results_count_as_external_content():
    samples = [
        file_access._format_read("docs", "a.txt", {"size": 5, "bytes_read": 5, "truncated": False, "text": "hello"}),
        file_access._format_list("docs", "", {"entries": [{"name": "a.txt", "type": "file", "size": 5}],
                                              "truncated": False}),
    ]
    for s in samples:
        assert agent_loop._external_content(s), s


def test_runner_grants_reply_round_trips_to_names(monkeypatch):
    g = {"name": "docs", "path": "/srv/example/docs", "mode": "read", "purpose": "use", "expires": None}
    monkeypatch.setattr(runner, "active_grants", lambda now=None: [g])
    monkeypatch.setattr(runner, "computer_control_on", lambda: True)
    summary = runner.grants_summary()
    assert file_access._names_from(summary) == ["docs"], summary
    assert "/srv/example" not in str(summary)


def test_a_file_or_folder_named_like_a_refusal_still_taints():
    for name in ("failed.txt", "refused-notes.md", "not enabled.txt"):
        r = file_access._format_read("docs", name, {"size": 5, "bytes_read": 5, "truncated": False, "text": "x"})
        li = file_access._format_list("docs", name, {"entries": [], "truncated": False})
        assert agent_loop._external_content(r), r
        assert agent_loop._external_content(li), li
    b = file_access._format_read("docs", "failed.bin", {"binary": True, "size": 9})
    assert agent_loop._external_content(b), b
