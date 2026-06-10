"""Tests for mcp_client.py — server registry + tool-call plumbing.
MCP sessions are faked; no server subprocess is spawned.
Run from backend:  python -m pytest -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import mcp_client


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point database.py's engine/SessionLocal at a fresh temp SQLite file."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", SessionLocal)
    return database


class FakeSession:
    """Stands in for an initialized mcp.ClientSession."""
    async def list_tools(self):
        return SimpleNamespace(tools=[
            SimpleNamespace(name="search_emails", description="Search Gmail",
                            inputSchema={"type": "object"}),
            SimpleNamespace(name="send_email", description=None, inputSchema=None),
        ])

    async def call_tool(self, tool, arguments):
        self.called_with = (tool, arguments)
        return SimpleNamespace(
            content=[SimpleNamespace(text="result line 1"),
                     SimpleNamespace(text=None),
                     SimpleNamespace(text="result line 2")],
            isError=False,
        )


@pytest.fixture
def fake_session(monkeypatch):
    session = FakeSession()

    async def _with_session(name, fn, timeout=mcp_client.DEFAULT_TIMEOUT):
        mcp_client._server_params(name)  # keep config/enabled validation in the path
        return await fn(session)

    monkeypatch.setattr(mcp_client, "_with_session", _with_session)
    return session


# ── Server registry ──────────────────────────────────────────────────────────
def test_set_get_remove_server_roundtrip(db):
    mcp_client.set_server("gmail", "npx", ["-y", "server-gmail"], {"TOKEN": "x"})
    servers = mcp_client.get_servers()
    assert servers["gmail"]["command"] == "npx"
    assert servers["gmail"]["args"] == ["-y", "server-gmail"]
    assert servers["gmail"]["enabled"] is True

    assert mcp_client.remove_server("gmail") is True
    assert mcp_client.get_servers() == {}
    assert mcp_client.remove_server("gmail") is False


def test_set_remote_server_with_url(db):
    mcp_client.set_server("zapier", url="https://mcp.zapier.com/api/mcp/x",
                          headers={"Authorization": "Bearer secret"})
    cfg = mcp_client.get_servers()["zapier"]
    assert cfg["url"] == "https://mcp.zapier.com/api/mcp/x"
    assert cfg["headers"] == {"Authorization": "Bearer secret"}
    assert "command" not in cfg
    assert mcp_client._server_params("zapier") == cfg


def test_set_server_requires_command_or_url(db):
    with pytest.raises(mcp_client.MCPError, match="command .* or a url"):
        mcp_client.set_server("broken")


def test_get_servers_empty_and_malformed_config(db):
    assert mcp_client.get_servers() == {}
    database.set_config(mcp_client.CONFIG_KEY, "not-a-dict")
    assert mcp_client.get_servers() == {}


def test_server_params_unknown_server_raises(db):
    with pytest.raises(mcp_client.MCPError, match="not configured"):
        mcp_client._server_params("ghost")


def test_server_params_disabled_server_raises(db):
    mcp_client.set_server("gmail", "npx", enabled=False)
    with pytest.raises(mcp_client.MCPError, match="disabled"):
        mcp_client._server_params("gmail")


# ── Tool operations (faked session) ──────────────────────────────────────────
def test_list_tools_normalizes_fields(db, fake_session):
    mcp_client.set_server("gmail", "npx")
    tools = asyncio.run(mcp_client.list_tools("gmail"))
    assert tools[0] == {"name": "search_emails", "description": "Search Gmail",
                        "input_schema": {"type": "object"}}
    assert tools[1] == {"name": "send_email", "description": "", "input_schema": {}}


def test_call_tool_joins_text_content(db, fake_session):
    mcp_client.set_server("gmail", "npx")
    out = asyncio.run(mcp_client.call_tool("gmail", "search_emails", {"q": "alerts"}))
    assert out == {"text": "result line 1\nresult line 2", "is_error": False}
    assert fake_session.called_with == ("search_emails", {"q": "alerts"})


def test_call_tool_unconfigured_server_raises(db, fake_session):
    with pytest.raises(mcp_client.MCPError):
        asyncio.run(mcp_client.call_tool("ghost", "tool"))


def test_ping_reachable_and_unreachable(db, fake_session):
    mcp_client.set_server("gmail", "npx")
    assert asyncio.run(mcp_client.ping("gmail")) == {"reachable": True, "tools": 2}

    out = asyncio.run(mcp_client.ping("ghost"))
    assert out["reachable"] is False
    assert "not configured" in out["error"]


# ── Degraded mode (mcp package absent) ───────────────────────────────────────
def test_call_without_mcp_package_raises_clear_error(db, monkeypatch):
    monkeypatch.setattr(mcp_client, "MCP_AVAILABLE", False)
    mcp_client.set_server("gmail", "npx")
    with pytest.raises(mcp_client.MCPError, match="not installed"):
        asyncio.run(mcp_client.list_tools("gmail"))
