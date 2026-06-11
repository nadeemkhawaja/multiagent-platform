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

from database import get_agent_data, save_agent_data, get_config, set_config

log = logging.getLogger("paper_broker")

AGENT_ID = "alpha_wolf"

DEFAULT_CAPITAL = 100_000.0
DEFAULT_POSITION_PCT = 10.0     # % of equity allocated to each new position
DEFAULT_MAX_POSITIONS = 8
MIN_ORDER_VALUE = 50.0          # skip allocations too small to matter
TRADE_LOG_LIMIT = 200

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
                       "reason": "daily plan idea"})
        open_slots -= 1
    return orders


def apply_orders(portfolio: dict, orders: list, prices: dict, settings: dict, trades: list):
    """Fill orders against the portfolio at the given prices (mutates portfolio
    and trades in place). Returns (executed, skipped)."""
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
        portfolio["cash"] = round(portfolio["cash"] - cost, 2)
        positions[o["ticker"]] = {
            "direction": o["direction"], "shares": shares, "entry_price": price,
            "last_price": price, "entry_date": now, "thesis": o.get("thesis", ""),
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

    orders = decide_orders(plan, portfolio["positions"], settings)
    tickers = sorted({o["ticker"] for o in orders} | set(portfolio["positions"]))
    prices = await asyncio.to_thread(_fetch_prices_sync, tickers) if tickers else {}

    executed, skipped = apply_orders(portfolio, orders, prices, settings, trades)
    mark_to_market(portfolio, prices)
    save_agent_data(AGENT_ID, {"portfolio": portfolio, "trades": trades})

    return {"enabled": True, "executed": executed, "skipped": skipped,
            "summary": portfolio_summary(portfolio)}


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
    save_agent_data(AGENT_ID, {"portfolio": portfolio, "trades": []})
    return {"status": "reset", "portfolio": portfolio}
