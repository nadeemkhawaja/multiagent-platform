"""The consolidation layer — one trade card per symbol.
======================================================
Three engines used to publish three verdicts side by side (a -6..+6 bias score,
a VWAP/EMA state, and a Decision Point verdict), and they routinely disagreed:
a symbol could read ENTER, +2 neutral, and DEAD at the same time. Three answers
to "what do I do" is the same as none.

This module replaces them with a single funnel where each stage can only narrow
what the last one allowed, never contradict it:

    1. CONTEXT   auction.day_context()  — which playbook is legal today
    2. LOCATION  points_of_interest()   — the zones worth acting at
    3. TRIGGER   smc.*                  — what must happen before clicking
    4. RISK      trade_card()           — entry, stop, T1/T2, R, size sanity

The old engines are not deleted; they become inputs. The bias score is one
input to context, and Decision Point's participation gate survives as the
liquidity filter it always was. What changes is that only ONE verdict reaches
the trader.

Everything here is pure. No network, no LLM, no broker.
"""
from tools import auction, smc

# Two reference levels closer together than this (in ATR) are the same zone…
CLUSTER_ATR = 0.25
# …but a zone may never grow wider than this, however tightly its members
# chain. Without the cap, single-linkage clustering walks: A is near B, B is
# near C, C is near D, and one "zone" ends up spanning the prior-day high AND
# the prior-day low. Live output showed exactly that — a 13-source zone on NVDA
# covering the whole session — and a zone that contains everything locates
# nothing.
MAX_ZONE_ATR = 0.40
# Structural stop buffer beyond the zone's far edge.
STOP_BUFFER_ATR = 0.15
# How close to a zone edge counts as "at the zone" for arming. Deliberately tied
# to CLUSTER_ATR: that is the tolerance the edge was built with, and a test finer
# than its own input is false precision.
ARM_PAD_ATR = CLUSTER_ATR
# …and a floor on the whole entry→stop distance. When the trigger bar closes
# right on the zone's near edge the structural stop lands a few cents away,
# which is inside the noise: it gets taken out by the spread, and because R is
# the denominator of every ratio downstream it also reports fantasy numbers —
# a live GBTC short priced a $0.12 stop and claimed 13R to its first target.
#
# This was 1.00 — exactly one average bar of movement — which does not clear the
# bar its own rationale sets: if less than one average bar is a coin flip on the
# next print, then one average bar is a coin flip on the bar after it. The floor
# binds on nearly every card (zones are capped at 0.40 intraday ATR, so the
# structural stop is almost always tighter than the floor), and at 1.00 it was
# still printing the numbers it was written to prevent: a live AVGO short
# measured a $0.80 stop on a $392 name and claimed 4.94R. Two bars of room is
# the minimum that makes R mean something.
MIN_STOP_ATR = 2.00
# …and the floor that actually binds, measured in DAILY ATR.
#
# MIN_STOP_ATR above is scaled to the intraday median true range, and on a
# megacap that is cents: two median CSCO bars is about $0.20 on a $109 stock,
# 0.18% away. The live account stopped out at a clean -1R on 43 of 97 trades —
# the stop was inside the noise, so the trade was decided by the spread rather
# than by whether the idea was right. A GOOGL short went on with entry 350.2336
# and stop 350.23; one NFLX short recorded -20.84R against a two-cent stop.
#
# Risk-based sizing means a wider stop costs nothing but share count: the dollar
# risk per trade is unchanged. So the stop belongs where the idea is WRONG,
# which on a daily-ATR instrument is a fraction of a daily range, not a fraction
# of a 5-minute one. See docs/STRATEGY_REVIEW.md.
MIN_STOP_DAILY_ATR = 0.40
# A trade must pay at least this to the first target, or the zone isn't worth it.
#
# 1.3R was the old bar, and it was not the real one: _targets() invents a 2R
# "measured move" whenever no structural level qualifies, so EVERY card cleared
# any threshold at or below 2.0 by construction. The cards all claimed ~2R and
# 14 of 97 trades actually paid it. T1 must now be a REAL level — see _targets.
MIN_RR_T1 = 2.0
MIN_CONFLUENCE = 2
# Grades that are allowed to become an order. C is "triggered, but at a zone
# only one method sees" — the trigger is then the entire thesis.
TRADEABLE_GRADES = ("A+", "A", "B")
# Trade location sanity: a POI further than this from price is tomorrow's
# problem. Measured in DAILY ATR — it answers "could price get there today?".
MAX_POI_ATR = 2.5
# …but "on the radar" and "worth committing a card to" are different bars, and
# conflating them is what made every card read WAIT. 2.5 daily ATRs runs 1.8-5.3x
# a full session's range on the live watchlist (MU: $179 of reach against a $41
# session), so a card naming a zone at the edge of the radar is describing next
# week while price stands somewhere else entirely. points_of_interest() keeps the
# wider net — the zone list is a useful radar and the UI shows it — but a card
# only trades what price can plausibly reach in the session it is standing in.
TRADEABLE_REACH_ATR = 1.0

# Weights say which levels actually move price. A naked POC and yesterday's
# value edge are where real size is resting; a 5-minute swing high is where a
# handful of stops are. Confluence is the weighted sum, not the raw count.
WEIGHTS = {
    "naked_poc": 3, "prior_vah": 3, "prior_val": 3, "prior_poc": 3,
    "pdh": 2, "pdl": 2, "vwap": 2, "poc": 2, "vah": 2, "val": 2,
    "onh": 2, "onl": 2, "ibh": 2, "ibl": 2,
    "ob": 2, "fvg": 2, "swing": 1, "pdc": 1,
}


# Levels that bound a range. Only these make a zone an "edge" worth fading on a
# balance day — POC and VWAP are the middle, and the middle is not an edge.
BALANCE_EDGES = {"prior_vah", "prior_val", "vah", "val", "pdh", "pdl",
                 "ibh", "ibl", "onh", "onl", "naked_poc"}


def _w(label: str) -> int:
    return WEIGHTS.get(label.split(":")[0], 1)


# ── Stage 2: location ───────────────────────────────────────────────────────
def reference_levels(*, price, vwap=None, profile=None, prior_profile=None,
                     prior=None, ib=None, on_range=None, nakeds=None,
                     swings=None, zones=None) -> list:
    """Every price the market has a reason to care about, flattened into one
    list of {price, label, weight}. Sources are deliberately heterogeneous —
    that is the point: a level that only one method sees is a weak level."""
    out = []

    def add(px, label):
        if px is not None:
            out.append({"price": round(float(px), 2), "label": label, "weight": _w(label)})

    add(vwap, "vwap")
    for k in ("poc", "vah", "val"):
        add((profile or {}).get(k), k)
    for k, lbl in (("poc", "prior_poc"), ("vah", "prior_vah"), ("val", "prior_val")):
        add((prior_profile or {}).get(k), lbl)
    for k in ("pdh", "pdl", "pdc"):
        add((prior or {}).get(k), k)
    for k in ("ibh", "ibl"):
        add((ib or {}).get(k), k)
    for k in ("onh", "onl"):
        add((on_range or {}).get(k), k)
    for n in nakeds or []:
        add(n.get("price"), "naked_poc")
    for s in swings or []:
        add(s, "swing")
    # FVGs and order blocks contribute their reaction point (the 50% midpoint),
    # and carry their own extent so the zone's edges survive clustering.
    for z in zones or []:
        if z.get("ce") is not None:
            out.append({"price": round(float(z["ce"]), 2), "label": f"{z['kind']}:{z['side']}",
                        "weight": _w(z["kind"]), "low": z.get("low"), "high": z.get("high")})
    return out


def points_of_interest(levels: list, price, atr, max_out: int = 4, reach_atr=None) -> list:
    """Cluster reference levels into zones and rank them by confluence.

    A POI is not an indicator reading — it is a price band where several
    independent methods land on the same number. `confluence` is the weighted
    sum of the sources in the band, `sources` names them so the card can say
    WHY without an LLM inventing a reason.

    `atr` sets the clustering scale and should be the INTRADAY ATR — it decides
    what counts as "the same level". `reach_atr` sets how far away a zone can
    be and still matter today, and should be the DAILY ATR; it defaults to
    `atr` when not supplied.
    """
    if not levels or price is None or not atr:
        return []
    reach = (reach_atr or atr) * MAX_POI_ATR
    tol, max_width = CLUSTER_ATR * atr, MAX_ZONE_ATR * atr
    ranked = sorted(levels, key=lambda x: x["price"])
    clusters, cur = [], [ranked[0]]
    for lv in ranked[1:]:
        near = lv["price"] - cur[-1]["price"] <= tol
        fits = lv["price"] - cur[0]["price"] <= max_width
        if near and fits:
            cur.append(lv)
        else:
            clusters.append(cur); cur = [lv]
    clusters.append(cur)

    out = []
    for c in clusters:
        lows = [x.get("low") for x in c if x.get("low") is not None]
        highs = [x.get("high") for x in c if x.get("high") is not None]
        lo = min([x["price"] for x in c] + lows)
        hi = max([x["price"] for x in c] + highs)
        mid = round((lo + hi) / 2, 2)
        dist = abs(mid - price)
        if dist > reach:
            continue
        out.append({
            "low": round(lo, 2), "high": round(hi, 2), "mid": mid,
            "confluence": sum(x["weight"] for x in c),
            "sources": sorted({x["label"] for x in c}),
            "side": "support" if mid < price else "resistance" if mid > price else "at_price",
            "distance": round(dist, 2), "distance_atr": round(dist / (reach_atr or atr), 2),
        })
    out.sort(key=lambda z: (-z["confluence"], z["distance"]))
    return out[:max_out]


# ── Stage 3: trigger ────────────────────────────────────────────────────────
def trigger_state(bars: list, poi: dict, direction: str, atr=None) -> dict:
    """Has the market done anything to earn the entry yet?

    NONE      price isn't at the zone — nothing to do
    ARMED     price is in the zone but has not confirmed; a resting limit is
              legal, a market order is not
    TRIGGERED a sweep-and-reclaim of the zone, or a structure shift out of it

    Touching a level is not a signal. This is the whole difference between the
    old VWAP/EMA state (which fires on a crossover regardless of location) and
    an entry that requires the market to prove the zone held.
    """
    if not bars or not poi:
        return {"state": "NONE", "why": "no data"}
    price = bars[-1]["close"]
    # The pad has to match the resolution of the thing it is testing. Zone edges
    # are not exact prices — points_of_interest() builds them by clustering
    # levels that sit within CLUSTER_ATR of each other, so an edge already
    # carries that much uncertainty. Testing against it with a 0.1 ATR pad was
    # tighter than the zone's own construction tolerance, which meant price could
    # be nearer the level than the level is knowable and still read NONE.
    pad = ARM_PAD_ATR * atr if atr else 0.0
    in_zone = (poi["low"] - pad) <= price <= (poi["high"] + pad)

    sweeps = smc.liquidity_sweeps(bars, [{"price": poi["low"] if direction == "long" else poi["high"],
                                          "label": "poi"}], atr=atr)
    if sweeps and sweeps[0]["side"] == direction:
        return {"state": "TRIGGERED", "kind": "sweep", "why": sweeps[0]["note"]}

    mss = smc.structure_shift(bars)
    if mss.get("direction") == direction and mss.get("kind") in ("MSS", "BOS"):
        near = in_zone or abs(price - poi["mid"]) <= (atr or 0)
        if near:
            return {"state": "TRIGGERED", "kind": mss["kind"].lower(), "why": mss["note"]}

    if in_zone:
        return {"state": "ARMED", "kind": None,
                "why": f"price is inside the {poi['low']}–{poi['high']} zone, waiting for confirmation"}
    # Distance reported on the SAME scale the in-zone test uses. poi's own
    # distance_atr is measured in daily ATR (it answers "reachable today?"), so
    # quoting it here produced lines like "0.08×ATR from the zone" next to a
    # NONE state, which reads as a contradiction.
    gap = (poi["low"] - price) if price < poi["low"] else (price - poi["high"])
    away = f"{gap / atr:.2f}×ATR" if atr else f"${gap:.2f}"
    return {"state": "NONE", "kind": None,
            "why": f"price {round(price, 2)} is {away} outside the zone"}


_TRIGGER_RANK = {"TRIGGERED": 0, "ARMED": 1, "NONE": 2}


def _pick_candidate(candidates: list, bars: list, direction: str, atr):
    """Choose the zone to TRADE — not merely the strongest one on the list.

    `pois` arrives ranked by confluence, so taking candidates[0] committed the
    card to whichever zone had the most agreeing sources anywhere on the radar.
    That is almost never the zone price is standing in, and since arming requires
    price inside a band a fraction of an intraday ATR wide, a live trigger became
    a coincidence rather than an outcome: measured across the watchlist, 8 of the
    11 waiting symbols had a closer zone on the correct side that was never even
    evaluated — NFLX's sat 13c from price, MSTR's 21c — while the card reported
    WAIT against something dollars overhead.

    So evaluate every candidate and tier them by what the market has actually
    done. Within a tier prefer the zone price can reach soonest, because a card
    that cannot arm today is not a trade; confluence breaks ties between zones at
    comparable distance, which is where it belongs.
    """
    # Distance is bucketed at the same resolution levels are clustered with, so
    # "comparably close" is a genuine tie that confluence then decides. Comparing
    # raw distances would let a zone a cent nearer beat one three times stronger.
    bucket = (CLUSTER_ATR * atr) if atr else None
    scored = []
    for poi in candidates:
        trig = trigger_state(bars, poi, direction, atr)
        proximity = int(poi["distance"] / bucket) if bucket else poi["distance"]
        scored.append(((_TRIGGER_RANK.get(trig["state"], 2), proximity,
                        -poi["confluence"]), poi, trig))
    scored.sort(key=lambda s: s[0])
    return scored[0][1], scored[0][2]


# ── Stage 4: risk ───────────────────────────────────────────────────────────
def _targets(direction: str, entry: float, stop: float, levels: list, atr,
             max_dist=None) -> list:
    """Targets are other people's levels, not round multiples of risk. The
    first magnet that pays at least MIN_RR_T1 becomes T1; the next one T2.

    Returns [] when no real level pays MIN_RR_T1 — and that is the point. This
    used to fall back to a 2R "measured move" anchored to the risk whenever
    structure ran out, which meant the reward/risk floor in trade_card() could
    never reject anything: a 2R target was manufactured from the stop distance
    and then presented as the reason the trade was worth taking. Across 100 live
    trades the cards claimed ~2R and 14 reached it.

    A measured move is still used to extend T2 once a structural T1 exists, so a
    runner is never left without an exit plan. It just cannot be the reason a
    trade is taken.

    `max_dist` keeps targets inside what the day can actually travel. The
    reference-level list contains daily swing levels, and without the cap a
    TSLA intraday long was handed a T2 12% away — a target the position would
    be force-closed long before reaching.
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return []
    lo = entry - max_dist if max_dist else float("-inf")
    hi = entry + max_dist if max_dist else float("inf")
    if direction == "long":
        ahead = sorted(l["price"] for l in levels if entry + 0.2 * risk < l["price"] <= hi)
    else:
        ahead = sorted((l["price"] for l in levels if lo <= l["price"] < entry - 0.2 * risk),
                       reverse=True)
    out = []
    for px in ahead:
        rr = (px - entry) / risk if direction == "long" else (entry - px) / risk
        if rr >= MIN_RR_T1 and (not out or abs(px - out[-1]["price"]) > 0.3 * (atr or risk)):
            out.append({"price": round(px, 2), "rr": round(rr, 2)})
        if len(out) == 2:
            break
    # No structural T1 → no trade. The caller reads rr1 == 0 and waits.
    if not out:
        return []
    # Measured-move T2, always BEYOND whatever is already there. Anchoring it to
    # entry instead produced a GBTC short with T1 at 13R (a real level far below)
    # and a 3R "T2" sitting between the entry and T1 — a second target the trade
    # would reach first and in the wrong order.
    while len(out) < 2:
        mult = max(2.0 if not out else 3.0, (out[-1]["rr"] + 1.0) if out else 0.0)
        px = entry + mult * risk if direction == "long" else entry - mult * risk
        out.append({"price": round(px, 2), "rr": round(mult, 2), "measured": True})
    return out


def _grade(confluence: int, trig: dict, rr1: float, in_play: bool) -> str:
    """A is reserved. It needs a real zone, a fired trigger and a 2R first target.
    B is a good ordinary setup; C is a setup still waiting on its trigger.

    A used to additionally require `in_play` — 2x relative volume. That is a
    SCANNER threshold: it exists to pick a handful of names out of a universe of
    thousands, and it does not transfer to grading a fixed list of 22 megacaps,
    which clear 2x only on earnings and shocks. The effect was that grade A was
    unreachable by construction, so "Today's A+ Setup" — the headline feature and
    the one-trade-per-day discipline the whole agent is built around — sat empty
    while cleanly triggered 2R cards were capped at B. It is the same trap already
    documented for Decision Point: participation is a QUALITY signal, not a gate.

    So A now grades the setup, and unusual participation makes it A+. The hard
    "is anyone trading this at all" floor still lives in liquidity_floor().
    """
    if trig["state"] == "NONE":
        return "NONE"
    if trig["state"] == "ARMED":
        return "C"
    if confluence >= 5 and rr1 >= 2.5:
        return "A+" if in_play else "A"
    if confluence >= MIN_CONFLUENCE and rr1 >= MIN_RR_T1:
        return "B"
    return "C"


def trade_card(*, symbol, label, price, bars, atr, context: dict, levels: list,
               pois: list, liquidity: dict = None, in_window: bool = True,
               reach_atr=None) -> dict:
    """The single verdict. Everything above collapses into this.

    Returns a card with `action` — one of:
      LONG / SHORT   a trade with entry, stop, T1, T2 and R
      WAIT           the right zone exists but price or confirmation is missing
      STAND_DOWN     the context, the liquidity gate or the clock says no

    `liquidity` is strategies.liquidity_floor()'s output: `pass` is the hard
    "is anyone trading this" gate — a perfect zone on a dead stock is still a
    trap — and `in_play` (2x relative volume) is what separates an A card from
    a B.
    """
    ctx = context.get("context", "UNDECIDED")
    liq = liquidity or {"pass": True, "in_play": False}
    base = {"symbol": symbol, "label": label, "price": price, "context": ctx,
            "playbook": context.get("playbook"), "grade": "NONE", "poi": None,
            "in_play": bool(liq.get("in_play")),
            "context_reasons": context.get("reasons", [])[:4]}

    # A stand-down is a verdict about ACTION, not a reason to withhold the map.
    # These three branches returned with poi=None, so on an undecided day the
    # reader got no zones, no levels and nothing to set an alert on — for 6 of 24
    # megacaps in one live run. The strict gate is right; losing the information
    # was not. Attach the nearest zone so the card can still say where price is
    # and what would have to change.
    nearest = min(pois, key=lambda z: z["distance"]) if pois else None
    watching = {"poi": nearest} if nearest else {}

    if not liq.get("pass", True):
        return {**base, **watching, "action": "STAND_DOWN",
                "why": "below the liquidity floor — " + "; ".join(liq.get("reasons") or ["no participation data"])}
    if ctx == "UNDECIDED":
        return {**base, **watching, "action": "STAND_DOWN", "why": context.get("playbook")}
    if not in_window:
        return {**base, **watching, "action": "STAND_DOWN",
                "why": "outside the entry window — setups here are not the ones the plan was built for"}

    direction = "long" if ctx == "TREND_UP" else "short" if ctx == "TREND_DOWN" else None
    if ctx == "BALANCE":
        # Fade the EDGE back toward the middle. The edge has to be a real
        # boundary — a value-area edge or a range extreme — not merely the
        # nearest zone: the POC and VWAP sit in the middle of a balance day, and
        # buying the middle is a trade with the mean as both entry and target.
        edges = [p for p in pois
                 if p["side"] in ("support", "resistance")
                 and set(p["sources"]) & BALANCE_EDGES]
        if not edges:
            return {**base, "action": "WAIT",
                    "why": "balance day, but price is mid-range — the edges are the trade "
                           "and price isn't at one"}
        near = min(edges, key=lambda z: z["distance"])
        direction = "long" if near["side"] == "support" else "short"
        candidates = [near]
    else:
        want = "support" if direction == "long" else "resistance"
        candidates = [p for p in pois if p["side"] in (want, "at_price")]

    # Trade only what this session can reach. Without this the card happily named
    # a zone two or three sessions of range away and then waited on it forever.
    side_word = "support" if direction == "long" else "resistance"
    reach_scale = reach_atr or atr
    if reach_scale and candidates:
        reach = TRADEABLE_REACH_ATR * reach_scale
        in_reach = [p for p in candidates if p["distance"] <= reach]
        if not in_reach:
            nearest = min(candidates, key=lambda z: z["distance"])
            return {**base, "action": "WAIT",
                    "why": f"{ctx.replace('_', ' ').lower()} but the nearest {side_word} zone "
                           f"({nearest['low']}–{nearest['high']}) is {nearest['distance']} away — "
                           f"more than a session's range, so it is not today's trade"}
        candidates = in_reach

    if not candidates:
        return {**base, "action": "WAIT",
                "why": f"{ctx.replace('_', ' ').lower()} but no {side_word} "
                       f"zone within reach — chasing here is the trade that loses"}

    poi, trig = _pick_candidate(candidates, bars, direction, atr)

    far = poi["low"] if direction == "long" else poi["high"]
    buf = STOP_BUFFER_ATR * atr if atr else 0.0
    stop = round(far - buf, 2) if direction == "long" else round(far + buf, 2)
    entry = round(price, 2) if trig["state"] == "TRIGGERED" else round(
        poi["high"] if direction == "long" else poi["low"], 2)
    # A resting limit must not sit on the wrong side of its own stop.
    if (direction == "long" and entry <= stop) or (direction == "short" and entry >= stop):
        entry = round(poi["mid"], 2)
    # Widen a stop that landed inside the noise, so R means something. Two
    # floors, and the wider wins: MIN_STOP_ATR bars of intraday range, and a
    # fraction of the DAILY range — the one that keeps a megacap's stop out of
    # the spread. Sizing is risk-based, so a wider stop buys fewer shares at the
    # same dollar risk; it does not make the trade bigger.
    stop_note = ""
    floors = []
    if atr:
        floors.append((MIN_STOP_ATR * atr, f"{MIN_STOP_ATR:g} intraday ATR"))
    if reach_atr:
        floors.append((MIN_STOP_DAILY_ATR * reach_atr, f"{MIN_STOP_DAILY_ATR:g} daily ATR"))
    if floors:
        floor, why = max(floors)
        if abs(entry - stop) < floor:
            stop = round(entry - floor, 2) if direction == "long" else round(entry + floor, 2)
            # Say so. Otherwise the card shows a stop well outside the zone it
            # names and the reader has no way to tell whether that is deliberate.
            stop_note = (f"stop widened to {why} (${round(floor, 2)}) — the structural "
                         f"stop at the zone edge was inside the noise")

    targets = _targets(direction, entry, stop, levels, atr,
                       max_dist=MAX_POI_ATR * (reach_atr or atr) if atr else None)
    rr1 = targets[0]["rr"] if targets else 0.0
    grade = _grade(poi["confluence"], trig, rr1, in_play=bool(liq.get("in_play")))

    card = {**base, "poi": poi, "grade": grade, "trigger": trig, "stop_note": stop_note,
            "direction": direction, "entry": entry, "stop": stop,
            "risk_per_share": round(abs(entry - stop), 2),
            "t1": targets[0] if targets else None,
            "t2": targets[1] if len(targets) > 1 else None,
            "rr": rr1}

    if grade == "NONE" or trig["state"] == "NONE":
        return {**card, "action": "WAIT",
                "why": f"zone at {poi['low']}–{poi['high']} is the level, but {trig['why']}"}
    if not targets:
        return {**card, "action": "WAIT", "grade": "NONE",
                "why": f"no real level pays {MIN_RR_T1:g}R from {entry} against the stop at "
                       f"{stop} — nothing ahead worth the risk"}
    if rr1 < MIN_RR_T1:
        return {**card, "action": "WAIT", "grade": "NONE",
                "why": f"only {rr1}R to the first magnet — not worth the stop at {stop}"}
    if trig["state"] == "ARMED":
        return {**card, "action": "WAIT",
                "why": f"armed at {poi['low']}–{poi['high']} ({', '.join(poi['sources'])}) — "
                       f"needs a sweep-and-reclaim or a structure shift before entry"}
    # Only a graded setup trades. A triggered card at a one-source zone used to
    # reach the broker as a grade C, which is the thinnest thing the funnel can
    # describe: a single level, no agreement, and the trigger doing all the work.
    if grade not in TRADEABLE_GRADES:
        return {**card, "action": "WAIT",
                "why": f"grade {grade} — a {poi['confluence']}-point zone "
                       f"({', '.join(poi['sources'])}) is one method's opinion, not confluence"}

    return {**card, "action": direction.upper(),
            "why": f"{ctx.replace('_', ' ').lower()} · {trig['why']} at a {poi['confluence']}-point "
                   f"zone ({', '.join(poi['sources'])}) · {rr1}R to {targets[0]['price']}"}


def card_line(c: dict) -> str:
    """One compact line for an email, an LLM prompt, or a log."""
    if not c:
        return ""
    if c["action"] in ("WAIT", "STAND_DOWN"):
        return f"{c['label']}: {c['action']} — {c.get('why', '')}"
    return (f"{c['label']}: {c['action']} {c['grade']} @ {c['entry']} "
            f"stop {c['stop']} T1 {c['t1']['price']} T2 {c['t2']['price']} "
            f"({c['rr']}R) — {c.get('why', '')}")
