import hashlib
import json
import pathlib
import sys
from dataclasses import replace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ragleap_voice import cli  # noqa: E402
from ragleap_voice.licences import validate_entries  # noqa: E402
from ragleap_voice.locks import canonical_bytes, lock_digest  # noqa: E402
from ragleap_voice.manifest import ManifestError, load_manifest  # noqa: E402
from ragleap_voice.pull import PullError, dependency_order  # noqa: E402
from test_pull import FILES, POLICY, REV, SRC_URL, hub  # noqa: E402,F401  (hub is a pytest fixture)


def raw(name, deps=None, status="unverified", default=False, **over):
    d = {"name": name, "kind": "stt", "source_url": SRC_URL, "revision": "", "sha256": "", "code_license": "MIT",
         "weights_license": "MIT", "languages": [], "capabilities": [], "min_hardware": "cpu",
         "status": status, "default": default}
    if status == "verified":
        d["revision"], d["sha256"] = REV, "0" * 64
    if deps is not None:
        d["depends_on"] = deps
    d.update(over)
    return d


def problems(*entries):
    return validate_entries(list(entries))


def test_valid_dependency_graphs():
    assert problems(raw("a", ["b"], status="verified"), raw("b", status="verified")) == []
    assert problems(raw("a", ["b"]), raw("b")) == []
    assert problems(raw("a", ["b", "c"]), raw("b", ["c"]), raw("c")) == []


def test_bad_dependencies_are_reported():
    assert any("unknown model" in p for p in problems(raw("a", ["zz"])))
    assert any("itself" in p for p in problems(raw("a", ["a"])))
    assert any("twice" in p for p in problems(raw("a", ["b", "b"]), raw("b")))
    assert any("list of strings" in p for p in problems(raw("a", "b")))
    assert any("cycle" in p for p in problems(raw("a", ["b"]), raw("b", ["c"]), raw("c", ["a"])))
    assert any("not verified" in p for p in problems(raw("a", ["b"], status="verified"), raw("b")))
    assert any("not verified" in p for p in problems(raw("a", ["b"], default=True, status="verified"), raw("b")))


def test_verified_entries_are_held_to_the_default_rules():
    assert any("pinned revision" in p for p in problems(raw("a", status="verified", revision="")))
    assert any("sha256" in p for p in problems(raw("a", status="verified", sha256="abc")))
    assert any("weights_license" in p for p in problems(raw("a", status="verified", weights_license="CC-BY-NC-4.0")))
    assert problems(raw("a")) == []


TOML = '''
[[model]]
name = "{name}"
kind = "stt"
source_url = "https://huggingface.co/owner/repo"
revision = "{rev}"
sha256 = "{digest}"
code_license = "MIT"
weights_license = "Apache-2.0"
languages = ["en"]
capabilities = []
min_hardware = "cpu"
status = "{status}"
default = false
depends_on = {deps}
'''


def lock_for(name):
    files = [{"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b in sorted(FILES.items())]
    return {"schema": 1, "model": name, "revision": REV, "source_url": SRC_URL, "files": files}


def project(tmp_path, status="verified", dep_status="verified", with_dep_lock=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "locks").mkdir(exist_ok=True)
    parts = []
    for name, deps, st in (("main", ["dep"], status), ("dep", [], dep_status)):
        lock = lock_for(name)
        if name != "dep" or with_dep_lock:
            (tmp_path / "locks" / (name + ".json")).write_bytes(canonical_bytes(lock))
        parts.append(TOML.format(name=name, rev=REV, digest=lock_digest(lock), status=st, deps=json.dumps(deps)))
    (tmp_path / "models.toml").write_text("\n".join(parts), encoding="utf-8")
    return str(tmp_path / "models.toml")


def test_manifest_parses_depends_on(tmp_path):
    entries, probs = load_manifest(project(tmp_path))
    by = {e.name: e for e in entries}
    assert by["main"].depends_on == ("dep",) and by["dep"].depends_on == ()
    assert probs == []


def test_depends_on_must_be_a_list_of_strings(tmp_path):
    p = tmp_path / "models.toml"
    p.write_text(TOML.format(name="x", rev=REV, digest="0" * 64, status="unverified", deps='"y"'), encoding="utf-8")
    with pytest.raises(ManifestError, match="depends_on"):
        load_manifest(str(p))


def test_dependency_order(tmp_path):
    by = {e.name: e for e in load_manifest(project(tmp_path))[0]}
    assert [e.name for e in dependency_order(by["main"], by)] == ["dep", "main"]
    by["x"] = replace(by["dep"], name="x", depends_on=("dep",))
    by["main"] = replace(by["main"], depends_on=("x", "dep"))
    assert [e.name for e in dependency_order(by["main"], by)] == ["dep", "x", "main"]
    by["dep"] = replace(by["dep"], depends_on=("main",))
    with pytest.raises(PullError, match="cycle"):
        dependency_order(by["main"], by)
    lone = {"main": replace(by["main"], depends_on=("zz",))}
    with pytest.raises(PullError, match="unknown"):
        dependency_order(lone["main"], lone)


def test_cli_pull_order_and_preflight(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "_network", lambda: (POLICY, "http://unused.invalid"))
    monkeypatch.setattr(cli, "pull_model", lambda entry, lock, root, **kw:
                        calls.append((entry.name, kw["allow_unverified"], kw["offline"])) or tmp_path / entry.name)
    mf = project(tmp_path / "ok")
    args = ["models", "pull", "main", "--manifest", mf, "--cache-dir", str(tmp_path / "c"), "--allow-unverified"]
    assert cli.main(args) == 0
    assert calls == [("dep", True, False), ("main", True, False)]
    out = capsys.readouterr().out
    assert "dependencies first" in out and "main is ready" in out
    calls.clear()
    mf = project(tmp_path / "nodep", with_dep_lock=False)
    assert cli.main(["models", "pull", "main", "--manifest", mf, "--cache-dir", str(tmp_path / "c")]) == 1
    assert "no lock file for dep" in capsys.readouterr().err
    assert calls == []


def test_cli_pull_and_verify_with_dependency(hub, tmp_path, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setattr(cli, "_network", lambda: (POLICY, hub.base_url))
    mf = project(tmp_path)
    home = str(tmp_path / "home")
    assert cli.main(["models", "pull", "main", "--manifest", mf, "--cache-dir", home]) == 0
    out = capsys.readouterr().out
    assert out.index("dep: 3 files") < out.index("main: 3 files")
    assert cli.main(["models", "verify", "main", "--manifest", mf, "--cache-dir", home]) == 0
    out = capsys.readouterr().out
    assert "dep: 3 file(s) verified OK" in out and "main: 3 file(s) verified OK" in out
    (pathlib.Path(home) / "models" / "dep" / REV / "config.json").write_bytes(b"junk")
    assert cli.main(["models", "verify", "main", "--manifest", mf, "--cache-dir", home]) == 1
    seen = capsys.readouterr()
    assert "verification of dep failed" in seen.err and "main: 3 file(s) verified OK" in seen.out


def test_cli_check_and_show_with_dependencies(tmp_path, capsys):
    mf = project(tmp_path / "good")
    assert cli.main(["models", "check", "--manifest", mf]) == 0
    assert "manifest OK: 2 model(s), 2 verified, 0 default" in capsys.readouterr().out
    assert cli.main(["models", "show", "main", "--manifest", mf]) == 0
    assert "depends_on:" in capsys.readouterr().out
    mf = project(tmp_path / "bad", dep_status="unverified")
    assert cli.main(["models", "check", "--manifest", mf]) == 1
    assert "not verified" in capsys.readouterr().err


def test_real_manifest_dependencies_are_locked_and_ordered():
    from ragleap_voice.locks import load_lock
    from ragleap_voice.manifest import default_manifest_path
    entries, probs = load_manifest()
    by = {e.name: e for e in entries}
    assert probs == []
    assert [e.name for e in dependency_order(by["indic-parler-tts"], by)] == ["flan-t5-large-tokenizer", "indic-parler-tts"]
    for name in ("indic-parler-tts", "flan-t5-large-tokenizer"):
        lock = load_lock(default_manifest_path().parent / "locks" / (name + ".json"))
        assert lock_digest(lock) == by[name].sha256 and lock["revision"] == by[name].revision
