"""Unit tests for pure logic — no network, LLM, or Ollama required.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Compass: pivot math ──────────────────────────────────────────────────────
def test_pivots_classic_formula():
    from agents.agent5_market_direction import _pivots, _bias
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
    from agents.agent5_market_direction import _headline_sentiment
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


def test_generate_json_parses_messy_output(monkeypatch):
    import llm_client

    async def fake(prompt, system_prompt="", agent_id=None, json_mode=False, use_cache=True):
        return 'noise before {"a": 2, "b": [1,2]} trailing'

    monkeypatch.setattr(llm_client, "generate_completion", fake)
    out = asyncio.run(llm_client.generate_json("x"))
    assert out == {"a": 2, "b": [1, 2]}


# ── Orchestrator status mapping ──────────────────────────────────────────────
def test_status_map():
    from orchestrator import STATUS_MAP
    assert STATUS_MAP["error"] == "crashed"
    assert STATUS_MAP["restarting"] == "queued"
    assert STATUS_MAP["running"] == "running"
