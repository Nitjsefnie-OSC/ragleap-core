"""Container hardening: the image installs exact pinned versions and runs as an unprivileged user."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_lines():
    text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


def test_lock_lines_are_exact_pins():
    lines = _lock_lines()
    assert len(lines) > 50
    for line in lines:
        assert re.fullmatch(r"[A-Za-z0-9_.\-]+==[^\s;@=<>]+", line), line


def test_lock_covers_every_requirement():
    pinned = {_norm(l.split("==")[0]) for l in _lock_lines()}
    for raw in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if not line or ";" in line:
            continue  # blank, or only for other Python versions
        name = re.split(r"[\[<>=!~ ]", line)[0]
        assert _norm(name) in pinned, name + " is in requirements.txt but not in requirements.lock"


def test_dockerfile_installs_from_the_lock_and_runs_unprivileged():
    d = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    installs = [l for l in d.splitlines() if "pip install" in l]
    assert installs and all("-r requirements.lock" in l for l in installs)
    assert "COPY requirements.txt requirements.lock" in d
    users = [l.split()[1] for l in d.splitlines() if l.strip().startswith("USER ")]
    assert users and users[-1] not in ("root", "0")
    assert d.index("USER ") > d.index("COPY . .")


def test_dockerignore_keeps_the_lock_file():
    ignored = [l.strip() for l in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()]
    assert "requirements.lock" not in ignored and "*.lock" not in ignored
