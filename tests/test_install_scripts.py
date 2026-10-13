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
