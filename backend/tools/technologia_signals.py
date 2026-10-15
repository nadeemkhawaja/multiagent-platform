"""Technologia's signal engine — MFI divergence, approximated VSA/CVD, and a
combined bias score, adapted from the EminiPlayer /ES thinkScript framework
(Volume Profile zones, VSA signals, VWAP/CVD momentum) for Python.

Two things don't survive the port honestly and are approximated, not faked:
  - VSA (Volume Spread Analysis) needs to know whether volume was buy- or
    sell-initiated. We only have OHLCV bars (no tick/bid-ask data), so
    "pressure" here is inferred from where each bar closes within its range
    — a reasonable proxy, not the real thing.
  - CVD (Cumulative Volume Delta) is built the same way: each bar's volume is
    split into an approximate buy/sell portion by close-in-range, not from
    actual trade-side data.
Both are labeled "approx" everywhere they surface so nothing pretends to be
more precise than it is.

Pure math only — no network. compute_for_symbol_sync (in agent14_technologia.py)
does the yfinance fetch and calls into this module.
"""

MFI_PERIOD = 14


def _typical_price(bar: dict) -> float:
    return (bar["high"] + bar["low"] + bar["close"]) / 3


def money_flow_index(bars: list, period: int = MFI_PERIOD) -> list:
    """Volume-weighted RSI. Returns a list aligned to `bars`, with None for
    the warm-up window before `period` money-flow deltas exist."""
    if len(bars) < period + 1:
        return [None] * len(bars)
    tp = [_typical_price(b) for b in bars]
    raw_mf = [tp[i] * (bars[i].get("volume") or 0) for i in range(len(bars))]

    out = [None] * len(bars)
    for i in range(period, len(bars)):
        pos = neg = 0.0
        for j in range(i - period + 1, i + 1):
            if tp[j] > tp[j - 1]:
                pos += raw_mf[j]
            elif tp[j] < tp[j - 1]:
                neg += raw_mf[j]
        if neg == 0:
            out[i] = 100.0
        else:
            ratio = pos / neg
            out[i] = round(100 - 100 / (1 + ratio), 1)
    return out


def mfi_divergence(bars: list, mfi_values: list, lookback: int = 10) -> str:
    """Bullish divergence: price makes a lower low, MFI makes a higher low
    (selling pressure exhausting). Bearish: mirrored at highs. None otherwise.
    Only looks at the most recent `lookback` bars with a valid MFI reading."""
    idx = [i for i in range(len(bars)) if mfi_values[i] is not None]
    recent = idx[-lookback:] if len(idx) >= 2 else idx
    if len(recent) < 2:
        return None

    lows = [(i, bars[i]["low"], mfi_values[i]) for i in recent]
    highs = [(i, bars[i]["high"], mfi_values[i]) for i in recent]

    low1 = min(lows, key=lambda t: t[1])
    lows_before = [t for t in lows if t[0] < low1[0]]
    if lows_before:
        low2 = min(lows_before, key=lambda t: t[1])
        if low1[1] < low2[1] and low1[2] > low2[2]:
            return "bullish"

    high1 = max(highs, key=lambda t: t[1])
    highs_before = [t for t in highs if t[0] < high1[0]]
    if highs_before:
        high2 = max(highs_before, key=lambda t: t[1])
        if high1[1] > high2[1] and high1[2] < high2[2]:
            return "bearish"

    return None


def approximate_vsa(bars: list, lookback: int = 20) -> dict:
    """Volume Spread Analysis approximation: flags the most recent bar as
    stopping/climactic volume when its volume is well above average and its
    range is narrow relative to that volume — a classic VSA "effort vs.
    result" mismatch (heavy effort, little price result = absorption)."""
    if len(bars) < 2:
        return {"signal": None, "note": "insufficient bars"}
    window = bars[-lookback:] if len(bars) >= lookback else bars
    vols = [b.get("volume") or 0 for b in window]
    avg_vol = sum(vols) / len(vols) if vols else 0
    last = bars[-1]
    vol = last.get("volume") or 0
    rng = last["high"] - last["low"]
    avg_rng = sum(b["high"] - b["low"] for b in window) / len(window) if window else 0

    if avg_vol <= 0 or avg_rng <= 0:
        return {"signal": None, "note": "no volume/range data"}

    vol_ratio = vol / avg_vol
    rng_ratio = rng / avg_rng
    close_pos = (last["close"] - last["low"]) / rng if rng > 0 else 0.5  # 0=low, 1=high

    if vol_ratio >= 1.5 and rng_ratio <= 0.8:
        # heavy volume, narrow range — absorption. Direction from where it closed.
        signal = "bullish_absorption" if close_pos >= 0.5 else "bearish_absorption"
    elif vol_ratio >= 1.5 and close_pos >= 0.7:
        signal = "buying_pressure"
    elif vol_ratio >= 1.5 and close_pos <= 0.3:
        signal = "selling_pressure"
    else:
        signal = None

    return {"signal": signal, "vol_ratio": round(vol_ratio, 2), "close_pos": round(close_pos, 2)}


def approximate_cvd(bars: list) -> dict:
    """Cumulative volume delta approximation: each bar's volume is split into
    a buy/sell portion by where the close falls within the bar's range
    (close near the high → mostly buy volume, near the low → mostly sell).
    Returns the running series' final value and its short-term trend."""
    if not bars:
        return {"cvd": None, "trend": None}
    cvd = 0.0
    series = []
    for b in bars:
        rng = b["high"] - b["low"]
        vol = b.get("volume") or 0
        close_pos = (b["close"] - b["low"]) / rng if rng > 0 else 0.5
        delta = vol * (2 * close_pos - 1)  # -vol..+vol
        cvd += delta
        series.append(cvd)
    trend = None
    if len(series) >= 5:
        recent_slope = series[-1] - series[-5]
        trend = "up" if recent_slope > 0 else "down" if recent_slope < 0 else "flat"
    return {"cvd": round(cvd, 0), "trend": trend}


def bias_score(vwap_position: str, mfi: float, divergence: str, vsa: dict, cvd: dict) -> dict:
    """Combine signals into a 0-6 bull/bear score (mirrors the source
    material's 0-6 VSA score, arrows fire at score >= 3). Positive = bullish
    lean, negative = bearish; magnitude is confidence."""
    score = 0
    reasons = []

    if vwap_position == "above":
        score += 1; reasons.append("price above VWAP")
    elif vwap_position == "below":
        score -= 1; reasons.append("price below VWAP")

    if mfi is not None:
        if mfi <= 20:
            score += 1; reasons.append(f"MFI oversold ({mfi})")
        elif mfi >= 80:
            score -= 1; reasons.append(f"MFI overbought ({mfi})")

    if divergence == "bullish":
        score += 2; reasons.append("bullish MFI divergence")
    elif divergence == "bearish":
        score -= 2; reasons.append("bearish MFI divergence")

    vsa_sig = (vsa or {}).get("signal")
    if vsa_sig in ("bullish_absorption", "buying_pressure"):
        score += 1; reasons.append(f"VSA approx: {vsa_sig}")
    elif vsa_sig in ("bearish_absorption", "selling_pressure"):
        score -= 1; reasons.append(f"VSA approx: {vsa_sig}")

    cvd_trend = (cvd or {}).get("trend")
    if cvd_trend == "up":
        score += 1; reasons.append("CVD approx trending up")
    elif cvd_trend == "down":
        score -= 1; reasons.append("CVD approx trending down")

    direction = "bullish" if score >= 3 else "bearish" if score <= -3 else "neutral"
    return {"score": score, "abs_score": abs(score), "direction": direction, "reasons": reasons}
