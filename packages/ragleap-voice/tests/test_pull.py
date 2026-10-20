import collections
import hashlib
import http.server
import json
import os
import pathlib
import shutil
import sys
import threading
import urllib.parse
from dataclasses import replace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ragleap_voice import cli  # noqa: E402
from ragleap_voice.fetch import Policy, check_url, repo_id_from_url, resolve_url  # noqa: E402
from ragleap_voice.fetch import FetchError  # noqa: E402
from ragleap_voice.locks import canonical_bytes, lock_digest, verify_dir  # noqa: E402
from ragleap_voice.manifest import ModelEntry  # noqa: E402
from ragleap_voice.pull import PullError, build_lock, plan_lock, pull_model, token_from_env  # noqa: E402

REV = "a" * 40
TOKEN = os.urandom(8).hex()  # fake value generated at run time, so no secret-like literal is committed
SRC_URL = "https://huggingface.co/owner/repo"
FILES = {"weights.safetensors": b"w" * 5000, "config.json": b'{"a": 1}', "sub/tok.model": b"tokens"}
POLICY = Policy(allowed_suffixes=("127.0.0.1", "localhost"), token_hosts=("127.0.0.1",), require_https=False, timeout=5.0)


class Hub:
    """A fake Hugging Face (hub + CDN) on 127.0.0.1 with switchable misbehaviour."""

    def __init__(self, files):
        self.files = dict(files)
        self.mode = "direct"          # direct | redirect | redirect_bad | loop
        self.tamper = {}              # path -> bytes served instead of the real content
        self.truncate = set()
        self.require_token = None
        self.api_sha = REV
        self.hub_log, self.cdn_log = [], []
        self.requests = 0
        self.downloads = 0

    def body_for(self, rel):
        return self.tamper.get(rel, self.files[rel])

    def start(self):
        hub = self

        class Base(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, body=b"", short=False, headers=None):
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body[:-3] if (short and body) else body)

        class HubHandler(Base):
            def do_GET(self):
                hub.requests += 1
                auth = self.headers.get("Authorization")
                hub.hub_log.append((self.path, auth))
                if hub.require_token is not None and auth != "Bearer " + hub.require_token:
                    return self.reply(401)
                if self.path.startswith("/api/models/owner/repo/revision/"):
                    data = {"sha": hub.api_sha,
                            "siblings": [{"rfilename": p, "size": len(b)} for p, b in sorted(hub.files.items())]}
                    return self.reply(200, json.dumps(data).encode())
                if self.path.startswith("/final/"):
                    rel = urllib.parse.unquote(self.path[len("/final/"):])
                    return self.reply(200, hub.body_for(rel)) if rel in hub.files else self.reply(404)
                prefix = "/owner/repo/resolve/" + REV + "/"
                if not self.path.startswith(prefix):
                    return self.reply(404)
                rel = urllib.parse.unquote(self.path[len(prefix):])
                if rel not in hub.files:
                    return self.reply(404)
                hub.downloads += 1
                quoted = urllib.parse.quote(rel)
                if hub.mode == "redirect":
                    return self.reply(302, headers={"Location": "http://localhost:%d/blob/%s?sig=SECRETSIG" % (hub.cdn_port, quoted)})
                if hub.mode == "redirect_bad":
                    return self.reply(302, headers={"Location": "http://evil.example:%d/blob/%s?sig=SECRETSIG" % (hub.cdn_port, quoted)})
                if hub.mode == "redirect_same":
                    return self.reply(307, headers={"Location": "/final/" + quoted})
                if hub.mode == "redirect_bounce":
                    return self.reply(302, headers={"Location": "http://localhost:%d/bounce/%s?sig=SECRETSIG" % (hub.cdn_port, quoted)})
                if hub.mode == "loop":
                    return self.reply(302, headers={"Location": self.path})
                return self.reply(200, hub.body_for(rel), short=rel in hub.truncate)

        class CdnHandler(Base):
            def do_GET(self):
                hub.cdn_log.append((self.path, self.headers.get("Authorization")))
                path = self.path.split("?")[0]
                if path.startswith("/bounce/"):
                    rel = path[len("/bounce/"):]
                    return self.reply(302, headers={"Location": "http://127.0.0.1:%d/final/%s" % (hub.hub_port, rel)})
                if not path.startswith("/blob/"):
                    return self.reply(404)
                rel = urllib.parse.unquote(path[len("/blob/"):])
                if rel not in hub.files:
                    return self.reply(404)
                return self.reply(200, hub.body_for(rel), short=rel in hub.truncate)

        self.hub_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HubHandler)
        self.cdn_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CdnHandler)
        self.base_url = "http://127.0.0.1:%d" % self.hub_srv.server_address[1]
        self.cdn_port = self.cdn_srv.server_address[1]
        self.hub_port = self.hub_srv.server_address[1]
        for srv in (self.hub_srv, self.cdn_srv):
            threading.Thread(target=srv.serve_forever, daemon=True).start()

    def stop(self):
        for srv in (self.hub_srv, self.cdn_srv):
            srv.shutdown()
            srv.server_close()


@pytest.fixture
def hub(monkeypatch):
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    h = Hub(FILES)
    h.start()
    yield h
    h.stop()


def make_lock(files):
    entries = [{"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b in sorted(files.items())]
    return {"schema": 1, "model": "m1", "revision": REV, "source_url": SRC_URL, "files": entries}


def make_entry(lock, **over):
    base = ModelEntry(name="m1", kind="stt", source_url=SRC_URL, revision=REV, sha256=lock_digest(lock),
                      code_license="MIT", weights_license="Apache-2.0", languages=("en",), capabilities=(),
                      min_hardware="cpu", status="verified", default=False)
    return replace(base, **over)


def pull(hub, tmp_path, lock=None, entry=None, **kw):
    lock = lock or make_lock(FILES)
    entry = entry or make_entry(lock)
    kw.setdefault("policy", POLICY)
    kw.setdefault("base_url", hub.base_url)
    kw.setdefault("say", lambda *a: None)
    return pull_model(entry, lock, tmp_path, **kw)


def no_staging(tmp_path):
    return list((tmp_path / "models" / "m1").glob(".partial-*")) == []


def test_pull_success(hub, tmp_path):
    dest = pull(hub, tmp_path)
    assert dest == tmp_path / "models" / "m1" / REV
    assert verify_dir(make_lock(FILES), dest) == []
    assert sorted(os.listdir(dest.parent)) == [REV]
    assert hub.downloads == 3


def test_token_never_sent_to_another_host_and_never_printed(hub, tmp_path, capsys):
    hub.mode = "redirect"
    hub.require_token = TOKEN
    pull(hub, tmp_path, token=TOKEN, say=print)
    seen = capsys.readouterr()
    assert TOKEN not in seen.out + seen.err and "SECRETSIG" not in seen.out + seen.err
    assert hub.hub_log and all(auth == "Bearer " + TOKEN for _, auth in hub.hub_log)
    assert hub.cdn_log and all(auth is None for _, auth in hub.cdn_log)


def test_redirect_to_disallowed_host_refused(hub, tmp_path):
    hub.mode = "redirect_bad"
    with pytest.raises(PullError, match="host not allowed"):
        pull(hub, tmp_path)
    assert no_staging(tmp_path) and not (tmp_path / "models" / "m1" / REV).exists()


def test_default_policy_refuses_plain_http(hub, tmp_path):
    with pytest.raises(PullError, match="non-HTTPS"):
        pull(hub, tmp_path, policy=Policy())
    assert no_staging(tmp_path)


def test_redirect_loop_refused(hub, tmp_path):
    hub.mode = "loop"
    with pytest.raises(PullError, match="too many redirects"):
        pull(hub, tmp_path)


def test_tampered_content_same_size(hub, tmp_path):
    hub.tamper["weights.safetensors"] = b"x" * 5000
    with pytest.raises(PullError, match="sha256 mismatch"):
        pull(hub, tmp_path)
    assert no_staging(tmp_path) and not (tmp_path / "models" / "m1" / REV).exists()


def test_longer_content_refused(hub, tmp_path):
    hub.tamper["weights.safetensors"] = b"w" * 5001
    with pytest.raises(PullError, match="does not match the locked size"):
        pull(hub, tmp_path)
    assert no_staging(tmp_path)


def test_truncated_download_refused(hub, tmp_path):
    hub.truncate.add("config.json")
    with pytest.raises(PullError):
        pull(hub, tmp_path)
    assert no_staging(tmp_path) and not (tmp_path / "models" / "m1" / REV).exists()


def test_gated_repo_needs_token(hub, tmp_path):
    hub.require_token = TOKEN
    with pytest.raises(PullError) as exc:
        pull(hub, tmp_path)
    assert "gated" in str(exc.value) and "HF_TOKEN" in str(exc.value) and TOKEN not in str(exc.value)
    dest = pull(hub, tmp_path / "second", token=TOKEN)
    assert verify_dir(make_lock(FILES), dest) == []


def test_offline_mode_makes_no_requests(hub, tmp_path):
    with pytest.raises(PullError, match="offline"):
        pull(hub, tmp_path, offline=True)
    assert hub.requests == 0
    pull(hub, tmp_path)
    before = hub.requests
    pull(hub, tmp_path, offline=True)
    assert hub.requests == before


def test_existing_verified_skips_network_and_corrupt_is_refused(hub, tmp_path):
    dest = pull(hub, tmp_path)
    before = hub.requests
    pull(hub, tmp_path)
    assert hub.requests == before
    (dest / "config.json").write_bytes(b"junk")
    with pytest.raises(PullError, match="remove that directory"):
        pull(hub, tmp_path)


def test_unverified_refused_unless_flag(hub, tmp_path):
    lock = make_lock(FILES)
    e = make_entry(lock, status="unverified")
    with pytest.raises(PullError, match="unverified"):
        pull(hub, tmp_path, lock=lock, entry=e)
    assert hub.requests == 0
    msgs = []
    pull(hub, tmp_path, lock=lock, entry=e, allow_unverified=True, say=msgs.append)
    assert any("WARNING" in m and "Apache-2.0" in m for m in msgs)


def test_banned_licence_refused_even_with_flag(hub, tmp_path):
    lock = make_lock(FILES)
    e = make_entry(lock, weights_license="CC-BY-NC-4.0", status="unverified")
    with pytest.raises(PullError, match="allowlist"):
        pull(hub, tmp_path, lock=lock, entry=e, allow_unverified=True)
    assert hub.requests == 0


def test_refusals_before_network(hub, tmp_path):
    lock = make_lock(FILES)
    with pytest.raises(PullError, match="huggingface.co"):
        pull(hub, tmp_path, lock=lock, entry=make_entry(lock, source_url="https://example.org/owner/repo"))
    with pytest.raises(PullError, match="40-character"):
        pull(hub, tmp_path, lock=lock, entry=make_entry(lock, revision="main"))
    with pytest.raises(PullError, match="digest"):
        pull(hub, tmp_path, lock=lock, entry=make_entry(lock, sha256="0" * 64))
    bad = make_lock(FILES)
    bad["files"][0]["path"] = "../escape"
    with pytest.raises(PullError, match="invalid"):
        pull(hub, tmp_path, lock=bad, entry=make_entry(bad))
    assert hub.requests == 0


def test_disk_space_checked_first(hub, tmp_path, monkeypatch):
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(10, 10, 1))
    with pytest.raises(PullError, match="disk space"):
        pull(hub, tmp_path)
    assert hub.requests == 0


@pytest.mark.parametrize("url", [
    "http://huggingface.co/x", "https://user:pw@huggingface.co/x", "https://huggingface.co:8443/x",
    "https://huggingface.co.evil.com/x", "https://evilhuggingface.co/x", "https://example.org/x",
    "ftp://huggingface.co/x", "https://huggingface.co:notaport/x",
])
def test_check_url_rejects(url):
    with pytest.raises(FetchError):
        check_url(url, Policy())


@pytest.mark.parametrize("url", ["https://huggingface.co/x", "https://cdn-lfs.hf.co/a/b?sig=1", "https://hf.co/x"])
def test_check_url_accepts(url):
    assert check_url(url, Policy())


def test_repo_id_and_resolve_url():
    assert repo_id_from_url("https://huggingface.co/ai4bharat/indic-parler-tts") == "ai4bharat/indic-parler-tts"
    assert repo_id_from_url("https://huggingface.co/a/b/") == "a/b"
    for bad in ("http://huggingface.co/a/b", "https://huggingface.co/a", "https://huggingface.co/a/b/c",
                "https://hf.co/a/b", "https://huggingface.co.evil.com/a/b", "https://huggingface.co/../b", "", None):
        assert repo_id_from_url(bad) is None
    assert resolve_url("https://huggingface.co/", "o/r", REV, "sub/a+b.bin") == \
        "https://huggingface.co/o/r/resolve/%s/sub/a%%2Bb.bin" % REV


def test_token_from_env():
    assert token_from_env({"HF_TOKEN": " abc "}) == "abc"
    assert token_from_env({"HUGGING_FACE_HUB_TOKEN": "xyz"}) == "xyz"
    assert token_from_env({"HF_TOKEN": "  "}) is None and token_from_env({}) is None


def test_plan_and_build_lock(hub):
    plan = plan_lock(SRC_URL, REV, policy=POLICY, base_url=hub.base_url)
    assert [p for p, _ in plan] == sorted(FILES) and dict(plan)["weights.safetensors"] == 5000
    lock = build_lock("m1", SRC_URL, REV, plan, policy=POLICY, base_url=hub.base_url, say=lambda *a: None)
    assert lock == make_lock(FILES)
    assert [p for p, _ in plan_lock(SRC_URL, REV, excludes=("*.json",), policy=POLICY, base_url=hub.base_url)] == \
        ["sub/tok.model", "weights.safetensors"]
    assert [p for p, _ in plan_lock(SRC_URL, REV, includes=("sub/*",), policy=POLICY, base_url=hub.base_url)] == ["sub/tok.model"]
    with pytest.raises(PullError, match="no files"):
        plan_lock(SRC_URL, REV, includes=("nothing*",), policy=POLICY, base_url=hub.base_url)


def test_lock_refuses_wrong_revision_and_bad_names(hub):
    hub.api_sha = "b" * 40
    with pytest.raises(PullError, match="did not return"):
        plan_lock(SRC_URL, REV, policy=POLICY, base_url=hub.base_url)
    hub.api_sha = REV
    hub.files["bad name.bin"] = b"x"
    with pytest.raises(PullError, match="unsupported"):
        plan_lock(SRC_URL, REV, policy=POLICY, base_url=hub.base_url)
    with pytest.raises(PullError, match="40-character"):
        plan_lock(SRC_URL, "main", policy=POLICY, base_url=hub.base_url)


TOML = '''
[[model]]
name = "m1"
kind = "stt"
source_url = "https://huggingface.co/owner/repo"
revision = "REVISION"
sha256 = "DIGEST"
code_license = "MIT"
weights_license = "Apache-2.0"
languages = ["en"]
capabilities = []
min_hardware = "cpu"
status = "STATUS"
default = false
'''


def project(tmp_path, status="verified", with_lock=True):
    lock = make_lock(FILES)
    (tmp_path / "locks").mkdir(exist_ok=True)
    if with_lock:
        (tmp_path / "locks" / "m1.json").write_bytes(canonical_bytes(lock))
    text = TOML.replace("REVISION", REV).replace("DIGEST", lock_digest(lock)).replace("STATUS", status)
    (tmp_path / "models.toml").write_text(text, encoding="utf-8")
    return str(tmp_path / "models.toml")


def test_cli_pull_flow(hub, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_network", lambda: (POLICY, hub.base_url))
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    hub.require_token = TOKEN
    mf = project(tmp_path)
    home = tmp_path / "home"
    args = ["models", "pull", "m1", "--manifest", mf, "--cache-dir", str(home)]
    assert cli.main(args) == 0
    seen = capsys.readouterr()
    assert "installed in" in seen.out and TOKEN not in seen.out + seen.err
    assert cli.main(["models", "verify", "m1", "--manifest", mf, "--cache-dir", str(home)]) == 0
    capsys.readouterr()
    assert cli.main(args) == 0
    assert "already present" in capsys.readouterr().out


def test_cli_pull_refusals(hub, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_network", lambda: (POLICY, hub.base_url))
    home = str(tmp_path / "home")
    mf = project(tmp_path, status="unverified")
    assert cli.main(["models", "pull", "m1", "--manifest", mf, "--cache-dir", home]) == 1
    assert "unverified" in capsys.readouterr().err
    assert cli.main(["models", "pull", "m1", "--manifest", mf, "--cache-dir", home, "--allow-unverified"]) == 0
    capsys.readouterr()
    mf = project(tmp_path / "nolock", with_lock=False) if (tmp_path / "nolock").mkdir() is None else ""
    assert cli.main(["models", "pull", "m1", "--manifest", mf, "--cache-dir", home]) == 1
    assert "no lock file" in capsys.readouterr().err
    assert cli.main(["models", "pull", "nope", "--manifest", mf]) == 1
    assert "unknown model" in capsys.readouterr().err


def test_cli_offline_flag_and_env(hub, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_network", lambda: (POLICY, hub.base_url))
    mf = project(tmp_path)
    home = str(tmp_path / "home")
    assert cli.main(["models", "pull", "m1", "--manifest", mf, "--cache-dir", home, "--offline"]) == 1
    assert "offline" in capsys.readouterr().err
    monkeypatch.setenv("RAGLEAP_VOICE_OFFLINE", "1")
    assert cli.main(["models", "pull", "m1", "--manifest", mf, "--cache-dir", home]) == 1
    assert "offline" in capsys.readouterr().err
    assert hub.requests == 0


def test_cli_lock_flow(hub, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_network", lambda: (POLICY, hub.base_url))
    mf = project(tmp_path, status="unverified", with_lock=False)
    out = tmp_path / "new" / "m1.json"
    base = ["models", "lock", "m1", "--manifest", mf, "--revision", REV, "--out", str(out)]
    assert cli.main(base) == 2
    text = capsys.readouterr().out
    assert "--yes" in text and "weights.safetensors" in text and not out.exists() and hub.downloads == 0
    assert cli.main(base + ["--yes"]) == 0
    text = capsys.readouterr().out
    lock = json.loads(out.read_text(encoding="utf-8"))
    assert lock == make_lock(FILES) and lock_digest(lock) in text
    assert cli.main(base + ["--yes"]) == 1
    assert "exists" in capsys.readouterr().err
    assert cli.main(base + ["--yes", "--overwrite", "--exclude", "*.json"]) == 0
    assert [f["path"] for f in json.loads(out.read_text(encoding="utf-8"))["files"]] == ["sub/tok.model", "weights.safetensors"]


# ---- token handling across redirects, and pickle-capable formats -------------------------------
import email.message  # noqa: E402
import io  # noqa: E402
import urllib.error  # noqa: E402

from ragleap_voice.fetch import open_url  # noqa: E402


def test_same_host_redirect_keeps_token_for_gated_repo(hub, tmp_path):
    hub.mode = "redirect_same"
    hub.require_token = TOKEN
    dest = pull(hub, tmp_path, token=TOKEN)
    assert verify_dir(make_lock(FILES), dest) == []
    assert any(path.startswith("/final/") and auth == "Bearer " + TOKEN for path, auth in hub.hub_log)
    with pytest.raises(PullError, match="access denied"):
        pull(hub, tmp_path / "second")


def test_token_not_resent_after_leaving_the_token_host(hub, tmp_path):
    hub.mode = "redirect_bounce"
    hub.require_token = TOKEN
    with pytest.raises(PullError, match="access denied"):
        pull(hub, tmp_path, token=TOKEN)
    finals = [auth for path, auth in hub.hub_log if path.startswith("/final/")]
    assert finals and all(a is None for a in finals)
    assert all(a is None for _, a in hub.cdn_log)


class _Resp:
    status = 200
    headers = {}

    def read(self, n=-1):
        return b""

    def close(self):
        pass


class ScriptedOpener:
    def __init__(self, script):
        self.script = script
        self.sent = []

    def open(self, req, timeout=None):
        self.sent.append((req.full_url, req.get_header("Authorization")))
        kind, value = self.script[req.full_url]
        if kind == "redirect":
            hdrs = email.message.Message()
            hdrs["Location"] = value
            raise urllib.error.HTTPError(req.full_url, 302, "Found", hdrs, io.BytesIO(b""))
        return _Resp()


START = "https://huggingface.co/o/r/resolve/" + REV + "/f"


def _auths(script, start, token=TOKEN):
    op = ScriptedOpener(script)
    open_url(start, Policy(), token=token, opener=op)
    return [auth for _, auth in op.sent]


def test_token_follows_same_host_redirect():
    nxt = "https://huggingface.co/o/r/resolve/x/f"
    assert _auths({START: ("redirect", nxt), nxt: ("ok", None)}, START) == ["Bearer " + TOKEN] * 2


def test_token_not_sent_to_cdn_and_not_resent_after_returning():
    cdn = "https://us.gcp.cdn.hf.co/blob/abc?sig=1"
    back = "https://huggingface.co/o/r/final"
    script = {START: ("redirect", cdn), cdn: ("redirect", back), back: ("ok", None)}
    assert _auths(script, START) == ["Bearer " + TOKEN, None, None]


def test_no_token_no_header_and_hf_co_is_not_a_token_host():
    assert _auths({START: ("ok", None)}, START, token=None) == [None]
    other = "https://hf.co/o/r/x"
    assert _auths({other: ("ok", None)}, other) == [None]


def test_pickle_capable_files(hub, tmp_path):
    hub.files["extra/model.pt"] = b"pickle-ish"
    lock = make_lock(dict(FILES, **{"extra/model.pt": b"pickle-ish"}))
    with pytest.raises(PullError, match="pickle-capable"):
        pull(hub, tmp_path, lock=lock, entry=make_entry(lock))
    assert hub.requests == 0
    msgs = []
    pull(hub, tmp_path, lock=lock, entry=make_entry(lock, status="unverified"), allow_unverified=True, say=msgs.append)
    assert any("pickle-capable" in m for m in msgs)


def test_cli_lock_warns_about_pickle_formats(hub, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_network", lambda: (POLICY, hub.base_url))
    hub.files["voices/a.pt"] = b"x"
    mf = project(tmp_path, status="unverified", with_lock=False)
    args = ["models", "lock", "m1", "--manifest", mf, "--revision", REV, "--out", str(tmp_path / "o.json")]
    assert cli.main(args) == 2
    assert "pickle-capable" in capsys.readouterr().out


# ---- format tags at lock time ----------------------------------------------------------------
import struct as _struct  # noqa: E402


def _ct2():
    return _struct.pack("<IH", 6, 12) + b"WhisperSpec\x00" + b"\x00" * 40


def test_build_lock_with_format_tag(hub):
    hub.files["model.bin"] = _ct2()
    plan = plan_lock(SRC_URL, REV, policy=POLICY, base_url=hub.base_url)
    lock = build_lock("m1", SRC_URL, REV, plan, policy=POLICY, base_url=hub.base_url,
                      say=lambda *a: None, formats={"model.bin": "ctranslate2"})
    tagged = [f for f in lock["files"] if "format" in f]
    assert [(f["path"], f["format"]) for f in tagged] == [("model.bin", "ctranslate2")]


def test_build_lock_refuses_bad_header(hub):
    hub.files["model.bin"] = _ct2()
    hub.tamper["model.bin"] = b"\x80\x04" + b"x" * 60
    plan = plan_lock(SRC_URL, REV, policy=POLICY, base_url=hub.base_url)
    with pytest.raises(PullError, match="header"):
        build_lock("m1", SRC_URL, REV, plan, policy=POLICY, base_url=hub.base_url,
                   say=lambda *a: None, formats={"model.bin": "ctranslate2"})


@pytest.mark.parametrize("formats", [{"nothing.bin": "ctranslate2"}, {"weights.safetensors": "ctranslate2"}, {"model.bin": "onnx"}])
def test_build_lock_refuses_bad_format_options(hub, formats):
    hub.files["model.bin"] = _ct2()
    plan = plan_lock(SRC_URL, REV, policy=POLICY, base_url=hub.base_url)
    with pytest.raises(PullError, match="format"):
        build_lock("m1", SRC_URL, REV, plan, policy=POLICY, base_url=hub.base_url, say=lambda *a: None, formats=formats)
    assert hub.downloads == 0


def test_cli_lock_format(hub, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_network", lambda: (POLICY, hub.base_url))
    hub.files["model.bin"] = _ct2()
    mf = project(tmp_path, status="unverified", with_lock=False)
    out = tmp_path / "new" / "m1.json"
    base = ["models", "lock", "m1", "--manifest", mf, "--revision", REV, "--out", str(out)]
    assert cli.main(base + ["--yes", "--format", "model.bin=ctranslate2"]) == 0
    capsys.readouterr()
    files = json.loads(out.read_text(encoding="utf-8"))["files"]
    assert [f["format"] for f in files if "format" in f] == ["ctranslate2"]
    assert cli.main(base + ["--yes", "--overwrite", "--format", "model.bin"]) == 1
    assert "PATH=NAME" in capsys.readouterr().err
