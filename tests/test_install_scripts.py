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
