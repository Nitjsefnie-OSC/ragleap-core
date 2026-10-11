import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from ragleap_voice.licences import check_licence, validate_entries  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

try:
    import tomllib
except ImportError:  # Python 3.10
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


@pytest.mark.parametrize("expr", ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC", "CC-BY-4.0",
                                   "MIT OR GPL-3.0-only", "MIT AND Apache-2.0"])
def test_allowed(expr):
    assert check_licence(expr)[0]


@pytest.mark.parametrize("expr", ["CC-BY-NC-4.0", "GPL-3.0-only", "AGPL-3.0-only",
                                   "LGPL-3.0-only", "LicenseRef-Coqui-CPML",
                                   "LicenseRef-Llama-3.2", "research-only", "",
                                   "MIT AND GPL-3.0-only", "(MIT OR ISC)"])
def test_rejected(expr):
    assert not check_licence(expr)[0]


def _good():
    return {"name": "m", "kind": "tts", "source_url": "https://example.org/m",
            "revision": "abc123", "sha256": "0" * 64, "code_license": "MIT",
            "weights_license": "Apache-2.0", "languages": ["en"], "capabilities": [],
            "min_hardware": "cpu", "status": "verified", "default": True}


def test_valid_default_entry_passes():
    assert validate_entries([_good()]) == []


def test_default_needs_verified_hash_and_revision():
    e = _good()
    e.update(status="unverified", sha256="", revision="")
    assert len(validate_entries([e])) == 3


def test_default_with_banned_weights_fails():
    e = _good()
    e["weights_license"] = "CC-BY-NC-4.0"
    assert validate_entries([e])


def test_cc_by_needs_notice():
    e = _good()
    e["weights_license"] = "CC-BY-4.0"
    assert validate_entries([e], notices_text="")
    assert validate_entries([e], notices_text="m: CC-BY-4.0, attribution ...") == []


def test_missing_field_and_duplicates():
    e = _good()
    del e["kind"]
    assert any("missing field kind" in p for p in validate_entries([e]))
    assert any("duplicate" in p for p in validate_entries([_good(), _good()]))


@pytest.mark.skipif(tomllib is None, reason="needs Python 3.11+ or tomli")
def test_real_manifest_passes():
    data = tomllib.loads((ROOT / "models.toml").read_text(encoding="utf-8"))
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert validate_entries(data["model"], notices) == []
