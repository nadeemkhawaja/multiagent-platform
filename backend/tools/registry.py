"""
Tool registry: one place where the platform's capabilities are declared.

A tool is any function registered with @tool — sync or async. The registry
derives a JSON schema from the signature's type hints, so the same definitions
serve three consumers: agents importing tools directly, the /api/tools
endpoints, and (future) LLM function-calling, which needs exactly this
name/description/input_schema shape.
"""
import asyncio
import inspect

_TOOLS = {}

_PY_TO_JSON = {
    str: "string", int: "integer", float: "number",
    bool: "boolean", list: "array", dict: "object",
}


class ToolError(Exception):
    pass


def tool(name: str = None, description: str = None):
    """Register a function as a callable platform tool."""
    def decorator(fn):
        tool_name = name or fn.__name__
        props, required = {}, []
        for pname, param in inspect.signature(fn).parameters.items():
            props[pname] = {"type": _PY_TO_JSON.get(param.annotation, "string")}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        _TOOLS[tool_name] = {
            "fn": fn,
            "name": tool_name,
            "description": (description or fn.__doc__ or "").strip(),
            "input_schema": {"type": "object", "properties": props, "required": required},
        }
        return fn
    return decorator


def all_tools() -> list:
    """Tool specs (no callables) — the shape LLM function-calling APIs expect."""
    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in _TOOLS.values()
    ]


def get(name: str):
    return _TOOLS.get(name)


async def call(name: str, arguments: dict = None):
    """Invoke a registered tool by name. Sync tools run in a thread so they
    never block the event loop."""
    spec = _TOOLS.get(name)
    if not spec:
        raise ToolError(f"unknown tool '{name}'")
    arguments = arguments or {}
    fn = spec["fn"]
    if inspect.iscoroutinefunction(fn):
        return await fn(**arguments)
    return await asyncio.to_thread(fn, **arguments)
