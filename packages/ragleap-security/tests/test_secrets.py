import copy
import pickle
import time

import pytest

from ragleap_security import LimitError, SecretError, SecretStr, from_env, redact


def test_secretstr_never_shows_value():
    s = SecretStr("hunter2-hunter2")
    for shown in (str(s), repr(s), f"{s}", "%s" % s, "{}".format(s), format(s, ">30")):
        assert "hunter2" not in shown
    assert s.reveal() == "hunter2-hunter2"


def test_secretstr_not_json_pickle_or_hashable():
    import json

    s = SecretStr("abcdefgh")
    with pytest.raises(TypeError):
        json.dumps({"k": s})
    with pytest.raises(TypeError):
        pickle.dumps(s)
    with pytest.raises(TypeError):
        hash(s)
    with pytest.raises(TypeError):
        SecretStr(b"bytes")


def test_secretstr_equality_and_bool():
    assert SecretStr("abc") == SecretStr("abc")
    assert SecretStr("abc") == "abc"
    assert SecretStr("abc") != SecretStr("abd")
    assert SecretStr("abc") != 5
    assert SecretStr("x") and not SecretStr("")
    assert SecretStr("a\ud800") == SecretStr("a\ud800")  # lone surrogate does not crash


def test_secretstr_copy_keeps_masking():
    s = copy.copy(SecretStr("abcdefgh"))
    assert "abcdefgh" not in repr(s)


def test_from_env(monkeypatch):
    monkeypatch.setenv("RS_TEST_KEY", "value-123456")
    assert from_env("RS_TEST_KEY").reveal() == "value-123456"
    monkeypatch.delenv("RS_TEST_KEY")
    with pytest.raises(SecretError) as e:
        from_env("RS_TEST_KEY")
    assert "RS_TEST_KEY" in str(e.value)
    assert from_env("RS_TEST_KEY", required=False) is None
    monkeypatch.setenv("RS_TEST_KEY", "")
    assert from_env("RS_TEST_KEY", required=False) is None


@pytest.mark.parametrize("bad", ["", "1ABC", "A-B", "A B", "A=B", None, "x" * 200])
def test_from_env_rejects_bad_names(bad):
    with pytest.raises(SecretError):
        from_env(bad)


KNOWN = [
    "sk-abcdefghijklmnopqrstuv1234", "gsk_abcdefghijklmnopqrstuvwx", "AIza" + "a" * 35,
    "ghp_" + "a" * 36, "github_pat_" + "a" * 60, "AKIAABCDEFGHIJKLMNOP", "xoxb-1234567890-abcdefghij",
    "eyJabcdefghij.eyJabcdefghij.abcdefghijkl", "Bearer abcdef123456",
]


@pytest.mark.parametrize("secret", KNOWN)
def test_redact_known_formats(secret):
    out = redact(f"before {secret} after")
    assert secret not in out and "[REDACTED]" in out and out.startswith("before ") and out.endswith(" after")


def test_redact_private_key_block():
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\ndef\n-----END RSA PRIVATE KEY-----"
    assert "MIIEabc" not in redact("x\n" + block + "\ny")


def test_redact_authorization_header_keeps_name():
    out = redact("Authorization: Basic dXNlcjpwYXNzd29yZA==")
    assert "dXNlcjpw" not in out and out.lower().startswith("authorization")


def test_redact_exact_values_and_short_values():
    assert redact("token is s3cr3t-value here", [SecretStr("s3cr3t-value")]) == "token is [REDACTED] here"
    assert redact("a short ab here", ["ab"]) == "a short ab here"  # below MIN_REDACT_LEN: untouched
    assert redact("keep it", [SecretStr("")]) == "keep it"


def test_redact_leaves_ordinary_text():
    text = "The quarterly meeting is at 3pm. See sk and AKIA are just words."
    assert redact(text) == text


def test_redact_limits_and_types():
    with pytest.raises(LimitError):
        redact("x" * 11, max_chars=10)
    with pytest.raises(TypeError):
        redact(b"bytes")


def test_redact_is_linear_on_hostile_input():
    for hostile in ("Bearer " + "a" * 400_000, "-----BEGIN PRIVATE KEY-----" * 20_000,
                    "authorization:" + " " * 400_000, "sk-" * 300_000):
        t = time.monotonic()
        redact(hostile)
        assert time.monotonic() - t < 5
