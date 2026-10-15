"""Fair value gaps, order blocks, structure shifts and liquidity sweeps.
========================================================================
The "smart money concepts" vocabulary (ICT and its descendants), implemented as
plain geometry over OHLCV bars so it can be tested rather than eyeballed.

Every function here is deliberately *mechanical*. The discretionary versions of
these ideas are unfalsifiable — on any chart you can find a gap or a block that
explains what already happened. What makes them tradeable is a fixed definition
plus a size floor: an FVG smaller than a fraction of ATR is measurement noise,
not an imbalance, and there is one on nearly every bar.

What each concept is used for downstream (see playbook.py):
  fair_value_gaps   candidate ENTRY zones on a pullback, with a 50% midpoint
  order_blocks      candidate ENTRY zones, stronger when they carry an FVG
  swing_points      the structural stop levels, and the raw material for MSS
  structure_shift   the TRIGGER — proof the pullback is over
  liquidity_sweeps  the TRIGGER — proof a level was raided and rejected

Bars are dicts {"open","high","low","close","volume"}, oldest first.
"""

# An imbalance narrower than this fraction of ATR is noise, not displacement.
MIN_GAP_ATR = 0.10
# The middle bar of an FVG must be a real move, not a doji with long wicks.
MIN_DISPLACEMENT_BODY = 0.55        # body / total range
MAX_ZONES = 6


def _body(b) -> float:
    return abs(b["close"] - b["open"])


def _range(b) -> float:
    return max(b["high"] - b["low"], 1e-9)


def displacement(bar: dict, atr=None) -> bool:
    """A conviction bar: mostly body, little wick, and large enough to matter.
    This is the gate that separates a real imbalance from a wide-ranging doji."""
    if _body(bar) / _range(bar) < MIN_DISPLACEMENT_BODY:
        return False
    return not atr or _range(bar) >= MIN_GAP_ATR * 2 * atr


# ── Fair value gaps ─────────────────────────────────────────────────────────
def fair_value_gaps(bars: list, atr=None, max_out: int = MAX_ZONES) -> list:
    """Three-bar imbalances that price has not yet traded back through.

    Bullish FVG: bar 3's low is above bar 1's high — the market moved so fast
    that the range between them never traded. Bearish is the mirror.

    Each gap carries `ce` (consequent encroachment, the 50% midpoint), which is
    the level price reacts from far more often than the edge, and `mitigated`,
    which tracks how much of the gap has since been filled. A gap price has
    fully traded back through is dropped — it did its job.
    """
    if len(bars or []) < 3:
        return []
    out = []
    for i in range(2, len(bars)):
        b1, b2, b3 = bars[i - 2], bars[i - 1], bars[i]
        if not displacement(b2, atr):
            continue
        if b3["low"] > b1["high"]:
            lo, hi, side = b1["high"], b3["low"], "bullish"
        elif b3["high"] < b1["low"]:
            lo, hi, side = b3["high"], b1["low"], "bearish"
        else:
            continue
        size = hi - lo
        if atr and size < MIN_GAP_ATR * atr:
            continue
        # Fill state from every bar after the gap formed.
        after = bars[i + 1:]
        if after:
            deepest = min(b["low"] for b in after) if side == "bullish" else max(b["high"] for b in after)
            filled = (hi - deepest) if side == "bullish" else (deepest - lo)
            frac = max(0.0, min(1.0, filled / size))
        else:
            frac = 0.0
        if frac >= 1.0:
            continue                      # fully mitigated — no longer a zone
        out.append({"kind": "fvg", "side": side, "low": round(lo, 2), "high": round(hi, 2),
                    "ce": round((lo + hi) / 2, 2), "size": round(size, 2),
                    "mitigated": round(frac, 2), "age": len(bars) - 1 - i})
    return out[-max_out:]


# ── Order blocks ────────────────────────────────────────────────────────────
def order_blocks(bars: list, atr=None, max_out: int = MAX_ZONES) -> list:
    """The last opposing candle before a displacement move.

    A bullish order block is the last down-close bar before an up displacement;
    price returning to it is returning to where the move was launched from.
    `with_fvg` marks blocks whose launch also left an imbalance behind — the
    pairing that turns an ordinary block into a high-probability zone.
    """
    if len(bars or []) < 3:
        return []
    out = []
    # i indexes the BLOCK; the drive is the bar right after it. Starting at 1
    # would silently skip a block sitting on the first bar of the series.
    for i in range(len(bars) - 1):
        drive = bars[i + 1]
        if not displacement(drive, atr):
            continue
        prev = bars[i]
        up_drive = drive["close"] > drive["open"]
        if up_drive and prev["close"] < prev["open"]:
            side, lo, hi = "bullish", prev["low"], prev["high"]
        elif not up_drive and prev["close"] > prev["open"]:
            side, lo, hi = "bearish", prev["low"], prev["high"]
        else:
            continue
        if atr and (hi - lo) < MIN_GAP_ATR * atr:
            continue
        after = bars[i + 2:]
        # A block is spent once price closes through its far side.
        if after:
            if side == "bullish" and min(b["close"] for b in after) < lo:
                continue
            if side == "bearish" and max(b["close"] for b in after) > hi:
                continue
        gap_here = bool(fair_value_gaps(bars[i:i + 3], atr, max_out=1))
        out.append({"kind": "ob", "side": side, "low": round(lo, 2), "high": round(hi, 2),
                    "ce": round((lo + hi) / 2, 2), "size": round(hi - lo, 2),
                    "with_fvg": gap_here, "age": len(bars) - 1 - i})
    return out[-max_out:]


# ── Structure ───────────────────────────────────────────────────────────────
def swing_points(bars: list, lookback: int = 2) -> dict:
    """Fractal swing highs and lows as (index, price) pairs, oldest first.
    `lookback` bars on each side must be lower (higher) — 2 is the intraday
    default; raise it for daily bars where noise is cheaper to ignore."""
    highs, lows = [], []
    for i in range(lookback, len(bars or []) - lookback):
        w = bars[i - lookback:i + lookback + 1]
        if bars[i]["high"] == max(b["high"] for b in w):
            highs.append((i, bars[i]["high"]))
        if bars[i]["low"] == min(b["low"] for b in w):
            lows.append((i, bars[i]["low"]))
    return {"highs": highs, "lows": lows}


def structure_shift(bars: list, lookback: int = 2) -> dict:
    """Break of structure / market structure shift on the most recent bars.

    Reports the direction of the last CLOSE through a prior swing point, and
    whether it continued the existing trend (BOS) or reversed it (MSS). This is
    the trigger the playbook waits for: touching a zone proves nothing, closing
    through the swing that created the pullback proves the pullback is over.
    """
    sw = swing_points(bars, lookback)
    if not bars or (not sw["highs"] and not sw["lows"]):
        return {}
    last_close = bars[-1]["close"]
    prior_highs = [p for i, p in sw["highs"] if i < len(bars) - 1]
    prior_lows = [p for i, p in sw["lows"] if i < len(bars) - 1]

    broke_up = bool(prior_highs) and last_close > max(prior_highs[-2:])
    broke_down = bool(prior_lows) and last_close < min(prior_lows[-2:])
    if broke_up == broke_down:                    # neither, or a bar that did both
        return {"direction": None, "kind": None}

    direction = "long" if broke_up else "short"
    # Trend before the break: rising swing lows = up, falling swing highs = down.
    trend = None
    if len(prior_lows) >= 2 and len(prior_highs) >= 2:
        if prior_lows[-1] > prior_lows[-2] and prior_highs[-1] > prior_highs[-2]:
            trend = "long"
        elif prior_lows[-1] < prior_lows[-2] and prior_highs[-1] < prior_highs[-2]:
            trend = "short"
    kind = "BOS" if trend == direction else "MSS" if trend else "BREAK"
    level = max(prior_highs[-2:]) if broke_up else min(prior_lows[-2:])
    return {"direction": direction, "kind": kind, "level": round(level, 2),
            "note": f"{kind} {direction} through {round(level, 2)}"}


# ── Liquidity ───────────────────────────────────────────────────────────────
def liquidity_sweeps(bars: list, levels: list, atr=None, window: int = 6) -> list:
    """Levels that were wicked through and then rejected inside `window` bars.

    This is the mechanical form of the rule the platform already states in
    prose — "the first opening-range breakout is typically a liquidity grab,
    trade the reversal, not the breakout". A sweep is a stop run: price takes
    out the level, finds no continuation, and closes back on the original side.
    The reversal it sets up is the highest-quality trigger in this module.
    """
    if len(bars or []) < 2 or not levels:
        return []
    start = max(1, len(bars) - window)
    pairs = [(bars[i - 1], bars[i]) for i in range(start, len(bars))]
    out = []
    for lvl in levels:
        px = lvl.get("price") if isinstance(lvl, dict) else lvl
        if px is None:
            continue
        # The bar BEFORE the excursion must already be on the side price
        # returns to. Without that precondition a bar that opens below a level
        # and closes above it — an ordinary breakout — reads as a sweep of that
        # level from above, and the trigger fires on exactly the wrong side.
        swept_high = any(prev["close"] < px and b["high"] > px and b["close"] < px
                         for prev, b in pairs)
        swept_low = any(prev["close"] > px and b["low"] < px and b["close"] > px
                        for prev, b in pairs)
        if not (swept_high or swept_low):
            continue
        recent = [b for _, b in pairs]
        depth = (max(b["high"] for b in recent) - px) if swept_high else (px - min(b["low"] for b in recent))
        if atr and depth < 0.05 * atr:
            continue                       # a tick through is not a raid
        out.append({"price": round(px, 2), "side": "short" if swept_high else "long",
                    "depth": round(depth, 2),
                    "label": (lvl.get("label") if isinstance(lvl, dict) else None),
                    "note": (f"swept {'above' if swept_high else 'below'} {round(px, 2)} "
                             f"and closed back {'below' if swept_high else 'above'} it")})
    return out
