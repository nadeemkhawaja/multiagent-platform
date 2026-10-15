# ============================================================================
# Alpaca Broker — real paper-trading execution for Alpha Wolf via Alpaca's
# Paper Trading API (https://paper-api.alpaca.markets). Replaces the local
# fill simulation this project started with: orders are placed against a real paper
# account, so positions/fills/equity all live in Alpaca (viewable in their
# app too), and bracket orders (stop-loss + take-profit legs) let Alpaca
# enforce risk levels server-side instead of our own polling loop.
#
# The only broker. Pure, broker-agnostic rules — sizing, the risk gates, order
# decisions, the journal and its stats — live in broker_rules.py, so every rule
# that decides whether money moves is testable without a network or a DB.
# ============================================================================
import os
import json
import logging
import asyncio
import datetime
import httpx
from dotenv import load_dotenv

from database import (get_agent_data, save_agent_data, get_config, set_config,
                      delete_config, delete_agent_data)

load_dotenv()
from broker_rules import (
    DEFAULT_CAPITAL, decide_orders, gate_plan, market_bias, traded_today,
    opened_today, entry_window_state, window_state_for, position_value, position_pnl,
    portfolio_summary,
    _default_levels, _sane_stop, _sane_target, _journal_close, size_position,
    journal_stats, TRADE_LOG_LIMIT, JOURNAL_LIMIT, DEFAULT_RISK_PCT,
    DEFAULT_MIN_RR, DEFAULT_MIN_GRADE, DEFAULT_ALLOW_SHORTS,
    DEFAULT_MAX_NEW_TRADES_PER_DAY, DEFAULT_MAX_POSITIONS, DEFAULT_POSITION_PCT,
    ENTRY_OPEN_MIN, ENTRY_CLOSE_MIN,
)

log = logging.getLogger("alpaca_broker")

AGENT_ID = "alpha_wolf"

ALPACA_KEY_ID = os.getenv("ALPACA_API_KEY_ID", "")
ALPACA_SECRET = os.getenv("ALPACA_API_SECRET_KEY", "")
TRADING_BASE = os.getenv("ALPACA_TRADING_BASE_URL", "https://paper-api.alpaca.markets")
DATA_BASE = os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")

DEFAULT_MAX_HOLD_DAYS = 10
DEFAULT_MAX_DAILY_LOSS_PCT = 3.0
NOT_CONFIGURED_NOTE = "Alpaca API keys not set — add ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY to .env"

# Entry discipline: how far (fraction of live price) the plan's entry level may
# sit from the live quote before the idea is skipped as unrealistic for today.
MAX_ENTRY_DRIFT = 0.05
# Exit management thresholds, in R (multiples of the initial entry→stop risk):
# at +1R the stop moves to breakeven, past +1.5R it trails price by 1×ATR.
BREAKEVEN_AT_R = 1.0
TRAIL_AT_R = 1.5
# Working entry orders still unfilled by this time (ET minutes) get cancelled —
# the setup didn't come to us today; tomorrow's plan re-decides from scratch.
ENTRY_CANCEL_AFTER_MIN = 15 * 60 + 50   # 15:50 ET
# Intraday positions are flattened here rather than carried. The signals that
# opened them — session VWAP, the session volume profile, the initial balance,
# the day's context — are all rebuilt from scratch at the next open, so a
# position held overnight is running on a thesis that no longer exists. The
# 10-day max_hold_days ceiling still governs explicitly-swing ideas; this is the
# floor for everything the intraday funnel produced.
SESSION_FLAT_MIN = 15 * 60 + 45         # 15:45 ET


def configured() -> bool:
    return bool(ALPACA_KEY_ID and ALPACA_SECRET)


def _headers() -> dict:
    return {"APCA-API-KEY-ID": ALPACA_KEY_ID, "APCA-API-SECRET-KEY": ALPACA_SECRET}


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ── Settings (`capital` is accepted but ignored — ──────────────────────────
# Alpaca paper accounts default to $100k and can't be resized via the API) ──
def get_settings() -> dict:
    return {
        "enabled":       bool(get_config("alpha_wolf_execution", True)),
        "position_pct":  float(get_config("alpha_wolf_position_pct", DEFAULT_POSITION_PCT)),
        "risk_pct":      float(get_config("alpha_wolf_risk_pct", DEFAULT_RISK_PCT)),
        "max_positions": int(get_config("alpha_wolf_max_positions", DEFAULT_MAX_POSITIONS)),
        "max_hold_days": int(get_config("alpha_wolf_max_hold_days", DEFAULT_MAX_HOLD_DAYS)),
        "max_daily_loss_pct": float(get_config("alpha_wolf_max_daily_loss_pct", DEFAULT_MAX_DAILY_LOSS_PCT)),
        "max_new_trades_per_day": int(get_config("alpha_wolf_max_new_trades_per_day",
                                                 DEFAULT_MAX_NEW_TRADES_PER_DAY)),
        # The funnel's grade replaces the LLM's 1-10 self-rated confidence, which
        # gated execution and predicted nothing — docs/STRATEGY_REVIEW.md.
        "min_grade": str(get_config("alpha_wolf_min_grade", DEFAULT_MIN_GRADE)),
        "allow_shorts": bool(get_config("alpha_wolf_allow_shorts", DEFAULT_ALLOW_SHORTS)),
        "min_rr": float(get_config("alpha_wolf_min_rr", DEFAULT_MIN_RR)),
        "entry_window": {"open_min": ENTRY_OPEN_MIN, "close_min": ENTRY_CLOSE_MIN,
                         "label": f"{ENTRY_OPEN_MIN // 60}:{ENTRY_OPEN_MIN % 60:02d}"
                                  f"-{ENTRY_CLOSE_MIN // 60}:{ENTRY_CLOSE_MIN % 60:02d} ET"},
        # One entry per symbol per session. On by default: the funnel re-runs
        # every 30 minutes and will happily print the opposite card on a name
        # the account already traded.
        "one_trade_per_symbol": bool(get_config("alpha_wolf_one_trade_per_symbol", True)),
        "broker": "alpaca",
        "configured": configured(),
    }


def save_settings(enabled=None, capital=None, position_pct=None, max_positions=None,
                  max_hold_days=None, max_daily_loss_pct=None, risk_pct=None,
                  min_rr=None, one_trade_per_symbol=None, min_grade=None,
                  allow_shorts=None, max_new_trades_per_day=None) -> dict:
    if enabled is not None:
        set_config("alpha_wolf_execution", bool(enabled))
    if position_pct is not None:
        set_config("alpha_wolf_position_pct", min(50.0, max(1.0, float(position_pct))))
    if risk_pct is not None:
        set_config("alpha_wolf_risk_pct", min(10.0, max(0.05, float(risk_pct))))
    if max_positions is not None:
        set_config("alpha_wolf_max_positions", min(8, max(1, int(max_positions))))
    if max_hold_days is not None:
        set_config("alpha_wolf_max_hold_days", min(60, max(1, int(max_hold_days))))
    if max_daily_loss_pct is not None:
        set_config("alpha_wolf_max_daily_loss_pct", min(50.0, max(0.5, float(max_daily_loss_pct))))
    if min_grade is not None and str(min_grade).upper() in ("A+", "A", "B", "C"):
        set_config("alpha_wolf_min_grade", str(min_grade).upper())
    if allow_shorts is not None:
        set_config("alpha_wolf_allow_shorts", bool(allow_shorts))
    if max_new_trades_per_day is not None:
        set_config("alpha_wolf_max_new_trades_per_day", min(20, max(1, int(max_new_trades_per_day))))
    if min_rr is not None:
        set_config("alpha_wolf_min_rr", min(10.0, max(1.0, float(min_rr))))
    if one_trade_per_symbol is not None:
        set_config("alpha_wolf_one_trade_per_symbol", bool(one_trade_per_symbol))
    return get_settings()


# ── Daily loss circuit breaker ────────────────────────────────────────────
def _today() -> str:
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def _daily_breaker_status(equity: float, settings: dict) -> dict:
    """Compares live equity to the equity recorded at the start of today's
    session (ET). The baseline resets automatically on the first check of
    each new trading day, so this never needs a manual daily reset."""
    today = _today()
    baseline_date = get_config("alpha_wolf_daily_baseline_date", None)
    if baseline_date != today:
        set_config("alpha_wolf_daily_baseline_date", today)
        set_config("alpha_wolf_daily_baseline_equity", equity)
        baseline = equity
    else:
        baseline = float(get_config("alpha_wolf_daily_baseline_equity", equity))
    daily_pnl = equity - baseline
    daily_pnl_pct = (daily_pnl / baseline * 100.0) if baseline else 0.0
    tripped = daily_pnl_pct <= -settings["max_daily_loss_pct"]
    return {"tripped": tripped, "baseline_equity": round(baseline, 2),
            "daily_pnl": round(daily_pnl, 2), "daily_pnl_pct": round(daily_pnl_pct, 2),
            "max_daily_loss_pct": settings["max_daily_loss_pct"]}


async def daily_breaker_status() -> dict:
    """Public read of today's breaker state without side effects on trading."""
    if not configured():
        return {"tripped": False, "note": NOT_CONFIGURED_NOTE}
    settings = get_settings()
    account = await _account()
    return _daily_breaker_status(float(account["equity"]), settings)


# ── Raw Alpaca REST calls ─────────────────────────────────────────────────
async def _account() -> dict:
    async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
        r = await c.get("/v2/account")
        r.raise_for_status()
        return r.json()


async def _positions() -> list:
    async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
        r = await c.get("/v2/positions")
        r.raise_for_status()
        return r.json()


async def _positions_by_ticker() -> dict:
    """Live Alpaca positions keyed by ticker, in broker_rules' position shape
    (direction/shares/entry_price/last_price) — Alpaca doesn't track our
    thesis/stop/target/entry-date, those come from the local meta store."""
    out = {}
    for p in await _positions():
        out[p["symbol"]] = {
            "direction": "short" if p.get("side") == "short" else "long",
            "shares": abs(float(p["qty"])),
            "entry_price": float(p["avg_entry_price"]),
            "last_price": float(p.get("current_price") or p["avg_entry_price"]),
        }
    return out


def api_error(e) -> str:
    """Alpaca's own words for why an order failed, short enough for a UI row.

    Every rejection used to reach the trader as the bare string "order rejected
    by Alpaca", with the actual cause — not shortable, wash trade, insufficient
    buying power, market closed — visible only in the server log. That is the
    one line a trader needs, so it travels with the skip record now.
    """
    resp = getattr(e, "response", None)
    text = getattr(resp, "text", "") or ""
    try:
        msg = (json.loads(text) or {}).get("message")
    except Exception:
        msg = None
    return str(msg or text or e)[:200].strip()


async def _close_position(ticker: str, errors: dict = None):
    """Market-closes a position — also cancels its bracket's other leg.
    `errors`, when given, collects the broker's reason for a failure."""
    async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
        try:
            r = await c.delete(f"/v2/positions/{ticker}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            why = api_error(e)
            if errors is not None:
                errors[ticker] = why
            log.warning(f"close_position failed for {ticker}: {why}")
            return None


def entry_order_kind(direction: str, entry: float, live: float):
    """Which order type expresses the plan's entry level, given where price is.
    A long entry BELOW the live quote is a pullback — buy limit; ABOVE it is a
    breakout — buy stop (mirrored for shorts). Entries too far from the live
    quote are unrealistic for today's session and are skipped. Pure."""
    if not entry or not live:
        return None, "no entry level"
    if abs(entry - live) / live > MAX_ENTRY_DRIFT:
        return None, (f"entry ${entry} is {abs(entry - live) / live * 100:.1f}% from "
                      f"live ${live} — too far to work today")
    if direction == "long":
        return ("limit" if entry <= live else "stop"), ""
    return ("limit" if entry >= live else "stop"), ""


async def _place_bracket(ticker: str, direction: str, shares: int, stop: float, target: float,
                         entry: float = None, entry_kind: str = "market", errors: dict = None):
    """Entry order with a bracket (stop-loss + take-profit) — Alpaca enforces
    the exit server-side, so positions don't need our own polling to close.
    entry_kind 'limit'/'stop' places the entry AT the plan's level instead of
    chasing the market: the trade only happens if price comes to us (limit,
    pullback) or proves the move (stop, breakout).

    time_in_force is GTC, not DAY: day-TIF bracket legs are cancelled by Alpaca
    at the closing bell, which left every position held overnight (max_hold_days
    defaults to 10) with no stop and no target the next morning — price could
    cross the target with no order left alive to fill it. Unfilled ENTRY orders
    are instead cancelled by risk_check at 15:50 ET (ENTRY_CANCEL_AFTER_MIN)."""
    side = "sell" if direction == "short" else "buy"
    body = {
        "symbol": ticker, "qty": str(shares), "side": side, "type": entry_kind,
        "time_in_force": "gtc", "order_class": "bracket",
        "take_profit": {"limit_price": str(round(target, 2))},
        "stop_loss": {"stop_price": str(round(stop, 2))},
    }
    if entry_kind == "limit":
        body["limit_price"] = str(round(entry, 2))
    elif entry_kind == "stop":
        body["stop_price"] = str(round(entry, 2))
    async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
        try:
            r = await c.post("/v2/orders", json=body)
            r.raise_for_status()
            order = r.json()
        except Exception as e:
            why = api_error(e)
            if errors is not None:
                errors[ticker] = why
            log.warning(f"order rejected for {ticker}: {why}")
            return None
    legs = order.get("legs") or []
    if len(legs) < 2:
        # Parent (entry) order was accepted but one or both bracket legs are
        # missing — the position would open with no working stop-loss and/or
        # take-profit. Log loudly; risk_check's naked-position sweep will
        # catch and safety-close it on the next pass regardless.
        log.warning(f"bracket for {ticker} accepted with only {len(legs)} leg(s) "
                    f"(expected stop-loss + take-profit) — order={order.get('id')}")
    return order


async def _get_order(order_id: str):
    async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
        try:
            r = await c.get(f"/v2/orders/{order_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning(f"order lookup failed for {order_id}: {e}")
            return None


async def _cancel_order(order_id: str) -> bool:
    async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
        try:
            r = await c.delete(f"/v2/orders/{order_id}")
            return r.status_code in (200, 204, 404)   # 404 = already gone
        except Exception as e:
            log.warning(f"order cancel failed for {order_id}: {e}")
            return False


async def _replace_order(order_id: str, **fields) -> bool:
    """PATCH an open order (e.g. move a bracket's stop leg for breakeven or
    trailing). Alpaca replaces the order in place, keeping the bracket intact."""
    body = {k: str(v) for k, v in fields.items() if v is not None}
    async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
        try:
            r = await c.patch(f"/v2/orders/{order_id}", json=body)
            r.raise_for_status()
            return True
        except Exception as e:
            body_text = getattr(getattr(e, "response", None), "text", "")
            log.warning(f"order replace failed for {order_id}: {e} {body_text}")
            return False


FILL_POLL_ATTEMPTS = 6
FILL_POLL_DELAY_S = 0.75


async def _await_fill(order_id: str) -> dict:
    """Poll a just-submitted order briefly for its real fill price and quantity.
    The POST response almost always comes back 'accepted' with filled_avg_price
    still null, so recording that would just re-record our own pre-trade quote
    and make slippage permanently invisible. Returns {} if it hasn't filled in
    time — the caller falls back to the quote, and risk_check backfills the
    true cost basis from Alpaca's live position on its next pass."""
    if not order_id:
        return {}
    async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
        for attempt in range(FILL_POLL_ATTEMPTS):
            try:
                r = await c.get(f"/v2/orders/{order_id}")
                r.raise_for_status()
                o = r.json()
            except Exception as e:
                log.warning(f"fill poll failed for order {order_id}: {e}")
                return {}
            if o.get("status") == "filled" and o.get("filled_avg_price"):
                return {"price": float(o["filled_avg_price"]),
                        "shares": int(abs(float(o.get("filled_qty") or 0))) or None}
            if o.get("status") in ("canceled", "expired", "rejected"):
                return {}
            if attempt < FILL_POLL_ATTEMPTS - 1:
                await asyncio.sleep(FILL_POLL_DELAY_S)
    return {}


_TERMINAL_ORDER_STATES = ("canceled", "expired", "rejected", "done_for_day", "replaced")


def _meta_from_fill(p: dict, entry_price: float, shares: int) -> dict:
    """Position meta for a pending entry that just filled — carries the levels
    the trade was planned with, plus initial_stop/atr14 for R-based exit
    management (breakeven move, ATR trail) and honest R-multiple journaling."""
    return {"opened_at": _now(), "stop": p.get("stop"), "target": p.get("target"),
            "initial_stop": p.get("stop"), "atr14": p.get("atr14"),
            "entry_price": entry_price, "shares": shares, "direction": p.get("direction"),
            "thesis": p.get("thesis", ""), "confidence": p.get("confidence")}


async def _reconcile_pending(pending: list, meta: dict, trades: list) -> tuple:
    """Check every working entry order against Alpaca: fills become tracked
    positions (with the REAL fill price in the trade log), dead orders are
    dropped, everything else stays pending. Returns (still_pending, fills)."""
    still, fills = [], []
    for p in pending or []:
        o = await _get_order(p.get("order_id"))
        if o is None:
            still.append(p)               # lookup failed — retry next pass
            continue
        status = o.get("status")
        if status == "filled" and o.get("filled_avg_price"):
            entry_price = float(o["filled_avg_price"])
            shares = int(abs(float(o.get("filled_qty") or 0))) or p.get("shares")
            meta[p["ticker"]] = _meta_from_fill(p, entry_price, shares)
            t = {"ts": _now(), "action": "SHORT" if p.get("direction") == "short" else "BUY",
                 "ticker": p["ticker"], "direction": p.get("direction"), "shares": shares,
                 "price": entry_price, "value": round(shares * entry_price, 2),
                 "slippage": round(entry_price - p["entry"], 4) if p.get("entry") else None,
                 "reason": f"{p.get('kind', 'limit')} entry filled @ ${entry_price}"}
            trades.insert(0, t)
            fills.append(t)
        elif status in _TERMINAL_ORDER_STATES:
            log.info(f"pending entry for {p.get('ticker')} ended as {status} — dropped")
        else:
            still.append(p)
    return still, fills


# Order states that are still working (will or could still execute). Alpaca's
# `status=open` listing EXCLUDES "held" — the state a bracket's stop-loss leg
# sits in while its take-profit sibling is live — so querying open-only both
# hid stops from the exit manager and would let the naked-position sweep
# misjudge protection. Query all and filter to working states instead.
_WORKING_ORDER_STATES = {"new", "accepted", "held", "partially_filled",
                         "pending_new", "accepted_for_bidding", "calculated"}


async def _open_orders_by_symbol() -> dict:
    """Working orders (incl. HELD bracket stop legs) keyed by symbol — used to
    detect positions that lost their protective orders, and to find the stop
    leg when exit management moves it to breakeven or a trail."""
    async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
        try:
            r = await c.get("/v2/orders", params={"status": "all", "limit": 500})
            r.raise_for_status()
        except Exception as e:
            log.warning(f"open orders lookup failed: {e}")
            return {}
    out = {}
    for o in r.json():
        if o.get("status") in _WORKING_ORDER_STATES:
            out.setdefault(o["symbol"], []).append(o)
    return out


async def _last_fill(ticker: str):
    """Most recent fill for a ticker — used to reconcile the exit price of a
    close we detect (stop/target hit, or a stale-position close) after the fact.
    Alpaca's activities endpoint silently ignores the `symbol` query param (it
    returns the whole account's recent fills regardless), so we pull a larger
    page and filter client-side — trusting the param alone previously picked
    up whatever ticker happened to have the most recent fill account-wide."""
    async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
        try:
            r = await c.get("/v2/account/activities/FILL",
                            params={"direction": "desc", "page_size": 100})
            r.raise_for_status()
            acts = [a for a in r.json() if a.get("symbol") == ticker]
            if acts:
                a = acts[0]
                return {"price": float(a["price"]), "reason": f"{a.get('side', 'closed')} fill @ ${a['price']}"}
        except Exception as e:
            log.warning(f"activity lookup failed for {ticker}: {e}")
    return None


# ── Live prices (Alpaca IEX feed — free tier) ─────────────────────────────
def _fetch_prices_sync(tickers: list) -> dict:
    if not tickers or not configured():
        return {}
    out = {}
    try:
        with httpx.Client(base_url=DATA_BASE, headers=_headers(), timeout=10) as c:
            r = c.get("/v2/stocks/trades/latest", params={"symbols": ",".join(tickers), "feed": "iex"})
            r.raise_for_status()
            for sym, t in (r.json().get("trades") or {}).items():
                if t and t.get("p"):
                    out[sym] = round(float(t["p"]), 2)
    except Exception as e:
        log.warning(f"Alpaca price fetch failed: {e}")
    return out


# ── Canonical portfolio snapshot (the shape the UI and the agent read, ────
# so decision_now()/the API/the frontend need no changes) ───────────────────
async def _snapshot_portfolio(meta: dict) -> dict:
    account = await _account()
    equity = float(account["equity"])
    baseline = get_config("alpha_wolf_baseline_equity", None)
    if baseline is None:
        baseline = equity
        set_config("alpha_wolf_baseline_equity", baseline)
    live = await _positions_by_ticker()
    positions = {}
    for t, p in live.items():
        m = meta.get(t, {})
        positions[t] = {**p, "thesis": m.get("thesis", ""), "stop": m.get("stop"),
                        "target": m.get("target"), "confidence": m.get("confidence"),
                        "entry_date": m.get("opened_at")}
    unrealized = sum(position_pnl(p) for p in positions.values())
    return {
        "cash": round(float(account["cash"]), 2),
        # Alpaca's own authoritative equity — NOT cash + sum(position_value):
        # position_value's short-position formula (margin + entry->price move)
        # was built for the old simulated cash ledger, where opening a
        # short reserves margin out of a locally-tracked cash balance. Alpaca's
        # real `cash` already accounts for short-sale proceeds under its own
        # margin rules, so layering that synthetic formula on top double-counts
        # short positions and inflates equity by thousands of dollars.
        "equity": round(equity, 2),
        "starting_capital": round(float(baseline), 2),
        "positions": positions,
        # equity - baseline = total P&L (no external deposits/withdrawals in a paper
        # account); realized = total - unrealized.
        "realized_pnl": round((equity - float(baseline)) - unrealized, 2),
        "created_at": get_config("alpha_wolf_created_at", _now()),
    }


def portfolio_equity(portfolio: dict) -> float:
    # Legacy snapshots (saved before the `equity` key existed) fall back to
    # the synthetic sum — correct-ish for longs, and gone after one refresh.
    eq = portfolio.get("equity")
    if eq is None:
        eq = portfolio.get("cash", 0.0) + sum(position_value(p)
                                              for p in (portfolio.get("positions") or {}).values())
    return round(float(eq), 2)


def _portfolio_summary(portfolio: dict) -> dict:
    """Like broker_rules.portfolio_summary, but with `equity`/`return_pct`
    corrected to use Alpaca's real equity instead of a synthetic
    cash + position_value formula (see the `equity` key comment above)."""
    summary = portfolio_summary(portfolio)
    equity = portfolio_equity(portfolio)
    start = portfolio.get("starting_capital") or equity
    summary["equity"] = equity
    summary["return_pct"] = round((equity - start) / start * 100, 2) if start else 0.0
    return summary


def _is_trading_day() -> bool:
    """Mon-Fri only — US equities don't trade weekends, and orders Alpaca merely
    *accepts* (rather than fills) on a closed session shouldn't be recorded here
    as if they executed."""
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo("America/New_York")).weekday() < 5


def split_pending(pending: list, today: str = None) -> tuple:
    """(still working from today, stale from an earlier day) — pure.

    `submitted_at` is stamped with the same local clock this reads, so the
    comparison is like-for-like. Anything without a stamp predates the field and
    is treated as stale, which is what it almost certainly is.
    """
    today = today or datetime.datetime.now().strftime("%Y-%m-%d")
    live = [p for p in pending or [] if str(p.get("submitted_at", "")).startswith(today)]
    return live, [p for p in pending or [] if p not in live]


# ── Main entry: execute a synthesized plan ────────────────────────────────
async def execute_plan(plan: dict) -> dict:
    settings = get_settings()
    if not settings["enabled"]:
        return {"enabled": False, "executed": [], "skipped": [],
                "note": "Trade execution is OFF — enable it from the Alpha Wolf tab."}
    if not configured():
        return {"enabled": True, "executed": [], "skipped": [], "note": NOT_CONFIGURED_NOTE}
    # Reconciling fills and closing positions is legal whenever the market is;
    # OPENING one is not. `window` is checked per idea in the gate below rather
    # than returning early, so the execution report still says plainly why
    # nothing opened instead of showing an empty run.
    window = entry_window_state()
    if not _is_trading_day():
        return {"enabled": True, "executed": [], "skipped": [], "entry_window": window,
                "note": "Markets are closed (weekend) — no orders submitted. Alpha Wolf only trades Mon-Fri."}

    data = get_agent_data(AGENT_ID) or {}
    meta = data.get("positions_meta", {})
    trades = data.get("trades", [])
    journal = data.get("journal", [])
    pending = data.get("pending_entries", [])

    executed, skipped = [], []
    # Ticker → the broker's own reason for a rejection, so a skip row says what
    # actually happened instead of "rejected by Alpaca".
    broker_errors = {}

    # Yesterday's unfilled entry orders: promote anything that filled since the
    # last check, then cancel the STALE rest — today's plan supersedes them.
    #
    # "Stale" means submitted on an earlier day, which is what the message has
    # always claimed and what the code did not check. Alpha Wolf now re-runs this
    # every 30 minutes so intraday funnel cards can actually trade, and a blanket
    # cancel killed the working limit orders THIS run's predecessor had just
    # placed: an entry resting at the plan's level was pulled 30 minutes later,
    # before the level had a chance to trade. Today's working orders stay put —
    # risk_check still expires them at 15:50 ET if they never fill.
    pending, fills = await _reconcile_pending(pending, meta, trades)
    executed += fills
    pending, stale = split_pending(pending)
    for p in stale:
        await _cancel_order(p.get("order_id"))
        skipped.append({"action": "open", "ticker": p.get("ticker"), "direction": p.get("direction"),
                        "why": "yesterday's entry order never filled — cancelled, superseded by today's plan"})

    live = await _positions_by_ticker()
    positions = {t: {**p, "thesis": meta.get(t, {}).get("thesis", "")} for t, p in live.items()}
    # Broader-market direction from the computed /ES + /NQ confluence, so
    # entries can't be opened against an agreeing tape.
    technologia = get_agent_data("technologia") or {}
    market = market_bias(technologia)
    # Symbols already traded this session — the one-trade-per-symbol rule reads
    # this, and it must be computed BEFORE this run adds its own fills.
    already = traded_today(trades) if settings.get("one_trade_per_symbol", True) else set()
    # Entries already opened today, for the daily cap. Counted BEFORE this run
    # adds its own fills, same as `already`.
    opened = opened_today(trades)
    gated_plan, gate_rejections = gate_plan(plan, settings, market, already, opened, window)
    skipped += gate_rejections
    orders = decide_orders(gated_plan, positions, settings)

    # A ticker whose entry order is still working is already committed at the
    # plan's level — it just hasn't traded there yet. `decide_orders` only sees
    # FILLED positions, so on an intraday re-run it would happily stack a second
    # order for the same idea. One resting order per idea.
    working = {str(p.get("ticker", "")).upper() for p in pending}
    if working:
        dupes = [o for o in orders if o["action"] == "open" and o["ticker"].upper() in working]
        skipped += [{**o, "why": "entry order already working at the plan's level"} for o in dupes]
        orders = [o for o in orders if o not in dupes]

    account_for_breaker = await _account()
    breaker = _daily_breaker_status(float(account_for_breaker["equity"]), settings)
    if breaker["tripped"]:
        for o in [o for o in orders if o["action"] == "open"]:
            skipped.append({**o, "why": f"daily loss circuit breaker tripped "
                                        f"({breaker['daily_pnl_pct']:+.1f}% today, "
                                        f"limit -{breaker['max_daily_loss_pct']:.1f}%) — no new entries until tomorrow"})
        orders = [o for o in orders if o["action"] != "open"]
        try:
            from orchestrator import orchestrator
            orchestrator.log_event(
                f"🛑 Alpha Wolf daily loss breaker tripped ({breaker['daily_pnl_pct']:+.1f}%) — new entries blocked for today",
                "#dc2626")
        except Exception:
            pass

    for o in [o for o in orders if o["action"] == "close"]:
        pos = positions.get(o["ticker"])
        if not pos:
            continue
        res = await _close_position(o["ticker"], broker_errors)
        if res is None:
            skipped.append({**o, "why": "close order failed — "
                                       + broker_errors.get(o["ticker"], "the broker did not respond")})
            continue
        if res.get("status") != "filled" or not res.get("filled_avg_price"):
            # Alpaca accepted the order but hasn't filled it yet (e.g. submitted
            # right at the close, or a fast-moving market) — don't record this as
            # closed. It stays in `meta`, so the next risk_check picks up the real
            # fill once it happens and journals it with the actual exit price.
            skipped.append({**o, "why": f"close order {res.get('status', 'pending')} — not yet filled, "
                                        "will reconcile once it fills"})
            continue
        m = meta.pop(o["ticker"], {})
        exit_price = float(res.get("filled_avg_price") or pos["last_price"])
        pnl = position_pnl(pos, exit_price)
        _journal_close(journal, o["ticker"], {**pos, "entry_date": m.get("opened_at"),
                                              "stop": m.get("stop"), "initial_stop": m.get("initial_stop"),
                                              "target": m.get("target"), "confidence": m.get("confidence")},
                       exit_price, pnl, o["reason"])
        t = {"ts": _now(), "action": "COVER" if pos["direction"] == "short" else "SELL",
             "ticker": o["ticker"], "direction": pos["direction"], "shares": pos["shares"],
             "price": exit_price, "value": round(pos["shares"] * exit_price, 2),
             "pnl": round(pnl, 2), "reason": o["reason"]}
        trades.insert(0, t); executed.append(t)

    if any(o["action"] == "open" for o in orders):
        account = await _account()
        equity, cash = float(account["equity"]), float(account["cash"])
        open_tickers = [o["ticker"] for o in orders if o["action"] == "open"]
        prices = await asyncio.to_thread(_fetch_prices_sync, open_tickers)
        for o in [o for o in orders if o["action"] == "open"]:
            price = prices.get(o["ticker"])
            if not price:
                skipped.append({**o, "why": "no price available"})
                continue
            # Entry AT the plan's level — limit (pullback) or stop (breakout)
            # instead of chasing the market at plan time. No usable plan level
            # means a marketable limit at the live quote, which still caps the
            # worst acceptable fill instead of paying whatever the open gives.
            entry = o.get("entry")
            kind, why_kind = entry_order_kind(o["direction"], entry, price) if entry else (None, "")
            if entry and kind is None:
                skipped.append({**o, "why": why_kind})
                continue
            if not entry:
                entry, kind = price, "limit"
            # Levels next — sized and validated off the ENTRY level (where the
            # position will actually open), not the current quote.
            stop = _sane_stop(o["direction"], entry, o.get("stop"))
            target = _sane_target(o["direction"], entry, o.get("target"))
            if stop is None or target is None:
                d_stop, d_target = _default_levels(o["direction"], entry, o.get("atr14"))
                stop, target = stop or d_stop, target or d_target
            shares, why = size_position(equity, cash, entry, stop, settings)
            if shares < 1:
                skipped.append({**o, "why": why})
                continue
            order = await _place_bracket(o["ticker"], o["direction"], shares, stop, target,
                                         entry=entry, entry_kind=kind, errors=broker_errors)
            if order is None:
                skipped.append({**o, "why": "rejected by Alpaca — "
                                           + broker_errors.get(o["ticker"], "no reason given")})
                continue
            legs = order.get("legs") or []
            confirmed_stop = next((float(l["stop_price"]) for l in legs if l.get("stop_price")), stop)
            confirmed_target = next((float(l["limit_price"]) for l in legs if l.get("limit_price")), target)
            record = {"order_id": order.get("id"), "ticker": o["ticker"], "direction": o["direction"],
                      "shares": shares, "entry": round(entry, 2), "kind": kind,
                      "stop": confirmed_stop, "target": confirmed_target,
                      "thesis": o.get("thesis", ""), "confidence": o.get("confidence"),
                      "atr14": o.get("atr14"), "submitted_at": _now()}
            # A marketable limit usually fills within seconds — catch it now so
            # the position is tracked (with its real fill price) immediately.
            fill = await _await_fill(order.get("id"))
            if fill.get("price"):
                entry_price = fill["price"]
                shares = fill.get("shares") or shares
                meta[o["ticker"]] = _meta_from_fill(record, entry_price, shares)
                cash -= shares * entry_price
                t = {"ts": _now(), "action": "SHORT" if o["direction"] == "short" else "BUY",
                     "ticker": o["ticker"], "direction": o["direction"], "shares": shares,
                     "price": entry_price, "value": round(shares * entry_price, 2),
                     "slippage": round(entry_price - entry, 4),
                     "reason": o["reason"]}
                trades.insert(0, t); executed.append(t)
            else:
                # Working order — the plan's level hasn't traded yet. risk_check
                # promotes it when it fills, or cancels it at 15:50 ET unfilled.
                pending.append(record)

    del trades[TRADE_LOG_LIMIT:]
    portfolio = await _snapshot_portfolio(meta)
    save_agent_data(AGENT_ID, {"portfolio": portfolio, "trades": trades, "journal": journal,
                               "positions_meta": meta, "pending_entries": pending})
    return {"enabled": True, "executed": executed, "skipped": skipped, "pending": pending,
            "summary": _portfolio_summary(portfolio), "daily_breaker": breaker,
            "market_bias": market, "entry_window": window,
            "opened_today": opened + sum(1 for t in executed
                                         if str(t.get("action", "")).upper() in ("BUY", "SHORT"))}


# ── Risk check: reconcile closes + enforce max hold days ──────────────────
def _market_open_now() -> bool:
    from zoneinfo import ZoneInfo
    now = datetime.datetime.now(ZoneInfo("America/New_York"))
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and 570 <= mins < 960   # 9:30–16:00 ET


# risk_check keeps polling for half an hour after the bell, in RECONCILE-ONLY
# mode. A bracket that fills at 15:58 used to be invisible until 09:30 the next
# morning: the position was gone from the account while `positions_meta` still
# claimed it was open, the exit never reached the journal, and the day the
# trader actually had — a closed, profitable AVGO round trip — showed on the
# performance card as no trades at all. Reconciling is safe after the close;
# placing orders is not, so everything that could submit one is skipped.
_RECONCILE_UNTIL_MIN = 16 * 60 + 30     # 16:30 ET


def _reconcile_window_now() -> bool:
    from zoneinfo import ZoneInfo
    now = datetime.datetime.now(ZoneInfo("America/New_York"))
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and 570 <= mins < _RECONCILE_UNTIL_MIN


async def _structure_trail(ticker: str, short: bool):
    """The most recent swing low (for a long) / swing high (for a short) on
    today's 5-minute bars, with a small buffer beyond it. None when there is no
    clean swing yet, in which case the caller keeps the ATR envelope."""
    try:
        from tools import levels as levels_tool, smc, strategies as strat
        bars = await asyncio.to_thread(levels_tool.fetch_session_bars_sync, ticker)
        if len(bars) < 10:
            return None
        sw = smc.swing_points(bars, lookback=2)
        pts = sw["highs"] if short else sw["lows"]
        if not pts:
            return None
        level = pts[-1][1]
        buf = (strat.atr(bars, 14) or 0) * 0.15
        return round(level + buf, 2) if short else round(level - buf, 2)
    except Exception as e:
        log.warning(f"structure trail lookup failed for {ticker}: {e}")
        return None


async def risk_check(force: bool = False) -> dict:
    """Alpaca enforces stop/target itself via bracket orders — this poll's job
    is to (a) promote working entry orders that filled into tracked positions
    (and cancel unfilled ones late in the session), (b) notice positions that
    closed since the last check and journal them with a reconciled fill price,
    (c) manage exits — move stops to breakeven at +1R and trail by 1×ATR past
    +1.5R, and (d) force-close anything aged past max_hold_days."""
    if not configured():
        return {"skipped": "Alpaca not configured"}
    if not force and not _reconcile_window_now():
        return {"skipped": "market closed"}
    # After the bell: journal what closed, cancel what never filled, and touch
    # nothing that would place an order into a shut market.
    reconcile_only = not _market_open_now()

    settings = get_settings()
    data = get_agent_data(AGENT_ID) or {}
    meta = data.get("positions_meta", {})
    trades = data.get("trades", [])
    journal = data.get("journal", [])
    pending = data.get("pending_entries", [])
    executed = []

    # ── Working entry orders: promote fills, expire late-day leftovers ──────
    if pending:
        pending, fills = await _reconcile_pending(pending, meta, trades)
        executed += fills
        from zoneinfo import ZoneInfo
        now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
        if now_et.hour * 60 + now_et.minute >= ENTRY_CANCEL_AFTER_MIN:
            for p in pending:
                await _cancel_order(p.get("order_id"))
                log.info(f"entry order for {p.get('ticker')} unfilled by 15:50 ET — cancelled")
            pending = []

    def _save_state(portfolio):
        set_config("alpha_wolf_last_sync", _now())
        save_agent_data(AGENT_ID, {"portfolio": portfolio, "trades": trades, "journal": journal,
                                   "positions_meta": meta, "pending_entries": pending})

    if not meta:
        portfolio = await _snapshot_portfolio(meta)
        _save_state(portfolio)
        return {"checked": 0, "closed": [], "filled_entries": executed}

    live = await _positions_by_ticker()

    # Backfill cost basis from Alpaca's authoritative avg_entry_price while the
    # position is still open. If an entry fill was too slow to catch at submit
    # time we stored the quote instead — this corrects it well before the
    # position closes, so realized P&L is computed against what we really paid.
    for t, p in live.items():
        if t in meta:
            meta[t] = {**meta[t], "entry_price": p["entry_price"],
                       "shares": p["shares"], "direction": p["direction"]}

    # Safety net: any still-open position with no live protective order at all
    # (bracket leg never placed, got cancelled, or was rejected after entry)
    # would otherwise ride past its stop/target with nothing to close it —
    # close it immediately rather than let it sit unprotected.
    open_orders = {} if reconcile_only else await _open_orders_by_symbol()
    for t in ([] if reconcile_only else
              [t for t in list(meta) if t in live and t not in open_orders]):
        pos = live[t]
        res = await _close_position(t)
        if res is None:
            log.warning(f"{t} has no protective order but safety-close failed — will retry next check")
            continue
        m = meta.pop(t)
        exit_price = float(res.get("filled_avg_price") or pos["last_price"])
        pnl = position_pnl(pos, exit_price)
        reason = "no protective stop/target order found — closed for safety"
        _journal_close(journal, t, {**pos, "entry_date": m.get("opened_at"),
                                    "stop": m.get("stop"), "initial_stop": m.get("initial_stop"),
                                    "target": m.get("target"), "confidence": m.get("confidence"),
                                    "thesis": m.get("thesis", "")}, exit_price, pnl, reason)
        rec = {"ts": _now(), "action": "COVER" if pos["direction"] == "short" else "SELL",
               "ticker": t, "direction": pos["direction"], "shares": pos["shares"],
               "price": exit_price, "pnl": round(pnl, 2), "reason": reason}
        trades.insert(0, rec); executed.append(rec)
        live = await _positions_by_ticker()  # re-sync after the forced close

    # Positions Alpaca closed on its own (stop/target hit) since our last check.
    for t in [t for t in list(meta) if t not in live]:
        m = meta.pop(t)
        fill = await _last_fill(t)
        exit_price = fill["price"] if fill else None
        exit_price = exit_price or 0.0
        entry_price = m.get("entry_price")
        if entry_price is None:
            # Legacy meta record from before entry_price/shares were tracked —
            # fall back to exit_price (shows $0 P&L) rather than crash on it.
            log.warning(f"{t}: closing with no entry_price on record — P&L for this trade will show as $0")
            entry_price = exit_price
        pos_for_journal = {"entry_price": entry_price, "shares": m.get("shares", 0),
                           "direction": m.get("direction", "long"), "entry_date": m.get("opened_at"),
                           "stop": m.get("stop"), "initial_stop": m.get("initial_stop"),
                           "target": m.get("target"), "confidence": m.get("confidence"),
                           "thesis": m.get("thesis", "")}
        pnl = position_pnl(pos_for_journal, exit_price)
        reason = (fill or {}).get("reason", "closed (stop/target hit)")
        _journal_close(journal, t, pos_for_journal, exit_price, pnl, reason)
        rec = {"ts": _now(), "action": "COVER" if m.get("direction") == "short" else "SELL",
               "ticker": t, "direction": m.get("direction"), "shares": m.get("shares", 0),
               "price": exit_price, "pnl": round(pnl, 2), "reason": reason}
        trades.insert(0, rec); executed.append(rec)

    # Stale positions — the plan stopped mentioning them; force-exit rather
    # than let a rotten thesis sit open indefinitely. Intraday positions are
    # additionally flattened at SESSION_FLAT_MIN: they were opened on levels
    # that get rebuilt at the next open, so holding them overnight keeps the
    # risk and discards the reason for it.
    from zoneinfo import ZoneInfo
    et_now = datetime.datetime.now(ZoneInfo("America/New_York"))
    session_over = (et_now.weekday() < 5
                    and et_now.hour * 60 + et_now.minute >= SESSION_FLAT_MIN)
    now = datetime.datetime.now()
    for t in ([] if reconcile_only else list(meta)):
        try:
            entered = datetime.datetime.strptime(meta[t].get("opened_at", ""), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        age_days = (now - entered).total_seconds() / 86400
        intraday = meta[t].get("horizon") == "intraday"
        if intraday and session_over:
            pass                                    # flatten below
        elif age_days <= settings["max_hold_days"]:
            continue
        pos = live.get(t)
        if not pos:
            continue
        res = await _close_position(t)
        if res is None:
            continue
        m = meta.pop(t)
        exit_price = float(res.get("filled_avg_price") or pos["last_price"])
        pnl = position_pnl(pos, exit_price)
        reason = ("intraday position flattened at the close — its levels reset at the next open"
                  if intraday and session_over else
                  f"stale — held {age_days:.0f}d beyond {settings['max_hold_days']}d limit")
        _journal_close(journal, t, {**pos, "entry_date": m.get("opened_at"),
                                    "stop": m.get("stop"), "initial_stop": m.get("initial_stop"),
                                    "target": m.get("target"), "confidence": m.get("confidence"),
                                    "thesis": m.get("thesis", "")}, exit_price, pnl, reason)
        rec = {"ts": _now(), "action": "COVER" if pos["direction"] == "short" else "SELL",
               "ticker": t, "direction": pos["direction"], "shares": pos["shares"],
               "price": exit_price, "pnl": round(pnl, 2), "reason": reason}
        trades.insert(0, rec); executed.append(rec)

    # ── Exit management: breakeven at +1R, then a 1×ATR trail past +1.5R ────
    # Winners stop round-tripping into losers: once a trade has earned its
    # initial risk, the worst case becomes scratch; once it's earned 1.5×,
    # the stop follows price up (long) / down (short) at one ATR's distance.
    # R is always measured against the INITIAL stop, so the thresholds don't
    # drift as the stop moves.
    open_orders = {} if reconcile_only else await _open_orders_by_symbol()
    managed = []
    for t, pos in ({} if reconcile_only else live).items():
        m = meta.get(t)
        if not m:
            continue
        entry, cur_stop = m.get("entry_price"), m.get("stop")
        init_stop = m.get("initial_stop") or cur_stop
        price = pos.get("last_price")
        if not (entry and cur_stop and init_stop and price):
            continue
        risk_ps = abs(entry - init_stop)
        if risk_ps <= 0:
            continue
        short = m.get("direction") == "short"
        r_now = ((entry - price) if short else (price - entry)) / risk_ps
        atr = m.get("atr14")
        new_stop, why = None, ""
        if r_now >= TRAIL_AT_R and atr:
            # Trail behind STRUCTURE when there is any, and fall back to the
            # ATR envelope when there isn't. A fixed 1×ATR trail sits wherever
            # volatility happens to put it — frequently mid-consolidation,
            # where it gets swept by the same rotation the trend is pausing in.
            # The last swing low (high) is the level whose break actually means
            # the trend is over, which is the only thing a trailing stop is
            # supposed to be waiting for.
            swing = await _structure_trail(t, short)
            trail = swing if swing is not None else (
                round(price + atr, 2) if short else round(price - atr, 2))
            src = "the last swing" if swing is not None else "1×ATR"
            if (short and trail < cur_stop) or (not short and trail > cur_stop):
                new_stop, why = trail, f"+{r_now:.1f}R — trailing behind {src} at ${trail}"
        if new_stop is None and r_now >= BREAKEVEN_AT_R:
            be = round(entry, 2)
            if (short and cur_stop > be) or (not short and cur_stop < be):
                new_stop, why = be, f"+{r_now:.1f}R — stop moved to breakeven"
        # The replaced stop must stay on the working side of the market or
        # Alpaca rejects it (a sell-stop above price / buy-stop below price).
        if new_stop is None or (short and new_stop <= price) or (not short and new_stop >= price):
            continue
        stop_leg = next((o for o in open_orders.get(t, [])
                         if o.get("type") in ("stop", "stop_limit") and o.get("stop_price")), None)
        if stop_leg and await _replace_order(stop_leg["id"], stop_price=new_stop):
            # Legacy meta (from before exit management) has no initial_stop —
            # pin it to the pre-move stop now, or the original risk (and all
            # future R math) would be lost the moment the stop moves.
            meta[t] = {**m, "stop": new_stop, "initial_stop": m.get("initial_stop") or cur_stop}
            managed.append({"ticker": t, "stop": new_stop, "why": why})

    del trades[TRADE_LOG_LIMIT:]
    portfolio = await _snapshot_portfolio(meta)
    _save_state(portfolio)

    if executed:
        try:
            from orchestrator import orchestrator
            closed = ", ".join(f"{t['ticker']} {t.get('pnl', 0):+.0f}" for t in executed)
            orchestrator.log_event(f"Alpha Wolf risk check closed {len(executed)} position(s): {closed}", "#dc2626")
        except Exception:
            pass
    if managed:
        try:
            from orchestrator import orchestrator
            moved = ", ".join(f"{m['ticker']} → ${m['stop']}" for m in managed)
            orchestrator.log_event(f"🛡 Alpha Wolf tightened stops: {moved}", "#7c3aed")
        except Exception:
            pass
    return {"checked": len(live) + len(executed), "closed": executed,
            "stops_moved": managed, "pending_entries": pending}


def journal_view(limit: int = 100) -> dict:
    data = get_agent_data(AGENT_ID) or {}
    journal = data.get("journal") or []
    return {"stats": journal_stats(journal), "journal": journal[:limit]}


# ── Views / management (used by the API) ──────────────────────────────────
async def portfolio_view(refresh_prices: bool = False) -> dict:
    settings = get_settings()
    if not configured():
        return {"settings": settings, "summary": {}, "positions": [], "trades": [],
                "created_at": None, "note": NOT_CONFIGURED_NOTE}
    data = get_agent_data(AGENT_ID) or {}
    meta = data.get("positions_meta", {})
    trades = data.get("trades") or []
    pending = data.get("pending_entries") or []
    portfolio = await _snapshot_portfolio(meta)
    save_agent_data(AGENT_ID, {"portfolio": portfolio})
    positions = [{"ticker": t, **p,
                  "initial_stop": meta.get(t, {}).get("initial_stop"),
                  "pnl": round(position_pnl(p), 2), "value": round(position_value(p), 2)}
                 for t, p in sorted(portfolio["positions"].items())]
    equity = portfolio_equity(portfolio)
    breaker = _daily_breaker_status(equity, settings)
    # Sync transparency: when the app's tracked state and Alpaca's account
    # disagree, say so on the tab instead of silently showing one of them.
    live_tickers = set(portfolio["positions"])
    sync = {
        "last_check": get_config("alpha_wolf_last_sync", None),
        "equity_source": "alpaca",
        # In Alpaca but not tracked here — opened outside the app (or meta lost).
        "untracked": sorted(live_tickers - set(meta)),
        # Tracked here but gone from Alpaca — closed remotely; next risk_check journals it.
        "unreconciled": sorted(set(meta) - live_tickers),
    }
    return {"settings": settings, "summary": _portfolio_summary(portfolio),
            "positions": positions, "trades": trades[:50], "created_at": portfolio.get("created_at"),
            "daily_breaker": breaker, "pending_entries": pending, "sync": sync,
            "market_bias": market_bias(get_agent_data("technologia") or {})}


async def cancel_pending(order_id: str) -> dict:
    """Cancel one working entry order (from the UI) and drop it from tracking."""
    if not configured():
        return {"status": "not_configured", "note": NOT_CONFIGURED_NOTE}
    ok = await _cancel_order(order_id)
    data = get_agent_data(AGENT_ID) or {}
    pending = [p for p in (data.get("pending_entries") or []) if p.get("order_id") != order_id]
    save_agent_data(AGENT_ID, {"pending_entries": pending})
    return {"status": "cancelled" if ok else "cancel_failed", "pending_entries": pending}


# All the config keys this agent owns. A reset clears every one of them so the
# next run starts from the defaults in broker_rules rather than from settings
# tuned for an account that no longer exists.
RESET_CONFIG_KEYS = (
    "alpha_wolf_baseline_equity", "alpha_wolf_created_at",
    "alpha_wolf_daily_baseline_date", "alpha_wolf_daily_baseline_equity",
    "alpha_wolf_position_pct", "alpha_wolf_risk_pct", "alpha_wolf_max_positions",
    "alpha_wolf_max_new_trades_per_day", "alpha_wolf_max_hold_days",
    "alpha_wolf_max_daily_loss_pct", "alpha_wolf_min_rr", "alpha_wolf_min_grade",
    "alpha_wolf_allow_shorts", "alpha_wolf_one_trade_per_symbol",
    # Retired: the LLM confidence floor. Cleared so a stale row can't linger.
    "alpha_wolf_min_confidence",
)

# Everything this app stores about trading, under the alpha_wolf agent.
RESET_DATA_KEYS = ("portfolio", "trades", "journal", "positions_meta",
                   "pending_entries", "plan", "pulse")


async def reset_state(close_at_broker: bool = False) -> dict:
    """Start over against a fresh account.

    Local state is what this clears: the portfolio snapshot, the trade log, the
    closed-trade journal, position metadata, working entry orders, the master
    plan, the pulse record and every alpha_wolf_* setting. Return% is then
    re-baselined against whatever the connected account actually holds.

    It does NOT touch the broker unless `close_at_broker` is set. The old
    reset always did — it cancelled all orders and closed all positions before
    anything else — which is wrong for the case this exists to serve: the
    account was deleted or replaced, so there is nothing to close, and firing
    DELETE /v2/positions at a brand-new account is a live order submission
    nobody asked for. Pass close_at_broker=True only to flatten a real,
    currently-held book.
    """
    closed = None
    if close_at_broker and configured():
        async with httpx.AsyncClient(base_url=TRADING_BASE, headers=_headers(), timeout=15) as c:
            try:
                await c.delete("/v2/orders")
            except Exception as e:
                log.warning(f"cancel-all-orders failed: {e}")
            try:
                r = await c.delete("/v2/positions", params={"cancel_orders": "true"})
                closed = len(r.json() or []) if r.content else 0
            except Exception as e:
                log.warning(f"close-all-positions failed: {e}")
        # Give the flatten a moment to fill before the equity baseline is read.
        await asyncio.sleep(2)

    rows = delete_agent_data(AGENT_ID, *RESET_DATA_KEYS)
    cfgs = delete_config(*RESET_CONFIG_KEYS)
    log.info(f"reset: dropped {rows} stored row(s) and {cfgs} setting(s)")

    if not configured():
        return {"status": "reset", "broker": "not configured", "closed_at_broker": closed,
                "note": NOT_CONFIGURED_NOTE + " — local state was cleared anyway."}

    account = await _account()
    equity = float(account["equity"])
    set_config("alpha_wolf_baseline_equity", equity)
    set_config("alpha_wolf_created_at", _now())
    # Today's circuit-breaker baseline too, so a reset mid-session doesn't read
    # the morning's equity as today's starting point.
    set_config("alpha_wolf_daily_baseline_date", _today())
    set_config("alpha_wolf_daily_baseline_equity", equity)
    portfolio = await _snapshot_portfolio({})
    settings = get_settings()
    return {
        "status": "reset", "portfolio": portfolio, "settings": settings,
        "closed_at_broker": closed,
        "account": {"number": account.get("account_number"), "status": account.get("status"),
                    "equity": equity, "cash": float(account["cash"]),
                    "shorting_enabled": account.get("shorting_enabled")},
        "note": (f"Local trading state cleared and return% re-baselined to ${equity:,.2f}. "
                 f"Risk settings are back to defaults: {settings['max_positions']} concurrent "
                 f"positions, {settings['max_new_trades_per_day']} new trades/day, grade "
                 f"{settings['min_grade']}+ only, "
                 f"{'shorts ON' if settings['allow_shorts'] else 'long-only'}, entries "
                 f"{settings['entry_window']['label']}."),
    }
