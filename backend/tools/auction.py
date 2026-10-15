"""Auction context — the layer that says what KIND of day this is.
==================================================================
Adapted from the market-profile / auction-market framework the rest of this
platform already leans on (EminiPlayer's daily zones + trade plan, which is
Dalton's "Mind Over Markets" applied to /ES), this module answers the one
question the old signal stack never asked: *is today a day to buy pullbacks,
fade edges, or sit out?*

Why it exists. tools/technologia_signals.bias_score() sums a momentum signal
(price above VWAP, +1) and a mean-reversion signal (MFI overbought, -1) into a
single number, so a strong trend day — the easiest day to trade — nets to zero
and reads "neutral". Momentum and reversion are not opposite ends of one axis;
they are different playbooks that apply on different days. Splitting the day
type out of the score is what makes the rest of the stack coherent:

    CONTEXT (this module)  →  which playbook is legal today
    LOCATION (playbook.py) →  the price zone to act at
    TRIGGER  (smc.py)      →  what must happen before clicking

Pure math over plain OHLCV dicts, oldest first. Bars may carry an optional
integer "t" (minutes since midnight ET); functions that need the clock say so
and degrade to None rather than guessing when it's absent.
"""

RTH_OPEN = 9 * 60 + 30      # 09:30 ET
RTH_CLOSE = 16 * 60         # 16:00 ET
IB_MINUTES = 60             # Dalton's initial balance: the first hour

# An IB narrower than this fraction of the 14-day ATR is a "narrow base" — the
# lamp is easy to knock over, so range extension is the expectation.
NARROW_IB_ATR = 0.35
WIDE_IB_ATR = 0.75


# ── Session slicing ─────────────────────────────────────────────────────────
def rth_bars(bars: list) -> list:
    """Regular-hours bars only. Bars without a "t" are assumed to be RTH
    already (that is what fetch_session_bars_sync returned historically)."""
    if not bars:
        return []
    if bars[0].get("t") is None:
        return list(bars)
    return [b for b in bars if RTH_OPEN <= b["t"] < RTH_CLOSE]


def overnight_bars(bars: list) -> list:
    """Globex/pre-market bars — everything outside RTH. Empty for equities
    without pre-market prints, which is a correct answer, not a failure."""
    if not bars or bars[0].get("t") is None:
        return []
    return [b for b in bars if b["t"] < RTH_OPEN or b["t"] >= RTH_CLOSE]


def _hi_lo(bars: list):
    if not bars:
        return None, None
    return round(max(b["high"] for b in bars), 2), round(min(b["low"] for b in bars), 2)


# ── Prior-day and overnight reference levels ────────────────────────────────
def prior_day_levels(daily_bars: list) -> dict:
    """PDH / PDL / PDC and the prior day's midpoint. These are the levels every
    desk marks before the open; nothing in the old stack computed them, which
    is why stops were being anchored to 3-month swing lows instead."""
    if len(daily_bars or []) < 2:
        return {}
    p = daily_bars[-2]
    return {"pdh": round(p["high"], 2), "pdl": round(p["low"], 2),
            "pdc": round(p["close"], 2), "pdm": round((p["high"] + p["low"]) / 2, 2)}


def overnight_range(bars: list) -> dict:
    """ONH/ONL from the pre-RTH bars of the current session. For /ES and /NQ
    this is the real overnight auction; for equities it is pre-market."""
    on = [b for b in overnight_bars(bars) if b["t"] < RTH_OPEN]
    hi, lo = _hi_lo(on)
    return {"onh": hi, "onl": lo} if hi is not None else {}


def initial_balance(bars: list, minutes: int = IB_MINUTES, atr=None) -> dict:
    """The first hour's range — the day's base. A narrow base relative to ATR
    means range extension is likely (Dalton's lamp), a wide one means the
    extremes tend to hold and the day rotates inside them.

    `extension` reports whether price has since traded outside the IB, which is
    the single most useful "is this a trend day" tell available by 11:00 ET.
    """
    rth = rth_bars(bars)
    if not rth:
        return {}
    if rth[0].get("t") is None:
        # No clock: fall back to bar count. 5-minute bars → 12 bars per hour.
        ib = rth[:max(1, minutes // 5)]
    else:
        cutoff = RTH_OPEN + minutes
        ib = [b for b in rth if b["t"] < cutoff]
    if not ib:
        return {}
    ibh, ibl = _hi_lo(ib)
    if ibh is None or ibl is None:
        return {}
    width = round(ibh - ibl, 2)
    out = {"ibh": ibh, "ibl": ibl, "ib_width": width, "ib_complete": len(ib) < len(rth)}

    if atr:
        out["ib_atr_ratio"] = round(width / atr, 2)
        out["ib_shape"] = ("narrow" if width < NARROW_IB_ATR * atr
                           else "wide" if width > WIDE_IB_ATR * atr else "normal")

    after = rth[len(ib):]
    if after:
        hi, lo = _hi_lo(after)
        up, down = hi > ibh, lo < ibl
        out["extension"] = ("both" if up and down else "up" if up else "down" if down else "none")
    else:
        out["extension"] = "none"
    return out


# ── Opening type ────────────────────────────────────────────────────────────
# The four classic opens. Confidence is the point: an Open Drive is the market
# telling you the day's direction in the first ten minutes and holding it; an
# Open Auction is the market saying it has no idea, and neither should you.
OPEN_TYPES = {
    "OPEN_DRIVE": "one-way from the bell and never looked back — highest conviction",
    "OPEN_TEST_DRIVE": "probed the other way, rejected it, then drove — high conviction",
    "OPEN_REJECTION_REVERSE": "drove one way, got rejected, reversed through the open — medium",
    "OPEN_AUCTION": "rotating around the open with no side in control — lowest conviction",
}


def opening_type(bars: list, window: int = 6, atr=None) -> dict:
    """Classify the open from the first `window` RTH bars (6 × 5m = 30 min).

    Returns {"type", "direction", "confidence", "note"}. direction is the side
    the open argues for — for OPEN_REJECTION_REVERSE that is the side price
    reversed TO, not the side it opened with.
    """
    rth = rth_bars(bars)
    if len(rth) < 3:
        return {}
    w = rth[:window]
    open_px = w[0]["open"]
    hi, lo = _hi_lo(w)
    last = w[-1]["close"]
    span = hi - lo
    if span <= 0:
        return {}

    up_ext, down_ext = hi - open_px, open_px - lo
    close_pos = (last - lo) / span          # 0 = at the low, 1 = at the high
    # "Meaningful" excursion — scaled to ATR when we have one, otherwise to the
    # opening window's own range so the classifier still works on any symbol.
    unit = (0.25 * atr) if atr else (0.30 * span)

    drove_up = up_ext > unit and down_ext <= unit
    drove_down = down_ext > unit and up_ext <= unit
    both_ways = up_ext > unit and down_ext > unit

    if drove_up and close_pos >= 0.7:
        t, d, conf = "OPEN_DRIVE", "long", 3
    elif drove_down and close_pos <= 0.3:
        t, d, conf = "OPEN_DRIVE", "short", 3
    elif both_ways and close_pos >= 0.7 and down_ext > up_ext * 0.5:
        t, d, conf = "OPEN_TEST_DRIVE", "long", 2
    elif both_ways and close_pos <= 0.3 and up_ext > down_ext * 0.5:
        t, d, conf = "OPEN_TEST_DRIVE", "short", 2
    # A reversal only counts if it carried BACK THROUGH the open by a
    # meaningful amount. Without that floor any two-sided rotation that happens
    # to close a tick above where it opened reads as a rejection-reverse, which
    # is the most common way this classifier turns chop into false conviction.
    elif both_ways and (last - open_px) > unit:
        t, d, conf = "OPEN_REJECTION_REVERSE", "long", 2
    elif both_ways and (open_px - last) > unit:
        t, d, conf = "OPEN_REJECTION_REVERSE", "short", 2
    else:
        t, d, conf = "OPEN_AUCTION", None, 1

    return {"type": t, "direction": d, "confidence": conf, "note": OPEN_TYPES[t],
            "open_px": round(open_px, 2)}


# ── Open versus prior value ────────────────────────────────────────────────
def open_vs_value(open_px, prior_vah, prior_val) -> dict:
    """Where the session opened relative to yesterday's value area — the first
    line of every trade plan. Opening outside value and staying there is an
    imbalance (trend); opening outside and coming back is the 80% rule setup."""
    if open_px is None or prior_vah is None or prior_val is None:
        return {}
    if open_px > prior_vah:
        loc, note = "above_value", "opened above yesterday's value — buyers paid up overnight"
    elif open_px < prior_val:
        loc, note = "below_value", "opened below yesterday's value — sellers pressed overnight"
    else:
        loc, note = "inside_value", "opened inside yesterday's value — balance until proven otherwise"
    return {"location": loc, "note": note}


def eighty_percent_rule(bars: list, prior_vah, prior_val, bars_inside: int = 6) -> dict:
    """Dalton's 80% rule. Opened outside yesterday's value, then traded back
    inside and STAYED there for two 30-minute periods (6 × 5m bars): odds
    strongly favour a full rotation to the far side of the value area.

    Reported as a setup with an explicit target, never as an order. It is a
    probability, not a promise — 20% of the time price leaves and does not
    come back, which is exactly what the stop is for.
    """
    rth = rth_bars(bars)
    if len(rth) < bars_inside + 1 or prior_vah is None or prior_val is None:
        return {}
    open_px = rth[0]["open"]
    if prior_val <= open_px <= prior_vah:
        return {}                               # opened inside — rule not in play
    inside = [prior_val <= b["close"] <= prior_vah for b in rth]
    # A run of `bars_inside` consecutive closes inside value, anywhere after the open.
    run = 0
    for ok in inside:
        run = run + 1 if ok else 0
        if run >= bars_inside:
            direction = "long" if open_px < prior_val else "short"
            target = prior_vah if direction == "long" else prior_val
            return {"active": True, "direction": direction, "target": round(target, 2),
                    "note": (f"opened {'below' if direction == 'long' else 'above'} value and "
                             f"accepted back inside — 80% rule targets the far edge at {round(target, 2)}")}
    return {"active": False, "note": "opened outside value but has not accepted back inside"}


# ── Naked / virgin POCs ─────────────────────────────────────────────────────
def naked_pocs(session_profiles: list, price, max_out: int = 4) -> list:
    """Prior-session POCs that price has not traded back to since they formed.

    Untested POCs act as magnets: everyone who positioned around that level is
    still waiting, so the first revisit reliably produces a reaction. Takes a
    list of {"date", "poc", "high", "low"} oldest first (the current session
    included and skipped), and returns the nearest untested ones to `price`.
    """
    if not session_profiles or price is None:
        return []
    out = []
    for i, s in enumerate(session_profiles[:-1]):        # the live session can't be naked
        poc = s.get("poc")
        if poc is None:
            continue
        later = session_profiles[i + 1:]
        touched = any(x.get("low") is not None and x["low"] <= poc <= x["high"] for x in later)
        if not touched:
            out.append({"price": round(poc, 2), "date": s.get("date"),
                        "side": "above" if poc > price else "below",
                        "distance": round(abs(poc - price), 2)})
    out.sort(key=lambda x: x["distance"])
    return out[:max_out]


# ── The context verdict ─────────────────────────────────────────────────────
CONTEXTS = ("TREND_UP", "TREND_DOWN", "BALANCE", "UNDECIDED")


def day_context(bars: list, vwap=None, prior=None, ib=None, opening=None,
                value_loc=None, atr=None) -> dict:
    """One label for the day, from the auction evidence — not from an indicator.

    TREND_UP / TREND_DOWN  directional: only pullback-continuation entries are
                           legal, and only in that direction.
    BALANCE                rotational: only fades at the edges, targeting the
                           middle. Breakout entries are illegal.
    UNDECIDED              the evidence disagrees or is too thin — no trade.

    Deliberately conservative. The cost of calling a balance day a trend day is
    a stopped-out breakout; the cost of UNDECIDED is a missed trade, which is
    the cheaper mistake and the one the source framework keeps choosing.
    """
    rth = rth_bars(bars)
    if len(rth) < 3:
        return {"context": "UNDECIDED", "score": 0, "reasons": ["session has barely started"]}

    price = rth[-1]["close"]
    up = down = 0
    reasons = []

    # 1. VWAP posture — where value is being accepted right now.
    if vwap:
        if price > vwap:
            up += 1; reasons.append("price accepted above session VWAP")
        elif price < vwap:
            down += 1; reasons.append("price accepted below session VWAP")

    # 2. Initial balance extension — the trend-day tell.
    ext = (ib or {}).get("extension")
    if ext == "up":
        up += 2; reasons.append("range extension above the initial balance")
    elif ext == "down":
        down += 2; reasons.append("range extension below the initial balance")
    elif ext == "both":
        reasons.append("extended both sides of the IB — two-way trade, no control")
    if (ib or {}).get("ib_shape") == "wide" and ext in (None, "none"):
        reasons.append("wide initial balance held — the extremes are the day's boundaries")

    # 3. The open.
    od = (opening or {}).get("direction")
    conf = (opening or {}).get("confidence", 0)
    if od == "long":
        up += conf; reasons.append(f"{opening['type'].replace('_', ' ').lower()} to the upside")
    elif od == "short":
        down += conf; reasons.append(f"{opening['type'].replace('_', ' ').lower()} to the downside")

    # 4. Position against yesterday's value.
    loc = (value_loc or {}).get("location")
    if loc == "above_value":
        up += 1; reasons.append("trading above yesterday's value area")
    elif loc == "below_value":
        down += 1; reasons.append("trading below yesterday's value area")
    elif loc == "inside_value":
        reasons.append("inside yesterday's value area — balance")

    # 5. Prior-day extremes taken and held.
    if prior:
        if prior.get("pdh") and price > prior["pdh"]:
            up += 1; reasons.append(f"holding above the prior-day high {prior['pdh']}")
        if prior.get("pdl") and price < prior["pdl"]:
            down += 1; reasons.append(f"holding below the prior-day low {prior['pdl']}")

    net = up - down
    rotational = loc == "inside_value" or ext in (None, "none")
    # A directional call needs a clear net AND near-agreement: 4 up against 3
    # down is a fight, not a trend, however large the winner's raw score. The
    # loser's cap is what enforces that, and it is why `net` alone isn't used.
    if net >= 3 and down <= 1:
        ctx = "TREND_UP"
    elif net <= -3 and up <= 1:
        ctx = "TREND_DOWN"
    # A rotational day with a slight lean is still a rotational day. Requiring
    # |net| <= 1 sent net=±2-with-rotational-evidence to UNDECIDED, which reads as
    # "the auction has not decided" when in fact it had — it decided to rotate.
    # BALANCE only permits fades at the edges anyway, so the looser bound cannot
    # authorise a directional trade; it just stops discarding the read.
    elif abs(net) <= 2 and rotational:
        ctx = "BALANCE"
    else:
        ctx = "UNDECIDED"

    return {"context": ctx, "score": net, "up": up, "down": down, "reasons": reasons,
            "playbook": PLAYBOOKS[ctx]}


PLAYBOOKS = {
    "TREND_UP": "Buy pullbacks into support POIs. No shorts, no fading strength.",
    "TREND_DOWN": "Sell rallies into resistance POIs. No longs, no catching knives.",
    "BALANCE": "Fade the edges back toward the POC. No breakout entries.",
    "UNDECIDED": "No trade. The auction has not decided and neither should you.",
}
