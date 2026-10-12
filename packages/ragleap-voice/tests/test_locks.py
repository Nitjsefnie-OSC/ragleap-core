import json
import os
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ragleap_voice import cli  # noqa: E402
from ragleap_voice.cache import cache_root, model_dir  # noqa: E402
from ragleap_voice.locks import (LockError, canonical_bytes, hash_file, load_lock, lock_digest,  # noqa: E402
                                 safe_relpath, validate_lock, verify_dir)
from ragleap_voice.manifest import load_manifest, lock_problems  # noqa: E402


def make_lock(directory, files, name="m1", revision="rev1"):
    entries = []
    for rel, data in files.items():
        p = directory.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        size, digest = hash_file(p)
        entries.append({"path": rel, "size": size, "sha256": digest})
    return {"schema": 1, "model": name, "revision": revision, "source_url": "https://example.org/m1", "files": entries}


@pytest.mark.parametrize("path", ["a.bin", "dir/a.safetensors", "onnx/model_q4.onnx", ".gitkeep"])
def test_safe_relpath_accepts(path):
    assert safe_relpath(path) is None


@pytest.mark.parametrize("path", ["", "/abs", "a//b", "a/../b", "..", ".", "a\\b", "a b", "a/", "x\x00y", "caf\u00e9.bin", None, 5])
def test_safe_relpath_rejects(path):
    assert safe_relpath(path)


def test_validate_lock(tmp_path):
    base = make_lock(tmp_path, {"a.bin": b"x", "b/c.bin": b"yy"})

    def mutated(fn):
        lock = json.loads(json.dumps(base))
        fn(lock)
        return validate_lock(lock, name="m1", revision="rev1")

    assert mutated(lambda lk: None) == []
    assert any("schema" in p for p in mutated(lambda lk: lk.update(schema=2)))
    assert any("does not match" in p for p in validate_lock(base, name="other"))
    assert any("does not match" in p for p in validate_lock(base, revision="other"))
    assert any("unknown key" in p for p in mutated(lambda lk: lk.update(extra=1)))
    assert any("files must be" in p for p in mutated(lambda lk: lk.update(files=[])))
    assert any("sha256" in p for p in mutated(lambda lk: lk["files"][0].update(sha256="ABC")))
    assert any("invalid size" in p for p in mutated(lambda lk: lk["files"][0].update(size=-1)))
    assert any("invalid size" in p for p in mutated(lambda lk: lk["files"][0].update(size=True)))
    assert any("duplicate" in p for p in mutated(lambda lk: lk["files"].append(dict(lk["files"][0], path="A.BIN"))))
    assert any("conflict" in p for p in mutated(lambda lk: lk["files"].append(dict(lk["files"][0], path="a.bin/x"))))
    assert any("'..'" in p for p in mutated(lambda lk: lk["files"][0].update(path="../x")))
    assert validate_lock([]) == ["lock is not a JSON object"]


def test_digest_is_canonical(tmp_path):
    lock = make_lock(tmp_path, {"a.bin": b"x"})
    d1 = lock_digest(lock)
    assert lock_digest({k: lock[k] for k in reversed(list(lock))}) == d1
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(lock, indent=4), encoding="utf-8")
    assert lock_digest(load_lock(pretty)) == d1
    lock["files"][0]["sha256"] = "f" * 64
    assert lock_digest(lock) != d1


def test_load_lock_rejects_bad_files(tmp_path):
    for text in ('{"a":1,"a":2}', "not json", "[1, 2]"):
        p = tmp_path / "x.json"
        p.write_text(text, encoding="utf-8")
        with pytest.raises(LockError):
            load_lock(p)
    with pytest.raises(LockError):
        load_lock(tmp_path / "missing.json")


def test_verify_dir_detects_tampering(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    lock = make_lock(d, {"a.bin": b"hello", "sub/b.bin": b"world!"})
    assert verify_dir(lock, d) == []
    (d / "a.bin").write_bytes(b"HELLO")
    assert any("sha256 mismatch" in p for p in verify_dir(lock, d))
    (d / "a.bin").write_bytes(b"hi")
    assert any("size" in p for p in verify_dir(lock, d))
    (d / "a.bin").unlink()
    assert any("missing" in p for p in verify_dir(lock, d))
    assert any("directory missing" in p for p in verify_dir(lock, tmp_path / "nope"))


def test_verify_dir_rejects_extras_and_symlinks(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    lock = make_lock(d, {"a.bin": b"hello", "sub/b.bin": b"world!"})
    (d / "extra.txt").write_text("x", encoding="utf-8")
    assert any("unexpected file" in p for p in verify_dir(lock, d))
    (d / "extra.txt").unlink()
    if not hasattr(os, "symlink"):
        pytest.skip("no symlink support")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"hello")
    (d / "a.bin").unlink()
    os.symlink(outside, d / "a.bin")
    assert any("a.bin: is a symlink" in p for p in verify_dir(lock, d))
    shutil.rmtree(d / "sub")
    real = tmp_path / "real"
    real.mkdir()
    (real / "b.bin").write_bytes(b"world!")
    os.symlink(real, d / "sub")
    assert any("parent directory is a symlink" in p for p in verify_dir(lock, d))


def test_cache_root_and_model_dir(tmp_path):
    assert cache_root({"RAGLEAP_VOICE_HOME": str(tmp_path)}) == tmp_path
    assert cache_root({"XDG_CACHE_HOME": str(tmp_path)}) == tmp_path / "ragleap-voice"
    assert model_dir("m1", "rev1", tmp_path) == tmp_path / "models" / "m1" / "rev1"
    for bad in ("..", "a/b", "", ".x", "a b"):
        with pytest.raises(LockError):
            model_dir(bad, "rev1", tmp_path)
    with pytest.raises(LockError):
        model_dir("m1", "../x", tmp_path)


TOML = '''
[[model]]
name = "m1"
kind = "stt"
source_url = "https://example.org/m1"
revision = "rev1"
sha256 = "DIGEST"
code_license = "MIT"
weights_license = "MIT"
languages = ["en"]
capabilities = []
min_hardware = "cpu"
status = "verified"
default = true
'''


def _project(tmp_path, lock, digest=None):
    (tmp_path / "locks").mkdir(exist_ok=True)
    (tmp_path / "locks" / "m1.json").write_bytes(canonical_bytes(lock))
    (tmp_path / "models.toml").write_text(TOML.replace("DIGEST", digest or lock_digest(lock)), encoding="utf-8")
    return str(tmp_path / "models.toml")


def test_lock_problems_ok_and_failures(tmp_path):
    lock = make_lock(tmp_path / "scratch", {"w.safetensors": b"abc"})
    mf = _project(tmp_path, lock)
    entries, problems = load_manifest(mf)
    assert problems == [] and lock_problems(entries, mf) == []

    mf = _project(tmp_path, lock, digest="0" * 64)
    entries, _ = load_manifest(mf)
    assert any("does not match the lock file digest" in p for p in lock_problems(entries, mf))

    mf = _project(tmp_path, lock)
    (tmp_path / "locks" / "other.json").write_bytes(canonical_bytes(lock))
    assert any("orphan" in p for p in lock_problems(entries, mf))
    (tmp_path / "locks" / "other.json").unlink()

    (tmp_path / "locks" / "m1.json").write_text("garbage", encoding="utf-8")
    assert any(p.startswith("m1:") for p in lock_problems(entries, mf))

    (tmp_path / "locks" / "m1.json").unlink()
    assert any("needs locks/m1.json" in p for p in lock_problems(entries, mf))


def test_real_manifest_has_no_lock_problems():
    entries, _ = load_manifest()
    assert lock_problems(entries) == []


def test_cli_verify(tmp_path, capsys):
    home = tmp_path / "home"
    d = home / "models" / "m1" / "rev1"
    d.mkdir(parents=True)
    lock = make_lock(d, {"w.bin": b"abc"})
    mf = _project(tmp_path, lock)
    args = ["models", "verify", "m1", "--manifest", mf, "--cache-dir", str(home)]
    assert cli.main(args) == 0
    assert "verified OK" in capsys.readouterr().out
    (d / "w.bin").write_bytes(b"abd")
    assert cli.main(args) == 1
    assert "sha256 mismatch" in capsys.readouterr().err
    assert cli.main(["models", "verify", "nope", "--manifest", mf]) == 1
    assert "unknown model" in capsys.readouterr().err
    (tmp_path / "locks" / "m1.json").unlink()
    assert cli.main(args) == 1
    assert "no lock file" in capsys.readouterr().err


def test_unsafe_format_files():
    from ragleap_voice.locks import unsafe_format_files
    lock = {"files": [{"path": "a.safetensors"}, {"path": "m/Weights.PT"}, {"path": "x.bin"},
                      {"path": "n.onnx"}, {"path": "c.pkl"}]}
    assert unsafe_format_files(lock) == ["c.pkl", "m/Weights.PT", "x.bin"]


def test_verified_entry_rejects_pickle_capable_lock(tmp_path):
    from dataclasses import replace
    lock = make_lock(tmp_path / "scratch", {"w.pt": b"abc"})
    mf = _project(tmp_path, lock)
    entries, _ = load_manifest(mf)
    assert any("pickle-capable" in p for p in lock_problems(entries, mf))
    relaxed = [replace(entries[0], status="unverified", default=False)]
    assert not any("pickle-capable" in p for p in lock_problems(relaxed, mf))
