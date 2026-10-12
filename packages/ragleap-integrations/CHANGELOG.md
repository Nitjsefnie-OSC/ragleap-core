# Changelog

All notable changes to `ragleap-integrations` are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Verified (after 0.1.0)

- Live check of the MODERN 2026-07-28 path on 2026-10-12, using the published
  0.1.0 wheel in a clean virtual environment (Python 3.10.12) against two
  public Google Cloud MCP endpoints (developerknowledge.googleapis.com/mcp and
  pubsub.googleapis.com/mcp). Read-only: tools/list only, no credentials, no
  tools/call. The server accepted the modern request (MCP-Protocol-Version,
  Mcp-Method and per-request _meta), the client recorded the modern era, the
  reply was plain application/json (non-stream), and the client discovered 3
  tools with their input schemas from one server.

### Observed

- A 15-tool server sent a 359,293-byte tools/list reply, above the default
  max_response_bytes (256 KiB): discovery failed with "response too large";
  with the limit raised to 8 MiB it succeeded on the modern path, and two tools
  were skipped with a stated reason (inputSchema larger than max_schema_chars,
  10,000 characters), as designed.
- Both servers answered an unsupported protocol version with HTTP 400 and
  JSON-RPC -32600 "Unsupported protocol version" and no supported-version list,
  and neither implements server/discover (-32601). This client never calls
  server/discover. A 400 whose JSON-RPC code is outside the recognized modern
  set is still read as a legacy server (behaviour unchanged).

### Not verified

- Modern-path tools/call, x-mcp-header mirroring, bearer-token authentication,
  pagination (neither server paginated), and where a -32022 error carries its
  supported-version list (not observed; the live servers returned -32600).

## [0.1.0] - 2026-10-06

Correction: the copy of this file inside the published 0.1.0 wheel and sdist says 2026-10-05. The files reached PyPI on 2026-10-06 (UTC), which is the real release date. PyPI files cannot be edited, so this entry is the correction. The live check described below really was on 2026-10-05.

### Added

- An MCP client over Streamable HTTP that returns `ragleap_tools.Tool`
  objects (`McpConfig`, `McpServerConfig`, `McpToolSpec`, `McpClient`,
  `make_mcp_tools`). Owner-configured servers and an exact `server.tool`
  allowlist; nothing is read from the environment; tools are discovered once
  (a snapshot) or supplied by the owner as specs, in which case nothing is
  sent over the network at setup.
- Modern (2026-07-28) requests with `Mcp-Method`, `Mcp-Name` and
  `Mcp-Param-*` headers (Base64 sentinel encoding where required) and
  `params._meta`; detection of legacy servers per the specification's
  backward-compatibility rules, with a legacy `initialize` fallback for
  2025-06-18 only.
- A bounded HTTPS transport using only the standard library: public-address
  check with the connection pinned to the resolved IP, TLS verified against the
  hostname, no redirects, a response-size cap, constant error messages, and a
  wall-clock deadline enforced by a watchdog (see
  `docs/design/mcp-client.md` for the slow-drip experiment behind it).

### Fixed

- Found by the live check, before release: a legacy server that rejects the
  modern request with its own JSON-RPC error (DeepWiki answered HTTP 400 and
  `-32600`) was reported as an error instead of triggering the legacy
  fallback. Only `-32020`, `-32021` and `-32022` are treated as recognized
  modern errors now, and a failed fallback still reports the first reply's
  code.

### Verified

- 201 tests, including the real-TLS transport tests described in the README.
- Live-checked on 2026-10-05 against DeepWiki's public MCP server (legacy path;
  see the README's Verification status for exactly what that covers).

### Not verified

- The modern 2026-07-28 path against a real server, `x-mcp-header`
  mirroring, the location of a `-32022` error's supported-version list,
  bearer-token authentication, plain JSON responses and pagination.

### Known limitations

- On a legacy server every call performs a full `initialize` handshake and
  never closes the session. `HeaderMismatch` is not retried. Only text
  content is returned. Server-supplied text (descriptions, schemas, results)
  is untrusted and not screened for prompt injection.
