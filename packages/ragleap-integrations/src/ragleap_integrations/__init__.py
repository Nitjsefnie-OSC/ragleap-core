"""
ragleap_integrations - connectors that return ragleap_tools.Tool objects.

v0.1.0: an MCP client over Streamable HTTP (see docs/design/mcp-client.md).

v0.1.1: the default response-size cap is 1 MiB (it was 256 KiB, which a real
15-tool server exceeded), and the "response too large" error names the
max_response_bytes setting.
"""

__version__ = "0.1.1"

from ragleap_integrations.mcp import (
    Discovery,
    McpClient,
    McpConfig,
    McpConfigError,
    McpDiscoveryError,
    McpServerConfig,
    McpToolSpec,
    make_mcp_tools,
)

__all__ = [
    "__version__",
    "Discovery",
    "McpClient",
    "McpConfig",
    "McpConfigError",
    "McpDiscoveryError",
    "McpServerConfig",
    "McpToolSpec",
    "make_mcp_tools",
]
