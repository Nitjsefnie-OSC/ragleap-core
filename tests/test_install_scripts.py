"""Static checks for the installers: they parse, keep Unix line endings, and keep their safety checks."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL_SCRIPTS = ["install.sh", "scripts/ragleap"]


def _read(name):
    path = ROOT / name
    if not path.exists():
        pytest.skip(name + " is not in this checkout")
    return path


@pytest.mark.parametrize("name", SHELL_SCRIPTS)
def test_shell_scripts_parse(name):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is not available")
    r = subprocess.run([bash, "-n", str(_read(name))], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("name", SHELL_SCRIPTS + ["install.ps1"])
def test_installers_have_no_crlf(name):
    assert b"\r" not in _read(name).read_bytes()


def test_gitattributes_keeps_shell_scripts_on_lf():
    text = _read(".gitattributes").read_text()
    assert "*.sh text eol=lf" in text
    assert "scripts/ragleap text eol=lf" in text


def test_install_sh_safety_checks_present():
    s = _read("install.sh").read_text()
    for needle in ("check_disk", "check_project_conflict", "host_ollama_up"):
        assert needle in s
    # the disk check must run before the repository is cloned
    assert s.index('check_disk "$MIN_FREE_GB"') < s.index("git clone")


def test_install_ps1_basics():
    s = _read("install.ps1").read_text()
    assert s.count("{") == s.count("}")
    assert s.count("(") == s.count(")")
    assert "Remove-Item Env:GEMINI_API_KEY" in s


def _preflight():
    s = _read("install.sh").read_text()
    return s[s.index("# --- preflight helpers ---"):s.index("# --- end preflight helpers ---")]


def test_compose_host_ports_are_configurable_with_unchanged_defaults():
    import re
    s = _read("docker-compose.yml").read_text()
    for needle in (
        "${DB_PORT:-5433}:5432",
        "${APP_PORT:-8000}:8000",
        "${VOICE_PORT:-8766}:8765",
        "${NEO4J_HTTP_PORT:-7475}:7474",
        "${NEO4J_BOLT_PORT:-7688}:7687",
        "${REDIS_PORT:-6380}:6379",
    ):
        assert needle in s
    assert not re.search(r'^\s+- "127\.0\.0\.1:\d+:\d+"', s, re.M)


def test_port_helpers_skip_a_busy_port():
    import socket
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is not available")
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    busy = srv.getsockname()[1]
    try:
        script = _preflight() + "\nport_busy %d && echo BUSY\necho PICK=$(pick_port %d)\n" % (busy, busy)
        r = subprocess.run([bash, "-c", script], capture_output=True, text=True, timeout=30)
    finally:
        srv.close()
    if "BUSY" not in r.stdout and "No such file" in r.stderr:
        pytest.skip("this bash has no /dev/tcp support")
    assert "BUSY" in r.stdout
    assert int(r.stdout.split("PICK=")[1].split()[0]) > busy


def test_installer_volume_check_is_project_specific_and_ragleap_reads_app_port():
    assert "grep -q 'ragleap_core_data'" not in _read("install.sh").read_text()
    assert "env_value APP_PORT" in _read("scripts/ragleap").read_text()


def test_usage_lists_key_rotate_and_installer_opens_browser_before_printing_key():
    assert "key [--rotate]" in _read("scripts/ragleap").read_text() or "key --rotate" in _read("scripts/ragleap").read_text()
    s = _read("install.sh").read_text()
    assert s.index('open_browser "$BASE_URL/office#key=$DASH_LOGIN"') < s.index('say "  $BASE_URL/office#key=$DASH_LOGIN"')


def test_open_browser_can_be_switched_off():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is not available")
    s = _read("install.sh").read_text()
    fn = s[s.index("# --- browser helper ---"):s.index("# --- end browser helper ---")]
    r = subprocess.run([bash, "-c", fn + "\nopen_browser http://localhost:1; echo rc=$?\n"],
                       capture_output=True, text=True, timeout=30,
                       env={"PATH": "/usr/bin:/bin", "RAGLEAP_NO_BROWSER": "1"})
    assert "rc=1" in r.stdout


def test_ragleap_key_rotate_replaces_key_and_keeps_other_settings(tmp_path):
    import http.server
    import os
    import socket
    import threading
    bash = shutil.which("bash")
    if not bash or not shutil.which("curl") or not shutil.which("awk"):
        pytest.skip("bash, curl and awk are needed")
    script = _read("scripts/ragleap")
    old = "a" * 48
    home = tmp_path / "home"
    home.mkdir()
    (home / "docker-compose.yml").write_text("services: {}\n")
    sk = socket.socket()
    sk.bind(("127.0.0.1", 0))
    port = sk.getsockname()[1]
    sk.close()
    envp = home / ".env"
    envp.write_text("FOO=bar\nRAGLEAP_API_KEY=%s\nAPP_PORT=%d\nBAZ=qux\n" % (old, port))

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            cur = [l.split("=", 1)[1] for l in envp.read_text().splitlines() if l.startswith("RAGLEAP_API_KEY=")][0]
            if self.path == "/health":
                code = 200
            else:
                code = 200 if self.headers.get("x-api-key") == cur else 401
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "docker.log"
    d = fake / "docker"
    d.write_text('#!/bin/sh\nif [ "$1" = compose ] && [ "$2" = version ]; then echo v2; exit 0; fi\n'
                 'echo "$@" >> "' + str(log) + '"\nexit 0\n')
    d.chmod(0o755)
    env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ["PATH"], RAGLEAP_HOME=str(home))
    try:
        r = subprocess.run([bash, str(script), "key", "--rotate"], capture_output=True, text=True, env=env, timeout=90)
    finally:
        srv.shutdown()
    assert r.returncode == 0, r.stdout + r.stderr
    lines = envp.read_text().splitlines()
    new = [l.split("=", 1)[1] for l in lines if l.startswith("RAGLEAP_API_KEY=")][0]
    assert new != old and len(new) == 48 and all(c in "0123456789abcdef" for c in new)
    assert "FOO=bar" in lines and "BAZ=qux" in lines and ("APP_PORT=%d" % port) in lines
    assert "#key=" + new in r.stdout
    assert old not in r.stdout and old not in r.stderr
    assert "WARNING" not in r.stderr
    assert "force-recreate" in log.read_text()


def test_install_ps1_does_not_advertise_the_wrapped_one_liner():
    s = _read("install.ps1").read_text()
    assert 'powershell -c "irm' not in s
    assert "irm https://raw.githubusercontent.com/antonyrag/ragleap-core/main/install.ps1 | iex" in s


def test_install_sh_guidance_for_missing_requirements_and_windows_hint():
    s = _read("install.sh").read_text()
    assert "command -v curl" in s
    assert "docs.docker.com/engine/install" in s
    assert "Git Bash" in s and "bash scripts/ragleap key" in s
