"""`ragleap files`: the owner's command for folder grants, the compose wiring and the ignore files.
Everything runs on a temporary folder; no Docker, network or database."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HELPER = ROOT / "scripts" / "ragleap_files.py"
_spec = importlib.util.spec_from_file_location("sandbox_runner_cli", ROOT / "sandbox" / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "install"
    h.mkdir()
    (h / "docker-compose.yml").write_text("services: {}\n")
    return h


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "data" / "reports"
    d.mkdir(parents=True)
    (d / "a.txt").write_text("hello")
    return d


def run(home, *args):
    env = dict(os.environ, RAGLEAP_HOME=str(home))
    p = subprocess.run([sys.executable, str(HELPER), *args], env=env, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def grants(home):
    return json.loads((home / "grants" / "grants.json").read_text())["grants"]


# ---------------- add ----------------

def test_add_writes_a_grant_the_runner_accepts(home, folder):
    rc, out, err = run(home, "add", str(folder), "--name", "reports")
    assert rc == 0, err
    g = grants(home)
    assert len(g) == 1 and g[0]["name"] == "reports" and g[0]["mode"] == "read" and g[0]["path"] == os.path.realpath(folder)
    parsed, why = runner.parse_grant(g[0])
    assert parsed is not None and parsed["path"] == os.path.realpath(folder)
    assert "Granted 'reports' (read-only)" in out and "Computer control is still off" in out
    assert not [p for p in (home / "grants").iterdir() if p.name.endswith(".tmp")]        # atomic write left nothing behind
    assert oct((home / "grants" / "grants.json").stat().st_mode & 0o777) == oct(0o644)


def test_add_stores_the_real_path_behind_a_link(home, folder, tmp_path):
    link = tmp_path / "shortcut"
    os.symlink(folder, link)
    rc, out, err = run(home, "add", str(link), "--name", "reports")
    assert rc == 0, err
    assert grants(home)[0]["path"] == os.path.realpath(folder) and "was a link" in out


@pytest.mark.parametrize("bad", ["/etc", "/", os.path.expanduser("~"), "/proc", "/var/run"])
def test_add_refuses_dangerous_folders(home, bad):
    rc, out, err = run(home, "add", bad, "--name", "x")
    assert rc == 1 and "Not granted" in err
    assert not (home / "grants" / "grants.json").exists()


def test_add_refuses_missing_paths_and_plain_files(home, folder):
    assert run(home, "add", str(folder / "nope"), "--name", "x")[0] == 1
    rc, out, err = run(home, "add", str(folder / "a.txt"), "--name", "x")
    assert rc == 1 and "not a folder" in err


def test_add_refuses_the_install_folder_and_its_parents(home, tmp_path):
    for target in (home, tmp_path, home / "grants"):
        (home / "grants").mkdir(exist_ok=True)
        rc, out, err = run(home, "add", str(target), "--name", "x")
        assert rc == 1 and "install folder" in err, target


def test_add_checks_names_modes_and_duplicates(home, folder):
    assert run(home, "add", str(folder), "--name", "Bad Name")[0] == 1
    rc, out, err = run(home, "add", str(folder), "--name", "reports", "--mode", "write")
    assert rc == 1 and "read-only" in err
    assert run(home, "add", str(folder), "--name", "reports")[0] == 0
    rc, out, err = run(home, "add", str(folder), "--name", "reports")
    assert rc == 1 and "already used" in err and len(grants(home)) == 1


def test_add_expiry(home, folder):
    assert run(home, "add", str(folder), "--name", "r", "--expires", "7d")[0] == 0
    when = datetime.fromisoformat(grants(home)[0]["expires"])
    assert timedelta(days=6, hours=23) < when - datetime.now(timezone.utc) < timedelta(days=7, minutes=1)
    for bad in ("0d", "banana", "2000-01-01", "-3d"):
        assert run(home, "add", str(folder), "--name", "x" + str(abs(hash(bad)) % 999), "--expires", bad)[0] in (1, 2), bad


def test_add_warns_about_unreadable_files_and_hidden_secrets(home, folder):
    (folder / "private.txt").write_text("x")
    os.chmod(folder / "private.txt", 0o600)
    (folder / ".env").write_text("SECRET=1")
    rc, out, err = run(home, "add", str(folder), "--name", "reports")
    assert rc == 0 and "not readable by everyone" in out and "private.txt" in out
    assert "protected item" in out


def test_a_broken_grants_file_is_never_overwritten(home, folder):
    (home / "grants").mkdir()
    (home / "grants" / "grants.json").write_text("{ not json")
    for args in (("add", str(folder), "--name", "x"), ("list",), ("remove", "x")):
        rc, out, err = run(home, *args)
        assert rc == 1 and "not valid JSON" in err, args
    assert (home / "grants" / "grants.json").read_text() == "{ not json"


# ---------------- list, remove, off, on, status ----------------

def test_list_remove_roundtrip(home, folder):
    assert "No folder grants yet" in run(home, "list")[1]
    run(home, "add", str(folder), "--name", "reports")
    rc, out, err = run(home, "list")
    assert "reports" in out and os.path.realpath(folder) in out and "[active]" in out
    assert run(home, "remove", "nope")[0] == 1
    rc, out, err = run(home, "remove", "reports")
    assert rc == 0 and grants(home) == []


def test_list_marks_expired_and_invalid_entries(home):
    (home / "grants").mkdir()
    (home / "grants" / "grants.json").write_text(json.dumps({"grants": [
        {"name": "old", "path": "/data/old", "mode": "read", "expires": "2000-01-01T00:00:00+00:00"},
        {"name": "etc", "path": "/etc", "mode": "read"}]}))
    out = run(home, "list")[1]
    assert "[expired]" in out and "invalid" in out


def test_off_and_on_create_and_remove_the_pause_flag(home):
    rc, out, err = run(home, "off")
    assert rc == 0 and (home / "grants" / "DISABLED").exists() and "immediately" in out
    rc, out, err = run(home, "on")
    assert rc == 0 and not (home / "grants" / "DISABLED").exists()
    assert "still off" in out                                   # no COMPUTER_CONTROL=true in .env
    (home / ".env").write_text("COMPUTER_CONTROL=true\n")
    assert "resumed" in run(home, "on")[1]


def test_status_reports_the_switches_without_printing_secrets(home):
    (home / ".env").write_text("RAGLEAP_API_KEY=supersecret\nCOMPUTER_CONTROL=true\n")
    rc, out, err = run(home, "status")
    assert rc == 0 and "true" in out and "supersecret" not in out + err


# ---------------- the ragleap wrapper, compose and ignore files ----------------

def test_the_ragleap_command_runs_the_files_helper(home):
    env = dict(os.environ, RAGLEAP_HOME=str(home))
    p = subprocess.run(["bash", str(ROOT / "scripts" / "ragleap"), "files", "list"], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and "No folder grants yet" in p.stdout
    rel = subprocess.run(["bash", "scripts/ragleap", "files", "list"], env=env, capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    assert rel.returncode == 0 and "No folder grants yet" in rel.stdout, rel.stderr          # run by a relative path too
    h = subprocess.run(["bash", str(ROOT / "scripts" / "ragleap"), "help"], env=env, capture_output=True, text=True, timeout=60)
    assert "files add" in h.stdout


def test_only_the_sandbox_service_mounts_the_grants_folder_read_only():
    yaml = pytest.importorskip("yaml")
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    assert [str(v) for v in services["sandbox"]["volumes"]] == ["/var/run/docker.sock:/var/run/docker.sock", "./grants:/grants:ro"]
    for name, svc in services.items():
        if name != "sandbox":
            assert not any("grants" in str(v) for v in svc.get("volumes", [])), name
    assert "COMPUTER_CONTROL" in services["sandbox"]["environment"]


def test_grants_stay_out_of_git_and_out_of_images():
    assert "grants/" in (ROOT / ".dockerignore").read_text().splitlines()
    ig = (ROOT / ".gitignore").read_text().splitlines()
    assert "grants/*" in ig and "!grants/README.txt" in ig
    assert (ROOT / "grants" / "README.txt").exists()
