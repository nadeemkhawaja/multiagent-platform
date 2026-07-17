"""Technical indicators from real price history (yfinance daily bars).

Feeds the trading agents hard numbers — RSI, moving-average trend, ATR —
so entries/stops/targets come from data instead of LLM guesses. ATR in
particular anchors stop distances: stop ≈ entry ∓ 1.2×ATR is a defensible
volatility-based stop, target ≥ 2×risk keeps reward/risk honest.
"""
import asyncio
import concurrent.futures
import logging

from .registry import tool

log = logging.getLogger("technicals")


def _rsi(closes, period: int = 14):
    """Wilder's RSI over a list of closes. None if not enough data."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def _atr(highs, lows, closes, period: int = 14):
    """Wilder's Average True Range. None if not enough data."""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 2)


def _sma(closes, period: int):
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def compute_for_symbol_sync(sym: str):
    """Indicator snapshot for one symbol from ~3 months of daily bars."""
    import yfinance as yf
    try:
        hist = yf.Ticker(sym).history(period="3mo", interval="1d")
        if hist.empty or len(hist) < 15:
            return None
        closes = [float(c) for c in hist["Close"]]
        highs = [float(h) for h in hist["High"]]
        lows = [float(l) for l in hist["Low"]]
        price = round(closes[-1], 2)
        sma20, sma50 = _sma(closes, 20), _sma(closes, 50)
        atr = _atr(highs, lows, closes)
        rsi = _rsi(closes)
        trend = None
        if sma20 and sma50:
            trend = ("uptrend" if price > sma20 > sma50 else
                     "downtrend" if price < sma20 < sma50 else "mixed")
        elif sma20:
            trend = "above SMA20" if price > sma20 else "below SMA20"
        out = {
            "symbol": sym, "price": price, "rsi14": rsi,
            "sma20": sma20, "sma50": sma50, "atr14": atr,
            "atr_pct": round(atr / price * 100, 2) if atr and price else None,
            "trend": trend,
            "chg5d_pct": round((closes[-1] - closes[-6]) / closes[-6] * 100, 2) if len(closes) >= 6 else None,
        }
        return out
    except Exception as e:
        log.warning(f"technicals failed for {sym}: {e}")
        return None


def compute_sync(symbols: list) -> dict:
    """Indicator snapshots for many symbols, fetched in parallel."""
    out = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for sym, res in zip(symbols, ex.map(compute_for_symbol_sync, symbols)):
            if res:
                out[sym] = res
    return out


def summary_line(t: dict) -> str:
    """One compact line per ticker for an LLM prompt."""
    bits = [f"${t['price']}"]
    if t.get("rsi14") is not None:
        state = " (overbought)" if t["rsi14"] >= 70 else " (oversold)" if t["rsi14"] <= 30 else ""
        bits.append(f"RSI {t['rsi14']}{state}")
    if t.get("trend"):
        bits.append(t["trend"])
    if t.get("sma20"):
        bits.append(f"SMA20 {t['sma20']}")
    if t.get("atr14"):
        bits.append(f"ATR {t['atr14']} ({t.get('atr_pct', '?')}%)")
    if t.get("chg5d_pct") is not None:
        bits.append(f"5d {t['chg5d_pct']:+}%")
    return f"{t['symbol']}: " + ", ".join(bits)


@tool("market.technicals", "RSI(14), SMA20/50 trend, ATR(14) and 5-day change per ticker from real daily bars (yfinance).")
async def technicals(symbols: list) -> dict:
    return await asyncio.to_thread(compute_sync, symbols)
