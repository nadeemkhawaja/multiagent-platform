"""Additional Orchestrator coverage: dashboard state shape, demo mode toggle,
and crash/recovery behavior.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_get_state_shape():
    from orchestrator import Orchestrator, AGENT_ORDER
    orch = Orchestrator()
    state = orch.get_state()

    for key in ("uptimeS", "agents", "llm", "events", "demo"):
        assert key in state

    assert len(state["agents"]) == len(AGENT_ORDER)
    for a in state["agents"]:
        for key in ("id", "n", "glyph", "desc", "color", "status"):
            assert key in a


def test_set_demo_mode_toggles_and_persists(monkeypatch):
    from orchestrator import Orchestrator
    orch = Orchestrator()
    saved = {}
    monkeypatch.setattr("orchestrator.set_config", lambda k, v: saved.update({k: v}))

    assert orch.set_demo_mode(True) is True
    assert orch.demo_mode is True
    assert saved["demo_mode"] is True

    assert orch.set_demo_mode(False) is False
    assert orch.demo_mode is False
    assert saved["demo_mode"] is False


def test_crash_marks_agent_error_and_schedules_recovery():
    from orchestrator import Orchestrator
    orch = Orchestrator()
    agent = "technologia"
    orch.agents_status[agent]["status"] = "idle"

    result = orch.crash(agent)
    assert result["status"] == f"Crashed {agent}"
    assert orch.agents_status[agent]["status"] == "error"
    assert orch.agents_status[agent]["error"] == "Demo crash (exit 1)"
    assert agent in orch._demo_crashed


def test_crash_unknown_agent_returns_error():
    from orchestrator import Orchestrator
    orch = Orchestrator()
    assert orch.crash("not_a_real_agent") == {"error": "Agent not found"}
