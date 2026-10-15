"""Proactive and Connectors tabs: the dashboard only calls routes that exist, and the script stays safe."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "core" / "office_static" / "app.js"


def _routes():
    from core import api
    found = {}
    for r in api.app.routes:
        found.setdefault(getattr(r, "path", ""), set()).update(getattr(r, "methods", None) or set())
    return found


def test_dashboard_has_both_tabs_and_their_calls():
    s = APP_JS.read_text(encoding="utf-8")
    assert '["proactive", "Proactive"]' in s and '["sources", "Connectors"]' in s
    for needle in ('"/proactive-triggers"', '"PATCH"', '"/integrations"', '"/integrations/csv"',
                   '"/test"', '"/sync"', "refreshProactive", "refreshSources"):
        assert needle in s, needle


def test_every_route_the_tabs_call_exists_with_that_method():
    found = _routes()
    assert {"GET", "POST"} <= found["/proactive-triggers"]
    assert {"PATCH", "DELETE"} <= found["/proactive-triggers/{trigger_id}"]
    assert "GET" in found["/integrations"] and "POST" in found["/integrations/csv"]
    assert "POST" in found["/integrations/{data_source_id}/test"]
    assert "POST" in found["/integrations/{data_source_id}/sync"]
    assert "GET" in found["/employees"]


def test_lock_forgets_the_new_forms():
    s = APP_JS.read_text(encoding="utf-8")
    lock = s[s.index("const lock = (msg) => {"):s.index("showLogin(msg);")]
    for name in ("proFormEl", "proListEl", "srcFormEl", "srcListEl"):
        assert name + " = null" in lock, name


def test_dashboard_script_still_parses_with_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--check", str(APP_JS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[:500]
