"""Unit tests for pure logic — no network, LLM, or Ollama required.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Compass: pivot math ──────────────────────────────────────────────────────
def test_pivots_classic_formula():
    from agents.agent5_compass import _pivots, _bias
    p = _pivots(110, 90, 100)          # H=110 L=90 C=100
    assert p["piv"] == 100.0
    assert p["r1"] == 110.0            # 2*100 - 90
    assert p["s1"] == 90.0            # 2*100 - 110
    assert p["r2"] == 120.0            # piv + (H-L)
    assert p["s2"] == 80.0            # piv - (H-L)
    assert _bias(105, 100) == "bull"
    assert _bias(95, 100) == "bear"
    assert _bias(100, 100) == "neutral"


def test_headline_sentiment_keywords():
    from agents.agent5_compass import _headline_sentiment
    assert _headline_sentiment("Stocks rally to record high") == "bull"
    assert _headline_sentiment("Markets plunge on rate fears") == "bear"
    assert _headline_sentiment("Treasury yields steady ahead of data") == "neutral"


# ── AI-Times helpers ─────────────────────────────────────────────────────────
def test_iso_duration_and_views():
    from agents.agent1_ai_times import _iso_duration, _human_views
    assert _iso_duration("PT12M4S") == "12:04"
    assert _iso_duration("PT2H41M9S") == "2:41:09"
    assert _human_views(1_240_000) == "1.2M"
    assert _human_views(184_000) == "184K"
    assert _human_views(42) == "42"


# ── Aegis stats ──────────────────────────────────────────────────────────────
def test_aegis_stats():
    from agents.agent6_aegis import _stats
    mentions = [
        {"sent": -80, "risk": "high", "status": "new"},
        {"sent": 20, "risk": "low", "status": "new"},
        {"sent": -10, "risk": "high", "status": "dismissed"},
    ]
    s = _stats(mentions)
    assert s["mentions"] == 3
    assert s["high_risk"] == 1          # dismissed high-risk excluded
    assert s["net_sentiment"] == round((-80 + 20 - 10) / 3)


# ── LLM client: parsing + cache key ──────────────────────────────────────────
def test_strip_think_and_cache_key():
    import llm_client
    assert llm_client.strip_think("<think>noise</think>answer") == "answer"
    k1 = llm_client._cache_key("m", "sys", "p", False)
    k2 = llm_client._cache_key("m", "sys", "p", False)
    k3 = llm_client._cache_key("m", "sys", "p2", False)
    assert k1 == k2 and k1 != k3


def test_llm_semaphore_serializes_concurrent_calls():
    import llm_client

    current = peak = 0

    async def worker():
        nonlocal current, peak
        async with llm_client.llm_semaphore:
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.01)
            current -= 1

    async def run():
        await asyncio.gather(*(worker() for _ in range(6)))

    asyncio.run(run())
    assert peak == 1   # single-permit semaphore: never more than one concurrent holder


def test_generate_completion_never_raises_on_connection_failure(monkeypatch):
    import llm_client
    import httpx

    async def boom(self, *a, **kw):
        raise httpx.ConnectError("Connection refused")

    async def no_delay(_seconds):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    monkeypatch.setattr(asyncio, "sleep", no_delay)   # skip the retry backoff
    out = asyncio.run(llm_client.generate_completion("ping", use_cache=False))
    assert isinstance(out, str)
    assert out.startswith("Error:")


def test_generate_json_parses_messy_output(monkeypatch):
    import llm_client

    async def fake(prompt, system_prompt="", agent_id=None, json_mode=False, use_cache=True):
        return 'noise before {"a": 2, "b": [1,2]} trailing'

    monkeypatch.setattr(llm_client, "generate_completion", fake)
    out = asyncio.run(llm_client.generate_json("x"))
    assert out == {"a": 2, "b": [1, 2]}


def test_generate_json_returns_none_on_unparseable_output(monkeypatch):
    import llm_client

    async def fake_error(prompt, system_prompt="", agent_id=None, json_mode=False, use_cache=True):
        return "Error: Connection refused"

    monkeypatch.setattr(llm_client, "generate_completion", fake_error)
    out = asyncio.run(llm_client.generate_json("x"))
    assert out is None


# ── Orchestrator status mapping ──────────────────────────────────────────────
def test_status_map():
    from orchestrator import STATUS_MAP
    assert STATUS_MAP["error"] == "crashed"
    assert STATUS_MAP["restarting"] == "queued"
    assert STATUS_MAP["running"] == "running"


def test_watchdog_restarts_then_disables_after_max_failures():
    from orchestrator import Orchestrator
    orch = Orchestrator()   # fresh instance — isolated from the app's shared singleton
    agent = "devdaily"
    run_count = 0

    async def crashing_job():
        nonlocal run_count
        run_count += 1
        orch.agents_status[agent]["status"] = "error"   # crashes again immediately

    orch.register_agent_job(agent, crashing_job)
    orch._restart_counts[agent] = 0   # _load_history() may have loaded real prior-run counts from orchestrator.db
    orch.agents_status[agent]["status"] = "error"

    async def run():
        for _ in range(orch.MAX_RESTARTS + 1):
            await orch._watchdog_pass()
            await asyncio.sleep(0)   # let the create_task'd restart run before the next pass

    asyncio.run(run())
    assert run_count == orch.MAX_RESTARTS
    assert orch._restart_counts[agent] == orch.MAX_RESTARTS
    assert orch.agents_status[agent]["status"] == "failed"
