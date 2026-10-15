"""Tests for the trade gate (idea_gate / gate_plan), the entry window and the
entry order type. Pure — no DB, no network.

Run from the backend directory:  python -m pytest -q tests/test_strategy_gate.py

These gates were rewritten after the first live account lost $2,331 over 100
trades; each test below names the behaviour that loss came from. See
docs/STRATEGY_REVIEW.md.
"""
import datetime
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker_rules import (  # noqa: E402
    idea_gate, gate_plan, entry_window_state, traded_today, opened_today,
    decide_orders, ENTRY_OPEN_MIN, ENTRY_CLOSE_MIN)
from alpaca_broker import entry_order_kind  # noqa: E402

ET = ZoneInfo("America/New_York")


def _settings(**kw):
    base = {"min_rr": 2.0, "min_grade": "B", "allow_shorts": False,
            "max_new_trades_per_day": 3, "max_positions": 2, "align_market": True}
    base.update(kw)
    return base


def _idea(ticker="NVDA", direction="long", grade="A", rr=2.4):
    return {"ticker": ticker, "direction": direction, "grade": grade, "rr": rr}


def _open_window():
    return {"open": True, "why": "entry window", "minutes": 600}


# ── The entry window ────────────────────────────────────────────────────────
# 16 pre-market entries lost $1,391 — 60% of the total loss from 16% of the
# trades — because execute_plan only ever checked that it was a weekday.
def test_premarket_is_outside_the_entry_window():
    at = datetime.datetime(2026, 9, 2, 8, 34, tzinfo=ET)       # a Wednesday, 08:34
    w = entry_window_state(at)
    assert w["open"] is False and "9:45" in w["why"]


def test_the_first_fifteen_minutes_are_outside_the_window():
    assert entry_window_state(datetime.datetime(2026, 9, 2, 9, 35, tzinfo=ET))["open"] is False


def test_the_session_middle_is_inside_the_window():
    assert entry_window_state(datetime.datetime(2026, 9, 2, 11, 0, tzinfo=ET))["open"] is True
    assert entry_window_state(datetime.datetime(2026, 9, 2, 9, 45, tzinfo=ET))["open"] is True


def test_late_entries_are_refused():
    w = entry_window_state(datetime.datetime(2026, 9, 2, 15, 40, tzinfo=ET))
    assert w["open"] is False and "15:30" in w["why"]


def test_the_weekend_is_never_an_entry_window():
    assert entry_window_state(datetime.datetime(2026, 9, 5, 11, 0, tzinfo=ET))["open"] is False


def test_the_window_bounds_are_the_ones_the_tab_shows():
    assert (ENTRY_OPEN_MIN, ENTRY_CLOSE_MIN) == (9 * 60 + 45, 15 * 60 + 30)


def test_an_idea_outside_the_window_is_gated_with_the_windows_own_reason():
    closed = entry_window_state(datetime.datetime(2026, 9, 2, 8, 34, tzinfo=ET))
    why = idea_gate(_idea(), _settings(), window=closed)
    assert why and "9:45" in why


# ── Direction ───────────────────────────────────────────────────────────────
# Shorts were 38 of 100 trades and $2,160 of the $2,331 loss.
def test_shorts_are_off_by_default():
    why = idea_gate(_idea(direction="short"), _settings(), window=_open_window())
    assert why and "shorts are off" in why


def test_shorts_can_be_turned_back_on():
    assert idea_gate(_idea(direction="short"), _settings(allow_shorts=True),
                     window=_open_window()) is None


def test_longs_are_unaffected_by_the_short_switch():
    assert idea_gate(_idea(direction="long"), _settings(), window=_open_window()) is None


def test_a_neutral_idea_is_never_gated_because_it_never_trades():
    assert idea_gate(_idea(direction="neutral"), _settings()) is None


# ── Quality: grade replaces the LLM's self-rated confidence ─────────────────
def test_a_graded_card_clears_the_gate():
    assert idea_gate(_idea(grade="A+"), _settings(), window=_open_window()) is None


def test_a_c_grade_is_below_the_floor():
    why = idea_gate(_idea(grade="C"), _settings(), window=_open_window())
    assert why and "below the B floor" in why


def test_a_card_with_no_grade_does_not_trade():
    idea = _idea()
    del idea["grade"]
    why = idea_gate(idea, _settings(), window=_open_window())
    assert why and "no grade" in why


def test_the_grade_floor_is_configurable():
    assert idea_gate(_idea(grade="B"), _settings(min_grade="A"),
                     window=_open_window()) is not None
    assert idea_gate(_idea(grade="A"), _settings(min_grade="A"),
                     window=_open_window()) is None


def test_poor_reward_risk_is_refused():
    why = idea_gate(_idea(rr=1.4), _settings(), window=_open_window())
    assert why and "reward/risk" in why


def test_a_missing_rr_is_not_itself_a_rejection():
    """The broker derives levels when a card gave none; the funnel's own 2R
    floor is what keeps a trade honest."""
    idea = _idea()
    del idea["rr"]
    assert idea_gate(idea, _settings(), window=_open_window()) is None


# ── The daily cap: 26 trades opened in the same minute as another lost $1,912
def test_the_daily_cap_stops_a_fourth_entry():
    why = idea_gate(_idea(), _settings(), opened=3, window=_open_window())
    assert why and "daily cap is 3" in why


def test_the_cap_still_allows_the_third():
    assert idea_gate(_idea(), _settings(), opened=2, window=_open_window()) is None


def test_gate_plan_counts_the_ideas_it_has_already_passed():
    """Four cards, a cap of three, one pass: the last one is refused — the cap
    cannot be evaded by everything being evaluated against the same count."""
    plan = {"daily": {"ideas": [_idea("NVDA"), _idea("AMD"), _idea("AAPL"), _idea("MU")]}}
    kept, rejected = gate_plan(plan, _settings(), window=_open_window())
    assert [i["ticker"] for i in kept["daily"]["ideas"]] == ["NVDA", "AMD", "AAPL"]
    assert rejected[0]["ticker"] == "MU" and "daily cap" in rejected[0]["why"]


def test_opened_today_counts_entries_not_round_trips():
    trades = [{"ts": "2026-09-02 10:00", "action": "BUY", "ticker": "NVDA"},
              {"ts": "2026-09-02 14:00", "action": "SELL", "ticker": "NVDA"},
              {"ts": "2026-09-02 11:00", "action": "SHORT", "ticker": "AMD"},
              {"ts": "2026-09-01 11:00", "action": "BUY", "ticker": "MU"}]
    assert opened_today(trades, "2026-09-02") == 2


# ── The tape ────────────────────────────────────────────────────────────────
def test_counter_tape_entries_are_blocked():
    bear = {"direction": "bearish", "detail": "/ES -4, /NQ -3"}
    why = idea_gate(_idea(), _settings(), market=bear, window=_open_window())
    assert why and "against the tape" in why


def test_an_indecisive_or_missing_tape_never_gates():
    for market in ({"direction": "mixed"}, {"direction": "neutral"},
                   {"direction": "unknown"}, None):
        assert idea_gate(_idea(), _settings(), market=market, window=_open_window()) is None


def test_align_market_can_be_switched_off():
    bear = {"direction": "bearish", "detail": "/ES -4, /NQ -3"}
    assert idea_gate(_idea(), _settings(align_market=False), market=bear,
                     window=_open_window()) is None


# ── One trade per symbol per session ────────────────────────────────────────
def test_traded_today_reads_the_days_fills():
    trades = [{"ts": "2026-09-02 14:00", "ticker": "AVGO"},
              {"ts": "2026-09-02 09:41", "ticker": "mu"},
              {"ts": "2026-08-21 08:36", "ticker": "COIN"}]
    assert traded_today(trades, "2026-09-02") == {"AVGO", "MU"}


def test_traded_today_is_empty_without_a_log():
    assert traded_today(None, "2026-09-02") == set()
    assert traded_today([], "2026-09-02") == set()


def test_a_symbol_already_traded_today_does_not_trade_again():
    why = idea_gate(_idea("AVGO"), _settings(), traded={"AVGO"}, window=_open_window())
    assert why and "one trade per symbol" in why


def test_the_reversal_of_a_filled_long_is_blocked():
    """AVGO filled LONG at 14:00; by 15:51 the funnel printed a SHORT on the
    same name. Closing the winner and reversing into it is an artifact of
    re-running the screen, not a decision."""
    plan = {"daily": {"ideas": [_idea("AVGO", "short")]}}
    kept, rejected = gate_plan(plan, _settings(allow_shorts=True), traded={"AVGO"},
                               window=_open_window())
    assert kept["daily"]["ideas"] == []
    assert rejected[0]["ticker"] == "AVGO" and "one trade per symbol" in rejected[0]["why"]


def test_the_rule_can_be_turned_off():
    assert idea_gate(_idea("AVGO"), _settings(one_trade_per_symbol=False),
                     traded={"AVGO"}, window=_open_window()) is None


def test_an_untraded_symbol_still_clears_the_gate():
    assert idea_gate(_idea("MU"), _settings(), traded={"AVGO"}, window=_open_window()) is None


# ── gate_plan plumbing ──────────────────────────────────────────────────────
def test_gate_plan_filters_ideas_and_reports_rejections():
    plan = {"daily": {"ideas": [_idea("NVDA", grade="A"), _idea("AMD", grade="C"),
                                _idea("MU", "short")]}}
    kept, rejected = gate_plan(plan, _settings(), window=_open_window())
    assert [i["ticker"] for i in kept["daily"]["ideas"]] == ["NVDA"]
    assert {r["ticker"] for r in rejected} == {"AMD", "MU"}
    assert all(r["action"] == "open" for r in rejected)


def test_gate_plan_leaves_the_rest_of_the_plan_alone():
    plan = {"headline": "chop", "avoid": ["TSLA"], "daily": {"bias": "NEUTRAL", "ideas": []}}
    kept, _ = gate_plan(plan, _settings(), window=_open_window())
    assert kept["headline"] == "chop" and kept["avoid"] == ["TSLA"]
    assert kept["daily"]["bias"] == "NEUTRAL"


# ── decide_orders respects plan order, which is grade order ─────────────────
def test_a_capped_account_opens_the_best_cards_not_the_first_hashed():
    plan = {"daily": {"ideas": [_idea("NVDA", grade="A+"), _idea("AMD", grade="A"),
                                _idea("AAPL", grade="B")]}}
    orders = decide_orders(plan, {}, _settings(max_positions=2))
    assert [o["ticker"] for o in orders if o["action"] == "open"] == ["NVDA", "AMD"]


def test_orders_carry_the_cards_numeric_levels():
    idea = {**_idea(), "entry_px": 100.0, "stop_px": 98.0, "target_px": 104.0, "atr14": 3.0}
    orders = decide_orders({"daily": {"ideas": [idea]}}, {}, _settings())
    o = orders[0]
    assert (o["entry"], o["stop"], o["target"], o["atr14"]) == (100.0, 98.0, 104.0, 3.0)
    assert o["grade"] == "A"


# ── Entry order type ────────────────────────────────────────────────────────
def test_entry_below_live_is_a_limit_and_above_is_a_stop_for_a_long():
    assert entry_order_kind("long", 99.0, 100.0)[0] == "limit"
    assert entry_order_kind("long", 101.0, 100.0)[0] == "stop"


def test_entry_order_kind_mirrors_for_a_short():
    assert entry_order_kind("short", 101.0, 100.0)[0] == "limit"
    assert entry_order_kind("short", 99.0, 100.0)[0] == "stop"


def test_an_entry_miles_from_the_quote_is_refused():
    kind, why = entry_order_kind("long", 50.0, 100.0)
    assert kind is None and why
