"""VWAP, volume profile, and support/resistance from real price history
(yfinance intraday + daily bars) — same "hard numbers, not LLM guesses"
philosophy as technicals.py. Feeds Alpha Wolf's idea enrichment (stop/target
defaults anchored to real levels instead of a generic ATR envelope) and the
Wallstreet Wolf watchlist display.

Pure math (session_vwap, volume_profile, swing_levels, nearest_levels) takes
plain OHLCV bar lists and has no network dependency — unit-testable without
yfinance. compute_for_symbol_sync/compute_sync are the only impure parts.

DELIBERATELY still on yfinance, unlike tools/market.py which now takes its last
trade from Alpaca. Everything computed here is volume-WEIGHTED — VWAP, the
volume profile's POC and value area, and downstream MFI/VSA/CVD in
technologia_signals.py. Alpaca's free IEX feed carries only IEX-routed volume,
measured at 3.7-4.0% of consolidated on AAPL and NVDA, so sourcing these bars
from it would compute every one of those signals from a 4% sample of the tape
and quietly corrupt them — including the /ES-/NQ reading that gates trade
direction in broker_rules.market_bias(). Consolidated bars are the requirement
here; a real upgrade means a paid consolidated feed, not the IEX one.
"""
import concurrent.futures
import logging

log = logging.getLogger("levels")


# ── Pure math ──────────────────────────────────────────────────────────────
def session_vwap(bars: list):
    """Cumulative (typical price × volume) / cumulative volume across bars.
    None if there's no volume to weight by (e.g. an empty or bad feed)."""
    num = den = 0.0
    for b in bars:
        vol = b.get("volume") or 0
        if vol <= 0:
            continue
        typical = (b["high"] + b["low"] + b["close"]) / 3
        num += typical * vol
        den += vol
    return round(num / den, 4) if den > 0 else None


def vwap_position(price, vwap) -> str:
    if price is None or vwap is None:
        return "unknown"
    diff_pct = (price - vwap) / vwap * 100
    if diff_pct > 0.15:
        return "above"
    if diff_pct < -0.15:
        return "below"
    return "at"


def volume_profile(bars: list, num_bins: int = 24, value_area_pct: float = 0.70) -> dict:
    """Bucket the session's traded range into bins, sum volume per bin. Returns
    the point of control (POC — highest-volume price) and the value area (the
    contiguous bins holding value_area_pct of total volume around the POC)."""
    if not bars:
        return {}
    lo = min(b["low"] for b in bars)
    hi = max(b["high"] for b in bars)
    if hi <= lo:
        return {}
    width = (hi - lo) / num_bins
    bins = [0.0] * num_bins

    def bin_idx(price):
        return max(0, min(num_bins - 1, int((price - lo) / width)))

    for b in bars:
        vol = b.get("volume") or 0
        if vol <= 0:
            continue
        b_lo, b_hi = bin_idx(b["low"]), bin_idx(b["high"])
        span = b_hi - b_lo + 1
        for i in range(b_lo, b_hi + 1):
            bins[i] += vol / span

    total = sum(bins)
    if total <= 0:
        return {}
    poc_idx = max(range(num_bins), key=lambda i: bins[i])

    lo_i = hi_i = poc_idx
    covered = bins[poc_idx]
    while covered / total < value_area_pct and (lo_i > 0 or hi_i < num_bins - 1):
        left = bins[lo_i - 1] if lo_i > 0 else -1
        right = bins[hi_i + 1] if hi_i < num_bins - 1 else -1
        if right >= left:
            hi_i += 1
            covered += bins[hi_i]
        else:
            lo_i -= 1
            covered += bins[lo_i]

    return {
        "poc": round(lo + (poc_idx + 0.5) * width, 2),
        "vah": round(lo + (hi_i + 1) * width, 2),
        "val": round(lo + lo_i * width, 2),
        "session_high": round(hi, 2),
        "session_low": round(lo, 2),
    }


def swing_levels(bars: list, lookback: int = 3, cluster_pct: float = 0.0025,
                 max_levels: int = 4, price=None) -> dict:
    """Support/resistance from fractal swing highs/lows: a bar's high (low)
    that's the max (min) among `lookback` bars on each side marks resistance
    (support). Nearby levels within cluster_pct of each other are merged.

    Levels are kept NEAREST-FIRST around `price` (the last close by default).
    Keeping the extremes instead — the highest resistances and the lowest
    supports — silently discarded every level actually in play: on a $125 name
    that had swing support at 124.12, the returned support was 97.63, so
    nearest_levels() handed a 22%-wide stop to position sizing and the trade
    was either rejected as unsizeable or opened with a stop nowhere near the
    structure it was supposed to sit behind.
    """
    n = len(bars)
    highs, lows = [], []
    for i in range(lookback, n - lookback):
        window = bars[i - lookback:i + lookback + 1]
        if bars[i]["high"] == max(b["high"] for b in window):
            highs.append(bars[i]["high"])
        if bars[i]["low"] == min(b["low"] for b in window):
            lows.append(bars[i]["low"])

    def cluster(vals):
        vals = sorted(vals)
        out = []
        for v in vals:
            if out and abs(v - out[-1]) / out[-1] <= cluster_pct:
                out[-1] = (out[-1] + v) / 2
            else:
                out.append(v)
        return out

    ref = price if price is not None else (bars[-1]["close"] if bars else None)

    def nearest(vals):
        if ref is None:
            return sorted(vals)[:max_levels]
        return sorted(sorted(vals, key=lambda v: abs(v - ref))[:max_levels])

    return {
        "resistance": [round(x, 2) for x in nearest(cluster(highs))],
        "support": [round(x, 2) for x in nearest(cluster(lows))],
    }


def nearest_levels(price, support: list, resistance: list) -> dict:
    """The one support below price and one resistance above price that
    actually matter for a stop/target decision right now."""
    if price is None:
        return {"support": None, "resistance": None}
    below = [s for s in (support or []) if s < price]
    above = [r for r in (resistance or []) if r > price]
    return {
        "support": max(below) if below else (min(support) if support else None),
        "resistance": min(above) if above else (max(resistance) if resistance else None),
    }


# ── Fetch (impure) ─────────────────────────────────────────────────────────
# A shared bar cache: the agents ask for overlapping symbol sets on overlapping
#
# Wallstreet Wolf (120-min interval) and Technologia (30-min) were registered at
# startup on intervals that align, so every two hours they started in the SAME
# SECOND — observed at 21:10:27 — and asked Yahoo for largely the same bars from
# two 8-worker thread pools at once. That is ~40 concurrent requests, and it
# failed the way thread-per-request fetching always fails: rate limits, then
# "[Errno 24] Too many open files". Each fetch below catches, logs a warning and
# returns [], so compute_sync() silently dropped the symbol — one stored run
# holds 2 of 24 symbols and is recorded as a clean success.
#
# Cheapest correct fix: cache by (symbol, kind, params) for a short TTL. The two
# agents want the same 5-minute bars, so the second one to arrive is served from
# memory instead of doubling the load. TTL is deliberately shorter than the
# fastest caller's interval, so nobody ever trades yesterday's tape.
import threading
import time as _time

_bar_cache = {}
_bar_cache_lock = threading.Lock()
BAR_CACHE_TTL = 240.0  # seconds


def _cached(key, produce):
    """Return a cached bar list, computing it once for concurrent callers.

    The per-key lock matters as much as the cache: without it, twenty threads
    that all miss on the same symbol still make twenty requests.
    """
    now = _time.monotonic()
    with _bar_cache_lock:
        hit = _bar_cache.get(key)
        if hit and now - hit[0] < BAR_CACHE_TTL:
            return hit[1]
        lock = _bar_cache.setdefault(("lock",) + key, threading.Lock())
    with lock:
        # Re-check: another thread may have filled it while we waited.
        with _bar_cache_lock:
            hit = _bar_cache.get(key)
            if hit and _time.monotonic() - hit[0] < BAR_CACHE_TTL:
                return hit[1]
        bars = produce()
        # Never cache an empty result — that would pin a rate-limit failure in
        # place for the whole TTL and turn a transient miss into a dead symbol.
        if bars:
            with _bar_cache_lock:
                _bar_cache[key] = (_time.monotonic(), bars)
        return bars


def clear_bar_cache():
    """Test seam, and a way to force a cold read after a symbol list changes."""
    with _bar_cache_lock:
        _bar_cache.clear()


def _bars_from_history(hist, index=None) -> list:
    """OHLCV dicts, plus "t" — minutes since midnight ET — when an ET-localized
    index is supplied. The clock is what lets tools/auction.py separate regular
    hours from the overnight session and time the initial balance; without it
    every bar looks like it happened at the same moment."""
    rows = [
        {"open": float(r.Open), "high": float(r.High), "low": float(r.Low),
         "close": float(r.Close), "volume": float(r.Volume)}
        for _, r in hist.iterrows()
    ]
    if index is not None:
        for bar, ts in zip(rows, index):
            bar["t"] = ts.hour * 60 + ts.minute
    return rows


def _et_index(hist):
    return hist.index.tz_convert("America/New_York") if hist.index.tz is not None else hist.index


def fetch_session_bars_sync(symbol: str, interval: str = "5m", prepost: bool = False) -> list:
    """Today's (or the most recent session's) intraday bars, for VWAP/profile.

    prepost defaults to False so session VWAP and the volume profile stay
    anchored to regular hours — that is what "session VWAP" means to everyone
    reading the number. Callers that need the overnight/pre-market auction (the
    ONH/ONL reference levels) pass prepost=True and split the bars themselves
    with tools.auction.rth_bars() / overnight_bars().
    """
    def _fetch():
        import yfinance as yf
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval=interval, prepost=prepost)
            if hist.empty:
                log.warning(f"session bars empty for {symbol} — likely rate-limited")
                return []
            idx = _et_index(hist)
            last_date = idx[-1].date()
            mask = idx.date == last_date
            return _bars_from_history(hist[mask], idx[mask])
        except Exception as e:
            log.warning(f"session bar fetch failed for {symbol}: {e}")
            return []

    return _cached(("session", symbol, interval, prepost), _fetch)


def fetch_recent_sessions_sync(symbol: str, days: int = 5, interval: str = "5m") -> list:
    """The last `days` intraday sessions as [{"date", "bars"}], oldest first.

    Needed for the levels that only exist across sessions: yesterday's value
    area, and naked POCs — prior points of control price has not returned to.
    Those are the highest-weight zones in the playbook and none of them are
    computable from a single session's bars.
    """
    def _fetch():
        import yfinance as yf
        try:
            hist = yf.Ticker(symbol).history(period=f"{max(days + 2, 5)}d", interval=interval)
            if hist.empty:
                log.warning(f"multi-session bars empty for {symbol} — likely rate-limited")
                return []
            idx = _et_index(hist)
            out = []
            for d in sorted({t.date() for t in idx})[-days:]:
                mask = idx.date == d
                bars = _bars_from_history(hist[mask], idx[mask])
                if bars:
                    out.append({"date": str(d), "bars": bars})
            return out
        except Exception as e:
            log.warning(f"multi-session fetch failed for {symbol}: {e}")
            return []

    return _cached(("sessions", symbol, days, interval), _fetch)


def fetch_daily_bars_sync(symbol: str, period: str = "3mo") -> list:
    """Daily bars for swing-based support/resistance (needs weeks of context,
    not just today's session)."""
    def _fetch():
        import yfinance as yf
        try:
            hist = yf.Ticker(symbol).history(period=period, interval="1d")
            if hist.empty:
                log.warning(f"daily bars empty for {symbol} — likely rate-limited")
                return []
            return _bars_from_history(hist)
        except Exception as e:
            log.warning(f"daily bar fetch failed for {symbol}: {e}")
            return []

    return _cached(("daily", symbol, period), _fetch)


def compute_for_symbol_sync(symbol: str):
    session_bars = fetch_session_bars_sync(symbol)
    daily_bars = fetch_daily_bars_sync(symbol)
    if not session_bars and not daily_bars:
        return None

    price = session_bars[-1]["close"] if session_bars else daily_bars[-1]["close"]
    vwap = session_vwap(session_bars)
    profile = volume_profile(session_bars)
    swings = swing_levels(daily_bars, price=price) if daily_bars else {"support": [], "resistance": []}
    near = nearest_levels(price, swings["support"], swings["resistance"])

    return {
        "symbol": symbol, "price": price,
        "vwap": vwap, "vwap_position": vwap_position(price, vwap),
        "poc": profile.get("poc"), "vah": profile.get("vah"), "val": profile.get("val"),
        "session_high": profile.get("session_high"), "session_low": profile.get("session_low"),
        "support": swings["support"], "resistance": swings["resistance"],
        "nearest_support": near["support"], "nearest_resistance": near["resistance"],
    }


def compute_sync(symbols: list) -> dict:
    out = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for sym, res in zip(symbols, ex.map(compute_for_symbol_sync, symbols)):
            if res:
                out[sym] = res
    return out


def summary_line(t: dict) -> str:
    """One compact line per ticker for an LLM prompt."""
    bits = []
    if t.get("vwap") is not None:
        bits.append(f"VWAP {t['vwap']} (price {t.get('vwap_position', '?')} it)")
    if t.get("poc") is not None:
        bits.append(f"volume POC {t['poc']}")
    if t.get("nearest_support") is not None:
        bits.append(f"support {t['nearest_support']}")
    if t.get("nearest_resistance") is not None:
        bits.append(f"resistance {t['nearest_resistance']}")
    return " · ".join(bits) if bits else "no levels data"
