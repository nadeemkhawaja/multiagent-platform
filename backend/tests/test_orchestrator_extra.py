"""Additional Orchestrator coverage: dashboard state shape, demo mode toggle,
spike/crash behavior, and resource alarm thresholds.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_get_state_shape():
    from orchestrator import Orchestrator, AGENT_ORDER
    orch = Orchestrator()
    state = orch.get_state()

    for key in ("uptimeS", "res", "threads", "agents", "llm", "events", "alarm", "demo"):
        assert key in state

    assert len(state["agents"]) == len(AGENT_ORDER)
    for a in state["agents"]:
        for key in ("id", "n", "glyph", "desc", "color", "status"):
            assert key in a

    for k in ("cpu", "ram", "disk", "gpu", "net"):
        assert "v" in state["res"][k]
        assert "hist" in state["res"][k]


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


def test_spike_overrides_next_sample_and_raises_alarm():
    from orchestrator import Orchestrator
    orch = Orchestrator()
    info = orch.spike("cpu")
    assert info["resource"] == "cpu"
    assert 91 <= info["value"] <= 97

    sample = orch._take_sample()
    assert sample["cpu"] == info["value"]

    res = orch.get_system_resources()
    assert res["alarm"] is True
    assert any(a["resource"] == "CPU" for a in res["alarms"])


def test_get_system_resources_no_alarm_under_threshold():
    from orchestrator import Orchestrator
    orch = Orchestrator()
    orch._last = {"cpu": 10.0, "ram": 20.0, "disk": 30.0, "gpu": 40.0, "net": 1.0, "threads": 5}
    res = orch.get_system_resources()
    assert res["alarm"] is False
    assert res["alarms"] == []


def test_get_system_resources_alarm_at_threshold():
    from orchestrator import Orchestrator
    orch = Orchestrator()
    orch._last = {"cpu": 95.0, "ram": 20.0, "disk": 30.0, "gpu": 40.0, "net": 1.0, "threads": 5}
    res = orch.get_system_resources()
    assert res["alarm"] is True
    assert res["alarms"][0]["resource"] == "CPU"
    assert "Throttle" in res["alarms"][0]["suggestion"]


def test_crash_marks_agent_error_and_schedules_recovery():
    from orchestrator import Orchestrator
    orch = Orchestrator()
    agent = "options_flow"
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
