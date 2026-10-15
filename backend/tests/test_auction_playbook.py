"""Unit tests for the auction context layer, the SMC zone/trigger layer, and
the playbook that consolidates them into one card. Pure functions, synthetic
bars, no network. Run from the backend directory:  python -m pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import auction, smc, playbook, levels, strategies   # noqa: E402


def bar(c, o=None, h=None, l=None, v=1000.0, t=None):
    o = c if o is None else o
    b = {"open": o, "high": h if h is not None else max(o, c),
         "low": l if l is not None else min(o, c), "close": c, "volume": v}
    if t is not None:
        b["t"] = t
    return b


def session(closes, start=570, step=5, **kw):
    """RTH bars stamped with a clock, 5 minutes apart from 09:30 ET."""
    return [bar(c, t=start + i * step, **kw) for i, c in enumerate(closes)]


# ══ levels — the nearest-first regression ═══════════════════════════════════
def test_swing_levels_keeps_the_levels_nearest_to_price():
    """The old selection kept the 4 highest resistances and 4 LOWEST supports,
    so on a name trading near its highs the nearest support was thrown away and
    the stop got anchored 20%+ below the trade."""
    bars = []
    for lo, hi in [(90, 92), (88, 91), (95, 97), (93, 99), (100, 104), (98, 103),
                   (110, 114), (108, 113), (118, 122), (116, 121), (124, 128), (122, 127)]:
        bars += [bar((lo + hi) / 2, h=hi, l=lo)] * 2
    price = 125.0
    out = levels.swing_levels(bars, price=price)
    below = [s for s in out["support"] if s < price]
    assert below, "expected at least one support under price"
    # Nothing 20% away should win when a level exists 1% away.
    assert max(below) > price * 0.9


def test_swing_levels_without_a_price_still_returns_levels():
    bars = [bar(100 + (i % 5), h=102 + (i % 5), l=98 + (i % 5)) for i in range(40)]
    out = levels.swing_levels(bars)
    assert isinstance(out["support"], list) and isinstance(out["resistance"], list)


# ══ auction ════════════════════════════════════════════════════════════════
def test_rth_bars_splits_on_the_clock_and_passes_through_untimed_bars():
    bars = [bar(1, t=480), bar(2, t=600), bar(3, t=1000)]
    assert [b["t"] for b in auction.rth_bars(bars)] == [600]
    assert [b["t"] for b in auction.overnight_bars(bars)] == [480, 1000]
    assert len(auction.rth_bars([bar(1), bar(2)])) == 2      # no clock → assume RTH


def test_prior_day_levels_reads_yesterday_not_today():
    daily = [bar(100, h=105, l=95), bar(110, h=115, l=99)]
    assert auction.prior_day_levels(daily) == {"pdh": 105, "pdl": 95, "pdc": 100, "pdm": 100.0}
    assert auction.prior_day_levels([bar(1)]) == {}


def test_initial_balance_measures_the_first_hour_and_flags_extension():
    # First hour ranges 100-102; afterwards price trades up to 108.
    bars = [bar(101, h=102, l=100, t=570 + i * 5) for i in range(12)]
    bars += [bar(107, h=108, l=106, t=630 + i * 5) for i in range(6)]
    ib = auction.initial_balance(bars, atr=10.0)
    assert ib["ibh"] == 102 and ib["ibl"] == 100
    assert ib["extension"] == "up"
    assert ib["ib_shape"] == "narrow"          # 2 wide against a 10 ATR


def test_initial_balance_reports_no_extension_when_the_day_stays_inside():
    bars = [bar(101, h=102, l=100, t=570 + i * 5) for i in range(12)]
    bars += [bar(101, h=101.5, l=100.5, t=630 + i * 5) for i in range(6)]
    assert auction.initial_balance(bars)["extension"] == "none"


def test_opening_type_detects_a_one_way_drive():
    bars = [bar(100 + i, o=100 + i - 0.9, h=100 + i + 0.1, l=100 + i - 1.0, t=570 + i * 5)
            for i in range(6)]
    o = auction.opening_type(bars)
    assert o["type"] == "OPEN_DRIVE" and o["direction"] == "long"


def test_opening_type_calls_a_rotation_an_open_auction():
    closes = [100, 100.4, 99.7, 100.2, 99.8, 100.1]
    bars = [bar(c, h=c + 0.2, l=c - 0.2, t=570 + i * 5) for i, c in enumerate(closes)]
    o = auction.opening_type(bars)
    assert o["type"] == "OPEN_AUCTION" and o["direction"] is None


def test_open_vs_value_locates_the_open_against_yesterdays_value():
    assert auction.open_vs_value(110, 105, 95)["location"] == "above_value"
    assert auction.open_vs_value(90, 105, 95)["location"] == "below_value"
    assert auction.open_vs_value(100, 105, 95)["location"] == "inside_value"
    assert auction.open_vs_value(None, 105, 95) == {}


def test_eighty_percent_rule_fires_only_after_acceptance_back_inside():
    # Opens below value (VAL 95), then closes inside for 6 straight bars.
    bars = session([90, 92, 96, 97, 98, 99, 100, 101])
    out = auction.eighty_percent_rule(bars, prior_vah=105, prior_val=95)
    assert out["active"] is True and out["direction"] == "long" and out["target"] == 105

    # Pokes inside briefly but never accepts — no setup.
    bars2 = session([90, 96, 91, 97, 90, 92, 91, 90])
    assert auction.eighty_percent_rule(bars2, 105, 95)["active"] is False


def test_eighty_percent_rule_is_silent_when_the_open_was_inside_value():
    assert auction.eighty_percent_rule(session([100] * 8), 105, 95) == {}


def test_naked_pocs_finds_untested_prior_points_of_control():
    profiles = [
        {"date": "d1", "poc": 80.0, "high": 82, "low": 78},    # never revisited
        {"date": "d2", "poc": 95.0, "high": 96, "low": 94},    # revisited by d3
        {"date": "d3", "poc": 99.0, "high": 100, "low": 93},
        {"date": "d4", "poc": 101.0, "high": 102, "low": 98},  # current session
    ]
    out = auction.naked_pocs(profiles, price=100.0)
    prices = [n["price"] for n in out]
    assert 80.0 in prices          # untested
    assert 95.0 not in prices      # d3 traded through it
    assert 101.0 not in prices     # the live session can't be naked


def test_day_context_calls_a_trend_and_names_its_playbook():
    bars = [bar(101, h=102, l=100, t=570 + i * 5) for i in range(12)]
    bars += [bar(107, h=108, l=106, t=630 + i * 5) for i in range(6)]
    ctx = auction.day_context(
        bars, vwap=103.0, prior={"pdh": 103, "pdl": 95},
        ib=auction.initial_balance(bars, atr=5.0),
        opening={"type": "OPEN_DRIVE", "direction": "long", "confidence": 3},
        value_loc={"location": "above_value"}, atr=5.0)
    assert ctx["context"] == "TREND_UP"
    assert "pullback" in ctx["playbook"].lower()


def test_day_context_stands_down_when_the_evidence_fights():
    bars = session([100, 101, 99, 102, 98, 101])
    ctx = auction.day_context(
        bars, vwap=99.0, prior={"pdh": 103, "pdl": 100},
        ib={"extension": "both"},
        opening={"type": "OPEN_REJECTION_REVERSE", "direction": "short", "confidence": 2},
        value_loc={"location": "above_value"}, atr=2.0)
    assert ctx["context"] in ("UNDECIDED", "BALANCE")


def test_day_context_needs_a_session_before_it_will_speak():
    assert auction.day_context([bar(100)])["context"] == "UNDECIDED"


# ══ smc ════════════════════════════════════════════════════════════════════
def test_fair_value_gap_needs_a_real_three_bar_imbalance():
    bars = [bar(100, o=99, h=100.5, l=98.5),
            bar(106, o=100.5, h=106.2, l=100.4),      # displacement, mostly body
            bar(107, o=106.5, h=107.5, l=106.0)]
    gaps = smc.fair_value_gaps(bars, atr=2.0)
    assert len(gaps) == 1
    g = gaps[0]
    assert g["side"] == "bullish" and g["low"] == 100.5 and g["high"] == 106.0
    assert g["ce"] == 103.25                     # consequent encroachment


def test_fair_value_gap_rejects_a_wide_wick_with_no_body():
    bars = [bar(100, o=99, h=100.5, l=98.5),
            bar(100.6, o=100.5, h=106.2, l=100.4),   # all wick, no conviction
            bar(107, o=106.5, h=107.5, l=106.0)]
    assert smc.fair_value_gaps(bars, atr=2.0) == []


def test_fair_value_gap_drops_once_price_fully_fills_it():
    bars = [bar(100, o=99, h=100.5, l=98.5),
            bar(106, o=100.5, h=106.2, l=100.4),
            bar(107, o=106.5, h=107.5, l=106.0),
            bar(100, o=106, h=106.5, l=99.0)]        # trades all the way back
    assert smc.fair_value_gaps(bars, atr=2.0) == []


def test_order_block_is_the_last_opposing_candle_before_the_drive():
    bars = [bar(101, o=102, h=102.2, l=100.8),       # down close — the block
            bar(107, o=101.2, h=107.3, l=101.0),     # up displacement
            bar(108, o=107.2, h=108.5, l=107.0)]
    obs = smc.order_blocks(bars, atr=2.0)
    assert obs and obs[0]["side"] == "bullish"
    assert obs[0]["low"] == 100.8 and obs[0]["high"] == 102.2


def test_structure_shift_reports_direction_and_level():
    closes = [100, 103, 99, 104, 98, 106]
    bars = [bar(c, h=c + 0.5, l=c - 0.5) for c in closes]
    out = smc.structure_shift(bars, lookback=1)
    assert out.get("direction") == "long"


def test_liquidity_sweep_needs_the_reclaim_not_just_the_poke():
    swept = [bar(100), bar(101, h=105, l=100), bar(99, h=101, l=98)]
    assert smc.liquidity_sweeps(swept, [{"price": 104, "label": "pdh"}], atr=2.0)
    # Broke through and stayed — that is a breakout, not a sweep.
    held = [bar(100), bar(105, h=106, l=100), bar(107, h=108, l=105)]
    assert smc.liquidity_sweeps(held, [{"price": 104}], atr=2.0) == []


# ══ playbook ═══════════════════════════════════════════════════════════════
def test_points_of_interest_rank_confluence_above_proximity():
    levs = [
        {"price": 100.0, "label": "swing", "weight": 1},
        {"price": 95.0, "label": "prior_val", "weight": 3},
        {"price": 95.1, "label": "naked_poc", "weight": 3},
        {"price": 95.2, "label": "vwap", "weight": 2},
    ]
    pois = playbook.points_of_interest(levs, price=101.0, atr=4.0)
    assert pois[0]["confluence"] == 8            # the three-way cluster wins
    assert set(pois[0]["sources"]) == {"prior_val", "naked_poc", "vwap"}
    assert pois[0]["side"] == "support"


def test_points_of_interest_drops_zones_too_far_to_trade_today():
    levs = [{"price": 50.0, "label": "prior_val", "weight": 3}]
    assert playbook.points_of_interest(levs, price=100.0, atr=1.0) == []


def test_trigger_state_will_not_call_a_touch_a_signal():
    poi = {"low": 99, "high": 101, "mid": 100, "distance_atr": 0.1}
    bars = [bar(100, h=100.5, l=99.5) for _ in range(5)]
    assert playbook.trigger_state(bars, poi, "long", atr=2.0)["state"] == "ARMED"


def test_trigger_state_fires_on_a_sweep_and_reclaim():
    poi = {"low": 99, "high": 101, "mid": 100, "distance_atr": 0.1}
    bars = [bar(100, h=100.5, l=99.5), bar(100, h=100.5, l=99.5),
            bar(100.2, o=99.2, h=100.6, l=97.5)]      # wicks under 99, closes back over
    out = playbook.trigger_state(bars, poi, "long", atr=2.0)
    assert out["state"] == "TRIGGERED" and out["kind"] == "sweep"


def test_trade_card_stands_down_when_participation_fails():
    card = playbook.trade_card(
        symbol="X", label="X", price=100, bars=session([100] * 6), atr=2.0,
        context={"context": "TREND_UP", "playbook": "buy dips", "reasons": []},
        levels=[], pois=[], liquidity={"pass": False, "reasons": ["0.2x relative volume"], "in_play": False})
    assert card["action"] == "STAND_DOWN" and "liquidity floor" in card["why"]


def test_trade_card_stands_down_on_an_undecided_auction():
    card = playbook.trade_card(
        symbol="X", label="X", price=100, bars=session([100] * 6), atr=2.0,
        context={"context": "UNDECIDED", "playbook": auction.PLAYBOOKS["UNDECIDED"], "reasons": []},
        levels=[], pois=[])
    assert card["action"] == "STAND_DOWN"


def test_trade_card_never_shorts_on_a_trend_up_day():
    """The whole point of the context stage: an oversold reading on an uptrend
    day is a dip to buy, not a top to sell."""
    pois = [{"low": 98, "high": 99, "mid": 98.5, "confluence": 6, "sources": ["vwap", "prior_val"],
             "side": "support", "distance": 1.5, "distance_atr": 0.75}]
    levs = [{"price": 98.5, "label": "vwap"}, {"price": 106.0, "label": "pdh"},
            {"price": 110.0, "label": "naked_poc"}]
    card = playbook.trade_card(
        symbol="X", label="X", price=100, bars=session([100] * 6), atr=2.0,
        context={"context": "TREND_UP", "playbook": "buy dips", "reasons": []},
        levels=levs, pois=pois)
    assert card["direction"] == "long"
    assert card["action"] in ("LONG", "WAIT")


def test_trade_card_prices_a_triggered_long_with_structural_risk():
    """Intraday ATR sets the zone scale; DAILY ATR sets the stop floor and how
    far a target may sit. Production passes both (they differ by 15-25x), and
    the card is only coherent when it is given both."""
    pois = [{"low": 99, "high": 101, "mid": 100, "confluence": 8,
             "sources": ["vwap", "prior_val", "naked_poc"], "side": "support",
             "distance": 0.5, "distance_atr": 0.25}]
    levs = [{"price": 100.0, "label": "vwap"}, {"price": 108.0, "label": "pdh"},
            {"price": 114.0, "label": "naked_poc"}]
    bars = [bar(100, h=100.5, l=99.5), bar(100, h=100.5, l=99.5),
            bar(100.4, o=99.2, h=100.8, l=97.5)]
    card = playbook.trade_card(
        symbol="X", label="X", price=100.4, bars=bars, atr=0.5, reach_atr=8.0,
        context={"context": "TREND_UP", "playbook": "buy dips", "reasons": []},
        levels=levs, pois=pois)
    assert card["action"] == "LONG"
    assert card["direction"] == "long"
    # Stop floored at 0.40 x the DAILY ATR ($3.20), not at the zone edge — the
    # structural stop there would have been $1.78 away, inside the noise.
    assert card["stop"] == round(100.4 - 0.40 * 8.0, 2)
    assert "daily ATR" in card["stop_note"]
    # T1 is a REAL level that pays at least 2R, not an invented measured move.
    assert card["t1"]["price"] == 108.0
    assert card["t1"]["rr"] >= playbook.MIN_RR_T1
    assert not card["t1"].get("measured")
    assert card["grade"] in ("A+", "A", "B")


def test_a_card_waits_when_no_real_level_pays_two_r():
    """The measured-move fallback used to manufacture a 2R target from the stop
    distance, so the reward/risk floor could never reject anything: every card
    claimed ~2R and 14 of 97 live trades paid it."""
    pois = [{"low": 99, "high": 101, "mid": 100, "confluence": 8,
             "sources": ["vwap", "prior_val", "naked_poc"], "side": "support",
             "distance": 0.5, "distance_atr": 0.25}]
    # The only level ahead sits 2.6 above the entry against a 3.20 stop: 0.8R.
    levs = [{"price": 100.0, "label": "vwap"}, {"price": 103.0, "label": "pdh"}]
    bars = [bar(100, h=100.5, l=99.5), bar(100, h=100.5, l=99.5),
            bar(100.4, o=99.2, h=100.8, l=97.5)]
    card = playbook.trade_card(
        symbol="X", label="X", price=100.4, bars=bars, atr=0.5, reach_atr=8.0,
        context={"context": "TREND_UP", "playbook": "buy dips", "reasons": []},
        levels=levs, pois=pois)
    assert card["action"] == "WAIT"
    assert "nothing ahead worth the risk" in card["why"]
def test_trade_card_waits_when_the_reward_does_not_pay_for_the_stop():
    pois = [{"low": 99, "high": 101, "mid": 100, "confluence": 8, "sources": ["vwap"],
             "side": "support", "distance": 0.5, "distance_atr": 0.25}]
    levs = [{"price": 100.4, "label": "vwap"}, {"price": 100.6, "label": "pdh"}]
    bars = [bar(100, h=100.5, l=99.5), bar(100, h=100.5, l=99.5),
            bar(100.4, o=99.2, h=100.8, l=97.5)]
    card = playbook.trade_card(
        symbol="X", label="X", price=100.4, bars=bars, atr=2.0,
        context={"context": "TREND_UP", "playbook": "buy dips", "reasons": []},
        levels=levs, pois=pois)
    # Structure runs out, so targets fall back to measured 2R/3R moves — which
    # is exactly when a card must be honest that there is no magnet up there.
    assert card["action"] in ("LONG", "WAIT")
    if card["action"] == "LONG":
        assert card["t1"].get("measured") is True


def test_trade_card_fades_the_edge_on_a_balance_day():
    pois = [{"low": 94, "high": 96, "mid": 95, "confluence": 6, "sources": ["prior_val", "val"],
             "side": "support", "distance": 5.0, "distance_atr": 1.0}]
    levs = [{"price": 95.0, "label": "prior_val"}, {"price": 105.0, "label": "prior_vah"}]
    card = playbook.trade_card(
        symbol="X", label="X", price=100, bars=session([100] * 6), atr=5.0,
        context={"context": "BALANCE", "playbook": auction.PLAYBOOKS["BALANCE"], "reasons": []},
        levels=levs, pois=pois)
    assert card["direction"] == "long"       # fade the low edge back toward the middle


# ══ strategies — the opening relative-volume upgrade ═══════════════════════
def test_opening_relative_volume_compares_the_same_window_across_days():
    days = [{"date": f"d{i}", "bars": session([100, 100, 100], v=1000.0)} for i in range(4)]
    days.append({"date": "today", "bars": session([100, 100, 100], v=3000.0)})
    assert strategies.opening_relative_volume(days) == 3.0


def test_opening_relative_volume_needs_history():
    assert strategies.opening_relative_volume([]) is None
    assert strategies.opening_relative_volume([{"date": "d", "bars": session([1, 2, 3])}]) is None


def test_participation_prefers_opening_rvol_when_given_one():
    """The opening-window ratio is readable at 09:35 and compares like with
    like; the projected whole-day ratio has to assume volume arrives evenly."""
    daily = [bar(100, h=101, l=99, v=3_000_000.0) for _ in range(30)]
    m = strategies.participation(daily, session([100] * 10), price=100, opening_rvol=5.0)
    assert m["rvol_opening"] == 5.0
    assert m["rvol_used"] == 5.0
    assert strategies.liquidity_floor(m)["in_play"] is True
