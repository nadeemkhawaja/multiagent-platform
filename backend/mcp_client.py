"""
MCP (Model Context Protocol) client layer.

Lets agents call tools on any MCP server — Gmail, GitHub, market data, or any
of the thousands of community servers — through one protocol instead of
hand-rolled API integrations.

Servers are registered in the config table under "mcp_servers". Two kinds:

    local (stdio subprocess — data never leaves the machine):
      {"gmail": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-gmail"],
                 "env": {}, "enabled": true}}

    remote (streamable HTTP — hosted servers like Zapier MCP):
      {"zapier": {"url": "https://mcp.zapier.com/api/mcp/...",
                  "headers": {"Authorization": "Bearer ..."}, "enabled": true}}

A connection is opened per call rather than held open: scheduled agents call
tools at most every few minutes, and per-call sessions mean a crashed or
wedged server can never poison a shared connection.

The `mcp` package is optional — without it the platform runs normally and
the API reports MCP as unavailable.
"""
import asyncio

from database import get_config, set_config

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

CONFIG_KEY = "mcp_servers"
DEFAULT_TIMEOUT = 60.0


class MCPError(Exception):
    pass


# ── Server registry (persisted in the config table) ──────────────────────────
def get_servers() -> dict:
    servers = get_config(CONFIG_KEY, {})
    return servers if isinstance(servers, dict) else {}


def set_server(name: str, command: str = None, args: list = None, env: dict = None,
               enabled: bool = True, url: str = None, headers: dict = None) -> dict:
    """Register a local server (command + args) or a remote one (url + headers)."""
    if not command and not url:
        raise MCPError("an MCP server needs either a command (local) or a url (remote)")
    servers = get_servers()
    if url:
        servers[name] = {"url": url, "headers": headers or {}, "enabled": bool(enabled)}
    else:
        servers[name] = {"command": command, "args": args or [],
                         "env": env or {}, "enabled": bool(enabled)}
    set_config(CONFIG_KEY, servers)
    return servers[name]


def remove_server(name: str) -> bool:
    servers = get_servers()
    if name not in servers:
        return False
    del servers[name]
    set_config(CONFIG_KEY, servers)
    return True


def _server_params(name: str) -> dict:
    """Validate that a server is configured and enabled; return its config."""
    cfg = get_servers().get(name)
    if not cfg:
        raise MCPError(f"MCP server '{name}' is not configured")
    if not cfg.get("enabled", True):
        raise MCPError(f"MCP server '{name}' is disabled")
    return cfg


async def _with_session(name: str, fn, timeout: float = DEFAULT_TIMEOUT):
    """Spawn the server, run fn(session) against an initialized session, clean up."""
    if not MCP_AVAILABLE:
        raise MCPError("mcp package not installed — add 'mcp' to requirements and pip install")
    cfg = _server_params(name)

    if cfg.get("url"):
        async def _run():
            async with streamablehttp_client(cfg["url"], headers=cfg.get("headers") or None) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await fn(session)
    else:
        params = StdioServerParameters(
            command=cfg["command"],
            args=cfg.get("args") or [],
            env=cfg.get("env") or None,
        )

        async def _run():
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await fn(session)

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError:
        raise MCPError(f"MCP server '{name}' timed out after {timeout}s")


# ── Operations ────────────────────────────────────────────────────────────────
async def list_tools(name: str, timeout: float = DEFAULT_TIMEOUT) -> list:
    """Tools exposed by a server: [{name, description, input_schema}]."""
    async def _op(session):
        result = await session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema or {},
            }
            for t in result.tools
        ]
    return await _with_session(name, _op, timeout)


async def call_tool(name: str, tool: str, arguments: dict = None,
                    timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Call a tool. Returns {"text": str, "is_error": bool} with all text
    content blocks joined — ready to drop into an LLM prompt."""
    async def _op(session):
        result = await session.call_tool(tool, arguments or {})
        texts = [c.text for c in result.content if getattr(c, "text", None)]
        return {"text": "\n".join(texts), "is_error": bool(result.isError)}
    return await _with_session(name, _op, timeout)


async def ping(name: str, timeout: float = 15.0) -> dict:
    """Quick reachability probe used by the dashboard/API."""
    try:
        tools = await list_tools(name, timeout=timeout)
        return {"reachable": True, "tools": len(tools)}
    except Exception as e:
        return {"reachable": False, "error": str(e)}
