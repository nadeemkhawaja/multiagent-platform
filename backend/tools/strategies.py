"""
Participation metrics — pure functions over bar lists.
======================================================
Everything here is computed from real bars (no LLM), takes plain dicts, and
returns plain dicts, so each rule is unit-testable without network or DB.

This module used to publish two more verdict engines beside the funnel — a
VWAP/EMA-cross state machine and the full "Decision Point" three-pillar in-play
screen. Both were displayed and then ignored: the funnel in tools/playbook.py is
what actually decides a trade, and it only ever consumed the participation
METRICS from Decision Point (via liquidity_floor). Three engines publishing three
verdicts for the same symbol is how the Technologia tab could read ENTER, +2
neutral and DEAD at once, and how the two trading tabs ended up describing
different worlds. See docs/STRATEGY_REVIEW.md.

So what survives is the part that was load-bearing: how much is this name
actually trading today, and is that enough to trade it at all.

Bars are dicts: {"open","high","low","close","volume"}, oldest first.
"""

# ── primitives ───────────────────────────────────────────────────────────────
def ema(values: list, period: int) -> list:
    """Exponential moving average, seeded with the SMA of the first `period`
    values. Returns a list the same length as `values`, None before the seed —
    so index alignment with the bars is never off by one."""
    if not values or period <= 0 or len(values) < period:
        return [None] * len(values)
    out = [None] * (period - 1)
    seed = sum(values[:period]) / period
    out.append(seed)
    k = 2 / (period + 1)
    prev = seed
    for v in values[period:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def atr(bars: list, period: int = 14):
    """Average true range (Wilder's true range, simple mean). None if short."""
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    return round(sum(trs[-period:]) / period, 4)


def intraday_atr(bars: list, min_bars: int = 20):
    """What a normal intraday bar is worth today, measured across the WHOLE session.

    atr(bars, 14) is right for daily bars but wrong here: on 5-minute bars it
    averages the last 14 — seventy minutes — so it reports whatever the most
    recent stretch happened to look like. Measured against the session median the
    last-14 window ran 24% low on CSCO and 57% HIGH on TSLA in the same run — the
    instability is the defect, in both directions.

    The median true range is the fix. It spans the session, so it is not a
    snapshot, and it ignores the tails at both ends — the opening bar and a
    late-day spike alike — which a mean does not.

    NOTE: this is deliberately NOT comparable to the daily ATR by any simple
    factor. Daily true range includes overnight gaps; an intraday bar range
    cannot, so the daily:intraday ratio sits around 16-25x on real data and that
    is normal, not a fault. Do not "fix" one to match the other. It is also why
    the STOP floor in playbook.py is scaled to the DAILY figure: two intraday
    median bars on a megacap is a few cents, and a few cents is not a stop.
    """
    if len(bars) < min_bars + 1:
        return None
    trs = sorted(max(bars[i]["high"] - bars[i]["low"],
                     abs(bars[i]["high"] - bars[i - 1]["close"]),
                     abs(bars[i]["low"] - bars[i - 1]["close"]))
                 for i in range(1, len(bars)))
    mid = len(trs) // 2
    med = trs[mid] if len(trs) % 2 else (trs[mid - 1] + trs[mid]) / 2
    return round(med, 4) or None


def relative_volume(daily_bars: list, lookback: int = 10):
    """Today's volume as a multiple of the average of the prior `lookback`
    sessions."""
    if len(daily_bars) < lookback + 1:
        return None
    prior = [b["volume"] for b in daily_bars[-(lookback + 1):-1]]
    avg = sum(prior) / len(prior) if prior else 0
    if not avg:
        return None
    return round(daily_bars[-1]["volume"] / avg, 2)


def session_progress(minutes_et: int) -> float:
    """How much of the 9:30-16:00 ET session has elapsed, as 0.05..1.0.
    Before the open it is the 0.05 floor (premarket volume is compared against
    a token slice of the day, not the whole thing); after the close, 1.0."""
    open_m, close_m = 9 * 60 + 30, 16 * 60
    if minutes_et is None:
        return 1.0
    if minutes_et <= open_m:
        return 0.05
    if minutes_et >= close_m:
        return 1.0
    return max(0.05, round((minutes_et - open_m) / (close_m - open_m), 4))


def projected_relative_volume(daily_bars: list, progress: float, lookback: int = 10):
    """Relative volume corrected for how much of the session has actually
    happened. Comparing a half-finished day against ten completed ones makes
    every stock look thin until the closing bell — the raw ratio at 11:00 is
    mechanically about a fifth of what the day will finish at."""
    rvol = relative_volume(daily_bars, lookback)
    if rvol is None or not progress:
        return None
    return round(rvol / progress, 2)


def opening_relative_volume(sessions: list, lookback_bars: int = 3):
    """Today's OPENING volume against the same opening window on prior days.

    Zarattini, Barbon & Aziz ("A Profitable Day Trading Strategy For The U.S.
    Equity Market", SFI 24-98) select their tradeable universe by dividing the
    day's first 5-minute volume by the average first 5-minute volume of the
    prior 14 sessions, and it is a materially better instrument than the
    whole-day ratio:

      - it is READABLE AT 09:35, before any entry decision has to be made,
        instead of only becoming meaningful near the close;
      - it compares like with like. projected_relative_volume() divides a
        part-day total by elapsed session fraction, which assumes volume
        arrives at a constant rate. It does not — the open and the close are
        several times heavier than midday, so the projection systematically
        over-reads in the first half hour and under-reads at lunch.

    `sessions` is [{"date", "bars"}] oldest first, current session last, as
    returned by levels.fetch_recent_sessions_sync(). Returns None when there
    isn't enough history to compare against.
    """
    if len(sessions or []) < 3:
        return None

    def rth(bars):
        return [b for b in bars if b.get("t") is None or 570 <= b["t"] < 960] or bars

    # The comparison window is capped by how many bars TODAY actually has. At
    # 09:35 today holds one bar; measuring it against three bars of every prior
    # day would report a third of the real ratio and mark every name dead for
    # the first fifteen minutes of the session.
    today_bars = rth(sessions[-1]["bars"])
    n = min(lookback_bars, len(today_bars))
    if n <= 0:
        return None

    def opening_volume(bars):
        return sum(b.get("volume") or 0 for b in rth(bars)[:n])

    today = sum(b.get("volume") or 0 for b in today_bars[:n])
    prior = [opening_volume(s["bars"]) for s in sessions[:-1]]
    prior = [v for v in prior if v > 0]
    if not prior or not today:
        return None
    return round(today / (sum(prior) / len(prior)), 2)


def average_volume(daily_bars: list, lookback: int = 10):
    if len(daily_bars) < lookback + 1:
        return None
    prior = [b["volume"] for b in daily_bars[-(lookback + 1):-1]]
    return round(sum(prior) / len(prior), 0) if prior else None


def gap_pct(daily_bars: list):
    """Today's open versus the prior close, in percent."""
    if len(daily_bars) < 2:
        return None
    prev_close = daily_bars[-2]["close"]
    if not prev_close:
        return None
    return round((daily_bars[-1]["open"] - prev_close) / prev_close * 100, 2)


def continuity(bars: list) -> float:
    """Share of session bars that actually traded. A chart of disconnected dots
    means no real order flow, and the pattern you think you see on it is not
    backed by participants."""
    if not bars:
        return 0.0
    traded = sum(1 for b in bars if (b.get("volume") or 0) > 0)
    return round(traded / len(bars), 3)


# ── Participation ────────────────────────────────────────────────────────────
MIN_RVOL = 2.0                 # unusual activity — a quality upgrade, not a gate
MIN_CONTINUITY = 0.90          # below this the tape is dots, not flow
# Continuity is a ratio, and a ratio over five bars is not evidence. Ten
# minutes into the session one empty 5-minute bar reads as 80% and condemns a
# megacap as having no order flow — which is what the first live run did to
# NVDA and MU. Below this many bars the check reports "unknown", not "fail".
MIN_CONTINUITY_BARS = 10


def participation(daily_bars: list, session_bars: list, price=None,
                  progress: float = 1.0, opening_rvol=None) -> dict:
    """How much is this name actually trading today?

    Returns a flat metrics dict — no verdict. liquidity_floor() below turns it
    into the one decision anybody needs from it, and playbook.trade_card() reads
    that. Nothing else in the platform grades a symbol any more.
    """
    if len(daily_bars or []) < 12:
        return {}
    price = price if price is not None else daily_bars[-1]["close"]
    cont = continuity(session_bars)
    n_bars = len(session_bars or [])
    rvol = relative_volume(daily_bars)
    rvol_proj = projected_relative_volume(daily_bars, progress)
    # Opening relative volume is preferred when the caller computed it: it is
    # readable at 09:35 and compares the same window across days, where the
    # projected whole-day ratio has to assume volume arrives evenly and doesn't.
    rvol_used = opening_rvol if opening_rvol is not None else rvol_proj
    return {
        "avg_volume": average_volume(daily_bars),
        "rvol": rvol, "rvol_projected": rvol_proj, "rvol_opening": opening_rvol,
        "rvol_used": rvol_used, "session_progress": progress,
        "atr14": atr(daily_bars, 14), "gap_pct": gap_pct(daily_bars),
        "continuity": cont if n_bars >= MIN_CONTINUITY_BARS else None,
        "continuity_bars": n_bars, "price": round(price, 2),
    }


# ── The liquidity floor ─────────────────────────────────────────────────────
# 2x relative volume is a SCANNER threshold. Its source uses it to find the
# handful of stocks in play out of thousands — "which names should be on my
# screen today". Applied instead to a fixed megacap watchlist it is a different
# test entirely, and one almost nothing can pass: a watchlist is already a
# pre-selection, so demanding that every member also be twice as active as usual
# returns DEAD nearly every day. That is what the live run showed on all 24
# symbols.
#
# The narrower claim worth keeping: do not trade a stock nobody is trading. So
# the floor asks whether a name is participating at all, and 2x relative volume
# is a grade upgrade rather than a gate.
FLOOR_RVOL = 0.7          # below ~70% of its own normal pace, a name is dead
FLOOR_AVG_VOLUME = 500_000
FLOOR_ATR = 0.50


def liquidity_floor(metrics: dict) -> dict:
    """Is there enough participation to trade this name at all today?

    Takes participation()'s metrics dict. Returns {"pass", "reasons",
    "in_play"} — `in_play` is the full 2x bar, kept as the quality signal it is,
    while `pass` is the much lower "not dead" bar that actually gates a trade.
    """
    avg_vol = metrics.get("avg_volume")
    rvol = metrics.get("rvol_used") or metrics.get("rvol_projected")
    atr14 = metrics.get("atr14")
    cont = metrics.get("continuity")

    fails = []
    if avg_vol is not None and avg_vol < FLOOR_AVG_VOLUME:
        fails.append(f"{avg_vol:,.0f} average volume — too thin to fill a stop")
    if atr14 is not None and atr14 < FLOOR_ATR:
        fails.append(f"ATR ${atr14} — the range can't pay for the spread")
    if cont is not None and cont < MIN_CONTINUITY:
        fails.append(f"only {cont:.0%} of session bars traded — no continuous order flow")
    if rvol is not None and rvol < FLOOR_RVOL:
        fails.append(f"{rvol}x relative volume — quieter than its own normal day")

    return {"pass": not fails, "reasons": fails,
            "in_play": rvol is not None and rvol >= MIN_RVOL,
            "rvol": rvol}


def participation_line(m: dict) -> str:
    """One-line rendering for the email and the LLM context."""
    if not m:
        return ""
    bits = []
    if m.get("rvol_used") is not None:
        bits.append(f"rvol {m['rvol_used']}x")
    if m.get("atr14") is not None:
        bits.append(f"ATR ${m['atr14']}")
    if m.get("gap_pct") is not None:
        bits.append(f"gap {m['gap_pct']:+.2f}%")
    return " · ".join(bits)
