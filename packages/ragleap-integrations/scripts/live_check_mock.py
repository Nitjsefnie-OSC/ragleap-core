#!/usr/bin/env python3
"""Live check of ragleap-integrations against public MCP mock servers.

Repository only (not in the wheel). Read-only probes of a third party's test
servers (https://mcpplaygroundonline.com/mock-mcp-servers); read their
Acceptable Use page first. About fifteen requests in total, no loops.

Everything a server returns is untrusted text and is printed with repr().
The bearer token is minted and held in memory only: it is never printed.

Usage: PYTHONPATH=src python3 scripts/live_check_mock.py [--dry-plan]
"""
import json
import sys
import time
import urllib.error
import urllib.request

from ragleap_integrations import McpClient, McpConfig, McpConfigError, McpDiscoveryError, McpServerConfig

BASE = "https://mcpplaygroundonline.com"
UA = "ragleap-live-check (+https://github.com/ragleap/ragleap-core)"
PLAN = [
    "A  modern tools/call: stateless server pinned to ?rev=2026-07-28, tool which_protocol_era",
    "B  same tool, no ?rev (the server decides)",
    "C  raw probe: a legacy initialize sent to the pinned-modern URL; where does -32022 carry the supported versions",
    "D  does any live tool schema carry x-mcp-header (complex-schema server, all four tools)",
    "E  bearer auth: no token (expect a failure), then a freshly minted token (auth server, tool get_user)",
    "F  tool errors: error server, simulate_error validation and rate_limit",
    "G  fallback: the stateless server pinned to ?rev=2025-11-25 (legacy only), tool which_protocol_era",
]


def show(check, verdict, detail=""):
    print("%-2s %-5s %s" % (check, verdict, detail), flush=True)


REDACT = []  # secrets that must never reach the output, even if a server echoes them


def clip(value, n=220):
    text = repr(value)
    for secret in REDACT:
        text = text.replace(secret, "[token]")
    return text[:n]


def one_tool(name, url, tool, token=None, arguments=None, max_schema=10000):
    cfg = McpConfig(servers=[McpServerConfig(name, url, token)], allowed_tools=["%s.%s" % (name, tool)],
                    max_schema_chars=max_schema)
    client = McpClient(cfg)
    disc = client.discover()
    if not disc.tools:
        return None, disc, client
    spec = disc.tools[0]
    return client.call_tool(name, tool, arguments or {}, spec.parameters), disc, client


def result_text(res):
    for attr in ("data", "result", "output", "content"):
        value = getattr(res, attr, None)
        if value:
            return value
    return None


def check_a_b():
    for check, suffix in (("A", "?rev=2026-07-28"), ("B", "")):
        try:
            res, disc, _ = one_tool("stateless", BASE + "/mcp-stateless-server" + suffix, "which_protocol_era")
            if res is None:
                show(check, "FAIL", "tool not discovered; skipped=%s" % clip(disc.skipped))
            else:
                show(check, "PASS" if res.success else "FAIL",
                     "success=%s error=%s text=%s" % (res.success, clip(res.error), clip(result_text(res))))
        except (McpConfigError, McpDiscoveryError) as e:
            show(check, "FAIL", "%s: %s" % (type(e).__name__, clip(str(e))))
        time.sleep(1)


def raw_post(url, obj, headers=None):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), method="POST", headers=dict({
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": UA,
    }, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.headers.get("Content-Type"), r.read(20000)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read(20000)


def check_c():
    legacy = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "ragleap-live-check", "version": "0"}}}
    try:
        status, ctype, body = raw_post(BASE + "/mcp-stateless-server?rev=2026-07-28", legacy)
        text = body.decode("utf-8", "replace")
        try:
            err = json.loads(text).get("error")
        except (ValueError, AttributeError):
            err = None
        code = err.get("code") if isinstance(err, dict) else None
        has_data = isinstance(err, dict) and "data" in err
        show("C", "INFO", "http=%s content-type=%s code=%s data_present=%s body=%s"
             % (status, clip(ctype), code, has_data, clip(text, 500)))
    except Exception as e:
        show("C", "FAIL", "%s: %s" % (type(e).__name__, clip(str(e))))
    time.sleep(1)


def check_d():
    names = ["create_user_profile", "process_order", "analyze_data", "configure_workflow"]
    try:
        cfg = McpConfig(servers=[McpServerConfig("complex", BASE + "/mcp-complex-server")],
                        allowed_tools=["complex." + n for n in names], max_schema_chars=200000)
        disc = McpClient(cfg).discover()
        carrying = [t.name for t in disc.tools if "x-mcp-header" in json.dumps(t.parameters)]
        show("D", "INFO", "tools=%d skipped=%s carrying_x-mcp-header=%s" % (len(disc.tools), clip(disc.skipped), carrying))
    except (McpConfigError, McpDiscoveryError) as e:
        show("D", "FAIL", "%s: %s" % (type(e).__name__, clip(str(e))))
    time.sleep(1)


def mint_token():
    req = urllib.request.Request(BASE + "/api/auth/token", data=b"", method="POST", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        obj = json.loads(r.read(20000).decode("utf-8", "replace"))
    keys = sorted(obj) if isinstance(obj, dict) else []
    for k in ("access_token", "token"):
        if isinstance(obj, dict) and isinstance(obj.get(k), str) and obj[k]:
            return obj[k], keys
    return None, keys


def check_e():
    url = BASE + "/mcp-auth-server"
    try:
        res, disc, _ = one_tool("auth", url, "get_user")
        show("E1", "FAIL" if res is None else "INFO", "no token: unexpectedly answered; skipped=%s" % clip(disc.skipped))
    except (McpConfigError, McpDiscoveryError) as e:
        show("E1", "PASS", "no token refused as expected: %s" % clip(str(e)))
    time.sleep(1)
    try:
        token, keys = mint_token()
        if not token:
            show("E2", "SKIP", "no token field found in the mint response; keys=%s" % keys)
            return
        REDACT.append(token)
        show("E2", "INFO", "token minted (%d chars, not shown); response keys=%s" % (len(token), keys))
        res, disc, _ = one_tool("auth", url, "get_user", token=token)
        if res is None:
            show("E3", "FAIL", "with token: tool not discovered; skipped=%s" % clip(disc.skipped))
        else:
            show("E3", "PASS" if res.success else "FAIL",
                 "with token: success=%s error=%s text=%s" % (res.success, clip(res.error), clip(result_text(res))))
    except (McpConfigError, McpDiscoveryError) as e:
        show("E3", "FAIL", "%s: %s" % (type(e).__name__, clip(str(e))))
    except Exception as e:
        show("E2", "FAIL", "%s: %s" % (type(e).__name__, clip(str(e))))
    time.sleep(1)


def check_f():
    for error_type in ("validation", "rate_limit"):
        try:
            res, disc, _ = one_tool("errors", BASE + "/mcp-error-server", "simulate_error",
                                    arguments={"errorType": error_type})
            if res is None:
                show("F", "FAIL", "%s: tool not discovered; skipped=%s" % (error_type, clip(disc.skipped)))
            else:
                show("F", "INFO", "%s: success=%s error=%s text=%s"
                     % (error_type, res.success, clip(res.error), clip(result_text(res))))
        except (McpConfigError, McpDiscoveryError) as e:
            show("F", "FAIL", "%s: %s: %s" % (error_type, type(e).__name__, clip(str(e))))
        time.sleep(1)


def check_g():
    try:
        res, disc, _ = one_tool("legacyonly", BASE + "/mcp-stateless-server?rev=2025-11-25", "which_protocol_era")
        if res is None:
            show("G", "INFO", "tool not discovered; skipped=%s" % clip(disc.skipped))
        else:
            show("G", "INFO", "success=%s error=%s text=%s" % (res.success, clip(res.error), clip(result_text(res))))
    except (McpConfigError, McpDiscoveryError) as e:
        show("G", "INFO", "%s: %s" % (type(e).__name__, clip(str(e))))
    time.sleep(1)


def main():
    if "--dry-plan" in sys.argv:
        print("\n".join(PLAN))
        return 0
    print("Live check against %s (third-party test servers; results are untrusted text)" % BASE)
    check_a_b()
    check_c()
    check_d()
    check_e()
    check_f()
    check_g()
    print("done: PASS/FAIL are about these servers and this client only; INFO lines need a human reading against the spec")
    return 0


if __name__ == "__main__":
    sys.exit(main())
