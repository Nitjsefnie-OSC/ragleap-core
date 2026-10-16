"""Owner-granted file access in the sandbox runner: grants, path rules, the fixed container spec, the reader
(run for real on a temporary folder, including escape attempts) and the HTTP endpoints.
No Docker, network or database is used. The spec tests are tripwires: widening file access must fail CI."""
import hashlib
import http.client
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sandbox_runner_files", ROOT / "sandbox" / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

GRANT = {"name": "reports", "path": "/data/reports", "mode": "read", "purpose": "use", "expires": None}


# ---------------- kill switch ----------------

def test_computer_control_is_off_by_default(monkeypatch):
    monkeypatch.delenv("COMPUTER_CONTROL", raising=False)
    assert runner.computer_control_on() is False
    assert runner.file_op({"op": "list", "grant": "x"}) == (403, {"error": "computer control is off"})
    assert runner.grants_summary() == {"enabled": False, "grants": []}
    monkeypatch.setenv("COMPUTER_CONTROL", "yes")
    assert runner.computer_control_on() is False           # only the literal "true"
    monkeypatch.setenv("COMPUTER_CONTROL", "true")
    assert runner.computer_control_on() is True


# ---------------- grants ----------------

@pytest.mark.parametrize("path", ["/home/alice/reports", "/data/shared", "/srv/files/q3", "/home/alice/projects/app"])
def test_fine_folders_can_be_granted(path):
    assert runner.grant_path_problem(path) is None


@pytest.mark.parametrize("path", [
    "/", "/home", "/home/alice", "/Users/bob", "/root", "/var", "/tmp", "/etc", "/etc/ssh", "/proc/1",
    "/var/run/docker.sock", "/var/lib/docker/volumes", "/usr/bin", "/run/user/1000",
    "relative/path", "", "/data/../etc", "/data//x", "/data/x/", "/data/./x",
    "/home/alice/.ssh", "/home/alice/.aws/creds", "/home/alice/project/.git", "/data/.env", "/data/keys/id_rsa",
    "/data/a\\b", "/data/\x00x",
])
def test_dangerous_or_odd_folders_are_refused(path):
    assert runner.grant_path_problem(path)


def test_grant_fields_are_checked():
    ok = {"name": "reports", "path": "/data/reports", "mode": "read"}
    assert runner.parse_grant(ok)[0]["purpose"] == "use"
    for bad in [dict(ok, name="Reports"), dict(ok, name=""), dict(ok, name="a b"), dict(ok, name="x" * 40),
                dict(ok, name="../x"), dict(ok, mode="rw"), dict(ok, mode=None), dict(ok, purpose="other"),
                dict(ok, expires="not a date"), dict(ok, path="/etc"), "text", None, 5]:
        assert runner.parse_grant(bad)[0] is None, bad


def test_expired_grants_are_not_active_and_naive_times_count_as_utc(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    f = tmp_path / "grants.json"
    f.write_text(json.dumps({"grants": [
        {"name": "past", "path": "/data/a", "mode": "read", "expires": (now - timedelta(hours=1)).isoformat()},
        {"name": "future", "path": "/data/b", "mode": "read", "expires": (now + timedelta(hours=1)).isoformat()},
        {"name": "naive", "path": "/data/c", "mode": "read", "expires": (now + timedelta(hours=2)).replace(tzinfo=None).isoformat()},
        {"name": "never", "path": "/data/d", "mode": "write"},
    ]}))
    monkeypatch.setattr(runner, "GRANTS_FILE", str(f))
    assert sorted(g["name"] for g in runner.active_grants()) == ["future", "naive", "never"]


def test_load_grants_skips_bad_and_duplicate_entries_and_survives_garbage(tmp_path, monkeypatch):
    f = tmp_path / "grants.json"
    monkeypatch.setattr(runner, "GRANTS_FILE", str(f))
    assert runner.load_grants() == []                       # no file
    f.write_text("not json at all")
    assert runner.load_grants() == []
    f.write_text(json.dumps({"grants": "nope"}))
    assert runner.load_grants() == []
    f.write_text(json.dumps({"grants": [
        {"name": "a", "path": "/data/a", "mode": "read"},
        {"name": "a", "path": "/data/other", "mode": "write"},      # duplicate name: the first one wins
        {"name": "etc", "path": "/etc", "mode": "read"},             # refused path
        {"name": "b", "path": "/data/b", "mode": "write"},
    ]}))
    got = runner.load_grants()
    assert [(g["name"], g["path"], g["mode"]) for g in got] == [("a", "/data/a", "read"), ("b", "/data/b", "write")]


def test_summary_never_contains_host_paths(tmp_path, monkeypatch):
    f = tmp_path / "grants.json"
    f.write_text(json.dumps({"grants": [{"name": "reports", "path": "/data/secret-place/reports", "mode": "read"}]}))
    monkeypatch.setattr(runner, "GRANTS_FILE", str(f))
    monkeypatch.setenv("COMPUTER_CONTROL", "true")
    s = runner.grants_summary()
    assert s["enabled"] is True and s["grants"][0]["name"] == "reports" and s["grants"][0]["mode"] == "read"
    assert "secret-place" not in json.dumps(s) and "path" not in s["grants"][0]


# ---------------- relative paths ----------------

@pytest.mark.parametrize("rel", ["q3/sales.csv", "notes.txt", "a/b/c.md", "./x.txt"])
def test_good_relative_paths(rel):
    assert runner.rel_problem(rel) is None


@pytest.mark.parametrize("rel", ["/etc/passwd", "../x", "a/../../x", "a\\b", ".env", "sub/.env", "id_rsa", "keys/server.pem",
                                 ".ssh/config", "x" * 400, "a\x00b", ".git/config", "Credentials.JSON", 5, None])
def test_bad_relative_paths(rel):
    assert runner.rel_problem(rel)


def test_an_empty_path_is_only_fine_for_list():
    assert runner.rel_problem("", allow_empty=True) is None
    assert runner.rel_problem("  ", allow_empty=True) is None
    assert runner.rel_problem("") == "give a file path"


# ---------------- the container spec (tripwires) ----------------

def test_file_spec_is_the_normal_hardened_spec_plus_one_read_only_mount():
    base = runner.build_spec("")
    spec = runner.build_file_spec(GRANT, "read", "a.txt")
    for key in base:
        if key not in ("Cmd", "Env", "HostConfig"):
            assert spec[key] == base[key], key
    host = dict(spec["HostConfig"])
    mounts = host.pop("Mounts")
    assert host == base["HostConfig"]                       # every limit and flag unchanged
    assert mounts == [{"Type": "bind", "Source": "/data/reports", "Target": "/data", "ReadOnly": True}]
    assert "Binds" not in spec["HostConfig"]
    assert spec["NetworkDisabled"] is True and spec["HostConfig"]["NetworkMode"] == "none"
    assert spec["HostConfig"]["ReadonlyRootfs"] is True and spec["HostConfig"]["CapDrop"] == ["ALL"]
    assert spec["HostConfig"]["Privileged"] is False and spec["User"] == "65534:65534"


def test_file_spec_runs_the_fixed_reader_and_passes_only_four_values():
    spec = runner.build_file_spec(GRANT, "list", "sub")
    assert spec["Cmd"] == ["python", "-I", "-B", "-c", runner.FILE_READER]
    assert sorted(e.split("=", 1)[0] for e in spec["Env"]) == ["MAXB", "MAXN", "OP", "REL"]
    evil = runner.build_file_spec(GRANT, "read", "x; rm -rf /")
    assert evil["Cmd"] == spec["Cmd"] and "rm -rf" in " ".join(evil["Env"]) and "rm -rf" not in " ".join(evil["Cmd"])


def test_write_grants_are_still_mounted_read_only_in_this_version():
    spec = runner.build_file_spec(dict(GRANT, mode="write"), "read", "a.txt")
    assert spec["HostConfig"]["Mounts"][0]["ReadOnly"] is True


# ---------------- the reader, run for real ----------------

@pytest.fixture
def tree(tmp_path):
    d = tmp_path / "reports"
    d.mkdir()
    (d / "a.txt").write_text("hello world\n")
    (d / "sub").mkdir()
    (d / "sub" / "b.md").write_text("# b")
    (d / ".env").write_text("SECRET=1")
    (d / "id_rsa").write_text("KEY")
    (d / "cert.pem").write_text("PEM")
    (d / "bin.dat").write_bytes(b"\x00\x01\x02" * 100)
    (d / "big.txt").write_text("x" * 50000)
    (d / "ctl.txt").write_text("\x01" * 12000)
    (d / "bad.txt").write_bytes(b"ok \xff\xfe bytes")
    os.symlink("/etc/passwd", d / "link_out")
    os.symlink("/etc", d / "etc_link")
    os.symlink("a.txt", d / "link_in")
    os.symlink(".env", d / "link_to_env")
    return d


def run_reader(base, op, rel):
    env = dict(os.environ, RL_DATA=str(base), OP=op, REL=rel,
               MAXB=str(runner.FILE_READ_BYTES), MAXN=str(runner.FILE_LIST_MAX))
    p = subprocess.run([sys.executable, "-I", "-B", "-c", runner.FILE_READER], env=env,
                       capture_output=True, text=True, timeout=30)
    return p.returncode, json.loads(p.stdout)


def test_reader_lists_files_and_hides_secrets_and_symlinks(tree):
    rc, out = run_reader(tree, "list", "")
    names = {e["name"] for e in out["entries"]}
    assert rc == 0 and {"a.txt", "sub", "bin.dat", "big.txt"} <= names
    assert not names & {".env", "id_rsa", "cert.pem", "link_out", "etc_link", "link_in", "link_to_env"}
    rc, out = run_reader(tree, "list", "sub")
    assert [e["name"] for e in out["entries"]] == ["b.md"]


def test_reader_reads_text_with_a_hash(tree):
    rc, out = run_reader(tree, "read", "a.txt")
    assert rc == 0 and out["text"] == "hello world\n" and out["truncated"] is False
    assert out["sha256"] == hashlib.sha256(b"hello world\n").hexdigest()
    assert run_reader(tree, "read", "sub/b.md")[1]["text"] == "# b"


def test_reader_truncates_big_files_and_keeps_the_answer_small(tree):
    rc, out = run_reader(tree, "read", "big.txt")
    assert rc == 0 and out["truncated"] is True and out["size"] == 50000 and out["bytes_read"] == runner.FILE_READ_BYTES
    rc, out = run_reader(tree, "read", "ctl.txt")             # control characters grow when written as JSON
    assert rc == 0 and out["truncated"] is True
    assert len(json.dumps(out, ensure_ascii=False).encode()) <= 15000 + 200


def test_reader_handles_binary_and_bad_encodings(tree):
    rc, out = run_reader(tree, "read", "bin.dat")
    assert rc == 0 and out["binary"] is True and "text" not in out
    rc, out = run_reader(tree, "read", "bad.txt")
    assert rc == 0 and out["text"].startswith("ok ")


@pytest.mark.parametrize("rel", [".env", "id_rsa", "cert.pem", "../a.txt", "sub/../../a.txt", "link_to_env"])
def test_reader_refuses_protected_names_and_parent_paths(tree, rel):
    rc, out = run_reader(tree, "read", rel)
    assert rc == 3 and "error" in out and "SECRET" not in json.dumps(out)


@pytest.mark.parametrize("rel", ["link_out", "etc_link/passwd", "etc_link"])
def test_reader_refuses_symlinks_that_leave_the_folder(tree, rel):
    rc, out = run_reader(tree, "read", rel)
    assert rc == 3 and "outside" in out["error"]
    assert "root:" not in json.dumps(out)


def test_reader_treats_an_absolute_looking_path_as_inside_the_folder(tree):
    rc, out = run_reader(tree, "read", "/etc/passwd")
    assert rc == 3 and "root:" not in json.dumps(out)


def test_reader_follows_a_symlink_that_stays_inside_the_folder(tree):
    rc, out = run_reader(tree, "read", "link_in")
    assert rc == 0 and out["text"] == "hello world\n"


def test_reader_rejects_wrong_kinds_and_unknown_operations(tree):
    assert run_reader(tree, "read", "sub")[0] == 3
    assert run_reader(tree, "list", "a.txt")[0] == 3
    assert run_reader(tree, "read", "missing.txt")[0] == 3
    assert run_reader(tree, "delete", "a.txt")[0] == 2


# ---------------- the HTTP endpoints ----------------

@pytest.fixture
def srv(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "TOKEN", "tok")
    f = tmp_path / "grants.json"
    f.write_text(json.dumps({"grants": [
        {"name": "reports", "path": "/data/reports", "mode": "read"},
        {"name": "old", "path": "/data/old", "mode": "read", "expires": "2000-01-01T00:00:00Z"},
    ]}))
    monkeypatch.setattr(runner, "GRANTS_FILE", str(f))
    monkeypatch.setenv("COMPUTER_CONTROL", "true")
    calls = []

    def fake_run(spec):
        calls.append(spec)
        return {"exit_code": 0, "stdout": json.dumps({"op": "read", "text": "hi", "bytes_read": 2}),
                "stderr": "", "timed_out": False, "oom": False}

    monkeypatch.setattr(runner, "_run_spec", fake_run)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), runner.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def call(method, path, body=None, token="tok"):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, json.loads(data or b"{}")

    yield call, calls
    httpd.shutdown()
    httpd.server_close()


def test_endpoints_need_the_token(srv):
    call, calls = srv
    assert call("POST", "/files", {"op": "list", "grant": "reports"}, token=None)[0] == 401
    assert call("POST", "/files", {"op": "list", "grant": "reports"}, token="wrong")[0] == 401
    assert call("GET", "/grants", token=None)[0] == 401
    assert call("GET", "/health", token=None)[0] == 200
    assert calls == []


def test_grants_endpoint_lists_names_only_and_hides_expired(srv):
    call, _ = srv
    status, body = call("GET", "/grants")
    assert status == 200 and body["enabled"] is True
    assert [g["name"] for g in body["grants"]] == ["reports"]
    assert "/data" not in json.dumps(body)


def test_files_endpoint_is_closed_while_computer_control_is_off(srv, monkeypatch):
    call, calls = srv
    monkeypatch.setenv("COMPUTER_CONTROL", "false")
    assert call("POST", "/files", {"op": "read", "grant": "reports", "path": "a.txt"}) == (403, {"error": "computer control is off"})
    assert call("GET", "/grants")[1] == {"enabled": False, "grants": []}
    assert calls == []


def test_files_endpoint_rejects_bad_requests_before_any_container_starts(srv):
    call, calls = srv
    for body in [{"op": "write", "grant": "reports", "path": "a.txt"},
                 {"op": "delete", "grant": "reports", "path": "a.txt"},
                 {"op": "read", "grant": 5, "path": "a.txt"},
                 {"op": "read", "grant": "reports", "path": ""},
                 {"op": "read", "grant": "reports", "path": "../a.txt"},
                 {"op": "read", "grant": "reports", "path": ".env"},
                 {"op": "read", "grant": "reports", "path": "/etc/passwd"},
                 [1, 2]]:
        assert call("POST", "/files", body)[0] == 400, body
    assert call("POST", "/files", {"op": "read", "grant": "nope", "path": "a.txt"})[0] == 404
    assert call("POST", "/files", {"op": "read", "grant": "old", "path": "a.txt"})[0] == 404     # expired
    assert calls == []


def test_files_endpoint_happy_path_mounts_only_the_named_grant(srv):
    call, calls = srv
    status, body = call("POST", "/files", {"op": "read", "grant": "reports", "path": "q3/a.txt"})
    assert status == 200 and body["ok"] is True and body["result"]["text"] == "hi"
    assert len(calls) == 1
    assert calls[0] == runner.build_file_spec(runner.active_grants()[0], "read", "q3/a.txt")
    assert calls[0]["HostConfig"]["Mounts"][0]["Source"] == "/data/reports"


def test_extra_fields_in_the_request_change_nothing(srv):
    call, calls = srv
    call("POST", "/files", {"op": "list", "grant": "reports", "path": "", "image": "evil", "mount": "/",
                            "network": "host", "Mounts": [{"Source": "/"}], "binds": ["/:/x"]})
    assert calls[0] == runner.build_file_spec(runner.active_grants()[0], "list", "")


def test_a_failing_read_is_reported_without_details(srv, monkeypatch):
    call, _ = srv
    monkeypatch.setattr(runner, "_run_spec", lambda spec: {"exit_code": 3, "stdout": json.dumps({"error": "not a file"}),
                                                           "stderr": "", "timed_out": False, "oom": False})
    assert call("POST", "/files", {"op": "read", "grant": "reports", "path": "sub"})[1] == {"ok": False, "error": "not a file"}
    monkeypatch.setattr(runner, "_run_spec", lambda spec: {"exit_code": None, "stdout": "", "stderr": "", "timed_out": True, "oom": False})
    assert call("POST", "/files", {"op": "read", "grant": "reports", "path": "a.txt"})[1] == {"ok": False, "error": "timed out"}


def test_the_busy_lock_applies_to_file_calls(srv):
    call, calls = srv
    assert runner._lock.acquire(blocking=False)
    try:
        assert call("POST", "/files", {"op": "list", "grant": "reports"})[0] == 429
    finally:
        runner._lock.release()
    assert calls == []


def test_the_run_endpoint_still_needs_the_token(srv):
    call, calls = srv
    assert call("POST", "/run", {"code": "print(1)"}, token=None)[0] == 401
    assert call("POST", "/nothing", {}, token="tok")[0] == 404
    assert calls == []


def test_the_disabled_flag_pauses_file_access_immediately(tmp_path, monkeypatch):
    f = tmp_path / "grants.json"
    f.write_text(json.dumps({"grants": [{"name": "a", "path": "/data/a", "mode": "read"}]}))
    monkeypatch.setattr(runner, "GRANTS_FILE", str(f))
    monkeypatch.setenv("COMPUTER_CONTROL", "true")
    assert runner.computer_control_on() is True
    (tmp_path / "DISABLED").write_text("paused")
    assert runner.computer_control_on() is False
    assert runner.file_op({"op": "list", "grant": "a"})[0] == 403
    assert runner.grants_summary() == {"enabled": False, "grants": []}
    (tmp_path / "DISABLED").unlink()
    assert runner.computer_control_on() is True
