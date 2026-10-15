"""Tests for tools/levels.py — VWAP, volume profile, and swing support/resistance.
Pure math only; no network. Run from backend:  python -m pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import levels


def bar(o, h, l, c, v):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


# ── session_vwap ─────────────────────────────────────────────────────────────
def test_vwap_weights_by_volume():
    bars = [bar(10, 10, 10, 10, 100), bar(20, 20, 20, 20, 300)]
    # typical price == close for these flat bars: (10*100 + 20*300) / 400 = 17.5
    assert levels.session_vwap(bars) == 17.5


def test_vwap_none_when_no_volume():
    bars = [bar(10, 11, 9, 10, 0), bar(11, 12, 10, 11, 0)]
    assert levels.session_vwap([]) is None
    assert levels.session_vwap(bars) is None


def test_vwap_position_thresholds():
    assert levels.vwap_position(101, 100) == "above"   # +1%
    assert levels.vwap_position(99, 100) == "below"    # -1%
    assert levels.vwap_position(100.05, 100) == "at"   # within +-0.15%
    assert levels.vwap_position(None, 100) == "unknown"
    assert levels.vwap_position(100, None) == "unknown"


# ── volume_profile ───────────────────────────────────────────────────────────
def test_volume_profile_poc_is_highest_volume_bin():
    bars = [
        bar(100, 101, 99, 100, 10),
        bar(100, 105, 104, 105, 500),   # heavy volume concentrated near 104-105
        bar(100, 101, 99, 100, 10),
    ]
    profile = levels.volume_profile(bars, num_bins=10)
    assert profile["poc"] == profile["poc"]  # sanity: didn't crash
    assert 104 <= profile["poc"] <= 105.5
    assert profile["session_low"] == 99
    assert profile["session_high"] == 105


def test_volume_profile_empty_bars():
    assert levels.volume_profile([]) == {}


def test_volume_profile_flat_range_returns_empty():
    bars = [bar(10, 10, 10, 10, 100)]  # hi == lo, no real range
    assert levels.volume_profile(bars) == {}


# ── swing_levels ─────────────────────────────────────────────────────────────
def test_swing_levels_finds_fractal_highs_and_lows():
    # A clean V shape: descends to a low at index 5, then rises — index 5
    # should register as a swing low (support).
    closes = [110, 108, 106, 104, 102, 100, 102, 104, 106, 108, 110]
    bars = [bar(c, c + 1, c - 1, c, 100) for c in closes]
    lv = levels.swing_levels(bars, lookback=3)
    assert any(abs(s - 99) <= 1 for s in lv["support"])


def test_swing_levels_clusters_nearby_levels():
    # Two lows within 0.25% of each other should merge into one support level.
    closes = [110, 108, 100.00, 108, 110, 108, 100.20, 108, 110]
    bars = [bar(c, c + 1, c - 1, c, 100) for c in closes]
    lv = levels.swing_levels(bars, lookback=1, cluster_pct=0.01)
    supports_near_100 = [s for s in lv["support"] if 99 <= s <= 101]
    assert len(supports_near_100) == 1


def test_swing_levels_empty_bars():
    lv = levels.swing_levels([])
    assert lv == {"support": [], "resistance": []}


# ── nearest_levels ───────────────────────────────────────────────────────────
def test_nearest_levels_picks_closest_below_and_above():
    near = levels.nearest_levels(100, support=[90, 95, 98], resistance=[102, 105, 110])
    assert near["support"] == 98
    assert near["resistance"] == 102


def test_nearest_levels_falls_back_when_price_outside_range():
    # price below every known support — fall back to the lowest support as a floor
    near = levels.nearest_levels(80, support=[90, 95], resistance=[102])
    assert near["support"] == 90
    near2 = levels.nearest_levels(120, support=[90], resistance=[100, 105])
    assert near2["resistance"] == 105


def test_nearest_levels_handles_missing_price_or_empty_lists():
    assert levels.nearest_levels(None, [1], [2]) == {"support": None, "resistance": None}
    assert levels.nearest_levels(100, [], []) == {"support": None, "resistance": None}


# ── summary_line ─────────────────────────────────────────────────────────────
def test_summary_line_includes_available_fields():
    line = levels.summary_line({"vwap": 100.5, "vwap_position": "above",
                                 "poc": 101.0, "nearest_support": 98, "nearest_resistance": 103})
    assert "VWAP 100.5" in line
    assert "support 98" in line
    assert "resistance 103" in line


def test_summary_line_empty_when_no_data():
    assert levels.summary_line({}) == "no levels data"
