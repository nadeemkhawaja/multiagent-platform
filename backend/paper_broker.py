# ============================================================================
# Paper Broker — simulated trade execution for Alpha Wolf.
# Turns the synthesized game-plan into sized orders, fills them at live
# yfinance prices, and manages a persistent virtual portfolio (cash,
# positions, realized P&L, trade log). No real money ever moves: this is a
# paper-trading engine with virtual capital.
# ============================================================================
import re
import asyncio
import logging
import datetime
from zoneinfo import ZoneInfo

from database import get_agent_data, save_agent_data, get_config, set_config

log = logging.getLogger("paper_broker")

AGENT_ID = "alpha_wolf"
ET = ZoneInfo("America/New_York")

DEFAULT_CAPITAL = 100_000.0
DEFAULT_POSITION_PCT = 10.0     # % of equity allocated to each new position
DEFAULT_MAX_POSITIONS = 8
MIN_ORDER_VALUE = 50.0          # skip allocations too small to matter
TRADE_LOG_LIMIT = 200
JOURNAL_LIMIT = 500
ATR_STOP_MULT = 1.2             # default stop distance when the plan gave none
ATR_TARGET_RR = 2.0             # default target = 2× the stop risk

_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")


# ── Settings (user-editable via /api/alpha-wolf/execution) ───────────────────
def get_settings() -> dict:
    return {
        "enabled":       bool(get_config("alpha_wolf_execution", True)),
        "capital":       float(get_config("alpha_wolf_capital", DEFAULT_CAPITAL)),
        "position_pct":  float(get_config("alpha_wolf_position_pct", DEFAULT_POSITION_PCT)),
        "max_positions": int(get_config("alpha_wolf_max_positions", DEFAULT_MAX_POSITIONS)),
    }


def save_settings(enabled=None, capital=None, position_pct=None, max_positions=None) -> dict:
    if enabled is not None:
        set_config("alpha_wolf_execution", bool(enabled))
    if capital is not None:
        set_config("alpha_wolf_capital", max(1000.0, float(capital)))
    if position_pct is not None:
        set_config("alpha_wolf_position_pct", min(50.0, max(1.0, float(position_pct))))
    if max_positions is not None:
        set_config("alpha_wolf_max_positions", min(20, max(1, int(max_positions))))
    return get_settings()


# ── Portfolio state ──────────────────────────────────────────────────────────
def new_portfolio(capital: float) -> dict:
    return {
        "cash": round(capital, 2),
        "starting_capital": round(capital, 2),
        "positions": {},        # ticker -> {direction, shares, entry_price, entry_date, last_price, thesis}
        "realized_pnl": 0.0,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def position_value(pos: dict, price: float = None) -> float:
    """Current liquidation value of a position. Shorts hold their entry value
    as reserved margin and earn/lose the move from entry."""
    price = price if price is not None else pos.get("last_price", pos["entry_price"])
    shares = pos["shares"]
    if pos.get("direction") == "short":
        margin = pos.get("margin", pos["entry_price"] * shares)
        return margin + (pos["entry_price"] - price) * shares
    return price * shares


def position_pnl(pos: dict, price: float = None) -> float:
    price = price if price is not None else pos.get("last_price", pos["entry_price"])
    move = (price - pos["entry_price"]) * pos["shares"]
    return -move if pos.get("direction") == "short" else move


def portfolio_equity(portfolio: dict) -> float:
    return round(portfolio["cash"] + sum(position_value(p) for p in portfolio["positions"].values()), 2)


def portfolio_summary(portfolio: dict) -> dict:
    equity = portfolio_equity(portfolio)
    start = portfolio.get("starting_capital") or DEFAULT_CAPITAL
    return {
        "equity": equity,
        "cash": round(portfolio["cash"], 2),
        "open_positions": len(portfolio["positions"]),
        "realized_pnl": round(portfolio.get("realized_pnl", 0.0), 2),
        "unrealized_pnl": round(sum(position_pnl(p) for p in portfolio["positions"].values()), 2),
        "return_pct": round((equity - start) / start * 100, 2) if start else 0.0,
    }


# ── Order decisions (pure — unit-testable without DB or network) ─────────────
def avoid_hits(avoid: list, held: set) -> set:
    """Held tickers explicitly mentioned in the plan's avoid list."""
    hits = set()
    for line in avoid or []:
        for word in _TICKER_RE.findall(str(line)):
            if word in held:
                hits.add(word)
    return hits


def decide_orders(plan: dict, positions: dict, settings: dict) -> list:
    """Translate the plan into close/open orders against current positions:
    - close anything the plan now says to avoid,
    - close (and re-open) anything whose direction flipped,
    - open daily ideas (long/short) up to max_positions."""
    daily = plan.get("daily") or {}
    ideas = [i for i in (daily.get("ideas") or []) if isinstance(i, dict) and i.get("ticker")]
    by_ticker = {str(i["ticker"]).upper(): i for i in ideas}
    held = set(positions)
    avoided = avoid_hits(plan.get("avoid"), held)

    orders = []
    for t in sorted(avoided):
        orders.append({"action": "close", "ticker": t, "reason": "flagged in today's avoid list"})

    flipped = set()
    for t, pos in positions.items():
        if t in avoided:
            continue
        idea = by_ticker.get(t)
        if not idea:
            continue
        d = str(idea.get("direction", "")).lower()
        if d in ("long", "short") and d != pos.get("direction"):
            orders.append({"action": "close", "ticker": t, "reason": f"plan flipped {pos.get('direction')} → {d}"})
            flipped.add(t)

    open_slots = settings["max_positions"] - (len(held) - len(avoided) - len(flipped))
    for t, idea in by_ticker.items():
        d = str(idea.get("direction", "")).lower()
        if d not in ("long", "short"):
            continue
        if t in avoided:
            continue
        if t in held and t not in flipped:
            continue                      # already positioned the right way
        if open_slots <= 0:
            break
        orders.append({"action": "open", "ticker": t, "direction": d,
                       "thesis": str(idea.get("thesis", ""))[:300],
                       "reason": "daily plan idea",
                       # risk levels parsed/validated upstream (agent13._enrich_ideas)
                       "stop": idea.get("stop_px"), "target": idea.get("target_px"),
                       "atr14": idea.get("atr14"),
                       "confidence": idea.get("confidence")})
        open_slots -= 1
    return orders


def _default_levels(direction: str, price: float, atr) -> tuple:
    """ATR-based stop/target when the plan didn't supply usable levels:
    stop 1.2×ATR against the trade, target at 2× that risk. Falls back to a
    2%/4% envelope when no ATR is known."""
    risk = ATR_STOP_MULT * atr if atr else price * 0.02
    if direction == "short":
        return round(price + risk, 2), round(price - ATR_TARGET_RR * risk, 2)
    return round(price - risk, 2), round(price + ATR_TARGET_RR * risk, 2)


def _sane_stop(direction, price, stop):
    """A stop on the wrong side of the entry is worse than none."""
    if not stop:
        return None
    return stop if (direction == "short") == (stop > price) else None


def _sane_target(direction, price, target):
    if not target:
        return None
    return target if (direction == "short") == (target < price) else None


def _journal_close(journal: list, ticker: str, pos: dict, price: float, pnl: float, reason: str):
    """Append a closed-trade record — the raw material for win-rate and
    P&L-attribution stats on the Alpha Wolf tab."""
    if journal is None:
        return
    basis = pos["entry_price"] * pos["shares"]
    hold_days = None
    try:
        entered = datetime.datetime.strptime(pos.get("entry_date", ""), "%Y-%m-%d %H:%M")
        hold_days = round((datetime.datetime.now() - entered).total_seconds() / 86400, 1)
    except ValueError:
        pass
    journal.insert(0, {
        "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ticker": ticker, "direction": pos.get("direction"),
        "shares": pos["shares"], "entry_price": pos["entry_price"], "exit_price": price,
        "entry_date": pos.get("entry_date"), "hold_days": hold_days,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / basis * 100, 2) if basis else 0.0,
        "stop": pos.get("stop"), "target": pos.get("target"),
        "confidence": pos.get("confidence"),
        "reason": reason, "thesis": pos.get("thesis", ""),
    })
    del journal[JOURNAL_LIMIT:]


def apply_orders(portfolio: dict, orders: list, prices: dict, settings: dict, trades: list,
                 journal: list = None):
    """Fill orders against the portfolio at the given prices (mutates portfolio,
    trades and journal in place). Returns (executed, skipped)."""
    executed, skipped = [], []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    positions = portfolio["positions"]

    def record(action, ticker, direction, shares, price, pnl=None, reason=""):
        t = {"ts": now, "action": action, "ticker": ticker, "direction": direction,
             "shares": shares, "price": price, "value": round(shares * price, 2), "reason": reason}
        if pnl is not None:
            t["pnl"] = round(pnl, 2)
        trades.insert(0, t)
        executed.append(t)

    # closes first — they free cash for the opens
    for o in [o for o in orders if o["action"] == "close"]:
        pos = positions.get(o["ticker"])
        price = prices.get(o["ticker"])
        if not pos:
            continue
        if price is None:
            skipped.append({**o, "why": "no price available"})
            continue
        pnl = position_pnl(pos, price)
        portfolio["cash"] += position_value(pos, price)
        portfolio["realized_pnl"] = round(portfolio.get("realized_pnl", 0.0) + pnl, 2)
        _journal_close(journal, o["ticker"], pos, price, pnl, o["reason"])
        del positions[o["ticker"]]
        action = "COVER" if pos.get("direction") == "short" else "SELL"
        record(action, o["ticker"], pos.get("direction"), pos["shares"], price, pnl=pnl, reason=o["reason"])

    for o in [o for o in orders if o["action"] == "open"]:
        price = prices.get(o["ticker"])
        if price is None or price <= 0:
            skipped.append({**o, "why": "no price available"})
            continue
        equity = portfolio_equity(portfolio)
        alloc = min(portfolio["cash"], equity * settings["position_pct"] / 100.0)
        if alloc < MIN_ORDER_VALUE:
            skipped.append({**o, "why": "insufficient cash"})
            continue
        shares = round(alloc / price, 4)
        cost = round(shares * price, 2)
        stop = _sane_stop(o["direction"], price, o.get("stop"))
        target = _sane_target(o["direction"], price, o.get("target"))
        if stop is None or target is None:
            d_stop, d_target = _default_levels(o["direction"], price, o.get("atr14"))
            stop, target = stop or d_stop, target or d_target
        portfolio["cash"] = round(portfolio["cash"] - cost, 2)
        positions[o["ticker"]] = {
            "direction": o["direction"], "shares": shares, "entry_price": price,
            "last_price": price, "entry_date": now, "thesis": o.get("thesis", ""),
            "stop": stop, "target": target, "confidence": o.get("confidence"),
            **({"margin": cost} if o["direction"] == "short" else {}),
        }
        record("SHORT" if o["direction"] == "short" else "BUY",
               o["ticker"], o["direction"], shares, price, reason=o["reason"])

    portfolio["cash"] = round(portfolio["cash"], 2)
    del trades[TRADE_LOG_LIMIT:]
    return executed, skipped


def mark_to_market(portfolio: dict, prices: dict):
    for t, pos in portfolio["positions"].items():
        if prices.get(t):
            pos["last_price"] = prices[t]
            pos["pnl"] = round(position_pnl(pos), 2)


# ── Live prices (yfinance, off the event loop) ───────────────────────────────
def _fetch_prices_sync(tickers: list) -> dict:
    import yfinance as yf
    out = {}
    for sym in tickers:
        try:
            tk = yf.Ticker(sym)
            price = None
            try:
                price = tk.fast_info.last_price
            except Exception:
                pass
            if price is None:
                hist = tk.history(period="5d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            if price:
                out[sym] = round(float(price), 2)
        except Exception as e:
            log.warning(f"price fetch failed for {sym}: {e}")
    return out


# ── Main entry: execute a synthesized plan ───────────────────────────────────
async def execute_plan(plan: dict) -> dict:
    """Execute the Alpha Wolf plan against the paper portfolio. Returns an
    execution report that gets embedded in the plan."""
    settings = get_settings()
    if not settings["enabled"]:
        return {"enabled": False, "executed": [], "skipped": [],
                "note": "Trade execution is OFF — enable it from the Alpha Wolf tab."}

    data = get_agent_data(AGENT_ID) or {}
    portfolio = data.get("portfolio") or new_portfolio(settings["capital"])
    trades = data.get("trades") or []
    journal = data.get("journal") or []

    orders = decide_orders(plan, portfolio["positions"], settings)
    tickers = sorted({o["ticker"] for o in orders} | set(portfolio["positions"]))
    prices = await asyncio.to_thread(_fetch_prices_sync, tickers) if tickers else {}

    executed, skipped = apply_orders(portfolio, orders, prices, settings, trades, journal)
    mark_to_market(portfolio, prices)
    save_agent_data(AGENT_ID, {"portfolio": portfolio, "trades": trades, "journal": journal})

    return {"enabled": True, "executed": executed, "skipped": skipped,
            "summary": portfolio_summary(portfolio)}


# ── Risk check: enforce stops/targets between plan runs ──────────────────────
def _market_open_now() -> bool:
    now = datetime.datetime.now(ET)
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and 570 <= mins < 960   # 9:30–16:00 ET


def stop_target_orders(positions: dict, prices: dict) -> list:
    """Close orders for every open position whose stop or target has been
    crossed at the given prices. Pure — unit-testable."""
    orders = []
    for t, pos in positions.items():
        price = prices.get(t)
        if not price:
            continue
        d = pos.get("direction")
        stop, target = pos.get("stop"), pos.get("target")
        if d == "long":
            if stop and price <= stop:
                orders.append({"action": "close", "ticker": t, "reason": f"stop hit (${stop})"})
            elif target and price >= target:
                orders.append({"action": "close", "ticker": t, "reason": f"target hit (${target})"})
        elif d == "short":
            if stop and price >= stop:
                orders.append({"action": "close", "ticker": t, "reason": f"stop hit (${stop})"})
            elif target and price <= target:
                orders.append({"action": "close", "ticker": t, "reason": f"target hit (${target})"})
    return orders


async def risk_check(force: bool = False) -> dict:
    """Scheduled during market hours: exit any open paper position whose
    stop-loss or profit target has been crossed — the plan's risk levels are
    actually enforced instead of just printed in an email."""
    if not force and not _market_open_now():
        return {"skipped": "market closed"}
    settings = get_settings()
    data = get_agent_data(AGENT_ID) or {}
    portfolio = data.get("portfolio")
    if not portfolio or not portfolio.get("positions"):
        return {"checked": 0, "closed": []}
    trades = data.get("trades") or []
    journal = data.get("journal") or []

    prices = await asyncio.to_thread(_fetch_prices_sync, sorted(portfolio["positions"]))
    orders = stop_target_orders(portfolio["positions"], prices)
    executed = []
    if orders:
        executed, _ = apply_orders(portfolio, orders, prices, settings, trades, journal)
    mark_to_market(portfolio, prices)
    save_agent_data(AGENT_ID, {"portfolio": portfolio, "trades": trades, "journal": journal})

    if executed:
        try:
            from orchestrator import orchestrator
            closed = ", ".join(f"{t['ticker']} {t.get('pnl', 0):+.0f}" for t in executed)
            orchestrator.log_event(f"Alpha Wolf risk check closed {len(executed)} position(s): {closed}", "#dc2626")
        except Exception:
            pass
    return {"checked": len(portfolio["positions"]) + len(executed), "closed": executed,
            "prices": prices}


# ── Performance stats from the closed-trade journal ──────────────────────────
def journal_stats(journal: list) -> dict:
    closed = [j for j in journal or [] if isinstance(j.get("pnl"), (int, float))]
    if not closed:
        return {"trades": 0}
    wins = [j for j in closed if j["pnl"] > 0]
    losses = [j for j in closed if j["pnl"] <= 0]
    gross_win = sum(j["pnl"] for j in wins)
    gross_loss = -sum(j["pnl"] for j in losses)
    holds = [j["hold_days"] for j in closed if isinstance(j.get("hold_days"), (int, float))]
    by_reason = {}
    for j in closed:
        key = ("stop" if "stop hit" in str(j.get("reason", "")) else
               "target" if "target hit" in str(j.get("reason", "")) else "plan")
        r = by_reason.setdefault(key, {"n": 0, "pnl": 0.0})
        r["n"] += 1
        r["pnl"] = round(r["pnl"] + j["pnl"], 2)
    return {
        "trades": len(closed),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1),
        "total_pnl": round(gross_win - gross_loss, 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "best": max(closed, key=lambda j: j["pnl"])["pnl"],
        "worst": min(closed, key=lambda j: j["pnl"])["pnl"],
        "avg_hold_days": round(sum(holds) / len(holds), 1) if holds else None,
        "by_exit": by_reason,
    }


def journal_view(limit: int = 100) -> dict:
    data = get_agent_data(AGENT_ID) or {}
    journal = data.get("journal") or []
    return {"stats": journal_stats(journal), "journal": journal[:limit]}


# ── Views / management (used by the API) ─────────────────────────────────────
async def portfolio_view(refresh_prices: bool = False) -> dict:
    settings = get_settings()
    data = get_agent_data(AGENT_ID) or {}
    portfolio = data.get("portfolio") or new_portfolio(settings["capital"])
    trades = data.get("trades") or []
    if refresh_prices and portfolio["positions"]:
        prices = await asyncio.to_thread(_fetch_prices_sync, sorted(portfolio["positions"]))
        mark_to_market(portfolio, prices)
        save_agent_data(AGENT_ID, {"portfolio": portfolio})
    positions = [{"ticker": t, **p, "pnl": round(position_pnl(p), 2),
                  "value": round(position_value(p), 2)}
                 for t, p in sorted(portfolio["positions"].items())]
    return {"settings": settings, "summary": portfolio_summary(portfolio),
            "positions": positions, "trades": trades[:50],
            "created_at": portfolio.get("created_at")}


def reset_portfolio() -> dict:
    settings = get_settings()
    portfolio = new_portfolio(settings["capital"])
    save_agent_data(AGENT_ID, {"portfolio": portfolio, "trades": [], "journal": []})
    return {"status": "reset", "portfolio": portfolio}
