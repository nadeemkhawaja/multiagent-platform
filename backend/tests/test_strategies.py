"""Unit tests for the named strategies — pure functions, synthetic bars, no
network. Run from the backend directory:  python -m pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import strategies as st   # noqa: E402


def bar(c, o=None, h=None, l=None, v=1000.0):
    o = c if o is None else o
    return {"open": o, "high": h if h is not None else max(o, c),
            "low": l if l is not None else min(o, c), "close": c, "volume": v}


def series(closes, **kw):
    return [bar(c, **kw) for c in closes]


# ── primitives ───────────────────────────────────────────────────────────────
def test_ema_seeds_with_sma_and_aligns_with_input():
    out = st.ema([1, 2, 3, 4, 5], 3)
    assert len(out) == 5
    assert out[:2] == [None, None]
    assert out[2] == 2.0                       # SMA of 1,2,3
    assert out[3] == 4 * 0.5 + 2.0 * 0.5       # k = 2/(3+1)


def test_ema_returns_all_none_when_too_short():
    assert st.ema([1, 2], 5) == [None, None]


def test_atr_uses_true_range_including_gaps():
    # TR spans the gap: high 21 against the prior close of 10, not the bar low.
    bars = [bar(10, h=10, l=9), bar(20, h=21, l=19)]
    assert st.atr(bars, 1) == 11.0
    assert st.atr([bar(10)], 14) is None


def test_relative_volume_compares_today_to_the_prior_average():
    bars = [bar(10, v=100.0) for _ in range(10)] + [bar(10, v=300.0)]
    assert st.relative_volume(bars, lookback=10) == 3.0


def test_relative_volume_none_without_enough_history():
    assert st.relative_volume([bar(10)] * 3, lookback=10) is None


def test_gap_pct_measures_open_against_the_prior_close():
    assert st.gap_pct([bar(100), bar(110, o=105)]) == 5.0
    assert st.gap_pct([bar(100)]) is None


def test_continuity_flags_a_polka_dot_chart():
    assert st.continuity([bar(1, v=10.0)] * 10) == 1.0
    mixed = [bar(1, v=10.0)] * 5 + [bar(1, v=0.0)] * 5
    assert st.continuity(mixed) == 0.5
    assert st.continuity([]) == 0.0



# ── Participation + the liquidity floor ─────────────────────────────────────
# The VWAP/EMA-cross state machine and the full Decision Point three-pillar
# screen were deleted: both published a verdict per symbol beside the funnel's
# card, nothing consumed either one, and the only part that was load-bearing was
# the participation metrics the liquidity floor reads. See the module docstring
# and docs/STRATEGY_REVIEW.md.
def test_session_progress_tracks_the_regular_session():
    assert st.session_progress(9 * 60) == 0.05            # pre-market floor
    assert st.session_progress(9 * 60 + 30) == 0.05
    assert st.session_progress(12 * 60 + 45) == 0.5
    assert st.session_progress(16 * 60) == 1.0
    assert st.session_progress(None) == 1.0


def test_projected_relative_volume_corrects_for_a_part_day():
    bars = [bar(10, v=1000.0) for _ in range(11)]
    assert st.relative_volume(bars) == 1.0
    assert st.projected_relative_volume(bars, 0.5) == 2.0
    assert st.projected_relative_volume(bars, 1.0) == 1.0
    assert st.projected_relative_volume([bar(10)] * 3, 0.5) is None


def _in_play_daily():
    """A year-ish of daily bars ending in a 5% gap up on 3x volume, at highs."""
    base = [bar(100 + i * 0.1, h=100 + i * 0.1 + 0.6, l=100 + i * 0.1 - 0.6, v=3_000_000.0)
            for i in range(40)]
    prev = base[-1]
    today = bar(112.0, o=prev["close"] * 1.05, h=113.0, l=110.0, v=9_000_000.0)
    return base + [today]


def test_participation_reports_metrics_and_no_verdict():
    m = st.participation(_in_play_daily(), series([108 + i * 0.1 for i in range(30)]),
                         price=112.0)
    assert m["avg_volume"] == 3_000_000
    assert m["rvol"] == 3.0
    assert m["atr14"] and m["gap_pct"] > 4
    # No verdict field of any kind — the card is the only verdict.
    assert not {"verdict", "signal", "action"} & set(m)


def test_participation_needs_history():
    assert st.participation([bar(10)] * 5, series([10] * 5)) == {}


def test_the_projected_pace_is_what_the_floor_reads():
    """A stock on a 3x pace at 11:00 must not read dead just because the
    session is only a fifth done."""
    daily = _in_play_daily()
    daily[-1]["volume"] = daily[-2]["volume"] * 0.6      # 0.6x raw so far
    session = series([108 + i * 0.1 for i in range(30)], v=200_000.0)
    early = st.participation(daily, session, price=112.0, progress=0.2)
    late = st.participation(daily, session, price=112.0, progress=1.0)
    assert early["rvol_projected"] == 3.0
    assert st.liquidity_floor(early)["pass"] is True
    assert st.liquidity_floor(late)["pass"] is False     # 0.6x finished is dead


def test_opening_rvol_wins_over_the_projection_when_present():
    daily = _in_play_daily()
    session = series([108 + i * 0.1 for i in range(30)], v=200_000.0)
    m = st.participation(daily, session, price=112.0, progress=0.2, opening_rvol=1.4)
    assert m["rvol_used"] == 1.4


def test_the_floor_passes_an_ordinary_liquid_name():
    """2x relative volume is a SCANNER threshold. On a fixed megacap watchlist
    it returns dead nearly every day, which is what the first live run did to
    all 24 symbols — the floor asks only whether anyone is trading this."""
    m = {"avg_volume": 30_000_000, "rvol_used": 0.9, "atr14": 4.0, "continuity": 0.99}
    out = st.liquidity_floor(m)
    assert out["pass"] is True
    assert out["in_play"] is False        # ordinary day, so not an A+ upgrade


def test_the_floor_marks_unusual_activity_in_play():
    m = {"avg_volume": 30_000_000, "rvol_used": 2.6, "atr14": 4.0, "continuity": 0.99}
    assert st.liquidity_floor(m)["in_play"] is True


def test_the_floor_rejects_a_name_nobody_is_trading():
    m = {"avg_volume": 30_000_000, "rvol_used": 0.4, "atr14": 4.0, "continuity": 0.99}
    out = st.liquidity_floor(m)
    assert out["pass"] is False and "quieter than its own normal day" in out["reasons"][0]


def test_the_floor_rejects_a_polka_dot_chart():
    m = {"avg_volume": 30_000_000, "rvol_used": 1.2, "atr14": 4.0, "continuity": 0.4}
    assert st.liquidity_floor(m)["pass"] is False


def test_the_floor_rejects_a_range_too_small_to_pay_the_spread():
    m = {"avg_volume": 30_000_000, "rvol_used": 1.2, "atr14": 0.2, "continuity": 0.99}
    assert st.liquidity_floor(m)["pass"] is False


def test_unknown_metrics_never_fail_the_floor():
    """Early in the session continuity is unknowable, not failing — one empty
    5-minute bar at 09:40 reads as 80% and would condemn a megacap."""
    assert st.liquidity_floor({})["pass"] is True
    assert st.liquidity_floor({"continuity": None, "rvol_used": None})["pass"] is True


def test_participation_line_renders_for_the_email():
    line = st.participation_line({"rvol_used": 1.8, "atr14": 3.2, "gap_pct": 1.4})
    assert "rvol 1.8x" in line and "ATR $3.2" in line
    assert st.participation_line({}) == ""
