"""Tests for the tools package — registry mechanics + built-in tool wiring.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys
import asyncio

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools
from tools import registry


# ── registry mechanics ───────────────────────────────────────────────────────
def test_decorator_registers_and_builds_schema():
    @registry.tool("test.add", "Add two numbers.")
    def add(a: int, b: int, scale: float = 1.0):
        return (a + b) * scale

    spec = registry.get("test.add")
    assert spec["description"] == "Add two numbers."
    schema = spec["input_schema"]
    assert schema["properties"]["a"] == {"type": "integer"}
    assert schema["properties"]["scale"] == {"type": "number"}
    assert schema["required"] == ["a", "b"]   # defaulted params are optional


def test_name_and_description_fall_back_to_fn(monkeypatch):
    @registry.tool()
    def test_docstring_tool(x: str):
        """Uses its docstring."""
        return x

    spec = registry.get("test_docstring_tool")
    assert spec["description"] == "Uses its docstring."


def test_call_sync_tool_runs_in_thread():
    @registry.tool("test.sync")
    def sync_tool(x: int):
        return x * 2

    assert asyncio.run(registry.call("test.sync", {"x": 21})) == 42


def test_call_async_tool():
    @registry.tool("test.async")
    async def async_tool(x: str):
        return f"hello {x}"

    assert asyncio.run(registry.call("test.async", {"x": "world"})) == "hello world"


def test_call_unknown_tool_raises():
    with pytest.raises(registry.ToolError, match="unknown tool"):
        asyncio.run(registry.call("test.nope"))


def test_all_tools_exposes_specs_without_callables():
    names = {t["name"] for t in registry.all_tools()}
    assert {"web.fetch_json", "weather.current", "market.quotes", "mcp.call"} <= names
    for t in registry.all_tools():
        assert set(t.keys()) == {"name", "description", "input_schema"}


# ── web.fetch_json ───────────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_json_success(monkeypatch):
    import httpx

    async def fake_get(self, url):
        return FakeResponse({"ok": True, "url": url})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    out = asyncio.run(tools.web.fetch_json("https://example.com/data"))
    assert out == {"ok": True, "url": "https://example.com/data"}


def test_fetch_json_retries_then_raises(monkeypatch):
    import httpx
    calls = {"n": 0}

    async def boom(self, url):
        calls["n"] += 1
        raise httpx.ConnectError("refused")

    async def no_delay(_seconds):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    monkeypatch.setattr(asyncio, "sleep", no_delay)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(tools.web.fetch_json("https://example.com", retries=2))
    assert calls["n"] == 3   # initial attempt + 2 retries


# ── weather.current ──────────────────────────────────────────────────────────
def test_current_weather_parses_wttr_shape(monkeypatch):
    async def fake_fetch(url, timeout=10.0):
        assert "Murphy+TX" in url
        return {"current_condition": [{
            "temp_F": "88", "FeelsLikeF": "94",
            "weatherDesc": [{"value": "Sunny"}],
            "humidity": "55", "windspeedMiles": "9",
        }]}

    monkeypatch.setattr("tools.weather.fetch_json", fake_fetch)
    out = asyncio.run(tools.weather.current_weather("Murphy+TX"))
    assert out["temp_f"] == 88
    assert out["feels_f"] == 94
    assert out["desc"] == "Sunny"
    assert out["summary"] == "Sunny, 88°F (feels 94°F), humidity 55%, wind 9 mph"
