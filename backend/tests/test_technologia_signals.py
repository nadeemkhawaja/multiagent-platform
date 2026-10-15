"""Tests for tools/technologia_signals.py — MFI, divergence, VSA/CVD
approximation, and the combined bias score. Pure math only; no network.
Run from backend:  python -m pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import technologia_signals as sig


def bar(o, h, l, c, v):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


# ── money_flow_index ─────────────────────────────────────────────────────────
def test_mfi_none_during_warmup():
    bars = [bar(10, 11, 9, 10, 100) for _ in range(5)]
    out = sig.money_flow_index(bars, period=14)
    assert all(v is None for v in out)


def test_mfi_100_when_no_negative_flow():
    # Strictly rising typical price every bar → no negative money flow.
    bars = [bar(10 + i, 11 + i, 9 + i, 10 + i, 100) for i in range(20)]
    out = sig.money_flow_index(bars, period=14)
    assert out[-1] == 100.0


def test_mfi_low_when_strictly_falling():
    bars = [bar(30 - i, 31 - i, 29 - i, 30 - i, 100) for i in range(20)]
    out = sig.money_flow_index(bars, period=14)
    assert out[-1] == 0.0


# ── mfi_divergence ───────────────────────────────────────────────────────────
def test_bullish_divergence_lower_low_higher_mfi():
    # Swing low at 95 (mfi 30), bounce to 105, then a lower low at 90 but MFI
    # rises to 40 — classic bullish divergence (selling pressure exhausting).
    bars, mfi = [], []
    for lo, m in [(100, 50), (95, 30), (105, 55), (90, 40)]:
        bars.append(bar(lo + 2, lo + 3, lo, lo + 1, 100))
        mfi.append(m)
    assert sig.mfi_divergence(bars, mfi) == "bullish"


def test_bearish_divergence_higher_high_lower_mfi():
    bars, mfi = [], []
    for hi, m in [(100, 50), (105, 70), (95, 40), (110, 60)]:
        bars.append(bar(hi - 2, hi, hi - 3, hi - 1, 100))
        mfi.append(m)
    assert sig.mfi_divergence(bars, mfi) == "bearish"


def test_no_divergence_when_insufficient_data():
    assert sig.mfi_divergence([], []) is None
    assert sig.mfi_divergence([bar(1, 2, 0, 1, 10)], [50]) is None


# ── approximate_vsa ──────────────────────────────────────────────────────────
def test_vsa_bullish_absorption_heavy_volume_narrow_range_close_high():
    window = [bar(10, 11, 9, 10, 100) for _ in range(19)]
    # Last bar: much heavier volume, narrower range, closes near the high.
    window.append(bar(10, 10.5, 10, 10.45, 300))
    out = sig.approximate_vsa(window)
    assert out["signal"] == "bullish_absorption"


def test_vsa_buying_pressure_heavy_volume_wide_range_close_high():
    window = [bar(10, 11, 9, 10, 100) for _ in range(19)]
    window.append(bar(10, 13, 9.5, 12.8, 300))
    out = sig.approximate_vsa(window)
    assert out["signal"] == "buying_pressure"


def test_vsa_none_when_volume_unremarkable():
    window = [bar(10, 11, 9, 10, 100) for _ in range(20)]
    out = sig.approximate_vsa(window)
    assert out["signal"] is None


def test_vsa_insufficient_bars():
    assert sig.approximate_vsa([])["signal"] is None
    assert sig.approximate_vsa([bar(1, 2, 0, 1, 10)])["signal"] is None


# ── approximate_cvd ──────────────────────────────────────────────────────────
def test_cvd_trends_up_on_closes_near_highs():
    bars = [bar(10, 12, 9, 11.8, 100) for _ in range(6)]  # closes near high each bar
    out = sig.approximate_cvd(bars)
    assert out["trend"] == "up"
    assert out["cvd"] > 0


def test_cvd_trends_down_on_closes_near_lows():
    bars = [bar(10, 12, 9, 9.2, 100) for _ in range(6)]  # closes near low each bar
    out = sig.approximate_cvd(bars)
    assert out["trend"] == "down"
    assert out["cvd"] < 0


def test_cvd_empty_bars():
    out = sig.approximate_cvd([])
    assert out == {"cvd": None, "trend": None}


# ── bias_score ────────────────────────────────────────────────────────────────
def test_bias_score_strong_bullish_confluence():
    out = sig.bias_score("above", 18, "bullish", {"signal": "buying_pressure"}, {"trend": "up"})
    assert out["direction"] == "bullish"
    assert out["score"] == 6
    assert len(out["reasons"]) == 5


def test_bias_score_strong_bearish_confluence():
    out = sig.bias_score("below", 85, "bearish", {"signal": "selling_pressure"}, {"trend": "down"})
    assert out["direction"] == "bearish"
    assert out["score"] == -6


def test_bias_score_neutral_when_signals_conflict():
    out = sig.bias_score("above", 50, None, {"signal": None}, {"trend": "down"})
    assert out["direction"] == "neutral"
    assert -2 <= out["score"] <= 2


def test_bias_score_handles_missing_data():
    out = sig.bias_score("unknown", None, None, None, None)
    assert out["score"] == 0
    assert out["direction"] == "neutral"
    assert out["reasons"] == []
