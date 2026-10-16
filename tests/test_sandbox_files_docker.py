"""Real-Docker tests for the file-grant reader (sandbox/runner.py).

Off unless RAGLEAP_DOCKER_TESTS=1. They start tiny no-network containers through the real
Docker socket, so they run in CI (core-tests) and not in the normal local run. The grant
lookup and the kill switch are replaced; everything else is the real runner code.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import tempfile

import pytest

ENABLED = os.environ.get("RAGLEAP_DOCKER_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not ENABLED, reason="set RAGLEAP_DOCKER_TESTS=1 (needs Docker and python:3.11-slim)")

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sandbox_runner_docker", ROOT / "sandbox" / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


@pytest.fixture
def granted(monkeypatch):
    assert os.path.exists(runner.DOCKER_SOCKET), "no Docker socket at " + runner.DOCKER_SOCKET
    # mkdtemp is mode 700; the container runs as uid 65534, so directories need 755
    base = pathlib.Path(tempfile.mkdtemp(prefix="rl-grant-"))
    os.chmod(base, 0o755)
    (base / "a.txt").write_text("hello world\n")
    (base / "sub").mkdir()
    (base / "sub" / "b.md").write_text("# b")
    (base / ".env").write_text("SECRET=1")
    (base / "id_rsa").write_text("KEY")
    os.chmod(base / "sub", 0o755)
    for f in ("a.txt", ".env", "id_rsa"):
        os.chmod(base / f, 0o644)
    os.chmod(base / "sub" / "b.md", 0o644)
    os.symlink("/etc/passwd", base / "link_out")
    os.symlink("/etc", base / "etc_link")
    grant = {"name": "docs", "path": str(base), "mode": "read", "purpose": "use", "expires": None}
    monkeypatch.setattr(runner, "computer_control_on", lambda: True)
    monkeypatch.setattr(runner, "active_grants", lambda now=None: [grant])
    yield grant
    shutil.rmtree(base, ignore_errors=True)


def call(grant, op, rel=""):
    return runner.file_op({"op": op, "grant": grant["name"], "path": rel})


def refused(status, body):
    return not (status == 200 and body.get("ok"))


def test_read_works(granted):
    st, body = call(granted, "read", "a.txt")
    assert st == 200 and body.get("ok") is True, body
    assert body["result"]["text"] == "hello world\n"
    assert len(body["result"]["sha256"]) == 64
    st, body = call(granted, "read", "sub/b.md")
    assert st == 200 and body.get("ok") is True, body
    assert body["result"]["text"] == "# b"


def test_list_works_and_hides_secrets_and_symlinks(granted):
    st, body = call(granted, "list")
    assert st == 200 and body.get("ok") is True, body
    names = {e["name"] for e in body["result"]["entries"]}
    assert {"a.txt", "sub"} <= names, names
    assert not names & {".env", "id_rsa", "link_out", "etc_link"}, names


@pytest.mark.parametrize("rel", [
    "../etc/passwd", "sub/../../etc/passwd", ".env", "id_rsa",
    "link_out", "etc_link/passwd", "/etc/passwd"])
def test_escapes_and_secrets_are_refused(granted, rel):
    st, body = call(granted, "read", rel)
    assert refused(st, body), (rel, st, body)
    dump = json.dumps(body)
    assert "root:" not in dump and "SECRET=1" not in dump, (rel, dump)


def test_the_mount_is_read_only(granted):
    base = pathlib.Path(granted["path"])
    os.chmod(base, 0o777)  # file permissions allow the write, so only the read-only flag can stop it
    spec = runner.build_file_spec(granted, "read", "a.txt")
    spec["Cmd"] = ["python", "-I", "-B", "-c", "open('/data/new.txt','w').write('x')"]
    res = runner._run_spec(spec)
    assert res["exit_code"] != 0, res
    assert "Read-only file system" in res["stderr"], res
    assert not (base / "new.txt").exists()


def test_the_container_has_no_network(granted):
    code = ("import socket,sys\n"
            "try:\n"
            "    socket.create_connection(('1.1.1.1',53),timeout=3)\n"
            "except OSError:\n"
            "    sys.exit(7)\n"
            "sys.exit(0)\n")
    spec = runner.build_file_spec(granted, "read", "a.txt")
    spec["Cmd"] = ["python", "-I", "-B", "-c", code]
    res = runner._run_spec(spec)
    assert res["exit_code"] == 7, res
