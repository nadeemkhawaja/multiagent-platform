"""Minimal FastAPI smoke tests for safe, read-only endpoints.
Deliberately avoids the app's `lifespan` (no scheduler/sampler/watchdog
startup) — TestClient(app) without a `with` block does not trigger lifespan
events, so these tests stay fast and side-effect free.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_health_endpoint():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "ollama" in body
    assert "database" in body
    assert "llm" in body


def test_system_resources_endpoint():
    r = client.get("/api/system/resources")
    assert r.status_code == 200
    body = r.json()
    for key in ("cpu_percent", "ram_percent", "disk_percent", "gpu_percent", "alarm", "alarms"):
        assert key in body


def test_system_agents_endpoint_lists_all_agents():
    from orchestrator import AGENT_ORDER
    r = client.get("/api/system/agents")
    assert r.status_code == 200
    body = r.json()
    for aid in AGENT_ORDER:
        assert aid in body


def test_state_endpoint_shape():
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    for key in ("uptimeS", "res", "agents", "events", "demo"):
        assert key in body


def test_agent_data_for_unknown_agent_returns_empty():
    r = client.get("/api/agent/does_not_exist/data")
    assert r.status_code == 200
    assert r.json() == {}


def test_email_preview_for_unknown_agent():
    r = client.get("/api/agent/does_not_exist/email-preview")
    assert r.status_code == 200
    assert "html" in r.json()


def test_get_config_returns_settings_shape():
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    for key in ("recipient", "key_people", "watchlist", "capitol_politicians", "capitol_months"):
        assert key in body


def test_get_demo_mode_returns_core_agents():
    from orchestrator import CORE_AGENTS
    r = client.get("/api/demo/mode")
    assert r.status_code == 200
    body = r.json()
    assert "enabled" in body
    assert body["core_agents"] == CORE_AGENTS


def test_get_schedules_for_all_agents():
    from orchestrator import AGENT_ORDER
    r = client.get("/api/schedules")
    assert r.status_code == 200
    body = r.json()
    for aid in AGENT_ORDER:
        assert aid in body
        assert "config" in body[aid]
        assert "name" in body[aid]


def test_trigger_unknown_agent_returns_error():
    r = client.post("/api/agent/does_not_exist/trigger", json={})
    assert r.status_code == 200
    assert r.json() == {"error": "Agent not found"}


def test_stop_unknown_agent_not_running():
    r = client.post("/api/agent/does_not_exist/stop")
    assert r.status_code == 200
    assert "not running" in r.json()["status"]
