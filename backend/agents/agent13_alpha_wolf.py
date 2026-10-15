# ============================================================================
# Agent 13 — Alpha Wolf (Master Agent)
# Leads the pack: ingests the cached output of two trading sub-agents
# (Wallstreet Wolf — tape + regime — and Technologia), makes ONE local-LLM call to
# synthesize a ranked Daily + Weekly trade game-plan, then EXECUTES the daily
# ideas through the paper broker (simulated fills at live prices, virtual capital).
# ============================================================================
import os
import re
import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo

from database import save_agent_data, get_agent_data, get_config
from llm_client import generate_json, resolve_model
from orchestrator import orchestrator
from email_utils import send_html_email
from tools import technicals as technicals_tool
from tools import levels as levels_tool
from agents import agent14_technologia
import alpaca_broker as broker

log = logging.getLogger("alpha_wolf")

ET = ZoneInfo("America/New_York")

AGENT_ID = "alpha_wolf"
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")

# The pack Alpha Wolf commands. Keyed by backend agent_id → the AgentData key
# each one persists under.
SUB_AGENTS = {
    "wallstreet_wolf": "market_data",
    "technologia":     "signals",
}

DISCLAIMER = ("Educational analysis only — not financial advice. Alpha Wolf executes trades in a "
              "simulated paper-trading portfolio with virtual capital; no real money ever moves. "
              "Do your own research and manage risk.")


# ── Compact summaries of each sub-agent's latest output (fed to the LLM) ──────
def _wolf_summary(d: dict) -> str:
    md = (d or {}).get("market_data", {}) or {}
    g = md.get("top_gainers", [])[:5]
    l = md.get("top_losers", [])[:5]
    gain = ", ".join(f"{s.get('symbol')} {s.get('change_pct')}%" for s in g) or "n/a"
    lose = ", ".join(f"{s.get('symbol')} {s.get('change_pct')}%" for s in l) or "n/a"
    return f"Top gainers: {gain}. Top losers: {lose}. Wolf read: {str(md.get('commentary',''))[:300]}"


def _compass_summary(d: dict) -> str:
    c = (d or {}).get("compass", {}) or {}
    sectors = c.get("sectors", []) or []
    sec = ", ".join(f"{s.get('k')} {s.get('bias'):+d}" for s in sectors
                    if isinstance(s.get("bias"), int)) or "n/a"
    vix = c.get("vix") or {}
    vix_txt = f" VIX {vix.get('level','?')} ({vix.get('regime','?')} volatility)." if vix else ""
    return (f"Composite bias: {c.get('composite','?')} (-100 bearish..+100 bullish).{vix_txt} "
            f"Sector bias: {sec}. Compass read: {str(c.get('read',''))[:300]}")


# Grades the funnel can produce, ranked. Carried onto the idea so the broker and
# the UI can both speak in grades instead of a self-assessed 1-10 score.
GRADE_ORDER = {"A+": 0, "A": 1, "B": 2, "C": 3}


def cards_to_ideas(d: dict) -> list:
    """Technologia's computed cards, as the plan's daily ideas. THE trade source.

    Each card is already a complete, auditable trade — context, zone, trigger,
    entry, stop, T1/T2 and R — produced by the four-stage funnel with no model in
    the loop. There used to be a second source: the LLM synthesized its own ideas
    with prose levels and a self-rated 1-10 `confidence`, which then gated
    execution at the broker. Over 100 live trades that score carried no
    information at all (grade 8: -$2,030; grade 9: +$1,010; three trades with no
    score traded anyway for -$1,149), and having two sources meant the Technologia
    tab and the Alpha Wolf tab described different worlds — the reconciliation
    machinery that existed to detect the drift is gone with the drift. See
    docs/STRATEGY_REVIEW.md.

    The model still writes the regime narrative. It no longer decides, prices or
    gates a trade.
    """
    s = (d or {}).get("signals", {}) or {}
    out = []
    for card in s.get("cards") or []:
        if card.get("action") not in ("LONG", "SHORT"):
            continue
        # /ES and /NQ are context, never orders — Alpaca can't trade futures.
        # They stay visible in `plan["funnel"]` and still drive the tape gate.
        if card.get("symbol") in agent14_technologia.FUTURES:
            continue
        t1, t2 = card.get("t1") or {}, card.get("t2") or {}
        poi = card.get("poi") or {}
        out.append({
            "ticker": str(card.get("symbol") or "").upper(),
            "direction": card["action"].lower(),
            "grade": card.get("grade"), "context": card.get("context"),
            # Numeric and authoritative: these ARE the order levels. Nothing
            # downstream re-parses a price out of prose any more.
            "entry_px": card.get("entry"), "stop_px": card.get("stop"),
            "target_px": t1.get("price"), "target2_px": t2.get("price"),
            "entry": card.get("entry"), "stop": card.get("stop"),
            "target": t1.get("price"),
            "rr": card.get("rr"), "risk_per_share": card.get("risk_per_share"),
            "zone": f"{poi.get('low')}–{poi.get('high')}" if poi.get("low") is not None else "",
            "confluence": poi.get("confluence"),
            "trigger": (card.get("trigger") or {}).get("why") or "",
            "in_play": card.get("in_play"),
            "thesis": card.get("why") or "", "why": card.get("why") or "",
            "risk": f"invalidated on a close beyond {card.get('stop')}",
            "stop_note": card.get("stop_note") or "",
            "source": "technologia_funnel",
        })
    # Best grade first, then the tightest reward/risk claim behind it.
    out.sort(key=lambda i: (GRADE_ORDER.get(i.get("grade"), 9), -(i.get("rr") or 0)))
    return out


def _technologia_summary(d: dict) -> str:
    s = (d or {}).get("signals", {}) or {}
    cards = cards_to_ideas(d)
    cov = s.get("coverage") or {}
    # Lead with the verdicts, and say plainly when the screen had no data rather
    # than letting a starved run read as a quiet tape.
    if cards:
        lines = "; ".join(
            f"{c['ticker']} {c['direction'].upper()} grade {c['grade']} @ {c['entry_px']} "
            f"stop {c['stop_px']} T1 {c['target_px']} ({c['rr']}R, {c['confluence']}-pt zone {c['zone']})"
            for c in cards[:6])
        head = f"Computed trade cards (deterministic, already gated): {lines}."
    else:
        head = ("No symbol produced a tradeable card — the funnel's answer today is "
                "stand down.")
    armed = s.get("armed_count") or 0
    armed_txt = f" {armed} more are at a zone waiting on a trigger." if armed else ""
    cov_txt = ""
    if cov and cov.get("returned") is not None and cov.get("requested"):
        if cov["returned"] < cov["requested"]:
            cov_txt = (f" WARNING: price data covered only {cov['returned']}/{cov['requested']} "
                       f"symbols this run — absence of cards is partly missing data, not a quiet tape.")
    win = (s.get("entry_window") or {}).get("in_window")
    win_txt = " /ES-/NQ entry window is OPEN (10:30-11:55 ET)." if win else ""
    return f"{head}{armed_txt}{cov_txt}{win_txt}"


# How stale Technologia's snapshot may be before Alpha Wolf refuses to build the
# master plan on it. The plan is the one artifact the whole app trades off, and
# it is only as current as the cards underneath it — a 25-minute bound sits just
# inside Technologia's own 30-minute cadence, so a scheduled run that happened on
# time is always accepted and only a genuinely missing one forces a recompute.
TECH_MAX_AGE_MIN = 25


async def ensure_fresh_cards(max_age_min: float = TECH_MAX_AGE_MIN) -> dict:
    """Technologia's snapshot, recomputed first if it is stale.

    Alpha Wolf is the master game-plan: what it shows must BE what the funnel
    currently says, not what it said whenever the two schedules last happened to
    line up. The plan cron fires at 08:30 and Technologia's interval is
    unsynchronized, so the plan was routinely synthesized on the previous
    session's closing cards — every intraday card the funnel produced reached
    the Technologia tab and nothing else.

    Outside the compute window there is nothing fresher to get, so the stored
    snapshot is returned as-is rather than overwritten with a dead-tape reading.
    """
    data = get_agent_data("technologia") or {}
    if not agent14_technologia._market_is_open():
        return data
    age = agent14_technologia.snapshot_age_minutes(data)
    if age is not None and age <= max_age_min:
        return data
    why = "no snapshot yet" if age is None else f"{age:.0f} min old"
    log.info(f"Technologia cards are stale ({why}) — recomputing before the plan")
    orchestrator.set_progress(AGENT_ID, "Refreshing Technologia's cards first…")
    try:
        await agent14_technologia.technologia_job()
    except Exception as e:
        # A failed refresh must not take the plan down with it — the previous
        # snapshot is still better than no plan, and `funnel.age_min` below
        # makes its age visible rather than silently passing it off as current.
        log.warning(f"Technologia refresh failed, using the stored snapshot: {e}")
    return get_agent_data("technologia") or {}


def funnel_snapshot(d: dict) -> dict:
    """EVERY card Technologia computed, in the shape both trading tabs read.

    This used to take the plan as well and measure each card against it —
    `in_plan`, `plan_note`, `measured`, plus a warning path for "tradeable card
    missing from the plan". All of that existed because the plan had a second,
    independent source of ideas, so a card could legitimately be absent and
    nobody could tell an intentional rejection from a dropped row.

    Now every actionable card IS an idea, by construction. The only thing left
    worth saying per card is whether the broker refused it, which `gate` carries
    (filled in by price_plan once execution has run).
    """
    s = (d or {}).get("signals", {}) or {}
    cards = []
    for c in s.get("cards") or []:
        poi = c.get("poi") or {}
        actionable = c.get("action") in ("LONG", "SHORT")
        futures = c.get("symbol") in agent14_technologia.FUTURES
        cards.append({
            "symbol": c.get("symbol"), "label": c.get("label") or c.get("symbol"),
            "action": c.get("action"), "grade": c.get("grade"),
            "context": c.get("context"), "price": c.get("price"),
            "entry": c.get("entry"), "stop": c.get("stop"),
            "target": (c.get("t1") or {}).get("price"), "rr": c.get("rr"),
            "zone": (f"{poi.get('low')}–{poi.get('high')}"
                     if poi.get("low") is not None else ""),
            "confluence": poi.get("confluence"),
            "trigger": (c.get("trigger") or {}).get("why") or "",
            "in_play": c.get("in_play"), "why": c.get("why", ""),
            "in_plan": actionable and not futures,
            "gate": "",
        })
    age = agent14_technologia.snapshot_age_minutes(d)
    # Four buckets that ADD UP to the card count, so "why is Technologia showing
    # 24 and Alpha Wolf 21" always has an arithmetic answer on screen.
    tradeable = sum(1 for c in cards if c["in_plan"])
    futures = sum(1 for c in cards if not c["in_plan"]
                  and c["symbol"] in agent14_technologia.FUTURES)
    armed = sum(1 for c in cards if not c["in_plan"] and c["action"] == "WAIT"
                and c["symbol"] not in agent14_technologia.FUTURES)
    return {
        "cards": cards,
        "tradeable": tradeable,
        "futures": futures,
        "armed": armed,
        "stand_down": len(cards) - tradeable - futures - armed,
        "coverage": s.get("coverage") or {},
        "best_of_session": (d or {}).get("best_of_session") or {},
        "entry_window": s.get("entry_window") or {},
        "generated_at": s.get("generated_at", ""),
        "generated_ts": s.get("generated_ts"),
        "age_min": None if age is None else round(age),
        "synced_at": datetime.datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        "synced_ts": datetime.datetime.now(ET).timestamp(),
    }


def _gather():
    data = {aid: get_agent_data(aid) for aid in SUB_AGENTS}
    # Wolf persists both halves of the desk — the tape under "market_data" and
    # the regime under "compass" — so one agent feeds two of the summaries.
    summaries = {
        "MARKET":     _wolf_summary(data["wallstreet_wolf"]),
        "REGIME":     _compass_summary(data["wallstreet_wolf"]),
        "TECHNOLOGIA": _technologia_summary(data["technologia"]),
    }
    sources_used = [aid for aid, key in SUB_AGENTS.items() if (data.get(aid) or {}).get(key)]
    return summaries, sources_used, data


def _candidate_tickers(data: dict) -> list:
    """Tickers the plan is likely to reference — top movers and currently held
    positions. Used to pull live quotes so the LLM anchors entry/stop/target
    levels to real prices."""
    syms = []
    md = (data.get("wallstreet_wolf") or {}).get("market_data", {}) or {}
    for k in ("top_gainers", "top_losers"):
        syms += [s.get("symbol") for s in md.get(k, [])[:5]]
    port = (get_agent_data(AGENT_ID) or {}).get("portfolio") or {}
    syms += list((port.get("positions") or {}).keys())
    out, seen = [], set()
    for s in syms:
        s = str(s or "").upper().strip()
        if s and s.replace("-", "").isalnum() and s not in seen:
            seen.add(s)
            out.append(s)
    return out[:14]


def _idea_levels(idea: dict, live=None) -> tuple:
    """(entry, stop, target, atr) for an idea, as floats.

    Every idea is a funnel card now, so every level is already a number computed
    off real structure. This used to parse dollar amounts out of LLM prose with a
    regex, anchored to the live quote to discard hallucinations, and fill the gaps
    from support/resistance — three separate ways to arrive at a stop, any of
    which could disagree with the one the broker actually placed."""
    def px(key):
        v = idea.get(key)
        return float(v) if isinstance(v, (int, float)) and v else None

    atr = idea.get("atr14")
    return (px("entry_px"), px("stop_px"), px("target_px"),
            float(atr) if isinstance(atr, (int, float)) and atr else None)


def _size_idea(direction: str, entry: float, stop, atr, equity: float, cash: float, settings: dict):
    """The size the broker would actually place for this idea.

    Both the plan email and the live tab used to size at `budget // price`,
    where budget is equity × position_pct — the *concentration cap* alone. The
    broker sizes on risk: risk_pct of equity divided by the entry→stop
    distance, and only then capped by concentration and cash. Those two numbers
    are not close — at the defaults (10% concentration, 0.5% risk) a 2%-wide
    stop sizes to a quarter of what the cap allows — so every size shown to the
    trader was several times the position that would appear in the account.
    One helper now answers for all three surfaces.

    Returns (shares, note); shares of 0 carries the broker's own reason why."""
    if not entry or entry <= 0:
        return 0, "no live quote"
    if not stop:
        # No usable stop even after enrichment: mirror the broker's own ATR
        # fallback, ATR included, so the number shown is the number traded.
        stop, _ = broker._default_levels(direction, entry, atr)
    stop = broker._sane_stop(direction, entry, stop)
    if not stop:
        return 0, "stop is on the wrong side of the entry"
    return broker.size_position(equity, cash, entry, stop, settings)


def _apply_sizing(ideas: list, prices: dict, equity: float, cash: float, settings: dict):
    """Annotate daily ideas with the concrete size the broker would place."""
    for i in ideas or []:
        live = prices.get(str(i.get("ticker", "")).upper())
        if not live:
            continue
        i["live"] = live
        entry, stop, _target, atr = _idea_levels(i, live)
        # Sized at the entry level the order rests at, not the current quote —
        # that is the fill the broker is working toward.
        shares, note = _size_idea(str(i.get("direction", "")).lower(), entry or live,
                                  stop, atr, equity, cash, settings)
        if shares >= 1:
            i["size_shares"] = shares
            i["size_usd"] = round(shares * (entry or live), 2)
        elif note:
            i["size_note"] = note


# ── Plan sanitization ─────────────────────────────────────────────────────────
# The local LLM does not always honor the schema: string fields sometimes come
# back as dicts/lists, list fields as scalars. The UI, the email, and the paper
# broker all consume this plan, so coerce every field to its expected type.
def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return ", ".join(filter(None, (_as_text(x) for x in v)))
    if isinstance(v, dict):
        return " — ".join(filter(None, (_as_text(x) for x in v.values())))
    return str(v)


def _as_text_list(v, limit: int = 8) -> list:
    items = v if isinstance(v, list) else ([v] if v else [])
    return [t for t in (_as_text(x) for x in items[:limit]) if t]


def _sanitize_idea(idea, weekly: bool) -> dict:
    if not isinstance(idea, dict):
        return {}
    direction = _as_text(idea.get("direction")).lower()
    out = {
        "ticker": _as_text(idea.get("ticker")).upper()[:10],
        "direction": direction if direction in ("long", "short", "neutral") else "neutral",
        "thesis": _as_text(idea.get("thesis")),
        "risk": _as_text(idea.get("risk")),
    }
    out["catalyst"] = _as_text(idea.get("catalyst"))
    return out


def _sanitize_horizon(h, weekly: bool) -> dict:
    """Coerce one horizon of the model's JSON.

    The DAILY horizon keeps no ideas from the model at all — daily.ideas is
    overwritten wholesale by the funnel's cards in price_plan(). Only the weekly
    view still carries model ideas, and those are commentary: nothing weekly is
    ever routed to the broker.

    The daily timeline went with them. It was an LLM-written schedule of what to
    do at each hour, and with one fixed 09:45-15:30 entry window there is nothing
    left for it to schedule.
    """
    h = h if isinstance(h, dict) else {}
    bias = _as_text(h.get("bias")).upper()
    out = {
        "bias": bias if bias in ("BULLISH", "BEARISH", "NEUTRAL") else "NEUTRAL",
        "summary": _as_text(h.get("summary")),
        "ideas": ([i for i in (_sanitize_idea(x, weekly) for x in (h.get("ideas") or [])[:6])
                   if i.get("ticker")] if weekly else []),
    }
    if weekly:
        out["themes"] = _as_text_list(h.get("themes"), 6)
    return out


def _sanitize_plan(plan: dict) -> dict:
    plan = plan if isinstance(plan, dict) else {}
    stance = _as_text(plan.get("stance")).upper()
    return {
        "headline": _as_text(plan.get("headline")),
        "stance": stance if stance in ("RISK-ON", "RISK-OFF", "NEUTRAL") else "NEUTRAL",
        "regime": _as_text(plan.get("regime")),
        "confluence": _as_text_list(plan.get("confluence"), 4),
        "daily": _sanitize_horizon(plan.get("daily"), weekly=False),
        "weekly": _sanitize_horizon(plan.get("weekly"), weekly=True),
        "avoid": _as_text_list(plan.get("avoid"), 6),
        "catalysts": _as_text_list(plan.get("catalysts"), 8),
        "risk_notes": _as_text(plan.get("risk_notes")),
    }


def _price_ideas(plan: dict, prices: dict, tech: dict, levels: dict = None):
    """Attach the context a card doesn't carry — ATR, VWAP, POC — and set aside
    any card whose entry level has run away from the live quote.

    This replaces `_enrich_ideas`, which validated LLM prose against live quotes,
    parsed entry/stop/target out of it with a regex, invented a stop from
    support/resistance when the model gave none, computed reward/risk from
    whatever came out, and then re-sorted the result so computed cards outranked
    a model that had rated its own idea 10/10. A card arrives with all of that
    already decided by tools/playbook.py.
    """
    levels = levels or {}
    daily = plan.get("daily") or {}
    kept = []
    for i in daily.get("ideas") or []:
        t = str(i.get("ticker", "")).upper()
        live = prices.get(t)
        entry = i.get("entry_px")
        # The level came from the funnel, not a guess, so a wide gap to the live
        # quote means the tape moved on since the card was computed. The broker
        # refuses these anyway (MAX_ENTRY_DRIFT); separating them here keeps the
        # plan honest about what can still trade instead of showing a dead level.
        if live and entry and abs(live - entry) / live > broker.MAX_ENTRY_DRIFT:
            i["stale"] = (f"entry {entry} is {abs(live - entry) / live * 100:.1f}% from the "
                          f"live {live} — the move left without us")
        tk = tech.get(t) or {}
        if tk.get("atr14"):
            i["atr14"] = tk["atr14"]
        lv = levels.get(t)
        if lv:
            i["vwap"], i["poc"] = lv.get("vwap"), lv.get("poc")
        i["live"] = live
        kept.append(i)
    daily["ideas"] = [i for i in kept if not i.get("stale")]
    daily["stale_ideas"] = [i for i in kept if i.get("stale")]


# ── Market clock & live "decision now" engine ────────────────────────────────
# Alpha Wolf is the trader's primary decision maker: given the synthesized plan,
# the current US/Eastern session and live quotes, it says what to do RIGHT NOW.
SESSIONS = [  # (key, label, start_min, end_min) — minutes since midnight ET
    ("pre",    "Pre-market",  4 * 60,       9 * 60 + 30),
    ("open",   "The open",    9 * 60 + 30, 10 * 60 + 30),
    ("midday", "Midday",      10 * 60 + 30, 15 * 60),
    ("power",  "Power hour",  15 * 60,      16 * 60),
    ("after",  "After-hours", 16 * 60,      20 * 60),
]
# The open and power hour are one hour of a sixteen-hour bar — 6% of its width,
# where "The open" cannot fit. Each segment carries a short label too.
SESSION_SHORT = {"pre": "PRE", "open": "OPEN", "midday": "MIDDAY",
                 "power": "POWER", "after": "AFTER"}
_SESSION_BOUNDS = {k: (a, b) for k, _, a, b in SESSIONS}
_SESSION_EVENTS = [(240, "Pre-market opens"), (570, "Opening bell"), (630, "Midday"),
                   (900, "Power hour"), (960, "Closing bell"), (1200, "After-hours end")]
# What each part of the day is FOR. The session banner shows this so the phase
# name alone never has to be interpreted.
SESSION_NOTES = {
    "pre":    "Prep only — mark levels and stage orders, don't chase thin quotes",
    "open":   "Highest volatility of the day — the opening drive sets the range",
    "midday": "Thinnest liquidity — chop; the /ES-/NQ entry window is 10:30-11:55",
    "power":  "Trend resolution — take profit, trail stops or size into the close",
    "after":  "Wind down — no new risk, review fills and tomorrow's catalysts",
    "closed": "Market closed — plan, don't trade",
}
# The 4:00→20:00 ET band the session bar spans.
_DAY_START, _DAY_END = 4 * 60, 20 * 60

_PRICE_RE = re.compile(r"\$\s*([0-9]{1,6}(?:,[0-9]{3})*(?:\.[0-9]{1,4})?)")
_NUM_RE = re.compile(r"\b([0-9]{2,6}(?:\.[0-9]{1,4})?)\b")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?", re.I)


def _fmt_min(m: int) -> str:
    return f"{m // 60}:{m % 60:02d}"


def market_clock(now: datetime.datetime = None) -> dict:
    now = now or datetime.datetime.now(ET)
    mins = now.hour * 60 + now.minute
    trading_day = now.weekday() < 5
    session, label = "closed", "Market closed"
    if trading_day:
        for key, lbl, a, b in SESSIONS:
            if a <= mins < b:
                session, label = key, lbl
                break
    nxt = None
    if trading_day:
        for m, lbl in _SESSION_EVENTS:
            if mins < m:
                nxt = {"label": lbl, "at": _fmt_min(m) + " ET", "in_min": m - mins}
                break
    if nxt is None:  # evening or weekend → next trading day's pre-market
        d = 1
        while (now.weekday() + d) % 7 >= 5:
            d += 1
        nxt = {"label": "Pre-market opens" + (f" {['Mon','Tue','Wed','Thu','Fri'][(now.weekday() + d) % 7]}" if d > 1 or not trading_day else ""),
               "at": "4:00 ET", "in_min": (24 * 60 - mins) + (d - 1) * 24 * 60 + 240}
    # Where the clock sits along the 4:00→20:00 ET band, for the session bar.
    day_pct = round(min(1.0, max(0.0, (mins - _DAY_START) / (_DAY_END - _DAY_START))) * 100, 1)
    phases = [{"key": k, "label": lbl, "short": SESSION_SHORT.get(k, lbl), "start": a, "end": b,
               "start_label": _fmt_min(a), "end_label": _fmt_min(b),
               "pct": round((a - _DAY_START) / (_DAY_END - _DAY_START) * 100, 2),
               "width": round((b - a) / (_DAY_END - _DAY_START) * 100, 2),
               "current": trading_day and k == session}
              for k, lbl, a, b in SESSIONS]
    return {"et": now.strftime("%-I:%M %p"), "date": now.strftime("%Y-%m-%d"),
            "weekday": now.strftime("%A"), "trading_day": trading_day,
            "is_open": trading_day and 570 <= mins < 960, "session": session,
            "session_label": label, "session_note": SESSION_NOTES.get(session, ""),
            "phases": phases, "day_pct": day_pct,
            "in_day_band": trading_day and _DAY_START <= mins < _DAY_END,
            "next_event": nxt, "minutes": mins,
            "in_pulse_hours": trading_day and 480 <= mins <= 990}


def _idea_now(idea: dict, live, clock: dict, equity: float, cash: float, settings: dict,
              held: bool = False, banked: dict = None, gate: str = None) -> dict:
    """Evaluate one daily idea against the live quote and the clock.

    `held` — whether the account is actually in this name — changes the advice,
    not just the wording. "Take profit" and "cover into weakness" are
    instructions to close a position; issued to a flat trader they read as an
    instruction to open one at the exact level the plan said to get out at,
    which is the worst entry on the chart.

    `banked` — a journal entry for this ticker closed earlier today — outranks
    every live-price state. A name we took to target and sold this morning is
    not "reached without us"; it is a win already in the books, and reading it
    as a missed move is how a profitable day looks like a flat one.

    `gate` — the broker's reason for refusing the idea at the last plan run.
    The entry-timing states below all answer "should I get in now"; if the
    broker has already answered "no", they are noise dressed as a signal."""
    d = str(idea.get("direction", "neutral")).lower()
    # The same validated levels the broker enforces — see _idea_levels. Scoring
    # STOPPED/TARGET_HIT off an independent re-parse meant the tab could call a
    # stop hit at a price the broker's own stop was nowhere near.
    entry, stop, target, atr = _idea_levels(idea, live)
    out = {"ticker": idea.get("ticker"), "direction": d, "live": live,
           "entry": entry, "stop": stop, "target": target,
           "when": idea.get("when", ""), "trigger": idea.get("trigger", ""),
           # The tab's action strip is the only place these ideas are read now,
           # so the "why" travels with the levels instead of living in a second
           # table the reader has to cross-reference by ticker.
           "thesis": idea.get("thesis", ""), "risk": idea.get("risk", ""),
           "grade": idea.get("grade", ""),
           "rr": idea.get("rr") or idea.get("funnel_rr")}
    # No size for a name already held: the entry question is settled, and a
    # dollar figure next to an open position reads as "add this much".
    if live and not held:
        shares, note = _size_idea(d, entry or live, stop, atr, equity, cash, settings)
        if shares >= 1:
            out["size_shares"] = shares
            out["size_usd"] = round(shares * (entry or live), 2)
        elif note:
            out["size_note"] = note

    def set_state(state, note):
        out["state"], out["note"] = state, note
        return out

    out["held"] = held
    out["gate"] = gate
    if banked:
        out["banked"] = {k: banked.get(k) for k in
                         ("pnl", "pnl_pct", "r_multiple", "shares", "entry_price",
                          "exit_price", "ts", "reason")}
        pnl = banked.get("pnl") or 0.0
        r = banked.get("r_multiple")
        return set_state("BANKED", f"closed {str(banked.get('ts', ''))[-5:]} at "
                         f"${banked.get('exit_price')} — {'+' if pnl >= 0 else ''}${pnl:,.2f}"
                         + (f" ({'+' if r >= 0 else ''}{r}R)" if r is not None else "")
                         + " — done for the day, do not re-enter")
    if live is None:
        return set_state("MONITOR", "no live quote — check the symbol")
    through = "≤" if d == "long" else "≥"
    if d in ("long", "short"):
        hit_stop = stop and (live <= stop if d == "long" else live >= stop)
        hit_target = target and (live >= target if d == "long" else live <= target)
        if hit_stop:
            return set_state("STOPPED", f"live ${live} {through} stop ${stop} — "
                             + ("exit now, the stop is through" if held
                                else "idea invalidated, stand aside"))
        if hit_target:
            close = "take profit" if d == "long" else "cover into weakness"
            return set_state(
                "TARGET_HIT",
                f"live ${live} {'≥' if d == 'long' else '≤'} target ${target} — "
                + (f"{close}, don't chase" if held
                   else "reached without us; the move is done, do not enter here"))
    if held:
        # Neither stop nor target is through and we are already in the name.
        # Everything below this line is entry timing, which is a question that
        # has already been answered — "ACT NOW: enter at $146" on a position
        # you are holding is an instruction to double up.
        return set_state("HOLDING", "already in this name — manage the open position; "
                         "the stop and target are working at the broker")
    if gate:
        # Every state below is entry timing. The broker has already declined
        # this idea, so "ACT NOW" on it would be an instruction nothing will
        # follow — the honest answer is why it was declined.
        return set_state("NO_TRADE", f"broker passed — {gate}")
    if not clock["trading_day"] or clock["session"] == "closed":
        return set_state("NEXT_SESSION", f"market closed — prep this for {clock['next_event']['label'].lower()}")
    # One entry window for every idea, and it is the SAME one the broker
    # enforces. Each idea used to carry its own window parsed out of an LLM
    # "when" string ("9:30-10:30 ET", "power hour"), so the tab could say ACT
    # NOW at 08:45 on a card the broker would refuse to open for another hour.
    win = broker.window_state_for(clock["minutes"], clock["trading_day"])
    if not win["open"]:
        state = "WAIT" if clock["minutes"] < broker.ENTRY_OPEN_MIN else "WINDOW_PASSED"
        return set_state(state, win["why"])
    if entry and abs(live - entry) / entry <= 0.006:
        return set_state("ACT", f"live ${live} is AT the entry zone ${entry} — execute per trigger")
    if entry:
        pct = (live - entry) / entry * 100
        return set_state("IN_WINDOW", f"live ${live} is {pct:+.1f}% from entry ${entry} — watch the trigger")
    return set_state("IN_WINDOW", "in the window — watch the trigger")


def _directive(clock: dict, ideas: list, plan: dict) -> str:
    if not clock["trading_day"]:
        return (f"Market closed ({clock['weekday']}). Review the plan and prep orders — "
                f"{clock['next_event']['label'].lower()} in {clock['next_event']['in_min'] // 60}h.")
    if clock["session"] == "closed":
        return f"Market closed — next: {clock['next_event']['label']} at {clock['next_event']['at']}. Review today's fills and tomorrow's catalysts."
    act = [i for i in ideas if i.get("state") == "ACT"]
    if act:
        return "ACT NOW: " + "; ".join(f"{i['ticker']} at entry ${i['entry']}" for i in act[:3])
    win = broker.window_state_for(clock["minutes"], clock["trading_day"])
    if not win["open"]:
        return f"No new entries — {win['why']}. Manage what is open."
    if not ideas:
        return ("No card cleared the funnel — stand down. A quiet tape is a finding, "
                "not a failure to find something.")
    return str((plan.get("daily") or {}).get("summary", "")) or "Work the cards below at their zones."


# ── Session bias — the one bullish/bearish read for right now ────────────────
# Three independent reads, weighted by how much each one is trusted to gate a
# trade: the /ES-/NQ tape actually blocks counter-trend entries at the broker,
# so it carries double the weight of an opinion.
_COMPASS_BAND = 15          # |composite| below this is noise, not a direction
_BIAS_THRESHOLD = 2         # weighted score needed to call a side


def session_bias(plan: dict = None) -> dict:
    """Reduce the tape, the Compass composite and the plan's own daily bias to
    ONE direction — BULLISH / BEARISH / MIXED / NEUTRAL — keeping every driver
    visible so the call is never a black box. `drivers` carries each read's
    own direction; `score` is their weighted sum in -4..+4."""
    drivers, score, weighed = [], 0, 0

    tape = broker.market_bias(get_agent_data("technologia") or {})
    tape_dir = str(tape.get("direction", "unknown"))
    tape_vote = 1 if tape_dir == "bullish" else -1 if tape_dir == "bearish" else 0
    if tape_dir != "unknown":
        score += tape_vote * 2
        weighed += 2
    drivers.append({"key": "tape", "label": "/ES + /NQ tape", "direction": tape_dir,
                    "detail": tape.get("detail", ""), "weight": 2,
                    "gating": tape_dir in ("bullish", "bearish")})

    comp = ((get_agent_data("wallstreet_wolf") or {}).get("compass") or {})
    composite = comp.get("composite")
    if isinstance(composite, (int, float)):
        comp_dir = ("bullish" if composite >= _COMPASS_BAND
                    else "bearish" if composite <= -_COMPASS_BAND else "neutral")
        score += (1 if comp_dir == "bullish" else -1 if comp_dir == "bearish" else 0)
        weighed += 1
        vix = (comp.get("vix") or {}).get("level")
        drivers.append({"key": "compass", "label": "Sector composite", "direction": comp_dir,
                        "detail": f"{composite:+.0f} of ±100"
                                  + (f" · VIX {vix}" if vix else ""),
                        "weight": 1, "gating": False})

    daily_bias = str(((plan or {}).get("daily") or {}).get("bias", "")).upper()
    if daily_bias in ("BULLISH", "BEARISH", "NEUTRAL"):
        plan_dir = daily_bias.lower()
        score += (1 if plan_dir == "bullish" else -1 if plan_dir == "bearish" else 0)
        weighed += 1
        drivers.append({"key": "plan", "label": "Alpha Wolf daily plan", "direction": plan_dir,
                        "detail": str((plan or {}).get("stance", "")).upper() or "—",
                        "weight": 1, "gating": False})

    sides = {d["direction"] for d in drivers if d["direction"] in ("bullish", "bearish")}
    if not weighed:
        direction, why = "unknown", "no readings yet — run Technologia and Compass"
    elif score >= _BIAS_THRESHOLD:
        direction = "bullish"
        why = "Longs favoured" + (" — new shorts are blocked while /ES and /NQ agree"
                                  if tape_dir == "bullish" else " — the reads lean up")
    elif score <= -_BIAS_THRESHOLD:
        direction = "bearish"
        why = "Shorts favoured" + (" — new longs are blocked while /ES and /NQ agree"
                                   if tape_dir == "bearish" else " — the reads lean down")
    elif len(sides) > 1 or tape_dir == "mixed":
        direction, why = "mixed", "The reads disagree — no direction imposed; trade levels, not bias"
    else:
        direction, why = "neutral", "No clear edge either way — smaller size, wait for the tape"
    agree = sum(1 for d in drivers if d["direction"] == direction)
    return {"direction": direction, "score": score, "max_score": weighed,
            "drivers": drivers, "why": why,
            "agreement": f"{agree}/{len(drivers)} reads agree" if drivers else ""}


def _plan_tickers(plan: dict) -> list:
    out, seen = [], set()
    for i in (plan.get("daily") or {}).get("ideas", []) or []:
        t = str(i.get("ticker", "")).upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _banked_today(journal: list, clock: dict) -> dict:
    """Ticker → the trade closed today, newest first. Journal rows are stored
    newest-first, so the first hit for a ticker is the one that matters."""
    today = str(clock.get("date") or datetime.datetime.now(ET).strftime("%Y-%m-%d"))
    out = {}
    for j in journal or []:
        if str(j.get("ts", "")).startswith(today):
            out.setdefault(str(j.get("ticker", "")).upper(), j)
    return out


def _gate_reasons(plan: dict) -> dict:
    """Ticker → why the broker refused to open it at the last plan run."""
    skipped = ((plan.get("execution") or {}).get("skipped") or [])
    return {str(o.get("ticker", "")).upper(): str(o.get("why", ""))
            for o in skipped if o.get("action") == "open" and o.get("why")}


async def decision_now() -> dict:
    """Live 'what should I do right now' snapshot: market clock + the plan's
    ideas scored against live quotes."""
    clock = market_clock()
    data = get_agent_data(AGENT_ID) or {}
    plan = data.get("plan") or {}
    if not plan:
        # The session banner is the one thing that must render with no plan at
        # all — the clock and the tape don't depend on a synthesis run.
        return {"status": "no_plan", "clock": clock, "bias": session_bias(None),
                "directive": "No game-plan yet — run the pack, then run Alpha Wolf."}
    portfolio = data.get("portfolio") or {}
    tickers = sorted(set(_plan_tickers(plan)) | set((portfolio.get("positions") or {}).keys()))
    prices = await asyncio.to_thread(broker._fetch_prices_sync, tickers) if tickers else {}
    settings = broker.get_settings()
    # Alpaca-backed settings carry no "capital" (equity lives at the broker) —
    # fall back to the default virtual capital when no portfolio exists yet.
    equity = (broker.portfolio_equity(portfolio)
              if portfolio.get("positions") is not None
              else settings.get("capital", broker.DEFAULT_CAPITAL))
    cash = portfolio.get("cash")
    if cash is None:
        cash = equity
    held = {str(t).upper() for t in (portfolio.get("positions") or {})}
    banked = _banked_today(data.get("journal") or [], clock)
    gates = _gate_reasons(plan)
    daily = plan.get("daily") or {}
    ideas = []
    for i in daily.get("ideas", []) or []:
        t = str(i.get("ticker", "")).upper()
        ideas.append(_idea_now(i, prices.get(t), clock, equity, cash, settings,
                               held=t in held, banked=banked.get(t), gate=gates.get(t)))
    return {"status": "ok", "clock": clock, "bias": session_bias(plan),
            "plan_generated_at": plan.get("generated_at"),
            "entry_window": broker.window_state_for(clock["minutes"],
                                                          clock["trading_day"]),
            "directive": _directive(clock, ideas, plan),
            # No budget_per_position: it was equity × position_pct, the
            # concentration cap, which is no longer how anything here is sized.
            # Nothing consumed it, and leaving it invited the old mistake back.
            "ideas": ideas, "prices": prices,
            "pulse": data.get("pulse") or {}}


# ── Pulse — scheduled in-session check-in that alerts on actionable changes ──
def _build_pulse_email(alerts: list, snap: dict) -> str:
    rows = ""
    for a in alerts:
        ticks = " ".join(f"<span style='font-family:monospace;font-weight:800;color:#7c3aed'>{t}</span>"
                         for t in a.get("tickers", [])[:6])
        rows += (f"<div style='padding:10px 0;border-bottom:1px solid #f0f0f0'>"
                 f"<div style='font-size:13px;font-weight:800;color:#1a1a2e'>{a.get('title', '')}</div>"
                 f"<div style='font-size:12.5px;color:#444;margin-top:3px;line-height:1.5'>{a.get('msg', '')} {ticks}</div></div>")
    clock = snap.get("clock", {})
    return f"""<!DOCTYPE html><html><body style='font-family:Helvetica,sans-serif;background:#f6f7f9;margin:0;padding:0'>
<div style='max-width:560px;margin:24px auto;background:#fff;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb'>
  <div style='background:linear-gradient(135deg,#4c1d95,#7c3aed);padding:18px 26px'>
    <div style='font-size:18px;font-weight:800;color:#fff'>🐺 Alpha Wolf — live alert</div>
    <div style='font-size:12px;color:#ddd6fe;margin-top:3px'>{clock.get('session_label', '')} · {clock.get('et', '')} ET · plan {snap.get('plan_generated_at', '')}</div>
  </div>
  <div style='padding:16px 26px'>{rows}</div>
  <div style='padding:12px 26px;font-size:10.5px;color:#aeb4bf;line-height:1.5'>{DISCLAIMER}</div>
</div></body></html>"""


async def sync_funnel(force: bool = False) -> dict:
    """Re-fold Technologia's current cards into the stored master plan.

    Called every pulse. The synthesis (the model's regime read and weekly view)
    is NOT redone — that is a once-a-day judgement and re-running it every 30
    minutes would make the plan flicker. What is redone is
    everything downstream of the cards: which funnel setups are ideas, what they
    are priced and sized at, and whether the broker will take them. That is the
    part that changes during a session, and it was the part frozen at 08:30.

    Returns {"synced": bool, "new": [tickers newly added], "gone": [...]}.
    """
    data = get_agent_data(AGENT_ID) or {}
    plan = data.get("plan") or {}
    if not plan:
        return {"synced": False, "why": "no plan to sync into"}

    tech_data = await ensure_fresh_cards()
    fresh = funnel_snapshot(tech_data)
    prior = plan.get("funnel") or {}
    # Nothing new to fold in: same Technologia run as last time, and the cards
    # it produced are already in the plan. Compared on the epoch where both
    # sides have one — the printed stamp is minute-resolution, so two runs
    # inside the same minute read as identical and the second one's cards would
    # be dropped.
    same = (prior.get("generated_ts") == fresh.get("generated_ts")
            if prior.get("generated_ts") and fresh.get("generated_ts")
            else bool(prior.get("generated_at")) and prior["generated_at"] == fresh["generated_at"])
    if not force and same:
        return {"synced": False, "why": "cards unchanged since the last sync"}
    # A run that priced NOTHING is a data outage, not a flat tape. Syncing it
    # would retire every funnel idea in the plan — the day's trades would vanish
    # from Alpha Wolf because yfinance had a bad minute, and the screen would
    # read exactly like an honest stand-down. Hold the previous cards instead.
    cov = fresh.get("coverage") or {}
    if cov.get("requested") and not cov.get("returned"):
        log.warning("Technologia priced 0 symbols — holding the previous cards")
        return {"synced": False, "why": f"no price data this run (0/{cov['requested']} symbols) — "
                                        f"holding the cards from {prior.get('generated_at') or 'the last run'}"}

    before = {str(i.get("ticker", "")).upper() for i in (plan.get("daily") or {}).get("ideas", []) or []
              if i.get("source") == "technologia_funnel"}
    # Pricing and sizing run whenever cards change so the tab stays current;
    # ORDERS only inside the entry window. The broker enforces the same window
    # per idea — this just avoids the round trip when nothing could open anyway.
    clock = market_clock()
    await price_plan(plan, tech_data,
                     tech=plan.get("technicals"), levels=plan.get("levels"),
                     execute=broker.entry_window_state()["open"])
    after = {str(i.get("ticker", "")).upper() for i in (plan.get("daily") or {}).get("ideas", []) or []
             if i.get("source") == "technologia_funnel"}
    plan["synced_at"] = datetime.datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    save_agent_data(AGENT_ID, {"plan": plan})

    new, gone = sorted(after - before), sorted(before - after)
    if new or gone:
        log.info(f"Alpha Wolf funnel sync — added {new or '[]'}, dropped {gone or '[]'}")
    return {"synced": True, "new": new, "gone": gone,
            "cards": fresh["tradeable"], "armed": fresh["armed"]}


async def pulse_job(force: bool = False, send_email: bool = True) -> dict:
    """Every 30 min during market hours: pull Technologia's latest cards into
    the master plan, re-score it against live quotes, and alert (email + event
    log) only when something actionable changed — a card entering the plan, a
    new session window opening, an entry zone reached, a stop/target hit."""
    clock = market_clock()
    if not force and not clock["in_pulse_hours"]:
        return {"skipped": "outside market hours", "clock": clock}
    # Sync FIRST: a card that appeared at 10:40 should be scored, sized and
    # alerted on in this same pass, not seen for the first time half an hour
    # later.
    sync = await sync_funnel()
    snap = await decision_now()
    if snap.get("status") != "ok":
        return snap
    data = get_agent_data(AGENT_ID) or {}
    pulse = data.get("pulse") or {}
    plan_id = snap.get("plan_generated_at")
    same_plan = pulse.get("plan_id") == plan_id
    sent = set(pulse.get("sent", [])) if same_plan else set()

    alerts = []
    # A card that retired forfeits its alert key, so if the funnel produces it
    # again later in the session that is news rather than a duplicate.
    for t in sync.get("gone", []):
        sent.discard(f"card:{t}")
    # A new computed card is the single most actionable thing that can happen
    # between plan runs — it is a complete trade the funnel just produced.
    for t in sync.get("new", []):
        idea = next((i for i in snap.get("ideas", []) if str(i.get("ticker", "")).upper() == t), {})
        key = f"card:{t}"
        if key in sent:
            continue
        sent.add(key)
        alerts.append({"kind": "card", "title": f"{t} — 🃏 new funnel card in the plan",
                       "msg": (idea.get("note") or "").strip()
                              or f"{idea.get('direction', '')} entry {idea.get('entry')} "
                                 f"stop {idea.get('stop')} target {idea.get('target')}",
                       "tickers": [t]})
    for i in snap.get("ideas", []):
        st = i.get("state")
        if st in ("ACT", "STOPPED", "TARGET_HIT"):
            key = f"{i.get('ticker')}:{st}"
            if key not in sent:
                sent.add(key)
                # "stop hit" and "target hit" describe something happening to a
                # position. On a name the account is flat in, the honest
                # headline is that the level came and went without us — the
                # old wording sent "✅ target hit" for trades never taken.
                titles = ({"ACT": "🎯 at entry zone", "STOPPED": "🛑 stop hit", "TARGET_HIT": "✅ target hit"}
                          if i.get("held") else
                          {"ACT": "🎯 at entry zone", "STOPPED": "⛔ level broke — idea void (flat)",
                           "TARGET_HIT": "↗ target reached without us (flat)"})
                alerts.append({"kind": st, "title": f"{i.get('ticker')} — {titles[st]}",
                               "msg": i.get("note", ""), "tickers": [i.get("ticker")]})

    recipient = get_config("recipient", "") or DAILY_DIGEST_EMAIL
    emailed = False
    if alerts and send_email and recipient:
        send_html_email(recipient, f"🐺 Alpha Wolf alert — {alerts[0]['title']}",
                        _build_pulse_email(alerts, snap), sender_name="Alpha Wolf")
        emailed = True
    save_agent_data(AGENT_ID, {"pulse": {
        "plan_id": plan_id, "checked_at": datetime.datetime.now(ET).strftime("%Y-%m-%d %H:%M"),
        "session": clock["session_label"], "sent": sorted(sent),
        "alerts": alerts, "emailed": emailed, "funnel_sync": sync,
    }})
    if alerts:
        orchestrator.log_event(f"Alpha Wolf pulse: {len(alerts)} alert(s) — {alerts[0]['title']}", "#7c3aed")
    return {"alerts": alerts, "emailed": emailed, "clock": clock, "funnel_sync": sync}


# ── LLM synthesis → structured Daily + Weekly plan ───────────────────────────
async def _synthesize(summaries: dict) -> dict:
    """The model's job: write the regime narrative. It does not pick trades.

    The old prompt was three times this length and contained an "EXECUTION
    CONTRACT": the model was told its daily ideas would become real resting
    orders, asked for one specific entry price each, warned that ideas are gated
    on a self-scored 1-10 confidence, and instructed to size stops at 1.2xATR.
    It was, in other words, the trading strategy — written in English, scored by
    its own author, and placed ahead of a deterministic funnel that had already
    computed the same decision from real levels.

    Over 100 live trades that arrangement lost $2,331 at a 26% win rate, and the
    confidence score it gated on carried no information whatsoever. The cards
    decide now. The model writes the part it is actually good at: what kind of
    day this is, and what to stay away from. See docs/STRATEGY_REVIEW.md.
    """
    context = "\n".join(f"- {k}: {v}" for k, v in summaries.items())
    prompt = f"""You are Alpha Wolf, the lead strategist reading the desk's feeds:
- MARKET      = today's movers + the Wolf's read (Wallstreet Wolf)
- REGIME      = sector bias, VIX and the overall market regime
- TECHNOLOGIA = the computed trade cards, ALREADY decided by a four-stage funnel
  (auction context -> zone -> trigger -> risk). These are the day's trades.
- LIVE PRICES / TECHNICALS / LEVELS = real computed numbers

INTEL:
{{context}}

Write the REGIME COMMENTARY around those cards. You are not choosing trades and
you are not pricing them — the funnel already did, off measured levels, and its
cards are what will be executed. Do not propose tickers to buy or sell, do not
invent entries, stops or targets, and do not contradict a card.

Return ONLY valid JSON with this exact shape:
{{{{
  "headline": "one sentence — what kind of day this is for a trader",
  "stance": "RISK-ON|RISK-OFF|NEUTRAL",
  "regime": "one sentence on the market regime and its key driver",
  "confluence": ["what the feeds agree on right now"],
  "daily": {{{{
    "bias": "BULLISH|BEARISH|NEUTRAL",
    "summary": "2-3 sentences: the tape, and how to carry the cards through it"
  }}}},
  "weekly": {{{{
    "bias": "BULLISH|BEARISH|NEUTRAL",
    "summary": "2-3 sentences on the week",
    "themes": ["theme 1","theme 2"],
    "ideas": [{{{{"ticker":"SYM","direction":"long|short|neutral","thesis":"why","catalyst":"event this week","risk":"what invalidates it"}}}}]
  }}}},
  "avoid": ["what to stay away from right now and why"],
  "catalysts": ["upcoming catalyst 1","catalyst 2"],
  "risk_notes": "one line on sizing and overall risk posture"
}}}}
The weekly ideas are a WATCHLIST for research, never orders — nothing weekly is
routed to a broker. Give 1-3 confluence notes and 1-3 avoids. If the cards are
mostly stand-downs, say so plainly: a quiet tape is a finding. Never guarantee an
outcome. /no_think"""
    plan = await generate_json(
        prompt,
        system_prompt="You are a disciplined trading strategist. You describe the market regime; "
                      "you do not pick or price trades. Return only valid JSON.",
        agent_id=AGENT_ID,
    )
    return plan if isinstance(plan, dict) else {}


# ── One pipeline from cards to orders ────────────────────────────────────────
async def price_plan(plan: dict, tech_data: dict, *, prices: dict = None,
                     tech: dict = None, levels: dict = None, execute: bool = True) -> dict:
    """Put the funnel's cards into the plan as its ideas, price them, size
    them, trade them.

    This is deliberately one function called from two places — the daily
    synthesis and the 30-minute pulse. When the pulse only re-SCORED the stored
    plan, a card the funnel produced at 10:40 could not become an idea, could
    not be sized and could never be executed: it waited for tomorrow's 08:30
    cron, by which time it was a card about a session that had already closed.
    Running the identical path from both keeps one master plan rather than a
    morning artifact and a live view of it that quietly disagree.

    `execute=False` prices and sizes without sending orders — used when the
    market is shut and there is nothing to fill.
    """
    # The cards ARE the daily ideas. Not merged with, not ranked against, not
    # vetoed by anything the model wrote — assigned. A card that went from LONG
    # back to WAIT disappears from the plan on the next pass because this is a
    # replacement, which is what the old additive merge needed a pruning rule to
    # fake.
    daily = plan.setdefault("daily", {}) or {}
    plan["daily"] = daily
    daily["ideas"] = cards_to_ideas(tech_data)
    plan["funnel"] = funnel_snapshot(tech_data)

    prices = dict(prices or {})
    tech = dict(tech or {})
    levels = dict(levels or {})
    missing = [t for t in _plan_tickers(plan) if t not in prices]
    if missing:
        prices.update(await asyncio.to_thread(broker._fetch_prices_sync, missing))
    missing_tech = [t for t in _plan_tickers(plan) if t not in tech]
    if missing_tech:
        tech.update(await asyncio.to_thread(technicals_tool.compute_sync, missing_tech))
    missing_levels = [t for t in _plan_tickers(plan) if t not in levels]
    if missing_levels:
        levels.update(await asyncio.to_thread(levels_tool.compute_sync, missing_levels))

    _price_ideas(plan, prices, tech, levels)
    plan["technicals"] = tech
    plan["levels"] = levels

    settings = broker.get_settings()
    portfolio = (get_agent_data(AGENT_ID) or {}).get("portfolio") or {}
    equity = (broker.portfolio_equity(portfolio)
              if portfolio.get("positions") is not None
              else settings.get("capital", broker.DEFAULT_CAPITAL))
    cash = portfolio.get("cash")
    _apply_sizing((plan.get("daily") or {}).get("ideas", []) or [], prices, equity,
                  equity if cash is None else cash, settings)

    if execute:
        orchestrator.set_progress(AGENT_ID, "Executing trades on the paper portfolio…")
        try:
            plan["execution"] = await broker.execute_plan(plan)
        except Exception as e:
            log.error(f"Alpha Wolf execution error: {e}", exc_info=True)
            plan["execution"] = {"enabled": True, "executed": [], "skipped": [],
                                 "note": f"Execution failed: {e}"}
        # Carry the broker's refusal back onto the card it refused. "Why is this
        # A-grade card not a position?" was previously answerable only by
        # cross-reading the execution report against the funnel table by ticker.
        #
        # A card whose position is already OPEN is the exception: the broker
        # declines it every half hour under the one-trade-per-symbol rule, and
        # rendering that as a warning would mark the day's working trade as the
        # one thing that failed. Held beats gated.
        gates = _gate_reasons(plan)
        held = {str(t).upper() for t in (portfolio.get("positions") or {})}
        for c in plan["funnel"]["cards"]:
            sym = str(c["symbol"]).upper()
            if sym in held:
                c["gate"] = ""
                c["plan_note"] = "held — the position is open and managed at the broker"
            elif c["in_plan"] and gates.get(sym):
                c["gate"] = gates[sym]
    return plan


# ── Main job ─────────────────────────────────────────────────────────────────
async def alpha_wolf_job():
    orchestrator.update_agent_status(AGENT_ID, "running")
    try:
        # The master plan is only as current as the cards under it — refresh a
        # stale funnel BEFORE reading the pack, not after synthesizing on it.
        await ensure_fresh_cards()
        orchestrator.set_progress(AGENT_ID, "Gathering intel from the pack…")
        summaries, sources_used, raw = _gather()

        orchestrator.set_progress(AGENT_ID, "Pulling live quotes for the pack's tickers…")
        candidates = _candidate_tickers(raw)
        prices = await asyncio.to_thread(broker._fetch_prices_sync, candidates) if candidates else {}
        if prices:
            summaries["LIVE PRICES"] = ", ".join(f"{t} ${p}" for t, p in sorted(prices.items()))

        orchestrator.set_progress(AGENT_ID, "Computing technicals (RSI · SMA trend · ATR)…")
        tech = await asyncio.to_thread(technicals_tool.compute_sync, candidates) if candidates else {}
        if tech:
            summaries["TECHNICALS"] = " | ".join(
                technicals_tool.summary_line(t) for _, t in sorted(tech.items()))

        orchestrator.set_progress(AGENT_ID, "Computing VWAP, volume profile & support/resistance…")
        levels = await asyncio.to_thread(levels_tool.compute_sync, candidates) if candidates else {}
        if levels:
            summaries["LEVELS"] = " | ".join(
                f"{t} {levels_tool.summary_line(v)}" for t, v in sorted(levels.items()))

        provider, model = resolve_model(AGENT_ID)
        orchestrator.set_progress(AGENT_ID, f"Synthesizing the game-plan with {model}…")
        plan = await _synthesize(summaries)
        if plan:
            plan = _sanitize_plan(plan)
        # fall back only when synthesis produced nothing usable
        if not plan or not (plan.get("headline") or plan.get("regime")
                            or plan["daily"]["ideas"] or plan["weekly"]["ideas"]):
            plan = {
                "headline": "Not enough intel yet — run the pack, then re-run Alpha Wolf.",
                "stance": "NEUTRAL",
                "regime": "Not enough sub-agent data yet — run the pack (Wolf, Technologia) "
                          "first, then re-run Alpha Wolf.",
                "confluence": [], "daily": {}, "weekly": {}, "avoid": [], "catalysts": [], "risk_notes": "",
            }
        plan["disclaimer"] = DISCLAIMER
        plan["inputs"] = summaries
        plan["sources_used"] = sources_used
        plan["generated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        orchestrator.set_progress(AGENT_ID, "Folding in the funnel's cards & sizing…")
        await price_plan(plan, raw.get("technologia"),
                         prices=prices, tech=tech, levels=levels)

        save_agent_data(AGENT_ID, {"plan": plan})

        recipient = get_config("recipient", "") or DAILY_DIGEST_EMAIL
        if recipient:
            send_html_email(recipient, "🐺 Alpha Wolf — Daily + Weekly Trade Plan",
                            _build_email(plan), sender_name="Alpha Wolf")

        orchestrator.update_agent_status(AGENT_ID, "idle")
        n_exec = len((plan.get("execution") or {}).get("executed", []))
        orchestrator.log_event(
            f"Alpha Wolf synthesized a plan from {len(sources_used)}/{len(SUB_AGENTS)} sub-agents"
            + (f" · executed {n_exec} paper trade{'s' if n_exec != 1 else ''}" if n_exec else ""),
            "#7c3aed")
        log.info(f"Alpha Wolf complete — {len(sources_used)} sources, {n_exec} trades executed")
    except Exception as e:
        log.error(f"Alpha Wolf error: {e}", exc_info=True)
        orchestrator.update_agent_status(AGENT_ID, "error", str(e))


# ── Email HTML ───────────────────────────────────────────────────────────────
def _idea_rows(ideas: list, weekly: bool = False) -> str:
    if not ideas:
        return "<div style='font-size:13px;color:#888;padding:8px 0'>No specific ideas this run.</div>"
    rows = ""
    for x in ideas[:4]:
        d = str(x.get("direction", "")).lower()
        dc = "#16a34a" if d == "long" else "#dc2626" if d == "short" else "#6b7280"
        third_label = "Catalyst" if weekly else "Trigger"
        third_val = x.get("catalyst", "") if weekly else x.get("trigger", "")
        levels = ""
        if not weekly:
            parts = [f"<b>{lbl}:</b> {x[k]}" for lbl, k in
                     (("Entry", "entry"), ("Stop", "stop"), ("Target", "target"), ("When", "when"))
                     if x.get(k)]
            if x.get("rr"):
                parts.append(f"<b>R:R</b> {x['rr']}:1")
            if x.get("size_usd"):
                parts.append(f"<b>Size:</b> ~${x['size_usd']:,.0f} · {x.get('size_shares')} sh")
            if parts:
                levels = (f"<div style='font-size:11.5px;color:#4c1d95;margin-top:4px;font-family:monospace'>"
                          f"{' &nbsp;·&nbsp; '.join(parts)}</div>")
        grade = x.get("grade")
        conf_pill = (f"<span style='font-size:10px;font-weight:800;color:#4c1d95;background:#4c1d9514;"
                     f"padding:2px 8px;border-radius:4px'>grade {grade}</span>") if grade else ""
        rows += f"""
        <div style='padding:12px 0;border-bottom:1px solid #f0f0f0'>
          <div style='display:flex;align-items:center;gap:8px'>
            <span style='font-family:monospace;font-weight:800;font-size:14px;color:#1a1a2e'>{x.get('ticker','—')}</span>
            <span style='font-size:10px;font-weight:800;color:{dc};background:{dc}14;padding:2px 8px;border-radius:4px;text-transform:uppercase'>{d or 'n/a'}</span>
            {conf_pill}
          </div>
          <div style='font-size:12.5px;color:#444;margin-top:4px;line-height:1.45'>{x.get('thesis','')}</div>
          {levels}
          <div style='font-size:11.5px;color:#666;margin-top:3px'><b>{third_label}:</b> {third_val} &nbsp;·&nbsp; <b>Risk:</b> {x.get('risk','')}</div>
        </div>"""
    return rows


def _execution_section(execution: dict) -> str:
    if not execution:
        return ""
    if not execution.get("enabled"):
        return ""
    executed = execution.get("executed", []) or []
    summary = execution.get("summary", {}) or {}
    if executed:
        rows = ""
        for t in executed[:8]:
            a = str(t.get("action", ""))
            ac = "#16a34a" if a in ("BUY", "COVER") else "#dc2626"
            pnl = t.get("pnl")
            pnl_txt = (f" &nbsp;·&nbsp; <b style='color:{'#16a34a' if pnl >= 0 else '#dc2626'}'>P&amp;L {pnl:+,.2f}</b>"
                       if isinstance(pnl, (int, float)) else "")
            rows += (f"<div style='padding:8px 0;border-bottom:1px solid #f0f0f0;font-size:12.5px;color:#444'>"
                     f"<span style='font-size:10px;font-weight:800;color:#fff;background:{ac};padding:2px 8px;"
                     f"border-radius:4px'>{a}</span> "
                     f"<span style='font-family:monospace;font-weight:800'>{t.get('ticker')}</span> "
                     f"{t.get('shares')} sh @ ${t.get('price')}{pnl_txt}"
                     f"<div style='font-size:11px;color:#888;margin-top:2px'>{t.get('reason','')}</div></div>")
    else:
        rows = "<div style='font-size:12.5px;color:#888'>No new trades this run — portfolio unchanged.</div>"
    eq = summary.get("equity")
    ret = summary.get("return_pct")
    stat = ""
    if eq is not None:
        rc = "#16a34a" if (ret or 0) >= 0 else "#dc2626"
        stat = (f"<div style='font-size:12px;color:#444;margin-top:10px'><b>Portfolio:</b> ${eq:,.2f} equity "
                f"· ${summary.get('cash', 0):,.2f} cash · {summary.get('open_positions', 0)} open positions "
                f"· <b style='color:{rc}'>{ret:+.2f}%</b> all-time</div>")
    return f"""
  <div style='padding:20px 32px;border-bottom:1px solid #e5e7eb;background:#fafaf9'>
    <div style='font-size:13px;font-weight:800;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px'>⚡ Trades Executed (paper)</div>
    {rows}{stat}
  </div>"""


def _bias_pill(bias: str) -> str:
    b = str(bias or "NEUTRAL").upper()
    c = "#16a34a" if b == "BULLISH" else "#dc2626" if b == "BEARISH" else "#6b7280"
    return f"<span style='font-size:11px;font-weight:800;color:{c};background:{c}16;padding:3px 10px;border-radius:6px'>{b}</span>"


def _build_email(plan: dict) -> str:
    daily = plan.get("daily", {}) or {}
    weekly = plan.get("weekly", {}) or {}
    catalysts = plan.get("catalysts", []) or []
    themes = weekly.get("themes", []) or []
    confluence = plan.get("confluence", []) or []
    avoid = plan.get("avoid", []) or []
    cat_html = "".join(f"<li style='margin:3px 0'>{c}</li>" for c in catalysts[:6]) or "<li>None flagged</li>"
    conf_html = "".join(f"<li style='margin:3px 0'>{c}</li>" for c in confluence[:4])
    avoid_html = "".join(f"<li style='margin:3px 0'>{c}</li>" for c in avoid[:4]) or "<li>Nothing flagged</li>"
    theme_html = " · ".join(themes[:4]) or "—"
    stance = str(plan.get("stance", "NEUTRAL")).upper()
    stance_c = "#16a34a" if stance == "RISK-ON" else "#dc2626" if stance == "RISK-OFF" else "#6b7280"
    return f"""<!DOCTYPE html><html><body style='font-family:Helvetica,sans-serif;background:#f6f7f9;margin:0;padding:0'>
<div style='max-width:660px;margin:24px auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb'>
  <div style='background:linear-gradient(135deg,#4c1d95,#7c3aed);padding:26px 32px'>
    <div style='font-size:23px;font-weight:800;color:#fff'>🐺 Alpha Wolf</div>
    <div style='font-size:13px;color:#ddd6fe;margin-top:4px'>Master game-plan · {plan.get('generated_at','')} · synthesized from {len(plan.get('sources_used', []))}/{len(SUB_AGENTS)} agents</div>
  </div>

  <div style='padding:18px 32px;background:#f5f3ff;border-bottom:1px solid #e5e7eb'>
    <div style='display:flex;align-items:center;gap:10px;margin-bottom:8px'>
      <span style='font-size:10px;font-weight:800;color:#fff;background:{stance_c};padding:3px 10px;border-radius:6px'>{stance}</span>
      <span style='font-size:15px;font-weight:800;color:#4c1d95'>{plan.get('headline','')}</span>
    </div>
    <div style='font-size:13px;line-height:1.55;color:#3730a3'><b>Regime:</b> {plan.get('regime','')}</div>
    {f"<div style='margin-top:10px'><div style='font-size:11px;font-weight:700;color:#7c3aed;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px'>Confluence (high conviction)</div><ul style='margin:0;padding-left:18px;font-size:12.5px;color:#3730a3'>{conf_html}</ul></div>" if conf_html else ""}
  </div>

  <div style='padding:20px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:13px;font-weight:800;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px'>Daily Plan {_bias_pill(daily.get('bias'))}</div>
    <div style='font-size:13px;color:#444;line-height:1.5;margin-bottom:6px'>{daily.get('summary','')}</div>
    {_idea_rows(daily.get('ideas', []))}
  </div>
{_execution_section(plan.get('execution', {}) or {})}
  <div style='padding:20px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:13px;font-weight:800;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px'>Weekly Plan {_bias_pill(weekly.get('bias'))}</div>
    <div style='font-size:13px;color:#444;line-height:1.5;margin-bottom:4px'>{weekly.get('summary','')}</div>
    <div style='font-size:11.5px;color:#7c3aed;margin-bottom:6px'><b>Themes:</b> {theme_html}</div>
    {_idea_rows(weekly.get('ideas', []), weekly=True)}
  </div>

  <div style='padding:18px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:12px;font-weight:700;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px'>Catalysts to watch</div>
    <ul style='margin:0;padding-left:18px;font-size:12.5px;color:#444'>{cat_html}</ul>
    <div style='font-size:12px;font-weight:700;color:#dc2626;text-transform:uppercase;letter-spacing:.5px;margin:12px 0 6px'>Avoid</div>
    <ul style='margin:0;padding-left:18px;font-size:12.5px;color:#444'>{avoid_html}</ul>
    <div style='font-size:12.5px;color:#444;margin-top:10px'><b>Risk:</b> {plan.get('risk_notes','')}</div>
  </div>

  <div style='padding:14px 32px;font-size:10.5px;color:#aeb4bf;line-height:1.5'>{plan.get('disclaimer', DISCLAIMER)}</div>
</div></body></html>"""


def email_preview() -> str:
    data = get_agent_data(AGENT_ID) or {}
    plan = data.get("plan", {})
    if not plan:
        return "<p>No Alpha Wolf plan yet. Run the sub-agents, then run Alpha Wolf.</p>"
    return _build_email(plan)
