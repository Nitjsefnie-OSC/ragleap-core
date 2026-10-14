import json
import os
import pathlib
import subprocess
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from ragleap_voice import cli  # noqa: E402
from ragleap_voice.manifest import ManifestError, load_manifest  # noqa: E402

GOOD = '''
[[model]]
name = "m1"
kind = "stt"
source_url = "https://example.org/m1"
revision = "abc123"
sha256 = "HASH"
code_license = "MIT"
weights_license = "Apache-2.0"
languages = ["en", "hi"]
capabilities = []
min_hardware = "cpu"
status = "verified"
default = true

[[model]]
name = "m2"
kind = "tts"
source_url = "https://example.org/m2"
revision = ""
sha256 = ""
code_license = "MIT"
weights_license = "CC-BY-NC-4.0"
languages = []
capabilities = ["clone"]
min_hardware = "unknown"
status = "unverified"
default = false
'''.replace("HASH", "0" * 64)


def _write(tmp_path, text=GOOD):
    p = tmp_path / "models.toml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_load_manifest_entries(tmp_path):
    entries, problems = load_manifest(_write(tmp_path))
    assert [e.name for e in entries] == ["m1", "m2"]
    assert entries[0].languages == ("en", "hi") and entries[0].default is True
    assert problems == []  # m2 has a banned licence but is not a default


@pytest.mark.parametrize("old,new,needle", [
    ('kind = "stt"\n', "", "kind"),
    ('name = "m1"\n', 'name = "m1"\ncolour = "red"\n', "unknown"),
    ("default = true", 'default = "yes"', "default"),
    ('languages = ["en", "hi"]', 'languages = "en"', "languages"),
])
def test_malformed_entries_raise(tmp_path, old, new, needle):
    assert GOOD.count(old) == 1
    with pytest.raises(ManifestError) as exc:
        load_manifest(_write(tmp_path, GOOD.replace(old, new)))
    assert needle in str(exc.value)


def test_unreadable_manifest_raises(tmp_path):
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, "[[model\n"))
    with pytest.raises(ManifestError):
        load_manifest(str(tmp_path / "nope.toml"))


def test_real_manifest_loads_and_passes():
    entries, problems = load_manifest()
    assert problems == []
    assert {"whisper-large-v3", "kokoro-82m"} <= {e.name for e in entries}
    assert not any(e.default and e.status != "verified" for e in entries)


def test_list_and_filter_and_json(tmp_path, capsys):
    mf = _write(tmp_path)
    assert cli.main(["models", "list", "--manifest", mf]) == 0
    out = capsys.readouterr().out
    assert "m1" in out and "m2" in out and "stt" in out
    assert cli.main(["models", "list", "--kind", "tts", "--manifest", mf]) == 0
    out = capsys.readouterr().out
    assert "m2" in out and "m1" not in out
    assert cli.main(["models", "list", "--json", "--manifest", mf]) == 0
    assert [d["name"] for d in json.loads(capsys.readouterr().out)] == ["m1", "m2"]


def test_show(tmp_path, capsys):
    mf = _write(tmp_path)
    assert cli.main(["models", "show", "m2", "--manifest", mf]) == 0
    out = capsys.readouterr().out
    assert "weights_license:" in out and "CC-BY-NC-4.0" in out and "unverified" in out
    assert cli.main(["models", "show", "nope", "--manifest", mf]) == 1
    assert "unknown model" in capsys.readouterr().err


def test_check_ok_and_failure(tmp_path, capsys):
    from ragleap_voice.locks import canonical_bytes, lock_digest
    lock = {"schema": 1, "model": "m1", "revision": "abc123", "source_url": "https://example.org/m1",
            "files": [{"path": "w.safetensors", "size": 3, "sha256": "1" * 64}]}
    (tmp_path / "locks").mkdir()
    (tmp_path / "locks" / "m1.json").write_bytes(canonical_bytes(lock))
    good = GOOD.replace("0" * 64, lock_digest(lock))
    assert cli.main(["models", "check", "--manifest", _write(tmp_path, good)]) == 0
    assert "manifest OK: 2 model(s), 1 verified, 1 default" in capsys.readouterr().out
    bad = good.replace('weights_license = "Apache-2.0"', 'weights_license = "CC-BY-NC-4.0"')
    assert cli.main(["models", "check", "--manifest", _write(tmp_path, bad)]) == 1
    assert "weights_license" in capsys.readouterr().err


def test_manifest_error_is_reported(tmp_path, capsys):
    assert cli.main(["models", "list", "--manifest", str(tmp_path / "nope.toml")]) == 1
    assert "error:" in capsys.readouterr().err


def test_no_command_and_version(capsys):
    assert cli.main([]) == 2
    assert cli.main(["models"]) == 2
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "ragleap-voice" in capsys.readouterr().out


def test_python_dash_m_runs_the_real_manifest():
    env = dict(os.environ, PYTHONPATH=str(SRC))
    r = subprocess.run([sys.executable, "-m", "ragleap_voice", "models", "check"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "manifest OK" in r.stdout
