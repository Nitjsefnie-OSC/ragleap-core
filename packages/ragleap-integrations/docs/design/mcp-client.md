# MCP client - allowlisted MCP tools as ragleap-tools Tools

## Problem

core/mcp_client.py (in the app) already calls allowlisted tools on
remote MCP servers, but it is coupled to the app: configuration is read
from environment variables, it depends on requests and
core.action_senders, and it makes three POSTs per call (initialize,
notifications/initialized, tools/call). It never calls tools/list, so it
has no tool schema (the caller passes arguments as a JSON string), it
keeps text content only, and it pins protocol revision 2025-06-18. Its
tests use an in-process fake server, not a real one.

This package extracts and hardens that client and returns
ragleap_tools.Tool objects, so MCP tools and native tools share one shape.

## Scope (v0.1.0)

MCP client over Streamable HTTP only. Deliberately excluded:
- stdio transport: it launches a local subprocess, i.e. code execution.
- HTTP+SSE: deprecated since 2025-03-26.
- Sampling, elicitation and roots (InputRequiredResult): v0.1.0 returns a
  clear "unsupported" ToolResult error.
- Resources, prompts, subscriptions/listen, OAuth.
- Code execution, HTTP fetch, database/business-system connectors and the
  agent loop: each is a separate security design pass or belongs to
  ragleap-agents.

## Design

Explicit configuration, no environment-variable fallback (the same BYOK
rule as ragleap-tools); the app builds the config from its env vars:
- McpServerConfig(name, url, token=None): static bearer token only.
- McpConfig(servers, allowed_tools): exact "server.tool" allowlist. The
  model supplies only arguments; it never chooses a URL, command or token.

make_mcp_tools(config) returns one ragleap_tools.Tool per allowlisted
tool, two ways to get the schema:
1. Owner-supplied specs (no network, safest): the owner states each
   tool's description and parameters.
2. Discovery: tools/list, restricted to allowlisted names, snapshotted
   once and not refreshed per call. A server that changes a description
   later has no effect. Descriptions are length-capped. Tool definitions
   with invalid x-mcp-header annotations are excluded with a warning, as
   the spec requires.

## Protocol

Two code paths, chosen per the spec's Backward Compatibility section:
- Modern (2026-07-28): each request is its own POST with Accept (JSON and
  event-stream), MCP-Protocol-Version, Mcp-Method, and Mcp-Name for
  tools/call, plus protocolVersion, clientInfo and clientCapabilities in
  _meta. No initialize, no session. x-mcp-header parameters are mirrored
  into Mcp-Param-* headers. Both application/json and text/event-stream
  responses are handled.
- Legacy (2025-06-18): initialize, notifications/initialized, then
  tools/call, with Mcp-Session-Id when the server issues one. Ported from
  core/mcp_client.py.
Try modern first, declaring the newest modern revision this package
implements. A modern server that does not support it answers with
UnsupportedProtocolVersionError listing the versions it does support (the
spec's example is 2026-07-28 and 2025-11-25); retry once with a mutually
supported version, otherwise report an error. server/discover is optional
and is not used in v0.1.0. A 4xx without a recognized modern error body
means a legacy server: fall back to legacy. The recognized modern errors are
-32020 (HeaderMismatch), -32021 (MissingRequiredClientCapability) and -32022
(UnsupportedProtocolVersion); on a 400 they are reported, never treated as
legacy (a -32022 whose supported list includes an allowlisted legacy version
continues with the legacy handshake). Any other JSON-RPC error on a 400 - a
live DeepWiki server answered -32600 - is a legacy server's own rejection and
falls back too. A fallback that then fails reports the legacy failure together
with the first reply's code, so a modern server that answered 400 and -32602
for bad arguments is not hidden. (The code numbers come from an SDK issue
summarising the spec's rule, a secondary source; the principle is in the spec.)

Legacy revisions are an explicit allowlist, not "whatever the server
answers": the app client accepts the version the server returns without
checking it, and this package will not. Which legacy revisions are
supported (2025-06-18 as in the app client, 2025-11-25, or both) is
decided after reading those revisions' transport pages.

## Network safety

https only, public addresses only (IPv4-mapped IPv6 addresses unwrapped
before the check); resolve DNS once and connect to that IP, then wrap the
socket in TLS (minimum 1.2) verified against the hostname and hand it to
http.client, the technique used in core/page_fetch.py; no redirects;
Accept-Encoding: identity; a response-size cap; constant error messages
(no library exception text in results); the token is sent only to its
configured URL and never logged.

Wall-clock deadline. core/page_fetch.py checks its deadline only between
chunks. A test on 2026-10-03 (plain HTTP on loopback) showed that a server
sending one byte every 0.2 s kept resp.read(8192) blocked for 80 s against
a 3 s deadline, because every byte arrived inside the per-operation
timeout. Two fixes were tried: read1() bounds the body phase (stopped at
3.0 s); a watchdog timer that shuts the socket down at the deadline bounds
both the header and the body phase (3.0 s each) but the read then looks
like a normal end of response, so the watchdog must set a flag and the
caller must raise a deadline error when it is set. This package uses the
watchdog plus read1(), started before the TLS handshake. Not yet tested
over TLS; that is a test with a local TLS server.

## Dependencies

ragleap-tools (for Tool and ToolResult) and otherwise the standard library
(http.client, ssl, json). No requests.

## Results and errors

Text content parts only; other content types are dropped and the result
says so. isError maps to ToolResult(success=False). Result length is
capped. Every failure (allowlist refusal, bad URL, network error, non-2xx,
malformed JSON-RPC, InputRequiredResult) is a ToolResult, never an
exception.

## Untrusted content

Tool descriptions, input schemas and results are text controlled by the
MCP server and flow into the model's context. This is a prompt-injection
surface and is not screened. Mitigations here are structural (the
allowlist, the snapshot, description caps, optional owner-supplied
specs), not content filtering.

## Testing

- One injectable transport function carries all HTTP, so tests exercise the
  real header and body construction without a network (the ragleap-tools
  convention of mocking at the lowest seam). The address check takes an
  injectable resolver.
- The address check gets its own tests, because the app's tests replace it
  with True: private, loopback, link-local including the cloud metadata
  address, multicast, IPv4-mapped IPv6, and a host with one public and one
  private address (must be refused).
- Ported behavior: allowlist parsing and refusal, no redirects, timeouts,
  size cap, session handling on the legacy path, isError, text-only content.
- Deadline: a slow-drip server (one byte per interval, under the
  per-operation timeout, in both the header and the body phase) must
  produce a deadline error, never a truncated success.
- Modern path: MCP-Protocol-Version, Mcp-Method and Mcp-Name headers,
  _meta contents, x-mcp-header mirroring including the Base64 sentinel
  encoding, rejection of invalid annotations, UnsupportedProtocolVersionError
  retry, and the 400-without-modern-error fallback.

## Packaging and CI

- packages/ragleap-integrations, hatchling build, src/ragleap_integrations,
  dependencies = ["ragleap-tools>=0.4.0"], the same layout as ragleap-tools.
- A ragleap-integrations-tests CI job on a Python 3.10/3.11/3.12 matrix
  (ragleap-vectorstores already runs 3.10 and 3.12). ragleap-tools' own CI
  runs 3.11 only although its classifiers list 3.10 to 3.12: a small
  separate follow-up.
- release.yml gets one new job, one dispatch option and one tag pattern.
  It is shared with other packages' jobs; nothing else in it changes.
- First-release prerequisite: the PyPI and TestPyPI projects do not exist
  yet (the name was free on 2026-10-03). The account owner must add a
  pending trusted publisher on each (repository ragleap/ragleap-core,
  workflow release.yml, environment pypi or testpypi).

## Verification status

Checked against the current public specification (the 2026-07-28
Streamable HTTP page, changelog and versioning page): per-request headers
and _meta, no sessions, no negotiation handshake, UnsupportedProtocolVersionError
with a supported list, optional server/discover, x-mcp-header mirroring,
backward-compatibility detection, and InputRequiredResult for
server-to-client interactions. Not yet checked: the tools page (tools/list
and inputSchema field names, pagination), the InputRequiredResult shape,
and the 2025-06-18 and 2025-11-25 transport pages.
Live check (2026-10-05): the package's real transport and client were run against
DeepWiki's public MCP server (https://mcp.deepwiki.com/mcp, no authentication)
with every exchange traced. The server answered the modern request with HTTP
400 and JSON-RPC -32600 (an unsupported-protocol-version message), which
exposed a bug in the first version of the detection rule (any JSON-RPC error
was treated as a modern server). After the fix the client fell back to the
legacy handshake, the server agreed to 2025-06-18, notifications/initialized
returned 202, tools/list and tools/call succeeded over event-stream responses
(CRLF framing), and read_wiki_structure returned a repository's documentation
structure. Verified live: the fallback decision, the legacy handshake,
event-stream parsing, discovery and the pinned TLS transport. Not verified
live: the modern 2026-07-28 path, x-mcp-header mirroring, where a -32022 error
carries its supported-version list, bearer-token authentication, plain JSON
responses and pagination. The existing app client had only ever run against a
fake in-process server.

Live check 2 (2026-10-12): the published 0.1.0 wheel, installed in a clean
virtual environment on Python 3.10.12, was run against two public Google
Cloud MCP endpoints (developerknowledge.googleapis.com/mcp and
pubsub.googleapis.com/mcp), read-only: tools/list only, no credentials, no
tools/call. Verified live: the modern request (MCP-Protocol-Version,
Mcp-Method and per-request _meta) is accepted by a real server; the client
records the modern era; replies arrive as plain application/json; tools/list
results and inputSchema are parsed (3 tools from one server). Findings:
(a) a 15-tool server replied with 359,293 bytes, above the default 256 KiB
response cap, so discovery failed ("response too large") until
max_response_bytes was raised; (b) two of its tools were skipped because their
input schemas exceed max_schema_chars (10,000), as designed; (c) both servers
answered an unsupported protocol version with HTTP 400 and -32600
"Unsupported protocol version" and no supported-version list, so the reading
above of -32600 as a legacy server's own rejection is not exclusive:
modern-capable servers use it too, and the client still falls back to the
legacy handshake in that case; (d) neither server implements server/discover
(-32601), which this client never calls. Still not verified live: modern
tools/call, x-mcp-header mirroring, bearer-token authentication, pagination
(neither server paginated), and where a -32022 error carries its
supported-version list (not observed).

Live check 3 (2026-10-16): the published 0.1.1 wheel (sdist and wheel
hashes matched PyPI's records; the changed source files were byte-identical
to main), installed in a clean virtual environment on Python 3.10.12, was
run against pubsub.googleapis.com/mcp, read-only: tools/list only, no
credentials, no tools/call, no limit overrides. Verified live: with the
default limits, the 359,293-byte tools/list reply of the 15-tool server is
accepted (0.1.0 refused it at the old 256 KiB default) and the client
records the modern era. Measured: four of the 15 tools have an inputSchema
above max_schema_chars (10,000): update_subscription 33,502 characters,
create_subscription 32,989, update_topic 23,537 and create_topic 22,835;
the other eleven are 2,631 or smaller. With the first three tools
allowlisted, discovery registered one and skipped create_topic and
update_topic (inputSchema too large), as designed. As an experiment only,
max_schema_chars=40000 (an override, not the default) registered all 15
tools and skipped none. The default is unchanged; whether to trim or
summarize very large schemas is an open design question. server/discover
again answered -32601 (this client never calls it) and an unsupported
version again answered HTTP 400 with -32600. Not verified: that schemas of
this size are usable by a model, and the items listed under live check 2.

## Open decisions (resolved when v0.1.0 was built)

Resolved: (1) both paths, with legacy limited to 2025-06-18; (2) DeepWiki's
public server was used for a live check, which exercises the legacy path only;
(3) not part of v0.1.0; (4) tools are exposed as <server>__<tool>, sanitized
and cut to 64 characters, and a collision is a setup error; (5) an explicit
port in a configured URL is allowed. The list below is kept as drafted.


1. Modern plus legacy, or modern only.
2. A public HTTPS MCP server for a live check; otherwise the package ships
   labelled unverified.
3. Whether core/ later imports this package instead of its own client
   (not part of v0.1.0).
4. Tool naming: function-calling APIs restrict name characters, so the
   "server.tool" allowlist key is not the exposed Tool name.
5. Ports: core/page_fetch.py allows 443 only because the model chooses its
   URL. Here the owner chooses the URL, so an explicit port in a configured
   URL could be allowed (still pinned and public-only). Proposed default:
   allow it.
