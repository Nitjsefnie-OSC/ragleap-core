# ragleap-integrations

An MCP (Model Context Protocol) client that turns allowlisted tools on remote
MCP servers into `ragleap_tools.Tool` objects, so MCP tools and native tools
share one shape.

```bash
pip install ragleap-integrations
```

## What this is (and isn't)

v0.1.1 is an MCP client over **Streamable HTTP only**. The *owner* configures
servers and an exact `server.tool` allowlist; the model only supplies a tool's
JSON arguments, never a URL, a token or a tool outside the allowlist. It does
not own a tool-calling loop (that is `ragleap-agents`' job).

Not supported in this version: stdio (it launches a subprocess), the
deprecated HTTP+SSE transport, sampling/elicitation/roots (a server asking
for client input gets a clear "unsupported" result), resources, prompts,
subscriptions and OAuth. Connectors, code execution and HTTP fetch are
deliberately not here: each needs its own security design pass.

## Quickstart

```python
from ragleap_integrations import McpConfig, McpServerConfig, make_mcp_tools

config = McpConfig(
    servers=[McpServerConfig("deepwiki", "https://mcp.deepwiki.com/mcp")],  # token="..." if a server needs one
    allowed_tools=["deepwiki.read_wiki_structure"],
)
tools = make_mcp_tools(config)  # discovers the allowlisted tools once (tools/list)

openai_tools = [t.to_openai_schema() for t in tools]  # or t.to_gemini_schema()
result = tools[0].call(repoName="sqlite/sqlite")
print(result.success, result.result)  # True {"text": "..."}
```

Nothing is read from the environment: your application builds the config.
Tools are exposed as `<server>__<tool>` (characters outside letters, digits,
`_` and `-` become `_`, at most 64 characters).

To keep server-controlled text out of the model's context entirely, give the
descriptions and schemas yourself; nothing is sent over the network at setup:

```python
from ragleap_integrations import McpToolSpec

spec = McpToolSpec(
    server="deepwiki", name="read_wiki_structure",
    description="List the documentation topics of a GitHub repository.",
    parameters={"type": "object", "properties": {"repoName": {"type": "string"}}, "required": ["repoName"]},
)
tools = make_mcp_tools(config, specs=[spec])
```

## Trust model

- Everything a server says is untrusted text: tool descriptions, input
  schemas and results flow into a model's context. This package does **not**
  screen them for prompt injection. The structural limits are the allowlist,
  a snapshot of the tool list taken once at setup (a server that changes a
  description later has no effect), length caps, and optional owner-supplied
  specs.
- Server-supplied error text is never put in a result; failures carry a
  constant message plus, at most, an HTTP status or a JSON-RPC error code.
- Network access is bounded in code: https only, no credentials in the URL,
  no IP-literal hosts, DNS resolved once with every address required to be
  public (so DNS rebinding cannot swap in an internal address), the
  connection pinned to that IP with TLS (minimum 1.2) verified against the
  hostname, no redirects, no compressed responses, a response-size cap, and a
  wall-clock deadline that also covers the TLS handshake and the headers.
- A bearer token, if configured, is sent only to its own server URL and is
  never logged.

## Protocol

The current revision (2026-07-28) is tried first: every request is its own
POST carrying `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` headers and
the version, client info and capabilities in `params._meta`; parameters marked
`x-mcp-header` in a tool's schema are mirrored into `Mcp-Param-*` headers.
A 4xx without a recognized modern error (`-32020`, `-32021`, `-32022`)
identifies a legacy server, and the client then uses the legacy `initialize`
handshake with protocol version 2025-06-18 only (an explicit allowlist, not
"whatever the server answers"). The era found is remembered per server.

## Limits and defaults

| Setting | Default |
|---|---|
| Whole-call deadline (`total_timeout`) | 30 s |
| Per-operation socket timeout (`op_timeout`) | 10 s |
| Response size (`max_response_bytes`) | 1 MiB (256 KiB in 0.1.0) |
| Result text (`max_result_chars`) | 4000 characters |
| Tool description (`max_description_chars`) | 500 characters |
| Input schema (`max_schema_chars`) | 10000 characters (larger: tool skipped) |

## Known limitations

- On a legacy server every tool call performs a full `initialize` handshake
  (three POSTs) and never closes the session.
- A `HeaderMismatch` error is reported, not retried after re-reading the
  tool list.
- Only text content is returned; other content types are counted and omitted.
- `ragleap_tools.Tool.call` in ragleap-tools 0.4.0 cannot take an argument
  literally named `self`.
- Not safe to share one client between threads while calls are running.
- A server whose tool list is larger than the response cap (1 MiB by default;
  256 KiB in 0.1.0, which a real 15-tool server's 359 KB list exceeded) makes
  discovery fail with "response too large; raise max_response_bytes" until
  the limit is raised.

## Verification status

- 208 tests, including a real local TLS server with a throwaway certificate
  for the transport (hostname verification, IP pinning, size cap, truncated
  bodies, and the deadline against slow-drip bodies, slow-drip headers and a
  stalled handshake).
- **Live-checked on 2026-10-05** against DeepWiki's public MCP server
  (`https://mcp.deepwiki.com/mcp`, no authentication): the server answered
  the modern request with HTTP 400 and a JSON-RPC `-32600` error, the client
  fell back to the legacy handshake, negotiated 2025-06-18, listed tools and
  read a repository's documentation structure. This verifies the legacy path,
  the fallback decision, event-stream responses and the pinned TLS transport
  against a real server.
- **Live-checked on 2026-10-12** against two public Google Cloud MCP
  endpoints (`https://developerknowledge.googleapis.com/mcp` and
  `https://pubsub.googleapis.com/mcp`) on the modern 2026-07-28 path, using
  the published 0.1.0 wheel in a clean virtual environment (Python 3.10.12).
  Read-only: `tools/list` only, no credentials, no `tools/call`. The server
  accepted the modern request, replied with plain `application/json`
  (non-stream), and the client discovered the tools and read their input
  schemas (3 tools from one server). A second server's tool list was 359,293
  bytes, above the default `max_response_bytes` (256 KiB): discovery failed
  with "response too large" until the limit was raised, and two of its tools
  were skipped because their input schemas exceed `max_schema_chars`. Both
  servers answered an unsupported protocol version with HTTP 400 and
  `-32600` and no supported-version list; neither implements `server/discover`
  (this client never calls it).
- **Live-checked on 2026-10-16** against `https://pubsub.googleapis.com/mcp`
  using the published 0.1.1 wheel in a clean virtual environment (Python
  3.10.12), with no limit overrides. Read-only: `tools/list` only, no
  credentials, no `tools/call`. The 359,293-byte list of the 15-tool server,
  which 0.1.0 refused at its 256 KiB default, is now accepted with the
  default `max_response_bytes` (1 MiB), and the client recorded the modern
  era. Four of the 15 tools have an input schema above the default
  `max_schema_chars` (10,000): `update_subscription` (33,502 characters),
  `create_subscription` (32,989), `update_topic` (23,537) and `create_topic`
  (22,835); the other eleven are 2,631 or smaller. With the first three tools
  allowlisted, discovery registered one and skipped `create_topic` and
  `update_topic`, as designed. As an experiment only, `max_schema_chars=40000`
  (an override; the default is unchanged) registered all 15 tools. Not
  verified: that schemas of this size are usable by a model.
- **Not live-verified:** modern-path `tools/call`, `x-mcp-header` mirroring,
  bearer-token authentication, pagination (neither server paginated) and
  where a `-32022` error carries its supported-version list (not observed:
  the live servers returned `-32600`). They follow the public specification
  and are covered by tests against fakes only; treat them as best-effort
  until confirmed live.

## License

MIT
