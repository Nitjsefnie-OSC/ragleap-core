"""connect(): one call from a URL to tools, a Toolkit and a readable report."""
import json

import pytest

from ragleap_integrations import Connection, McpPolicy, connect, connect_config
from ragleap_integrations._net import HttpResponse
from ragleap_integrations.mcp import McpConfig, McpConfigError, McpDiscoveryError, McpServerConfig, McpToolSpec
from ragleap_tools import Toolkit

URL = "https://mcp.example.com/mcp"
SMALL = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}


class Fake:
    def __init__(self, tools, status=200):
        self.tools, self.status, self.methods = tools, status, []

    def __call__(self, url, headers, body, stop=None):
        req = json.loads(body)
        self.methods.append(req["method"])
        if self.status != 200:
            return HttpResponse(self.status, {}, b"", "")
        if req["method"] == "tools/list":
            result = {"tools": self.tools}
        else:
            result = {"content": [{"type": "text", "text": "done:" + json.dumps(req["params"]["arguments"])}]}
        payload = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}).encode()
        return HttpResponse(200, {}, payload, "application/json")


def items(*names, annotations=None, schema=None):
    return [{"name": n, "description": "tool " + n, "inputSchema": schema or SMALL,
             **({"annotations": annotations} if annotations else {})} for n in names]


def test_connect_returns_ready_tools_and_a_toolkit():
    fake = Fake(items("list_orders", "get_order"))
    conn = connect(URL, allow=["list_orders", "get_order"], transport=fake)
    assert isinstance(conn, Connection) and isinstance(conn.toolkit, Toolkit)
    assert [t.name for t in conn.tools] == ["mcp__list_orders", "mcp__get_order"]
    assert conn.toolkit.names() == [t.name for t in conn.tools] and conn.skipped == []
    assert fake.methods == ["tools/list"]


def test_the_toolkit_dispatches_a_model_call_to_the_server():
    conn = connect(URL, allow=["get_order"], transport=Fake(items("get_order")))
    result = conn.toolkit.call("mcp__get_order", '{"id": "A-1"}')
    assert result.success is True and result.result["text"] == 'done:{"id": "A-1"}'


def test_the_toolkit_rejects_arguments_that_break_the_servers_schema_before_any_call():
    fake = Fake(items("get_order"))
    conn = connect(URL, allow=["get_order"], transport=fake)
    for raw in ('{"id": 5}', "{}", '{"id": "x", "zzz": 1}'):
        assert conn.toolkit.call("mcp__get_order", raw).success is False
    assert "tools/call" not in fake.methods


def test_name_prefixes_the_tool_names():
    conn = connect(URL, allow=["get_order"], name="shop", transport=Fake(items("get_order")))
    assert conn.toolkit.names() == ["shop__get_order"]
    assert conn.tools[0].metadata["mcp"]["server"] == "shop"


def test_report_lists_ready_and_skipped_tools_with_hints():
    big = {"type": "object", "properties": {"x": {"type": "string", "description": "d" * 400}}}
    fake = Fake(items("get_order") + items("huge", schema=big))
    conn = connect(URL, allow=["get_order", "huge", "ghost"], max_schema_chars=200, transport=fake)
    report = conn.report()
    assert report.splitlines()[0] == "1 tool(s) ready, 2 skipped"
    assert "  ready: mcp__get_order (approval: required)" in report
    assert "  skipped: mcp.huge - inputSchema is too large (raise max_schema_chars)" in report
    assert "  skipped: mcp.ghost - not offered by the server (check the tool name)" in report


def test_report_says_when_approval_is_not_required():
    conn = connect(URL, allow=["list_orders"], trust_annotations=True,
                   transport=Fake(items("list_orders", annotations={"readOnlyHint": True})))
    assert "(approval: not required)" in conn.report()
    untrusted = connect(URL, allow=["list_orders"], transport=Fake(items("list_orders", annotations={"readOnlyHint": True})))
    assert "(approval: required)" in untrusted.report()


def test_approve_and_pre_approved_build_the_policy():
    seen = []

    def approve(server, tool, arguments):
        seen.append(tool)
        return False

    fake = Fake(items("get_order", "list_orders"))
    conn = connect(URL, allow=["get_order", "list_orders"], approve=approve, pre_approved=["list_orders"], transport=fake)
    assert isinstance(conn.config.policy, McpPolicy)
    assert conn.toolkit.call("mcp__list_orders", '{"id": "1"}').success is True
    denied = conn.toolkit.call("mcp__get_order", '{"id": "1"}')
    assert denied.success is False and denied.error == "MCP call was not approved" and seen == ["get_order"]


def test_on_event_is_wired_through():
    events = []
    conn = connect(URL, allow=["get_order"], on_event=events.append, transport=Fake(items("get_order")))
    conn.toolkit.call("mcp__get_order", '{"id": "1"}')
    assert [e["event"] for e in events] == ["discover", "call"]


@pytest.mark.parametrize("allow", ["get_order", [], None, ["ok", 5], ("a", None), {"a": 1}])
def test_allow_must_be_a_non_empty_list_of_names(allow):
    with pytest.raises(McpConfigError, match="allow must be"):
        connect(URL, allow=allow, transport=Fake([]))


def test_pre_approved_must_be_a_list_of_names_inside_allow():
    with pytest.raises(McpConfigError, match="pre_approved"):
        connect(URL, allow=["a"], pre_approved="a", transport=Fake([]))
    with pytest.raises(McpConfigError, match="pre_approved"):
        connect(URL, allow=["a"], pre_approved=[5], transport=Fake([]))
    with pytest.raises(McpConfigError, match="not in allowed_tools"):
        connect(URL, allow=["a"], pre_approved=["b"], transport=Fake([]))


def test_bad_urls_and_names_fail_at_configuration_time():
    with pytest.raises(McpConfigError):
        connect("http://insecure.example.com/mcp", allow=["a"], transport=Fake([]))
    with pytest.raises(McpConfigError):
        connect(URL, allow=["a"], name="", transport=Fake([]))


def test_limits_are_passed_through_and_unknown_limits_fail():
    conn = connect(URL, allow=["get_order"], max_result_chars=77, transport=Fake(items("get_order")))
    assert conn.config.max_result_chars == 77
    with pytest.raises(TypeError):
        connect(URL, allow=["get_order"], max_resultz=1, transport=Fake([]))


def test_a_failed_discovery_raises():
    with pytest.raises(McpDiscoveryError):
        connect(URL, allow=["get_order"], transport=Fake([], status=500))


def test_connect_config_with_owner_supplied_specs_makes_no_request():
    fake = Fake([])
    config = McpConfig(servers=[McpServerConfig("srv", URL)], allowed_tools=["srv.get_order"])
    spec = McpToolSpec("srv", "get_order", "d", SMALL)
    conn = connect_config(config, specs=[spec], transport=fake)
    assert conn.toolkit.names() == ["srv__get_order"] and conn.skipped == [] and fake.methods == []


def test_connect_config_handles_several_servers():
    fake = Fake(items("a_tool"))
    config = McpConfig(servers=[McpServerConfig("one", URL), McpServerConfig("two", "https://two.example.com/mcp")],
                       allowed_tools=["one.a_tool", "two.a_tool"])
    conn = connect_config(config, transport=fake)
    assert conn.toolkit.names() == ["one__a_tool", "two__a_tool"]


def test_the_token_is_sent_and_never_appears_in_the_report():
    headers_seen = []

    def spy(url, headers, body, stop=None):
        headers_seen.append(dict(headers))
        return Fake(items("get_order"))(url, headers, body, stop)

    conn = connect(URL, allow=["get_order"], token="example-token-value", transport=spy)
    assert any("example-token-value" in str(h) for h in headers_seen)
    assert "example-token-value" not in conn.report() and "example-token-value" not in repr(conn.tools)


def test_pre_approved_alone_builds_a_policy_without_an_approve_hook():
    fake = Fake(items("get_order", "list_orders"))
    conn = connect(URL, allow=["get_order", "list_orders"], pre_approved=["list_orders"], transport=fake)
    assert conn.config.policy.pre_approved == ["mcp.list_orders"] and conn.config.policy.approve is None
    flags = {t.name: t.metadata["mcp"]["requires_approval"] for t in conn.tools}
    assert flags == {"mcp__get_order": True, "mcp__list_orders": False}
    assert conn.toolkit.call("mcp__get_order", '{"id": "1"}').success is True  # advice only, nothing enforced


def test_a_tool_without_governance_metadata_is_reported_as_needing_approval():
    from ragleap_tools import Tool, ToolResult

    bare = Tool(name="bare", description="d", parameters={"type": "object", "properties": {}},
                handler=lambda **kw: ToolResult(success=True))
    config = McpConfig(servers=[McpServerConfig("srv", URL)], allowed_tools=["srv.x"])
    conn = Connection(config=config, client=None, tools=[bare], skipped=[])
    assert "  ready: bare (approval: required)" in conn.report()
