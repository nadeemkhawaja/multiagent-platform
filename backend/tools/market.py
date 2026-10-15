"""Market quotes — real-time last trade from Alpaca, everything else yfinance.

yfinance quotes are 15-minute delayed and increasingly rate-limited, so the
LAST TRADE now comes from Alpaca's IEX feed (one batched request, using keys
this app already has for trading).

Deliberately split, not a wholesale migration: Alpaca's free IEX feed only sees
IEX-routed volume, a few percent of consolidated, so its aggregates are not
trustworthy — its prior close for AAPL was 333.07 against a true 312.33. Only
the last trade (a real print) is taken from Alpaca; the previous close, company
name and 10-day history stay with yfinance's consolidated data. Everything
falls back to yfinance when Alpaca is unconfigured, unreachable, or doesn't
carry the symbol (/ES and /NQ are futures — Alpaca has no equity data for them).
"""
import asyncio
import logging
import os
import re

import httpx
import yfinance as yf
from dotenv import load_dotenv

from .registry import tool

# This module is imported before anything else calls load_dotenv(), so reading
# the keys at import time without this yields "" and silently disables Alpaca.
load_dotenv()

log = logging.getLogger("tools.market")

ALPACA_DATA_BASE = os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")
# US equity tickers only: letters, optionally with a class suffix (BRK.B).
_EQUITY_SYMBOL = re.compile(r"[A-Z]{1,5}(?:\.[A-Z])?")


def alpaca_last_trades_sync(symbols: list) -> dict:
    """{symbol: last_trade_price} from Alpaca's IEX feed, in one batched call.

    ONLY the last trade is taken. Alpaca's free IEX feed sees just IEX-routed
    volume (a few percent of consolidated), so its daily BARS are unreliable —
    it reported AAPL's prior close as 333.07 against a true 312.33, which would
    render a -1.1% day as -7.4% and poison the gainers/losers ranking. The last
    trade is a real print and is trustworthy; the previous close stays with
    yfinance, whose consolidated daily bars are correct.

    Returns {} rather than raising when unconfigured or unreachable — callers
    treat a miss as "use yfinance for this symbol"."""
    key, secret = os.getenv("ALPACA_API_KEY_ID", ""), os.getenv("ALPACA_API_SECRET_KEY", "")
    # Alpaca rejects the WHOLE batch with a 400 if any symbol isn't a US
    # equity, so yfinance-style futures/index tickers (ES=F, NQ=F, ^VIX) are
    # dropped here rather than being allowed to take the good symbols down
    # with them.
    symbols = [s for s in (symbols or []) if _EQUITY_SYMBOL.fullmatch(str(s))]
    if not (key and secret) or not symbols:
        return {}
    out = {}
    try:
        with httpx.Client(base_url=ALPACA_DATA_BASE, timeout=10,
                          headers={"APCA-API-KEY-ID": key,
                                   "APCA-API-SECRET-KEY": secret}) as c:
            r = c.get("/v2/stocks/trades/latest",
                      params={"symbols": ",".join(symbols), "feed": "iex"})
            r.raise_for_status()
            trades = (r.json() or {}).get("trades") or {}
        for sym, t in trades.items():
            if isinstance(t, dict) and t.get("p"):
                out[sym] = float(t["p"])
    except Exception as e:
        log.warning(f"Alpaca quote fetch failed, falling back to yfinance: {e}")
        return {}
    return out


def fetch_quotes_sync(symbols: list) -> list:
    """Latest price, daily change and 10-day close history for each symbol.
    Synchronous — call via quotes() or asyncio.to_thread to keep the loop free."""
    import concurrent.futures
    tickers = yf.Tickers(" ".join(symbols))
    data = []

    def fetch_one(sym):
        try:
            ticker = tickers.tickers[sym]
            info = ticker.fast_info

            name = sym
            try:
                full_info = ticker.info
                name = full_info.get("shortName") or full_info.get("longName") or sym
            except Exception:
                pass

            last_price = info.last_price
            prev_close = info.previous_close
            hist = ticker.history(period="10d")
            history_prices = hist['Close'].tolist() if not hist.empty else []

            if last_price is None or prev_close is None:
                if not history_prices:
                    return None
                if last_price is None:
                    last_price = history_prices[-1]
                if prev_close is None:
                    prev_close = history_prices[-2] if len(history_prices) >= 2 else history_prices[-1]

            change = last_price - prev_close
            change_pct = (change / prev_close) * 100 if prev_close else 0

            return {
                "symbol": sym,
                "name": name,
                "price": round(last_price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "history": [round(p, 2) for p in history_prices[-10:]]
            }
        except Exception as e:
            print(f"[tools.market] Failed to fetch data for {sym}: {e}")
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_one, symbols))

    for r in results:
        if r is not None:
            data.append(r)

    return apply_live_prices(data, alpaca_last_trades_sync([r["symbol"] for r in data]))


def apply_live_prices(rows: list, live: dict) -> list:
    """Overlay Alpaca's real-time last trade on yfinance rows, recomputing the
    change against YFINANCE's previous close (see alpaca_last_trades_sync for
    why Alpaca's own prior close is not used). Symbols Alpaca doesn't carry —
    /ES, /NQ — keep their yfinance row untouched. Pure; mutates and returns
    rows for the caller's convenience."""
    for r in rows:
        last = live.get(r["symbol"])
        if not last:
            continue
        prev = r["price"] - r["change"]        # yfinance's consolidated prev close
        r["price"] = round(last, 2)
        r["change"] = round(last - prev, 2)
        r["change_pct"] = round((last - prev) / prev * 100, 2) if prev else 0.0
        r["realtime"] = True
    return rows


@tool("market.quotes", "Latest price and daily change (real-time via Alpaca IEX, falling back to yfinance) plus 10-day history.")
async def quotes(symbols: list) -> list:
    return await asyncio.to_thread(fetch_quotes_sync, symbols)
