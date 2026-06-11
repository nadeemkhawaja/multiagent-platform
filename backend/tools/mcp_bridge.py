"""Bridge so registered MCP servers are reachable through the tool registry."""
import mcp_client

from .registry import tool


@tool("mcp.call", "Call a tool on a registered MCP server (see /api/mcp for servers).")
async def call_mcp_tool(server: str, tool_name: str, arguments: dict = None) -> dict:
    return await mcp_client.call_tool(server, tool_name, arguments)


@tool("mcp.list_tools", "List the tools exposed by a registered MCP server.")
async def list_mcp_tools(server: str) -> list:
    return await mcp_client.list_tools(server)
