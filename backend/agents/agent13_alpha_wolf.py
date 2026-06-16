# ============================================================================
# Agent 13 — Alpha Wolf (Master Agent)
# Leads the pack: ingests the cached output of six trading sub-agents
# (Wallstreet Wolf, Wallstreet Compass, Strategy Scout, Capitol Tracker,
# Options Flow, Earnings Calendar), makes ONE local-LLM call to synthesize
# a ranked Daily + Weekly trade game-plan, then EXECUTES the daily ideas
# through the paper broker (simulated fills at live prices, virtual capital).
# ============================================================================
import os
import re
import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo

from database import save_agent_data, get_agent_data, get_config
from llm_client import generate_json
from orchestrator import orchestrator
from email_utils import send_html_email
import paper_broker

log = logging.getLogger("alpha_wolf")

ET = ZoneInfo("America/New_York")

AGENT_ID = "alpha_wolf"
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")

# The pack Alpha Wolf commands. Keyed by backend agent_id → the AgentData key
# each one persists under.
SUB_AGENTS = {
    "wallstreet_wolf": "market_data",
    "compass":         "compass",
    "strategy_scout":  "scout",
    "capitol_tracker": "tracker",
    "options_flow":    "flow",
    "earnings_cal":    "calendar",
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


def _scout_summary(d: dict) -> str:
    s = (d or {}).get("scout", {}) or {}
    strats = s.get("strategies", [])[:6]
    listed = "; ".join(f"{x.get('name')} ({x.get('type')}/{x.get('timeframe')})" for x in strats)
    return "Trending strategies: " + (listed or "n/a")


def _capitol_summary(d: dict) -> str:
    t = (d or {}).get("tracker", {}) or {}
    trades = t.get("trades", [])[:10]
    def _last(name): return (name or "?").split()[-1] if name else "?"
    tr = ", ".join(f"{_last(x.get('politician'))} {str(x.get('type',''))[:4]} {x.get('ticker') or '—'}"
                   for x in trades) or "n/a"
    return f"Recent congressional trades: {tr}. Note: {str(t.get('commentary',''))[:200]}"


def _options_summary(d: dict) -> str:
    f = (d or {}).get("flow", {}) or {}
    top = f.get("top5", []) or f.get("signals", []) or []
    sig = ", ".join(f"{x.get('ticker')} {x.get('type','')} IV%ile {x.get('iv_pct','?')}"
                    for x in top[:6]) or "n/a"
    return f"Unusual options flow: {sig}. Note: {str(f.get('commentary',''))[:200]}"


def _earnings_summary(d: dict) -> str:
    c = (d or {}).get("calendar", {}) or {}
    tw = c.get("this_week", []) or []
    ev = ", ".join(f"{e.get('ticker')} {e.get('earnings_date','')} exp±{e.get('expected_pct','?')}%"
                   for e in tw[:8]) or "none this week"
    return f"Earnings this week: {ev}. IV-crush setups flagged: {len(c.get('iv_crush_opp', []))}."


def _gather():
    data = {aid: get_agent_data(aid) for aid in SUB_AGENTS}
    summaries = {
        "MARKET":     _wolf_summary(data["wallstreet_wolf"]),
        "REGIME":     _compass_summary(data["compass"]),
        "STRATEGIES": _scout_summary(data["strategy_scout"]),
        "CONGRESS":   _capitol_summary(data["capitol_tracker"]),
        "OPTIONS":    _options_summary(data["options_flow"]),
        "EARNINGS":   _earnings_summary(data["earnings_cal"]),
    }
    sources_used = [aid for aid, key in SUB_AGENTS.items() if (data.get(aid) or {}).get(key)]
    return summaries, sources_used, data


def _candidate_tickers(data: dict) -> list:
    """Tickers the plan is likely to reference — top movers, unusual options
    flow, earnings names, and currently held positions. Used to pull live
    quotes so the LLM anchors entry/stop/target levels to real prices."""
    syms = []
    md = (data.get("wallstreet_wolf") or {}).get("market_data", {}) or {}
    for k in ("top_gainers", "top_losers"):
        syms += [s.get("symbol") for s in md.get(k, [])[:5]]
    fl = (data.get("options_flow") or {}).get("flow", {}) or {}
    syms += [x.get("ticker") for x in (fl.get("top5") or fl.get("signals") or [])[:5]]
    cal = (data.get("earnings_cal") or {}).get("calendar", {}) or {}
    syms += [e.get("ticker") for e in cal.get("this_week", [])[:5]]
    port = (get_agent_data(AGENT_ID) or {}).get("portfolio") or {}
    syms += list((port.get("positions") or {}).keys())
    out, seen = [], set()
    for s in syms:
        s = str(s or "").upper().strip()
        if s and s.replace("-", "").isalnum() and s not in seen:
            seen.add(s)
            out.append(s)
    return out[:14]


def _apply_sizing(ideas: list, prices: dict, budget: float):
    """Annotate daily ideas with a concrete dollar/share size suggestion."""
    for i in ideas or []:
        live = prices.get(str(i.get("ticker", "")).upper())
        if not live or not budget:
            continue
        shares = int(budget // live)
        if shares >= 1:
            i["live"] = live
            i["size_shares"] = shares
            i["size_usd"] = round(shares * live, 2)


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
    if weekly:
        out["catalyst"] = _as_text(idea.get("catalyst"))
    else:
        out["trigger"] = _as_text(idea.get("trigger"))
        out["entry"] = _as_text(idea.get("entry"))
        out["stop"] = _as_text(idea.get("stop"))
        out["target"] = _as_text(idea.get("target"))
        out["when"] = _as_text(idea.get("when"))
    return out


def _sanitize_slot(slot) -> dict:
    """One time-of-day entry in the daily session timeline."""
    if not isinstance(slot, dict):
        return {}
    raw = slot.get("tickers")
    items = raw if isinstance(raw, list) else ([raw] if raw else [])
    return {
        "time": _as_text(slot.get("time")),
        "action": _as_text(slot.get("action")),
        "tickers": [t for t in (_as_text(x).upper()[:10] for x in items[:6]) if t],
    }


def _sanitize_horizon(h, weekly: bool) -> dict:
    h = h if isinstance(h, dict) else {}
    bias = _as_text(h.get("bias")).upper()
    out = {
        "bias": bias if bias in ("BULLISH", "BEARISH", "NEUTRAL") else "NEUTRAL",
        "summary": _as_text(h.get("summary")),
        "ideas": [i for i in (_sanitize_idea(x, weekly) for x in (h.get("ideas") or [])[:6])
                  if i.get("ticker")],
    }
    if weekly:
        out["themes"] = _as_text_list(h.get("themes"), 6)
    else:
        out["timeline"] = [s for s in (_sanitize_slot(x) for x in (h.get("timeline") or [])[:8])
                           if s.get("action")]
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
_SESSION_BOUNDS = {k: (a, b) for k, _, a, b in SESSIONS}
_SESSION_EVENTS = [(240, "Pre-market opens"), (570, "Opening bell"), (630, "Midday"),
                   (900, "Power hour"), (960, "Closing bell"), (1200, "After-hours end")]

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
    return {"et": now.strftime("%-I:%M %p"), "date": now.strftime("%Y-%m-%d"),
            "weekday": now.strftime("%A"), "trading_day": trading_day,
            "is_open": trading_day and 570 <= mins < 960, "session": session,
            "session_label": label, "next_event": nxt, "minutes": mins,
            "in_pulse_hours": trading_day and 480 <= mins <= 990}


def _first_price(text, live: float = None):
    """Pull the first dollar level out of LLM text like '$146.20 zone (9:35 ET)'.
    A parsed level wildly far from the live quote is a hallucination — drop it."""
    s = str(text or "")
    m = _PRICE_RE.search(s)
    if not m:
        m = _NUM_RE.search(re.sub(r"\b\d{1,2}:\d{2}\b", " ", s))  # don't match times
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    if live and not (0.4 * live <= v <= 2.5 * live):
        return None
    return v


def _window_minutes(text):
    """Parse a time window from idea/slot text — explicit times ('9:30-10:30',
    '3:45 PM') first, session names ('power hour') as fallback."""
    s = str(text or "").lower()
    times = []
    for h, mm, ap in _TIME_RE.findall(s):
        t = int(h) % 12 * 60 + int(mm) if ap else int(h) * 60 + int(mm)
        if ap and ap.lower() == "pm":
            t += 12 * 60
        elif not ap and int(h) <= 7:   # bare '3:45' in market context means PM
            t += 12 * 60
        times.append(t)
    if len(times) >= 2:
        a, b = min(times[0], times[-1]), max(times[0], times[-1])
        return (a, b if b > a else a + 30)
    if len(times) == 1:
        return (times[0] - 10, times[0] + 50)
    for key, words in (("pre", ("pre-market", "premarket", "pre market")),
                       ("power", ("power hour", "power-hour")),
                       ("midday", ("midday", "mid-day", "lunch")),
                       ("close", ("close", "closing")),
                       ("open", ("open",))):
        if any(w in s for w in words):
            return _SESSION_BOUNDS.get(key, (945, 960)) if key != "close" else (945, 960)
    return None


def _idea_now(idea: dict, live, clock: dict, budget: float) -> dict:
    """Evaluate one daily idea against the live quote and the clock."""
    d = str(idea.get("direction", "neutral")).lower()
    entry = _first_price(idea.get("entry") or idea.get("trigger"), live)
    stop = _first_price(idea.get("stop"), live)
    target = _first_price(idea.get("target"), live)
    out = {"ticker": idea.get("ticker"), "direction": d, "live": live,
           "entry": entry, "stop": stop, "target": target,
           "when": idea.get("when", ""), "trigger": idea.get("trigger", "")}
    if live and budget:
        shares = int(budget // live)
        if shares >= 1:
            out["size_shares"] = shares
            out["size_usd"] = round(shares * live, 2)

    def set_state(state, note):
        out["state"], out["note"] = state, note
        return out

    if live is None:
        return set_state("MONITOR", "no live quote — check the symbol")
    if d == "long":
        if stop and live <= stop:
            return set_state("STOPPED", f"live ${live} ≤ stop ${stop} — idea invalidated, stand aside")
        if target and live >= target:
            return set_state("TARGET_HIT", f"live ${live} ≥ target ${target} — take profit, don't chase")
    elif d == "short":
        if stop and live >= stop:
            return set_state("STOPPED", f"live ${live} ≥ stop ${stop} — idea invalidated, stand aside")
        if target and live <= target:
            return set_state("TARGET_HIT", f"live ${live} ≤ target ${target} — cover into weakness")
    if not clock["trading_day"] or clock["session"] == "closed":
        return set_state("NEXT_SESSION", f"market closed — prep this for {clock['next_event']['label'].lower()}")
    win = _window_minutes(idea.get("when")) or (570, 960)
    mins = clock["minutes"]
    if mins < win[0]:
        return set_state("WAIT", f"window opens {_fmt_min(win[0])} ET — set alerts, don't act yet")
    if mins >= win[1]:
        return set_state("WINDOW_PASSED", "window passed — stand down unless the trigger re-fires")
    if entry and abs(live - entry) / entry <= 0.006:
        return set_state("ACT", f"live ${live} is AT the entry zone ${entry} — execute per trigger")
    if entry:
        pct = (live - entry) / entry * 100
        return set_state("IN_WINDOW", f"live ${live} is {pct:+.1f}% from entry ${entry} — watch the trigger")
    return set_state("IN_WINDOW", "in the window — watch the trigger")


def _current_slot(timeline: list, clock: dict):
    if not clock["trading_day"] or clock["session"] in ("closed",):
        return None
    mins = clock["minutes"]
    for i, slot in enumerate(timeline or []):
        win = _window_minutes(slot.get("time"))
        if win and win[0] <= mins < win[1]:
            return {"index": i, **slot}
    return None


def _directive(clock: dict, slot, ideas: list, plan: dict) -> str:
    if not clock["trading_day"]:
        return (f"Market closed ({clock['weekday']}). Review the plan and prep orders — "
                f"{clock['next_event']['label'].lower()} in {clock['next_event']['in_min'] // 60}h.")
    if clock["session"] == "closed":
        return f"Market closed — next: {clock['next_event']['label']} at {clock['next_event']['at']}. Review today's fills and tomorrow's catalysts."
    act = [i for i in ideas if i.get("state") == "ACT"]
    if act:
        return "ACT NOW: " + "; ".join(f"{i['ticker']} at entry ${i['entry']}" for i in act[:3])
    if slot:
        return str(slot.get("action", ""))
    return str((plan.get("daily") or {}).get("summary", "")) or "No timeline entry for this window — follow the daily plan."


def _plan_tickers(plan: dict) -> list:
    out, seen = [], set()
    for i in (plan.get("daily") or {}).get("ideas", []) or []:
        t = str(i.get("ticker", "")).upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


async def decision_now() -> dict:
    """Live 'what should I do right now' snapshot: market clock + the plan's
    ideas scored against live quotes + the active timeline slot."""
    clock = market_clock()
    data = get_agent_data(AGENT_ID) or {}
    plan = data.get("plan") or {}
    if not plan:
        return {"status": "no_plan", "clock": clock,
                "directive": "No game-plan yet — run the pack, then run Alpha Wolf."}
    portfolio = data.get("portfolio") or {}
    tickers = sorted(set(_plan_tickers(plan)) | set((portfolio.get("positions") or {}).keys()))
    prices = await asyncio.to_thread(paper_broker._fetch_prices_sync, tickers) if tickers else {}
    settings = paper_broker.get_settings()
    equity = paper_broker.portfolio_equity(portfolio) if portfolio.get("positions") is not None else settings["capital"]
    budget = equity * settings["position_pct"] / 100.0
    daily = plan.get("daily") or {}
    ideas = [_idea_now(i, prices.get(str(i.get("ticker", "")).upper()), clock, budget)
             for i in daily.get("ideas", []) or []]
    slot = _current_slot(daily.get("timeline") or [], clock)
    return {"status": "ok", "clock": clock, "plan_generated_at": plan.get("generated_at"),
            "current_slot": slot, "directive": _directive(clock, slot, ideas, plan),
            "ideas": ideas, "prices": prices, "budget_per_position": round(budget, 2),
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


async def pulse_job(force: bool = False, send_email: bool = True) -> dict:
    """Every 30 min during market hours: re-score the plan against live quotes
    and alert (email + event log) only when something actionable changed —
    a new session window opening, an entry zone reached, a stop/target hit."""
    clock = market_clock()
    if not force and not clock["in_pulse_hours"]:
        return {"skipped": "outside market hours", "clock": clock}
    snap = await decision_now()
    if snap.get("status") != "ok":
        return snap
    data = get_agent_data(AGENT_ID) or {}
    pulse = data.get("pulse") or {}
    plan_id = snap.get("plan_generated_at")
    same_plan = pulse.get("plan_id") == plan_id
    sent = set(pulse.get("sent", [])) if same_plan else set()

    alerts = []
    slot = snap.get("current_slot")
    if slot is not None and f"slot:{slot['index']}" not in sent:
        sent.add(f"slot:{slot['index']}")
        alerts.append({"kind": "slot", "title": f"⏰ {slot.get('time', 'Now')} — window open",
                       "msg": slot.get("action", ""), "tickers": slot.get("tickers", [])})
    for i in snap.get("ideas", []):
        st = i.get("state")
        if st in ("ACT", "STOPPED", "TARGET_HIT"):
            key = f"{i.get('ticker')}:{st}"
            if key not in sent:
                sent.add(key)
                titles = {"ACT": "🎯 at entry zone", "STOPPED": "🛑 stop hit", "TARGET_HIT": "✅ target hit"}
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
        "alerts": alerts, "emailed": emailed,
    }})
    if alerts:
        orchestrator.log_event(f"Alpha Wolf pulse: {len(alerts)} alert(s) — {alerts[0]['title']}", "#7c3aed")
    return {"alerts": alerts, "emailed": emailed, "clock": clock}


# ── LLM synthesis → structured Daily + Weekly plan ───────────────────────────
async def _synthesize(summaries: dict) -> dict:
    context = "\n".join(f"- {k}: {v}" for k, v in summaries.items())
    prompt = f"""You are Alpha Wolf, the lead strategist commanding a pack of six specialist agents.
Each agent below reports a different slice of the market:
- MARKET      = today's movers + the Wolf's read (Wallstreet Wolf)
- REGIME      = sector bias + overall market regime (Wallstreet Compass)
- STRATEGIES  = setups other traders are actively running (Strategy Scout)
- CONGRESS    = recent congressional buys/sells (Capitol Tracker)
- OPTIONS     = unusual options flow / positioning (Options Flow)
- EARNINGS    = upcoming earnings catalysts (Earnings Calendar)
- LIVE PRICES = real-time quotes — anchor EVERY entry/stop/target level to these; never invent a price

INTEL:
{context}

Your job: CROSS-REFERENCE all six feeds and build ONE clear, actionable game-plan. Your
highest-conviction calls are names where MULTIPLE feeds line up — e.g. a bullish regime + unusual
call flow + congressional buying + a near-term catalyst on the same ticker. Tell the trader exactly
what to do, WHEN in the trading day to do it, and what to avoid. Be specific with tickers, price
levels and times (US/Eastern). Never guarantee outcomes; always frame the risk.

Return ONLY valid JSON with this exact shape:
{{
  "headline": "one punchy sentence — the single most important move or stance right now",
  "stance": "RISK-ON|RISK-OFF|NEUTRAL",
  "regime": "one sentence on the overall market regime and key driver",
  "confluence": ["TICKER — which feeds agree and why it's high-conviction"],
  "daily": {{
    "bias": "BULLISH|BEARISH|NEUTRAL",
    "summary": "2-3 sentences on today's plan",
    "ideas": [{{"ticker":"SYM","direction":"long|short|neutral","thesis":"why — cite which agents support it","trigger":"entry condition/level","entry":"entry price/zone","stop":"stop-loss level","target":"profit target","when":"best time window e.g. 9:30-10:30 ET open","risk":"what invalidates it"}}],
    "timeline": [{{"time":"08:30 ET pre-market","action":"specific instruction — what to check or do, with levels","tickers":["SYM"]}}]
  }},
  "weekly": {{
    "bias": "BULLISH|BEARISH|NEUTRAL",
    "summary": "2-3 sentences on the week",
    "themes": ["theme 1","theme 2"],
    "ideas": [{{"ticker":"SYM","direction":"long|short|neutral","thesis":"why — cite which agents support it","catalyst":"event/why this week","risk":"what invalidates it"}}]
  }},
  "avoid": ["what to stay away from right now and why"],
  "catalysts": ["upcoming catalyst 1","catalyst 2"],
  "risk_notes": "position sizing and overall risk guidance"
}}
Both "daily.ideas" and "weekly.ideas" MUST contain 2-4 entries each — never leave them empty;
every daily idea needs concrete entry/stop/target levels and a "when" time window. Pick daily
tickers from the LIVE PRICES feed when possible and derive levels from the quoted price
(entry near it, stop ~1-2% beyond, target ~2-4% beyond, direction-appropriate). The daily
timeline must walk the whole US session in order — pre-market (before 9:30 ET), the open
(9:30-10:30), midday (10:30-15:00), power hour (15:00-16:00) and the close — one entry each,
naming the exact tickers to act on or watch in that window. Give 1-3 confluence calls and
1-3 avoids. /no_think"""
    plan = await generate_json(
        prompt,
        system_prompt="You are a disciplined trading strategist who fuses many signals into one plan. Return only valid JSON.",
        agent_id=AGENT_ID,
    )
    return plan if isinstance(plan, dict) else {}


# ── Main job ─────────────────────────────────────────────────────────────────
async def alpha_wolf_job():
    orchestrator.update_agent_status(AGENT_ID, "running")
    try:
        orchestrator.set_progress(AGENT_ID, "Gathering intel from the pack…")
        summaries, sources_used, raw = _gather()

        orchestrator.set_progress(AGENT_ID, "Pulling live quotes for the pack's tickers…")
        candidates = _candidate_tickers(raw)
        prices = await asyncio.to_thread(paper_broker._fetch_prices_sync, candidates) if candidates else {}
        if prices:
            summaries["LIVE PRICES"] = ", ".join(f"{t} ${p}" for t, p in sorted(prices.items()))

        orchestrator.set_progress(AGENT_ID, "Synthesizing the game-plan with Qwen3…")
        plan = await _synthesize(summaries)
        if plan:
            plan = _sanitize_plan(plan)
        # fall back only when synthesis produced nothing usable
        if not plan or not (plan.get("headline") or plan.get("regime")
                            or plan["daily"]["ideas"] or plan["weekly"]["ideas"]):
            plan = {
                "headline": "Not enough intel yet — run the pack, then re-run Alpha Wolf.",
                "stance": "NEUTRAL",
                "regime": "Not enough sub-agent data yet — run the pack (Wolf, Compass, Strategy Scout, "
                          "Capitol Tracker, Options Flow, Earnings) first, then re-run Alpha Wolf.",
                "confluence": [], "daily": {}, "weekly": {}, "avoid": [], "catalysts": [], "risk_notes": "",
            }
        plan["disclaimer"] = DISCLAIMER
        plan["inputs"] = summaries
        plan["sources_used"] = sources_used
        plan["generated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        # Dollar/share sizing per daily idea, from the paper portfolio's budget
        ideas = (plan.get("daily") or {}).get("ideas", []) or []
        missing = [t for t in _plan_tickers(plan) if t not in prices]
        if missing:
            prices.update(await asyncio.to_thread(paper_broker._fetch_prices_sync, missing))
        settings = paper_broker.get_settings()
        portfolio = (get_agent_data(AGENT_ID) or {}).get("portfolio") or {}
        equity = paper_broker.portfolio_equity(portfolio) if portfolio.get("positions") is not None else settings["capital"]
        _apply_sizing(ideas, prices, equity * settings["position_pct"] / 100.0)

        orchestrator.set_progress(AGENT_ID, "Executing trades on the paper portfolio…")
        try:
            plan["execution"] = await paper_broker.execute_plan(plan)
        except Exception as e:
            log.error(f"Alpha Wolf execution error: {e}", exc_info=True)
            plan["execution"] = {"enabled": True, "executed": [], "skipped": [],
                                 "note": f"Execution failed: {e}"}

        save_agent_data(AGENT_ID, {"plan": plan})

        recipient = get_config("recipient", "") or DAILY_DIGEST_EMAIL
        if recipient:
            send_html_email(recipient, "🐺 Alpha Wolf — Daily + Weekly Trade Plan",
                            _build_email(plan), sender_name="Alpha Wolf")

        orchestrator.update_agent_status(AGENT_ID, "idle")
        n_exec = len((plan.get("execution") or {}).get("executed", []))
        orchestrator.log_event(
            f"Alpha Wolf synthesized a plan from {len(sources_used)}/6 sub-agents"
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
            if x.get("size_usd"):
                parts.append(f"<b>Size:</b> ~${x['size_usd']:,.0f} · {x.get('size_shares')} sh")
            if parts:
                levels = (f"<div style='font-size:11.5px;color:#4c1d95;margin-top:4px;font-family:monospace'>"
                          f"{' &nbsp;·&nbsp; '.join(parts)}</div>")
        rows += f"""
        <div style='padding:12px 0;border-bottom:1px solid #f0f0f0'>
          <div style='display:flex;align-items:center;gap:8px'>
            <span style='font-family:monospace;font-weight:800;font-size:14px;color:#1a1a2e'>{x.get('ticker','—')}</span>
            <span style='font-size:10px;font-weight:800;color:{dc};background:{dc}14;padding:2px 8px;border-radius:4px;text-transform:uppercase'>{d or 'n/a'}</span>
          </div>
          <div style='font-size:12.5px;color:#444;margin-top:4px;line-height:1.45'>{x.get('thesis','')}</div>
          {levels}
          <div style='font-size:11.5px;color:#666;margin-top:3px'><b>{third_label}:</b> {third_val} &nbsp;·&nbsp; <b>Risk:</b> {x.get('risk','')}</div>
        </div>"""
    return rows


def _timeline_rows(timeline: list) -> str:
    """Daily session schedule — what to do at each point of the trading day."""
    if not timeline:
        return ""
    rows = ""
    for slot in timeline[:8]:
        ticks = "".join(f"<span style='font-family:monospace;font-weight:800;font-size:10.5px;color:#7c3aed;"
                        f"background:#7c3aed14;padding:1px 7px;border-radius:4px;margin-left:5px'>{t}</span>"
                        for t in slot.get("tickers", [])[:6])
        rows += f"""
        <div style='display:flex;gap:10px;padding:7px 0;border-bottom:1px solid #f0f0f0'>
          <div style='min-width:130px;font-family:monospace;font-size:11px;font-weight:800;color:#4c1d95;white-space:nowrap'>{slot.get('time','')}</div>
          <div style='font-size:12px;color:#444;line-height:1.45'>{slot.get('action','')}{ticks}</div>
        </div>"""
    return f"""
    <div style='margin:10px 0 14px'>
      <div style='font-size:11px;font-weight:800;color:#7c3aed;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px'>⏰ Today's schedule (ET)</div>
      {rows}
    </div>"""


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
    <div style='font-size:13px;color:#ddd6fe;margin-top:4px'>Master game-plan · {plan.get('generated_at','')} · synthesized from {len(plan.get('sources_used', []))}/6 agents</div>
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
    {_timeline_rows(daily.get('timeline', []) or [])}
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
