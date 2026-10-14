"""v0.1.1: the default response-size cap is 1 MiB and the too-large error names the setting.

A real 15-tool server (Google Cloud Pub/Sub's MCP endpoint) replied with 359,293
bytes to tools/list, which the old 256 KiB default refused.
"""
import pytest
from test_net import URL, Client, make_server, read_request, respond, tls_material  # noqa: F401

from ragleap_integrations import McpClient, McpConfig, McpDiscoveryError, McpServerConfig, _net
from ragleap_integrations._net import TransportError, https_post

MIB = 1024 * 1024
REAL_PUBSUB_REPLY_BYTES = 359293


def _client(make_server, tls_material, size):
    def handler(server, conn):
        read_request(conn)
        respond(conn, 200, b"x" * size)
    return Client(make_server(handler), tls_material)


def test_default_response_cap_is_one_mib():
    assert _net.DEFAULT_MAX_BYTES == MIB
    cfg = McpConfig(servers=[McpServerConfig(name="g", url=URL)], allowed_tools=["g.x"])
    assert cfg.max_response_bytes == MIB


def test_a_reply_the_size_of_the_real_pubsub_tool_list_passes_with_the_default(make_server, tls_material):
    cl = _client(make_server, tls_material, REAL_PUBSUB_REPLY_BYTES)
    resp = https_post(URL, {}, b"{}", **cl.kwargs())
    assert len(resp.body) == REAL_PUBSUB_REPLY_BYTES


def test_exactly_one_mib_passes_and_one_byte_more_is_refused(make_server, tls_material):
    resp = https_post(URL, {}, b"{}", **_client(make_server, tls_material, MIB).kwargs())
    assert len(resp.body) == MIB
    with pytest.raises(TransportError) as e:
        https_post(URL, {}, b"{}", **_client(make_server, tls_material, MIB + 1).kwargs())
    assert e.value.code == "too_large"


def test_an_explicit_smaller_cap_still_applies(make_server, tls_material):
    with pytest.raises(TransportError) as e:
        https_post(URL, {}, b"{}", **_client(make_server, tls_material, 5000).kwargs(max_bytes=4096))
    assert e.value.code == "too_large"


def test_the_too_large_message_names_the_setting_and_stays_constant():
    assert TransportError("too_large").message == "response too large; raise max_response_bytes"


def _raising_client():
    def transport(url, headers, body, stop):
        raise TransportError("too_large")
    cfg = McpConfig(servers=[McpServerConfig(name="g", url=URL)], allowed_tools=["g.x"])
    return McpClient(cfg, transport=transport)


def test_discovery_error_names_the_setting():
    with pytest.raises(McpDiscoveryError) as e:
        _raising_client().discover()
    assert "raise max_response_bytes" in str(e.value)


def test_a_tool_call_error_names_the_setting():
    result = _raising_client().call_tool("g", "x", {})
    assert result.success is False and "raise max_response_bytes" in result.error
