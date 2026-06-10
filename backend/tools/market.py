"""Market quotes via yfinance — the fetch logic Wolf pioneered, shared as a tool."""
import asyncio

import yfinance as yf

from .registry import tool


def fetch_quotes_sync(symbols: list) -> list:
    """Latest price, daily change and 10-day close history for each symbol.
    Synchronous — call via quotes() or asyncio.to_thread to keep the loop free."""
    tickers = yf.Tickers(" ".join(symbols))
    data = []
    for sym in symbols:
        try:
            ticker = tickers.tickers[sym]
            info = ticker.fast_info

            last_price = info.last_price
            prev_close = info.previous_close
            hist = ticker.history(period="10d")
            history_prices = hist['Close'].tolist() if not hist.empty else []

            # Fall back to historical close if fast_info returns None (weekends, API gaps)
            if last_price is None or prev_close is None:
                if not history_prices:
                    print(f"[tools.market] No data available for {sym}, skipping")
                    continue
                if last_price is None:
                    last_price = history_prices[-1]
                if prev_close is None:
                    prev_close = history_prices[-2] if len(history_prices) >= 2 else history_prices[-1]

            change = last_price - prev_close
            change_pct = (change / prev_close) * 100 if prev_close else 0

            data.append({
                "symbol": sym,
                "price": round(last_price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "history": [round(p, 2) for p in history_prices[-10:]]
            })
        except Exception as e:
            print(f"[tools.market] Failed to fetch data for {sym}: {e}")

    return data


@tool("market.quotes", "Latest price, daily change and 10-day history for ticker symbols (yfinance).")
async def quotes(symbols: list) -> list:
    return await asyncio.to_thread(fetch_quotes_sync, symbols)
