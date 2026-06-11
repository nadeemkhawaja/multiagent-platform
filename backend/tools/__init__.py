"""
Platform tool registry. Importing this package registers all built-in tools;
see registry.py for how tools are declared and called.
"""
from .registry import tool, all_tools, get, call, ToolError

# Importing the modules below registers their tools.
from . import web        # noqa: F401  web.fetch_json
from . import weather    # noqa: F401  weather.current
from . import market     # noqa: F401  market.quotes
from . import mcp_bridge # noqa: F401  mcp.call / mcp.list_tools
