"""Tests for the Technologia → Alpha Wolf card sync: the master plan must show
the same cards the funnel does, keep them current intraday, and say why any card
it is NOT trading was left out. Pure, no network.
Run from the backend directory:  python -m pytest -q
"""
import asyncio
import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import agent13_alpha_wolf as aw  # noqa: E402
from agents.agent13_alpha_wolf import (  # noqa: E402
    ET, _price_ideas, cards_to_ideas, funnel_snapshot)
from agents.agent14_technologia import _market_is_open, snapshot_age_minutes  # noqa: E402
from alpaca_broker import split_pending  # noqa: E402


def _card(symbol="NVDA", action="LONG", grade="A", entry=100.0):
    return {"symbol": symbol, "label": symbol, "action": action, "grade": grade,
            "context": "TREND_UP", "price": entry, "entry": entry, "stop": entry - 1,
            "t1": {"price": entry + 3}, "rr": 3.0, "why": "test card",
            "poi": {"low": entry - 0.5, "high": entry + 0.5, "confluence": 4},
            "trigger": {"why": "sweep reclaimed"}, "in_play": True}


def _data(cards, minutes_ago=0):
    ts = datetime.datetime.now(ET) - datetime.timedelta(minutes=minutes_ago)
    return {"signals": {"cards": cards, "generated_ts": ts.timestamp(),
                        "generated_at": ts.strftime("%Y-%m-%d %H:%M ET")}}


# ── The compute window has to open before the plan is synthesized ───────────
def test_technologia_computes_before_the_0830_plan_cron():
    day = datetime.datetime(2026, 9, 2, 8, 0, tzinfo=ET)      # a Wednesday
    assert _market_is_open(day) is True
    assert _market_is_open(day.replace(hour=8, minute=29)) is True
    assert _market_is_open(day.replace(hour=7, minute=30)) is False
    assert _market_is_open(day.replace(hour=17)) is False


def test_market_closed_on_the_weekend():
    assert _market_is_open(datetime.datetime(2026, 9, 4, 11, 0, tzinfo=ET)) is True   # Friday
    assert _market_is_open(datetime.datetime(2026, 9, 5, 11, 0, tzinfo=ET)) is False  # Saturday
    assert _market_is_open(datetime.datetime(2026, 9, 6, 11, 0, tzinfo=ET)) is False  # Sunday


# ── Snapshot age drives the "refresh before you plan" decision ──────────────
def test_snapshot_age_reads_the_epoch_stamp():
    assert snapshot_age_minutes(_data([], minutes_ago=40)) == pytest.approx(40, abs=1)


def test_snapshot_age_falls_back_to_the_printed_stamp():
    d = _data([], minutes_ago=47)
    del d["signals"]["generated_ts"]
    assert snapshot_age_minutes(d) == pytest.approx(47, abs=1)


def test_snapshot_age_is_none_without_a_snapshot():
    assert snapshot_age_minutes({}) is None
    assert snapshot_age_minutes({"signals": {"generated_at": "not a date"}}) is None


# ── Which cards become ideas ────────────────────────────────────────────────
def test_only_actionable_equity_cards_become_ideas():
    data = _data([_card("NVDA", "LONG"), _card("AAPL", "WAIT"),
                  _card("TSLA", "STAND_DOWN"), _card("ES=F", "LONG")])
    assert [c["ticker"] for c in cards_to_ideas(data)] == ["NVDA"]


def test_futures_cards_never_reach_the_broker():
    data = _data([_card("ES=F", "LONG"), _card("NQ=F", "SHORT")])
    assert cards_to_ideas(data) == []


# ── Parity: every card is in the plan's funnel record, labelled ─────────────
def test_snapshot_carries_every_card_with_a_reason():
    data = _data([_card("NVDA", "LONG"), _card("AAPL", "WAIT"),
                  _card("TSLA", "STAND_DOWN"), _card("ES=F", "LONG")])
    snap = funnel_snapshot(data)
    by = {c["symbol"]: c for c in snap["cards"]}
    assert set(by) == {"NVDA", "AAPL", "TSLA", "ES=F"}
    assert by["NVDA"]["in_plan"] is True
    assert by["AAPL"]["in_plan"] is False and by["AAPL"]["action"] == "WAIT"
    assert by["TSLA"]["in_plan"] is False and by["TSLA"]["action"] == "STAND_DOWN"
    assert by["ES=F"]["in_plan"] is False          # futures are context, never orders
    assert (snap["tradeable"], snap["armed"], snap["stand_down"]) == (1, 1, 1)


def test_snapshot_survives_an_empty_payload():
    snap = funnel_snapshot({})
    assert snap["cards"] == [] and snap["tradeable"] == 0
    assert snap["age_min"] is None


# ── The cards ARE the ideas: assignment, not a merge ───────────────────────
def test_the_cards_become_the_plans_ideas():
    ideas = cards_to_ideas(_data([_card("NVDA", "LONG")]))
    assert [i["ticker"] for i in ideas] == ["NVDA"]
    assert ideas[0]["source"] == "technologia_funnel"
    # Numeric, not prose — these are the levels the broker places.
    assert ideas[0]["entry_px"] == 100.0 and ideas[0]["stop_px"] == 99.0
    assert ideas[0]["target_px"] == 103.0


def test_a_card_that_goes_back_to_wait_leaves_the_plan():
    """No pruning rule needed: the list is replaced every run."""
    assert [i["ticker"] for i in cards_to_ideas(_data([_card("NVDA", "LONG")]))] == ["NVDA"]
    assert cards_to_ideas(_data([_card("NVDA", "WAIT")])) == []


def test_ideas_are_ordered_by_grade_so_a_capped_day_takes_the_best():
    data = _data([_card("AAPL", "LONG", grade="B"), _card("NVDA", "LONG", grade="A+"),
                  _card("AMD", "LONG", grade="A")])
    assert [i["ticker"] for i in cards_to_ideas(data)] == ["NVDA", "AMD", "AAPL"]


def test_the_card_grade_travels_with_the_idea():
    idea = cards_to_ideas(_data([_card("NVDA", "LONG", grade="A+")]))[0]
    assert idea["grade"] == "A+"
    assert "confidence" not in idea      # the model no longer rates anything


# ── Re-running execution intraday must not cancel its own working orders ────
def test_todays_working_entry_orders_are_not_cancelled_as_stale():
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    live = {"ticker": "NVDA", "submitted_at": f"{today} 09:52"}
    old = {"ticker": "AAPL", "submitted_at": "2026-08-31 10:14"}
    still, stale = split_pending([live, old])
    assert still == [live]
    assert stale == [old]


def test_pending_without_a_stamp_is_treated_as_stale():
    still, stale = split_pending([{"ticker": "NVDA"}])
    assert still == [] and len(stale) == 1


# ── The invariant: the plan holds every trade, and only trades ──────────────
def _planned(cards):
    """The plan's ideas and the funnel snapshot, from one set of cards."""
    data = _data(cards)
    plan = {"daily": {"ideas": cards_to_ideas(data)}}
    return plan, funnel_snapshot(data)


def test_every_tradeable_card_is_an_idea_and_nothing_else_is():
    cards = [_card("NVDA", "LONG"), _card("AMD", "SHORT"), _card("AAPL", "WAIT"),
             _card("TSLA", "STAND_DOWN"), _card("ES=F", "LONG")]
    plan, snap = _planned(cards)
    routed = {i["ticker"] for i in plan["daily"]["ideas"]}
    # ALL trades: every LONG/SHORT equity card is in the plan.
    assert routed == {"NVDA", "AMD"}
    # ONLY trades: nothing that isn't one got in.
    assert {c["symbol"] for c in snap["cards"] if c["in_plan"]} == routed


def test_the_two_tabs_cannot_disagree():
    """The old failure mode: Technologia showed a card the plan had quietly
    dropped. One source means the question can't arise — the snapshot and the
    ideas are derived from the same card list in the same pass."""
    cards = [_card("NVDA", "LONG"), _card("AMD", "SHORT")]
    plan, snap = _planned(cards)
    assert ({i["ticker"] for i in plan["daily"]["ideas"]}
            == {c["symbol"] for c in snap["cards"] if c["in_plan"]})


def test_the_buckets_add_up_to_the_card_count():
    cards = [_card("NVDA", "LONG"), _card("AMD", "SHORT"), _card("AAPL", "WAIT"),
             _card("TSLA", "STAND_DOWN"), _card("ES=F", "LONG"), _card("NQ=F", "WAIT")]
    _, snap = _planned(cards)
    assert (snap["tradeable"], snap["armed"], snap["stand_down"], snap["futures"]) == (2, 1, 1, 2)
    assert snap["tradeable"] + snap["armed"] + snap["stand_down"] + snap["futures"] == len(cards)


def test_a_wait_card_with_no_zone_still_lands_in_a_bucket():
    card = _card("AAPL", "WAIT")
    card["poi"] = None                       # armed on nothing — still not a trade
    _, snap = _planned([card])
    assert snap["armed"] == 1
    assert snap["tradeable"] + snap["armed"] + snap["stand_down"] + snap["futures"] == 1


def test_a_card_whose_level_ran_away_is_set_aside_not_traded():
    data = _data([_card("NVDA", "LONG", entry=100.0)])
    plan = {"daily": {"ideas": cards_to_ideas(data)}}
    _price_ideas(plan, {"NVDA": 140.0}, {}, {})      # 40% above the card's entry
    assert plan["daily"]["ideas"] == []
    assert plan["daily"]["stale_ideas"][0]["ticker"] == "NVDA"


def test_a_card_at_its_level_survives_pricing():
    data = _data([_card("NVDA", "LONG", entry=100.0)])
    plan = {"daily": {"ideas": cards_to_ideas(data)}}
    _price_ideas(plan, {"NVDA": 100.5}, {"NVDA": {"atr14": 3.0}}, {})
    assert [i["ticker"] for i in plan["daily"]["ideas"]] == ["NVDA"]
    assert plan["daily"]["ideas"][0]["atr14"] == 3.0


# ── sync_funnel: what an empty card list MEANS depends on coverage ──────────
def _wired(monkeypatch, tech, plan):
    """sync_funnel against an in-memory store, no DB, no network, no broker."""
    store = {"technologia": tech, "alpha_wolf": {"plan": plan}}
    monkeypatch.setattr(aw, "get_agent_data", lambda a: store.get(a, {}))
    monkeypatch.setattr(aw, "save_agent_data",
                        lambda a, d: store.setdefault(a, {}).update(d))
    monkeypatch.setattr(aw, "ensure_fresh_cards", lambda *a, **k: _async(store["technologia"]))
    monkeypatch.setattr(aw.broker, "_fetch_prices_sync", lambda syms, *a, **k: {s: 100.0 for s in syms})
    monkeypatch.setattr(aw.broker, "get_settings", lambda: {
        "min_confidence": 6, "min_rr": 1.5, "capital": 100000.0, "position_pct": 10,
        "risk_pct": 0.5, "max_positions": 5, "align_market": True, "align_cards": True})
    monkeypatch.setattr(aw.technicals_tool, "compute_sync", lambda s: {})
    monkeypatch.setattr(aw.levels_tool, "compute_sync", lambda s: {})
    monkeypatch.setattr(aw.broker, "execute_plan",
                        lambda p: _async({"enabled": True, "executed": [], "skipped": []}))
    return store


async def _async(v):
    return v


def _tech(cards, requested=3, returned=3, minutes_ago=0):
    d = _data(cards, minutes_ago)
    d["signals"]["coverage"] = {"requested": requested, "returned": returned, "missing": []}
    return d


def test_a_quiet_tape_retires_the_cards_it_no_longer_shows(monkeypatch):
    plan = {"stance": "NEUTRAL", "generated_at": "2026-09-02 08:30",
            "daily": {"ideas": []}, "funnel": {}}
    store = _wired(monkeypatch, _tech([_card("NVDA", "LONG")], minutes_ago=30), plan)
    assert asyncio.run(aw.sync_funnel())["new"] == ["NVDA"]
    # A later run that priced everything and found nothing: a real stand-down.
    store["technologia"] = _tech([])
    res = asyncio.run(aw.sync_funnel())
    assert res["synced"] is True and res["gone"] == ["NVDA"]
    assert store["alpha_wolf"]["plan"]["daily"]["ideas"] == []


def test_a_run_that_priced_nothing_holds_the_previous_cards(monkeypatch):
    plan = {"stance": "NEUTRAL", "generated_at": "2026-09-02 08:30",
            "daily": {"ideas": []}, "funnel": {}}
    store = _wired(monkeypatch, _tech([_card("NVDA", "LONG")], minutes_ago=30), plan)
    asyncio.run(aw.sync_funnel())
    # Same run, but the data feed failed — absence of cards is missing data.
    store["technologia"] = _tech([], returned=0)
    res = asyncio.run(aw.sync_funnel())
    assert res["synced"] is False and "no price data" in res["why"]
    assert [i["ticker"] for i in store["alpha_wolf"]["plan"]["daily"]["ideas"]] == ["NVDA"]


def test_the_same_run_is_not_re_folded(monkeypatch):
    plan = {"stance": "NEUTRAL", "generated_at": "2026-09-02 08:30", "daily": {"ideas": []}}
    _wired(monkeypatch, _tech([_card("NVDA", "LONG")]), plan)
    assert asyncio.run(aw.sync_funnel())["synced"] is True
    assert asyncio.run(aw.sync_funnel())["synced"] is False


def test_nothing_to_sync_into_without_a_plan(monkeypatch):
    _wired(monkeypatch, _tech([_card("NVDA", "LONG")]), {})
    assert asyncio.run(aw.sync_funnel())["synced"] is False


# ── The card says what actually happened to it ─────────────────────────────
def _priced(monkeypatch, cards, positions=None, skipped=None):
    plan = {"stance": "NEUTRAL", "generated_at": "2026-09-02 08:30", "daily": {"ideas": []}}
    store = {"alpha_wolf": {"plan": plan,
                            "portfolio": {"cash": 100000.0, "positions": positions or {}}}}
    monkeypatch.setattr(aw, "get_agent_data", lambda a: store.get(a, {}))
    monkeypatch.setattr(aw, "save_agent_data", lambda a, d: store.setdefault(a, {}).update(d))
    monkeypatch.setattr(aw.broker, "_fetch_prices_sync", lambda syms, *a, **k: {s: 100.0 for s in syms})
    monkeypatch.setattr(aw.broker, "portfolio_equity", lambda p: 100000.0)
    monkeypatch.setattr(aw.broker, "get_settings", lambda: {
        "min_confidence": 6, "min_rr": 1.5, "capital": 100000.0, "position_pct": 10,
        "risk_pct": 0.5, "max_positions": 5})
    monkeypatch.setattr(aw.technicals_tool, "compute_sync", lambda s: {})
    monkeypatch.setattr(aw.levels_tool, "compute_sync", lambda s: {})
    monkeypatch.setattr(aw.broker, "execute_plan",
                        lambda p: _async({"enabled": True, "executed": [], "skipped": skipped or []}))
    asyncio.run(aw.price_plan(plan, _data(cards), execute=True))
    return {c["symbol"]: c for c in plan["funnel"]["cards"]}


def test_a_rejected_card_carries_the_brokers_own_reason(monkeypatch):
    by = _priced(monkeypatch, [_card("AVGO", "SHORT")],
                 skipped=[{"action": "open", "ticker": "AVGO",
                           "why": "rejected by Alpaca — insufficient buying power"}])
    assert by["AVGO"]["gate"] == "rejected by Alpaca — insufficient buying power"


def test_a_held_position_reads_as_held_not_as_gated(monkeypatch):
    """The one-trade rule declines the same symbol every half hour once it has
    filled. Rendering that as a warning would flag the day's working trade as
    the one thing that failed."""
    by = _priced(monkeypatch, [_card("MU", "LONG")],
                 positions={"MU": {"direction": "long", "shares": 10}},
                 skipped=[{"action": "open", "ticker": "MU",
                           "why": "gated: already traded today — one trade per symbol per session"}])
    assert by["MU"]["gate"] == ""
    assert "held" in by["MU"]["plan_note"]
