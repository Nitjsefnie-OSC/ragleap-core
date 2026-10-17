import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ragleap_voice.locks import (FORMAT_EXCEPTIONS, check_ctranslate2_header, hash_file,  # noqa: E402
                                 unsafe_format_files, validate_lock, verify_dir)

GOOD = struct.pack("<IH", 6, 12) + b"WhisperSpec\x00" + struct.pack("<I", 3) + b"\x00" * 40


def lock_for(directory, files, tags=None):
    tags = tags or {}
    entries = []
    for rel, data in files.items():
        p = directory / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        size, digest = hash_file(p)
        entry = {"path": rel, "size": size, "sha256": digest}
        if rel in tags:
            entry["format"] = tags[rel]
        entries.append(entry)
    return {"schema": 1, "model": "m1", "revision": "rev1", "source_url": "https://example.org/m1", "files": entries}


def test_table_is_closed():
    assert FORMAT_EXCEPTIONS == {"ctranslate2": ".bin"}


def test_good_header_accepted():
    assert check_ctranslate2_header(GOOD) is None


@pytest.mark.parametrize("head", [
    b"",
    b"\x80\x04" + b"x" * 60,
    b"PK\x03\x04" + b"x" * 60,
    GOOD[:5],
    struct.pack("<IH", 99, 12) + b"WhisperSpec\x00",
    struct.pack("<IH", 6, 12) + b"WhisperSpeX\x00",
    struct.pack("<IH", 6, 12) + b"WhisperSpec!",
    struct.pack("<IH", 6, 2) + b"S\x00",
])
def test_bad_headers_refused(head):
    assert check_ctranslate2_header(head) is not None


def test_untagged_lock_still_valid(tmp_path):
    lock = lock_for(tmp_path, {"model.bin": GOOD})
    assert validate_lock(lock) == []
    assert unsafe_format_files(lock) == ["model.bin"]


def test_tagged_bin_is_not_unsafe(tmp_path):
    lock = lock_for(tmp_path, {"model.bin": GOOD, "w.pt": b"x"}, {"model.bin": "ctranslate2"})
    assert validate_lock(lock) == []
    assert unsafe_format_files(lock) == ["w.pt"]


@pytest.mark.parametrize("path,tag", [("w.pt", "ctranslate2"), ("model.bin", "onnx"), ("model.bin", 5), ("model.bin", None)])
def test_bad_tags_refused(tmp_path, path, tag):
    lock = lock_for(tmp_path, {path: GOOD})
    lock["files"][0]["format"] = tag
    assert any("format tag" in p for p in validate_lock(lock))
    assert path in unsafe_format_files(lock)


def test_verify_checks_header(tmp_path):
    lock = lock_for(tmp_path, {"model.bin": GOOD}, {"model.bin": "ctranslate2"})
    assert verify_dir(lock, tmp_path) == []
    bad = tmp_path / "bad"
    lock2 = lock_for(bad, {"model.bin": b"\x80\x04" + b"x" * 60}, {"model.bin": "ctranslate2"})
    problems = verify_dir(lock2, bad)
    assert any("model.bin" in p and "header check failed" in p for p in problems)


def test_verify_still_checks_hash(tmp_path):
    lock = lock_for(tmp_path, {"model.bin": GOOD}, {"model.bin": "ctranslate2"})
    (tmp_path / "model.bin").write_bytes(GOOD[:-1] + b"\x01")
    assert any("sha256 mismatch" in p for p in verify_dir(lock, tmp_path))
