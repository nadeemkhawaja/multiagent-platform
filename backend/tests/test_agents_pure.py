"""Unit tests for pure-logic helpers across the financial/content agents — no
network, LLM, or Ollama required.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Compass: VIX regime classification ───────────────────────────────────────
def test_vix_regime_thresholds():
    from agents.agent3_wallstreet_wolf import _vix_regime
    assert _vix_regime(12) == "Low"
    assert _vix_regime(15) == "Normal"   # boundary: not < 15
    assert _vix_regime(20) == "Normal"
    assert _vix_regime(25) == "Normal"   # boundary: not > 25
    assert _vix_regime(30) == "Elevated"


# ── Alpha Wolf: cross-agent summaries fed to the synthesis LLM call ──────────
def test_compass_summary_includes_vix_when_present():
    from agents.agent13_alpha_wolf import _compass_summary
    d = {"compass": {"composite": 12, "sectors": [{"k": "Technology", "bias": 20}],
                      "vix": {"level": 14.2, "regime": "Low"}, "read": "Markets look constructive."}}
    out = _compass_summary(d)
    assert "VIX 14.2 (Low volatility)" in out
    assert "Composite bias: 12" in out
    assert "Technology +20" in out


def test_compass_summary_handles_missing_vix():
    from agents.agent13_alpha_wolf import _compass_summary
    d = {"compass": {"composite": -5, "sectors": [], "read": "Quiet day."}}
    out = _compass_summary(d)
    assert "VIX" not in out
    assert "Composite bias: -5" in out


def test_compass_summary_handles_empty_input():
    from agents.agent13_alpha_wolf import _compass_summary
    assert "Composite bias: ?" in _compass_summary({})
    assert "Composite bias: ?" in _compass_summary(None)


def test_wolf_summary_formats_gainers_and_losers():
    from agents.agent13_alpha_wolf import _wolf_summary
    d = {"market_data": {"top_gainers": [{"symbol": "NVDA", "change_pct": 5.2}],
                          "top_losers": [{"symbol": "INTC", "change_pct": -3.1}],
                          "commentary": "Tech leads."}}
    out = _wolf_summary(d)
    assert "NVDA 5.2%" in out
    assert "INTC -3.1%" in out
    assert "Tech leads." in out


# ── Paper Broker: order decisions + fills for Alpha Wolf execution ───────────
def _settings(**kw):
    base = {"enabled": True, "capital": 100_000.0, "position_pct": 10.0, "max_positions": 8}
    base.update(kw)
    return base


def test_decide_orders_opens_daily_ideas():
    from broker_rules import decide_orders
    plan = {"daily": {"ideas": [
        {"ticker": "NVDA", "direction": "long", "thesis": "AI demand"},
        {"ticker": "TSLA", "direction": "short", "thesis": "weak deliveries"},
        {"ticker": "SPY", "direction": "neutral", "thesis": "wait"},
    ]}}
    orders = decide_orders(plan, {}, _settings())
    assert [(o["action"], o["ticker"], o.get("direction")) for o in orders] == [
        ("open", "NVDA", "long"), ("open", "TSLA", "short")]


def test_decide_orders_skips_already_held_and_respects_max_positions():
    from broker_rules import decide_orders
    plan = {"daily": {"ideas": [
        {"ticker": "NVDA", "direction": "long"},
        {"ticker": "AMD", "direction": "long"},
        {"ticker": "MSFT", "direction": "long"},
    ]}}
    positions = {"NVDA": {"direction": "long", "shares": 10, "entry_price": 100.0}}
    orders = decide_orders(plan, positions, _settings(max_positions=2))
    # NVDA already held long → skipped; only one slot left after NVDA
    assert [(o["action"], o["ticker"]) for o in orders] == [("open", "AMD")]


def test_decide_orders_closes_and_reopens_on_direction_flip():
    from broker_rules import decide_orders
    plan = {"daily": {"ideas": [{"ticker": "TSLA", "direction": "long"}]}}
    positions = {"TSLA": {"direction": "short", "shares": 5, "entry_price": 200.0}}
    orders = decide_orders(plan, positions, _settings())
    assert orders[0]["action"] == "close" and orders[0]["ticker"] == "TSLA"
    # open orders carry the card's own levels and its grade
    assert orders[1]["action"] == "open" and orders[1]["ticker"] == "TSLA"
    assert orders[1]["direction"] == "long" and orders[1]["reason"] == "funnel card"
    assert set(orders[1]) >= {"entry", "stop", "target", "atr14", "grade", "rr"}


def test_decide_orders_closes_avoided_holdings_without_reopening():
    from broker_rules import decide_orders
    plan = {"daily": {"ideas": [{"ticker": "COIN", "direction": "long"}]},
            "avoid": ["Stay away from COIN into the SEC ruling"]}
    positions = {"COIN": {"direction": "long", "shares": 5, "entry_price": 150.0}}
    orders = decide_orders(plan, positions, _settings())
    assert [(o["action"], o["ticker"]) for o in orders] == [("close", "COIN")]


def test_avoid_hits_only_matches_held_tickers():
    from broker_rules import avoid_hits
    hits = avoid_hits(["Avoid NVDA and meme stocks", "No crypto until VIX settles"],
                      {"NVDA", "AAPL"})
    assert hits == {"NVDA"}


# ── Alpha Wolf: plan sanitization (LLM output does not always honor schema) ──
def test_sanitize_plan_coerces_object_fields_to_text():
    from agents.agent13_alpha_wolf import _sanitize_plan
    messy = {
        "headline": {"text": "Risk-on into CPI", "confidence": 0.8},
        "stance": "risk-on",
        "regime": ["Bullish regime", "vol compressed"],
        "confluence": [{"ticker": "NVDA", "feeds": ["flow", "congress"]}],
        "daily": {"bias": "bullish", "summary": {"note": "Buy dips."},
                  "ideas": [{"ticker": "nvda", "direction": "LONG",
                             "thesis": {"reason": "AI demand"},
                             "trigger": {"level": 120}, "risk": "below 110"}]},
        "weekly": {"bias": "sideways", "summary": "Wait.",
                   "themes": [{"name": "AI capex"}], "ideas": "none"},
        "avoid": [{"ticker": "COIN", "why": "SEC ruling"}],
        "catalysts": "CPI Thursday",
        "risk_notes": {"sizing": "2% per trade"},
    }
    plan = _sanitize_plan(messy)
    assert plan["headline"] == "Risk-on into CPI — 0.8"
    assert plan["stance"] == "RISK-ON"
    assert plan["regime"] == "Bullish regime, vol compressed"
    assert plan["confluence"] == ["NVDA — flow, congress"]
    assert plan["daily"]["bias"] == "BULLISH"
    assert plan["daily"]["summary"] == "Buy dips."
    # The model's own daily ideas are DISCARDED — daily.ideas is assigned from
    # the funnel's cards in price_plan(), so anything the model wrote here would
    # be a second, unpriced source of trades.
    assert plan["daily"]["ideas"] == []
    assert "timeline" not in plan["daily"]              # the LLM schedule is gone
    assert plan["weekly"]["bias"] == "NEUTRAL"          # invalid bias → NEUTRAL
    assert plan["weekly"]["themes"] == ["AI capex"]
    assert plan["weekly"]["ideas"] == []                # non-list ideas dropped
    assert plan["avoid"] == ["COIN — SEC ruling"]
    assert plan["catalysts"] == ["CPI Thursday"]
    assert plan["risk_notes"] == "2% per trade"
    # every value the UI renders directly is now a plain string
    for v in [plan["headline"], plan["regime"], plan["risk_notes"],
              *plan["confluence"], *plan["avoid"], *plan["catalysts"],
              *plan["weekly"]["themes"]]:
        assert isinstance(v, str)


def test_sanitize_plan_handles_garbage_input():
    from agents.agent13_alpha_wolf import _sanitize_plan
    for garbage in (None, "not a dict", [], {"daily": "x", "weekly": 7}):
        plan = _sanitize_plan(garbage)
        assert plan["stance"] == "NEUTRAL"
        assert plan["daily"]["ideas"] == [] and plan["weekly"]["ideas"] == []


def test_sanitize_plan_drops_weekly_ideas_without_ticker():
    from agents.agent13_alpha_wolf import _sanitize_plan
    plan = _sanitize_plan({"weekly": {"ideas": [
        {"direction": "long", "thesis": "no ticker"},
        "just a string",
        {"ticker": "AMD", "direction": "long"},
    ]}})
    assert [i["ticker"] for i in plan["weekly"]["ideas"]] == ["AMD"]


def test_the_model_cannot_put_a_trade_in_the_daily_plan():
    """The whole point of the rewrite: no path from model prose to an order."""
    from agents.agent13_alpha_wolf import _sanitize_plan
    plan = _sanitize_plan({"daily": {"ideas": [
        {"ticker": "NVDA", "direction": "long", "confidence": 10,
         "entry": "$120", "stop": "$118", "target": "$130"}]}})
    assert plan["daily"]["ideas"] == []


# ── Alpha Wolf: live decision engine (market clock + idea scoring) ───────────
def _et(y, mo, d, h, mi):
    import datetime
    from agents.agent13_alpha_wolf import ET
    return datetime.datetime(y, mo, d, h, mi, tzinfo=ET)


def test_market_clock_sessions():
    from agents.agent13_alpha_wolf import market_clock
    # Friday 2026-06-12 across the trading day
    assert market_clock(_et(2026, 6, 12, 8, 0))["session"] == "pre"
    assert market_clock(_et(2026, 6, 12, 9, 45))["session"] == "open"
    midday = market_clock(_et(2026, 6, 12, 12, 0))
    assert midday["session"] == "midday" and midday["is_open"] is True
    assert market_clock(_et(2026, 6, 12, 15, 30))["session"] == "power"
    closed = market_clock(_et(2026, 6, 12, 21, 0))
    assert closed["session"] == "closed" and closed["is_open"] is False


def test_market_clock_phases_drive_the_session_bar():
    from agents.agent13_alpha_wolf import market_clock
    c = market_clock(_et(2026, 6, 12, 12, 0))
    assert [p["key"] for p in c["phases"]] == ["pre", "open", "midday", "power", "after"]
    assert sum(p["width"] for p in c["phases"]) == 100
    assert [p["key"] for p in c["phases"] if p["current"]] == ["midday"]
    assert c["phases"][0]["pct"] == 0
    assert c["in_day_band"] is True
    assert 0 <= c["day_pct"] <= 100
    assert c["session_note"]


def test_market_clock_day_pct_clamps_outside_the_band():
    from agents.agent13_alpha_wolf import market_clock
    assert market_clock(_et(2026, 6, 12, 2, 0))["day_pct"] == 0.0
    late = market_clock(_et(2026, 6, 12, 22, 0))
    assert late["day_pct"] == 100.0 and late["in_day_band"] is False


def test_market_clock_weekend_phases_never_read_as_current():
    from agents.agent13_alpha_wolf import market_clock
    sat = market_clock(_et(2026, 6, 13, 11, 0))
    assert not any(p["current"] for p in sat["phases"])
    assert sat["in_day_band"] is False


# ── Session bias: the one bullish/bearish read on the banner ─────────────────
def _bias(monkeypatch, tape, agent_data=None, plan=None):
    from agents import agent13_alpha_wolf as aw
    monkeypatch.setattr(aw.broker, "market_bias", lambda _d: tape)
    monkeypatch.setattr(aw, "get_agent_data", lambda aid: (agent_data or {}).get(aid, {}))
    return aw.session_bias(plan)


def test_session_bias_calls_bullish_when_tape_and_compass_agree(monkeypatch):
    out = _bias(monkeypatch,
                {"direction": "bullish", "score": 8, "detail": "/ES +4, /NQ +4"},
                {"wallstreet_wolf": {"compass": {"composite": 40}}},
                {"daily": {"bias": "BULLISH"}, "stance": "RISK-ON"})
    assert out["direction"] == "bullish"
    assert out["score"] == 4 and out["max_score"] == 4
    assert "blocked" in out["why"]
    assert [d["gating"] for d in out["drivers"]] == [True, False, False]


def test_session_bias_calls_bearish_on_the_tape_alone(monkeypatch):
    # The tape carries double weight, so it clears the bar without help.
    out = _bias(monkeypatch,
                {"direction": "bearish", "score": -7, "detail": "/ES -3, /NQ -4"},
                {"wallstreet_wolf": {"compass": {"composite": 2}}})
    assert out["direction"] == "bearish" and out["score"] == -2


def test_session_bias_is_mixed_when_the_reads_disagree(monkeypatch):
    out = _bias(monkeypatch,
                {"direction": "mixed", "score": 0, "detail": "indices disagree"},
                {"wallstreet_wolf": {"compass": {"composite": 40}}},
                {"daily": {"bias": "BEARISH"}})
    assert out["direction"] == "mixed"


def test_session_bias_reports_unknown_with_no_readings(monkeypatch):
    out = _bias(monkeypatch, {"direction": "unknown", "score": 0, "detail": "no reading"})
    assert out["direction"] == "unknown" and out["max_score"] == 0
    assert out["drivers"][0]["gating"] is False


def test_session_bias_ignores_a_compass_composite_inside_the_noise_band(monkeypatch):
    out = _bias(monkeypatch,
                {"direction": "neutral", "score": 1, "detail": "no clear tape"},
                {"wallstreet_wolf": {"compass": {"composite": 10}}})
    assert out["direction"] == "neutral" and out["score"] == 0
    assert out["drivers"][1]["direction"] == "neutral"


def test_market_clock_weekend_is_closed():
    from agents.agent13_alpha_wolf import market_clock
    sat = market_clock(_et(2026, 6, 13, 11, 0))      # Saturday
    assert sat["trading_day"] is False and sat["is_open"] is False
    assert "Pre-market" in sat["next_event"]["label"]


_SIZING = {"risk_pct": 0.5, "position_pct": 10.0}


def test_idea_now_states():
    from agents.agent13_alpha_wolf import _idea_now, market_clock
    clock = market_clock(_et(2026, 6, 12, 10, 0))     # in the open window
    idea = {"ticker": "AMD", "direction": "long", "entry_px": 146.20,
            "stop_px": 143.80, "target_px": 152.50, "grade": "A"}
    now = lambda live, clk=clock: _idea_now(idea, live, clk, 100_000.0, 100_000.0, _SIZING)
    assert now(143.0)["state"] == "STOPPED"
    assert now(153.0)["state"] == "TARGET_HIT"
    assert now(146.25)["state"] == "ACT"   # at entry
    # before the entry window opens → WAIT (pre-market is not an entry)
    assert now(146.25, market_clock(_et(2026, 6, 12, 9, 0)))["state"] == "WAIT"
    assert now(146.25, market_clock(_et(2026, 6, 12, 8, 34)))["state"] == "WAIT"
    # and after it closes → the move is not today's trade any more
    assert now(146.25, market_clock(_et(2026, 6, 12, 15, 40)))["state"] == "WINDOW_PASSED"


def test_idea_now_sizes_on_risk_not_on_the_concentration_cap():
    """The tab must show the size the broker will actually place. Sizing at
    budget // price ignored the stop entirely, so a wide-stop idea advertised
    the full concentration cap — here 68 shares against a real 30."""
    from agents.agent13_alpha_wolf import _idea_now, market_clock
    clock = market_clock(_et(2026, 6, 12, 10, 0))
    idea = {"ticker": "AMD", "direction": "long", "entry_px": 146.20,
            "stop_px": 130.00, "target_px": 180.00, "grade": "A"}
    sized = _idea_now(idea, 146.25, clock, 100_000.0, 100_000.0, _SIZING)
    # 0.5% of $100k = $500 of risk; $146.20 − $130.00 = $16.20 per share.
    assert sized["size_shares"] == 30
    assert sized["size_usd"] == round(30 * 146.20, 2)
    # and the old formula's answer — the 10% cap — is well clear of it
    assert int(100_000.0 * 0.10 // 146.25) == 68


def test_idea_now_advice_depends_on_whether_the_position_is_actually_held():
    """"Take profit" / "cover into weakness" are close instructions. Handed to a
    flat trader they say: open a position at the exact level the plan called the
    exit. The state must know whether we are in the name."""
    from agents.agent13_alpha_wolf import _idea_now, market_clock
    clock = market_clock(_et(2026, 6, 12, 10, 0))
    idea = {"ticker": "DELL", "direction": "short", "entry_px": 450.00,
            "stop_px": 460.00, "target_px": 439.50, "grade": "A"}
    args = (439.17, clock, 100_000.0, 100_000.0, _SIZING)

    flat = _idea_now(idea, *args, held=False)
    assert flat["state"] == "TARGET_HIT"
    assert "do not enter here" in flat["note"]
    assert "cover" not in flat["note"]

    inpos = _idea_now(idea, *args, held=True)
    assert inpos["state"] == "TARGET_HIT"
    assert "cover into weakness" in inpos["note"]


def test_a_held_name_is_not_told_to_enter_again():
    from agents.agent13_alpha_wolf import _idea_now, market_clock
    clock = market_clock(_et(2026, 6, 12, 10, 0))
    idea = {"ticker": "AMD", "direction": "long", "entry_px": 146.20,
            "stop_px": 143.80, "target_px": 152.50, "grade": "A"}
    # At the entry zone, with nothing through: flat → ACT, held → HOLDING.
    assert _idea_now(idea, 146.25, clock, 100_000.0, 100_000.0, _SIZING)["state"] == "ACT"
    held = _idea_now(idea, 146.25, clock, 100_000.0, 100_000.0, _SIZING, held=True)
    assert held["state"] == "HOLDING"
    assert "manage the open position" in held["note"]


def test_a_held_name_with_the_stop_through_is_told_to_exit():
    from agents.agent13_alpha_wolf import _idea_now, market_clock
    clock = market_clock(_et(2026, 6, 12, 10, 0))
    idea = {"ticker": "AMD", "direction": "long", "entry_px": 146.20,
            "stop_px": 143.80, "target_px": 152.50, "grade": "A"}
    assert "exit now" in _idea_now(idea, 143.0, clock, 100_000.0, 100_000.0, _SIZING, held=True)["note"]
    assert "stand aside" in _idea_now(idea, 143.0, clock, 100_000.0, 100_000.0, _SIZING)["note"]


def test_idea_now_scores_off_the_enriched_levels_not_the_raw_prose():
    """_enrich_ideas parses the LLM's text into entry_px/stop_px/target_px —
    anchored to the live quote, with missing stops filled from real support and
    resistance — and the BROKER executes off exactly those. Re-parsing the prose
    here would score the tab against different numbers than the ones working at
    the broker."""
    from agents.agent13_alpha_wolf import _idea_now, _idea_levels, market_clock
    clock = market_clock(_et(2026, 6, 12, 10, 0))
    idea = {"ticker": "AMD", "direction": "long",
            # Prose says one thing; enrichment resolved another (a real S/R
            # level, not the number the model typed).
            "entry": "around $146.20", "stop": "$143.80", "target": "$152.50",
            "entry_px": 145.00, "stop_px": 141.00, "target_px": 160.00,
            "atr14": 3.1}
    assert _idea_levels(idea, 146.0) == (145.00, 141.00, 160.00, 3.1)

    scored = _idea_now(idea, 142.0, clock, 100_000.0, 100_000.0, _SIZING)
    # $142 is under the prose stop of $143.80 but above the real stop of $141 —
    # the broker is still in the trade, so the tab must not call it stopped.
    assert scored["state"] != "STOPPED"
    assert scored["stop"] == 141.00


def test_a_held_name_is_given_no_position_size():
    """A dollar figure beside an open position reads as "add this much"."""
    from agents.agent13_alpha_wolf import _idea_now, market_clock
    clock = market_clock(_et(2026, 6, 12, 10, 0))
    idea = {"ticker": "AMD", "direction": "long", "entry_px": 146.20,
            "stop_px": 143.80, "target_px": 152.50}
    assert _idea_now(idea, 146.25, clock, 100_000.0, 100_000.0, _SIZING)["size_shares"] > 0
    assert "size_shares" not in _idea_now(idea, 146.25, clock, 100_000.0, 100_000.0,
                                         _SIZING, held=True)


def test_a_missing_stop_sizes_off_the_same_atr_envelope_the_broker_uses():
    import broker_rules as rules
    from agents.agent13_alpha_wolf import _size_idea
    atr = 4.0
    shares, note = _size_idea("long", 100.0, None, atr, 100_000.0, 100_000.0, _SIZING)
    stop, _ = rules._default_levels("long", 100.0, atr)
    expected, _ = rules.size_position(100_000.0, 100_000.0, 100.0, stop, _SIZING)
    assert note == ""
    assert shares == expected
    # and the ATR envelope is genuinely different from the flat-2% fallback
    assert stop != rules._default_levels("long", 100.0, None)[0]


def test_idea_now_reports_why_an_idea_cannot_be_sized():
    from agents.agent13_alpha_wolf import _idea_now, market_clock
    clock = market_clock(_et(2026, 6, 12, 10, 0))
    # $10 of risk budget against a $40-wide stop buys less than one share.
    idea = {"ticker": "AMD", "direction": "long", "entry_px": 146.20,
            "stop_px": 106.00, "target_px": 152.50, "grade": "A"}
    sized = _idea_now(idea, 146.25, clock, 2_000.0, 2_000.0, _SIZING)
    assert "size_shares" not in sized
    assert "too wide" in sized["size_note"]



# ── Paper Broker: risk management (stops/targets) + journal stats ────────────
def test_default_levels_from_atr():
    from broker_rules import _default_levels
    stop, target = _default_levels("long", 100.0, 2.0)   # risk = 1.2×2 = 2.4
    assert stop == 97.6 and target == 104.8
    stop, target = _default_levels("short", 100.0, 2.0)
    assert stop == 102.4 and target == 95.2
    stop, target = _default_levels("long", 100.0, None)  # 2% envelope fallback
    assert stop == 98.0 and target == 104.0


def test_sane_stop_rejects_wrong_side():
    from broker_rules import _sane_stop, _sane_target
    assert _sane_stop("long", 100.0, 95.0) == 95.0
    assert _sane_stop("long", 100.0, 105.0) is None     # stop above a long entry
    assert _sane_stop("short", 100.0, 105.0) == 105.0
    assert _sane_target("long", 100.0, 95.0) is None    # target below a long entry
    assert _sane_target("short", 100.0, 95.0) == 95.0


def test_journal_stats_win_rate_and_profit_factor():
    from broker_rules import journal_stats
    journal = [
        {"pnl": 100.0, "hold_days": 1.0, "reason": "target hit ($x)"},
        {"pnl": 60.0,  "hold_days": 2.0, "reason": "plan flipped"},
        {"pnl": -40.0, "hold_days": 0.5, "reason": "stop hit ($y)"},
        {"pnl": -20.0, "hold_days": 1.5, "reason": "stop hit ($z)"},
    ]
    s = journal_stats(journal)
    assert s["trades"] == 4 and s["wins"] == 2 and s["losses"] == 2
    assert s["win_rate"] == 50.0
    assert s["total_pnl"] == 100.0
    assert s["profit_factor"] == round(160 / 60, 2)
    assert s["by_exit"]["stop"]["n"] == 2
    assert s["by_exit"]["target"]["n"] == 1
    assert s["by_exit"]["plan"]["n"] == 1
    assert journal_stats([]) == {"trades": 0}


# ── Alpha Wolf: confidence coercion + idea enrichment ────────────────────────
def test_a_trade_banked_earlier_today_is_not_reported_as_a_missed_move():
    """The live states only knew about *currently open* positions, so a name
    taken to target and sold at 08:36 came back at 15:29 as "reached without
    us; the move is done" — a winning day reading as a flat one, on the one
    screen whose job is to say what happened."""
    from agents.agent13_alpha_wolf import _idea_now, market_clock
    clock = market_clock(_et(2026, 6, 12, 15, 29))
    idea = {"ticker": "COIN", "direction": "long", "entry_px": 172.46,
            "stop_px": 170.35, "target_px": 176.68, "grade": "A"}
    closed = {"ticker": "COIN", "pnl": 529.54, "r_multiple": 2.34,
              "exit_price": 182.21, "ts": "2026-06-12 08:36"}

    missed = _idea_now(idea, 185.34, clock, 100_000.0, 100_000.0, _SIZING)
    assert missed["state"] == "TARGET_HIT"        # flat and never in it

    banked = _idea_now(idea, 185.34, clock, 100_000.0, 100_000.0, _SIZING,
                       banked=closed)
    assert banked["state"] == "BANKED"
    assert "529.54" in banked["note"] and "2.34R" in banked["note"]
    assert "without us" not in banked["note"]
    assert banked["banked"]["exit_price"] == 182.21


def test_a_gated_idea_is_never_shown_as_an_entry_to_take():
    """The broker refused it at the last plan run; "ACT NOW" on that idea is an
    instruction nothing will execute."""
    from agents.agent13_alpha_wolf import _idea_now, market_clock
    clock = market_clock(_et(2026, 6, 12, 10, 0))
    idea = {"ticker": "AMZN", "direction": "short", "entry_px": 260.19,
            "stop_px": 261.08, "target_px": 258.58, "grade": "A"}
    args = (260.19, clock, 100_000.0, 100_000.0, _SIZING)

    assert _idea_now(idea, *args)["state"] == "ACT"

    gated = _idea_now(idea, *args, gate="gated: no fresh shorts on a RISK-ON stance")
    assert gated["state"] == "NO_TRADE"
    assert "RISK-ON stance" in gated["note"]

    # A stop already through outranks the gate: "invalidated" is the more
    # useful answer than "we wouldn't have taken it anyway".
    stopped = _idea_now(idea, 262.0, clock, 100_000.0, 100_000.0, _SIZING,
                        gate="gated: whatever")
    assert stopped["state"] == "STOPPED"


def test_gate_reasons_and_banked_map_are_keyed_by_ticker():
    from agents.agent13_alpha_wolf import _gate_reasons, _banked_today
    plan = {"execution": {"skipped": [
        {"action": "open", "ticker": "smci", "why": "reward/risk 1.4:1 below the floor"},
        {"action": "close", "ticker": "NVDA", "why": "no price available"},
        {"action": "open", "ticker": "GOOG"},          # no reason → not a gate
    ]}}
    assert _gate_reasons(plan) == {"SMCI": "reward/risk 1.4:1 below the floor"}

    journal = [{"ticker": "coin", "ts": "2026-06-12 14:02", "pnl": 10.0},
               {"ticker": "COIN", "ts": "2026-06-12 08:36", "pnl": 529.54},
               {"ticker": "TSLA", "ts": "2026-06-11 15:00", "pnl": -80.0}]
    today = _banked_today(journal, {"date": "2026-06-12"})
    assert set(today) == {"COIN"}                      # yesterday's close is not today's
    assert today["COIN"]["pnl"] == 10.0                # newest-first wins
