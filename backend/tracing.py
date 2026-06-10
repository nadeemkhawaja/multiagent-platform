"""
Per-run agent telemetry.

The orchestrator opens a trace when an agent's run starts and folds the
collected metrics into the run's AgentRun row when it finishes. While the run
is open, the LLM client records token usage automatically and agents can time
named stages:

    with tracing.stage("wallstreet_wolf", "fetch"):
        market_data = await fetch_market_data()

Everything is in-process and failure-proof: recording against an agent with no
open trace is a silent no-op, so library code can always call record_* without
caring whether it's inside a scheduled run.
"""
import time
from contextlib import contextmanager

_active = {}


def start(agent_id: str):
    _active[agent_id] = {
        "llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "llm_ms": 0,
        "stages": {},
    }


def record_llm(agent_id: str, tokens_in: int = 0, tokens_out: int = 0, ms: int = 0):
    trace = _active.get(agent_id)
    if not trace:
        return
    trace["llm_calls"] += 1
    trace["tokens_in"] += int(tokens_in or 0)
    trace["tokens_out"] += int(tokens_out or 0)
    trace["llm_ms"] += int(ms or 0)


def record_stage(agent_id: str, name: str, ms: int):
    trace = _active.get(agent_id)
    if not trace:
        return
    trace["stages"][name] = trace["stages"].get(name, 0) + int(ms or 0)


@contextmanager
def stage(agent_id: str, name: str):
    """Time a block and record it as a named stage of the current run."""
    t0 = time.monotonic()
    try:
        yield
    finally:
        record_stage(agent_id, name, int((time.monotonic() - t0) * 1000))


def current(agent_id: str):
    """Peek at the open trace (or None). For dashboards/tests."""
    return _active.get(agent_id)


def finish(agent_id: str):
    """Close the trace and return its metrics, or None if none was open."""
    return _active.pop(agent_id, None)
