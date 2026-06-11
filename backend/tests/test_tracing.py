"""Tests for tracing.py and its orchestrator/AgentRun integration.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tracing


def test_trace_lifecycle_accumulates_llm_and_stages():
    tracing.start("t_agent")
    tracing.record_llm("t_agent", tokens_in=10, tokens_out=20, ms=150)
    tracing.record_llm("t_agent", tokens_in=5, tokens_out=7, ms=50)
    tracing.record_stage("t_agent", "fetch", 300)
    tracing.record_stage("t_agent", "fetch", 200)

    metrics = tracing.finish("t_agent")
    assert metrics == {"llm_calls": 2, "tokens_in": 15, "tokens_out": 27,
                       "llm_ms": 200, "stages": {"fetch": 500}}
    assert tracing.current("t_agent") is None
    assert tracing.finish("t_agent") is None


def test_record_without_open_trace_is_noop():
    tracing.record_llm("ghost", tokens_in=1, tokens_out=1, ms=1)
    tracing.record_stage("ghost", "fetch", 1)
    assert tracing.current("ghost") is None


def test_stage_context_manager_times_block():
    tracing.start("t_agent2")
    with tracing.stage("t_agent2", "work"):
        pass
    metrics = tracing.finish("t_agent2")
    assert "work" in metrics["stages"]
    assert metrics["stages"]["work"] >= 0


def test_stage_records_even_when_block_raises():
    tracing.start("t_agent3")
    try:
        with tracing.stage("t_agent3", "boom"):
            raise ValueError("x")
    except ValueError:
        pass
    assert "boom" in tracing.finish("t_agent3")["stages"]


def test_orchestrator_persists_metrics_onto_agent_run():
    from orchestrator import Orchestrator
    from database import SessionLocal, AgentRun

    orch = Orchestrator()
    agent = "devdaily"
    orch.update_agent_status(agent, "running")
    rid = orch._open_runs[agent]
    tracing.record_llm(agent, tokens_in=100, tokens_out=40, ms=900)
    tracing.record_stage(agent, "fetch", 1234)
    orch.update_agent_status(agent, "idle")

    db = SessionLocal()
    run = db.query(AgentRun).get(rid)
    db.close()
    assert run.status == "idle"
    assert run.llm_calls == 1
    assert run.tokens_in == 100
    assert run.tokens_out == 40
    assert run.llm_ms == 900
    assert json.loads(run.stages) == {"fetch": 1234}
