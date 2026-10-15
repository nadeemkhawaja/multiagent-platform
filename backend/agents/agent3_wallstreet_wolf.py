"""
Agent-3: Wallstreet Wolf — the market desk
==========================================
One agent, two halves that always wanted the same fetch:

  TAPE    watchlist quotes, top gainers/losers, index futures, metals, FX,
          VWAP/support/resistance on the movers, and an LLM commentary
  REGIME  sector bias from the 11 SPDR sector ETFs, VIX regime, floor-trader
          pivots for /ES, /NQ and the majors, scored headlines, and an LLM read
          that resolves into a single composite (-100 bearish .. +100 bullish)

These ran as two agents (Wallstreet Wolf + Wallstreet Compass) hitting Yahoo
Finance on separate schedules for an overlapping symbol set, then getting fused
back together downstream by Alpha Wolf anyway. Merged, it's one fetch pass, one
run, one email — and the composite can never disagree with the tape it was
computed from, because they're now the same snapshot.

Stored under agent_name="wallstreet_wolf" in two keys: "market_data" (tape) and
"compass" (regime). The keys are unchanged so existing rows keep working.
"""

import os
import re
import json
import asyncio
from datetime import datetime

import httpx
import yfinance as yf

from database import SessionLocal, AgentData, get_config
from llm_client import generate_completion, generate_json
from orchestrator import orchestrator
from email_utils import send_html_email, bullets_to_html
from tools import market as market_tools
from tools import levels as levels_tool
import memory
import tracing

AGENT_ID = "wallstreet_wolf"
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")

# Watchlist of 22 user-curated stocks — mega-cap tech, semiconductors/AI infra,
# and crypto-adjacent names. User can override via Settings → watchlist (needs 20+).
DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NFLX", "ORCL",  # mega-cap tech
    "NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU", "SMCI", "CSCO",      # chips & AI infra
    "DELL", "BABA", "PLTR", "GBTC", "COIN", "MSTR",                   # hardware, China tech, crypto
]

# Symbol → company name. The watchlist table shows a real name instead of just
# echoing the ticker; unknown (user-added) symbols fall back to the ticker.
TICKER_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
    "META": "Meta Platforms", "TSLA": "Tesla", "NFLX": "Netflix", "ORCL": "Oracle",
    "NVDA": "NVIDIA", "AMD": "Advanced Micro Devices", "INTC": "Intel", "AVGO": "Broadcom",
    "QCOM": "Qualcomm", "MU": "Micron Technology", "SMCI": "Super Micro Computer",
    "CSCO": "Cisco Systems", "DELL": "Dell Technologies", "BABA": "Alibaba Group",
    "PLTR": "Palantir Technologies", "GBTC": "Grayscale Bitcoin Trust",
    "COIN": "Coinbase Global", "MSTR": "Strategy (MicroStrategy)",
    # extra common names so a customized watchlist still resolves
    "AMAT": "Applied Materials", "LRCX": "Lam Research", "ARM": "Arm Holdings",
    "TSM": "Taiwan Semiconductor", "ASML": "ASML Holding", "MRVL": "Marvell Technology",
    "CRM": "Salesforce", "ADBE": "Adobe", "UBER": "Uber Technologies", "SHOP": "Shopify",
    "JPM": "JPMorgan Chase", "BAC": "Bank of America", "V": "Visa", "MA": "Mastercard",
    "DIS": "Walt Disney", "PYPL": "PayPal", "SQ": "Block", "HOOD": "Robinhood",
}


def ticker_name(symbol: str) -> str:
    return TICKER_NAMES.get((symbol or "").upper(), symbol)


# Broad-market index futures — the headline risk gauges traders watch first.
FUTURES = {"ES=F": ("/ES", "S&P 500 E-mini"), "NQ=F": ("/NQ", "Nasdaq-100 E-mini")}
METALS = ["GC=F", "SI=F"]  # Gold, Silver
CURRENCIES = ["EURUSD=X", "GBPUSD=X", "JPY=X"]

# Sector ETFs → readable sector name (all 11 SPDR sector ETFs for full breadth)
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLY": "Consumer",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communications",
}
MAJORS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "NFLX", "BTC-USD"]


def get_watchlist():
    raw = get_config("watchlist", "")
    syms = [s.strip().upper() for s in str(raw).replace("\n", ",").split(",") if s.strip()]
    return syms if len(syms) >= 20 else DEFAULT_WATCHLIST


async def fetch_market_data():
    """Quote fetch lives in tools/market.py now — shared with any agent that needs it."""
    WATCHLIST = get_watchlist()
    all_symbols = WATCHLIST + list(FUTURES.keys()) + METALS + CURRENCIES
    return await market_tools.quotes(all_symbols)


# ── Regime: pivot math (computed, not LLM) ───────────────────────────────────
def _pivots(h, l, c):
    piv = (h + l + c) / 3
    return {
        "piv": round(piv, 2),
        "r1": round(2 * piv - l, 2),
        "r2": round(piv + (h - l), 2),
        "s1": round(2 * piv - h, 2),
        "s2": round(piv - (h - l), 2),
    }


def _bias(px, piv):
    if px is None or piv is None:
        return "neutral"
    if px > piv * 1.001:
        return "bull"
    if px < piv * 0.999:
        return "bear"
    return "neutral"


def _last_session(sym):
    """Return (last_price, prior_high, prior_low, prior_close) for a symbol."""
    try:
        t = yf.Ticker(sym)
        hist = t.history(period="5d")
        if hist is None or hist.empty:
            return None, None, None, None
        last_px = float(hist["Close"].iloc[-1])
        prior = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
        return (
            round(last_px, 2),
            float(prior["High"]),
            float(prior["Low"]),
            float(prior["Close"]),
        )
    except Exception as e:
        print(f"[Wolf] {sym} fetch error: {e}")
        return None, None, None, None


def _fetch_sectors_sync():
    sectors = []
    try:
        tickers = yf.Tickers(" ".join(SECTOR_ETFS.keys()))
        for sym, name in SECTOR_ETFS.items():
            try:
                info = tickers.tickers[sym].fast_info
                price = info.last_price
                prev = info.previous_close
                # Fall back to history if fast_info returns None (weekends, API gaps)
                if price is None or prev is None:
                    hist = tickers.tickers[sym].history(period="5d")
                    if hist.empty:
                        continue
                    closes = hist["Close"].tolist()
                    if price is None:
                        price = closes[-1]
                    if prev is None:
                        prev = closes[-2] if len(closes) >= 2 else closes[-1]
                price, prev = float(price), float(prev)
                chg_pct = ((price - prev) / prev * 100) if prev else 0.0
                score = int(max(-100, min(100, round(chg_pct * 28))))
                tone = "firm" if score > 15 else "soft" if score < -15 else "mixed"
                sectors.append({
                    "k": name,
                    "bias": score,
                    "why": f"{name} {tone} — {sym} {'+' if chg_pct >= 0 else ''}{chg_pct:.2f}% on the session.",
                })
            except Exception as e:
                print(f"[Wolf] {sym} sector error: {e}")
    except Exception as e:
        print(f"[Wolf] Sector fetch error: {e}")
    return sectors


def _fetch_pivot_futures_sync():
    out = []
    for sym, (label, name) in FUTURES.items():
        px, h, l, c = _last_session(sym)
        if px is None:
            continue
        p = _pivots(h, l, c)
        out.append({"t": label, "n": name, "px": px, "bias": _bias(px, p["piv"]), **p})
    return out


def _fetch_levels_sync():
    out = []
    for sym in MAJORS:
        px, h, l, c = _last_session(sym)
        if px is None:
            continue
        p = _pivots(h, l, c)
        out.append({"t": sym, "px": px, "piv": p["piv"], "r1": p["r1"], "s1": p["s1"],
                    "bias": _bias(px, p["piv"])})
    return out


def _vix_regime(level: float) -> str:
    if level < 15:
        return "Low"
    if level > 25:
        return "Elevated"
    return "Normal"


def _fetch_vix_sync():
    """CBOE Volatility Index — the market's fear gauge. Used to bias the
    composite toward caution when volatility is elevated."""
    try:
        t = yf.Ticker("^VIX")
        hist = t.history(period="5d")
        if hist is None or hist.empty:
            return None
        level = round(float(hist["Close"].iloc[-1]), 2)
        prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else level
        return {"level": level, "change": round(level - prev, 2), "regime": _vix_regime(level)}
    except Exception as e:
        print(f"[Wolf] VIX fetch error: {e}")
        return None


async def fetch_headlines():
    headlines = []
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(
                "https://finance.yahoo.com/rss/headline?s=^GSPC",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 200:
                items = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", r.text)
                for title in items[1:7]:  # skip the feed title
                    headlines.append({"src": "Yahoo Finance", "t": title,
                                      "s": _headline_sentiment(title), "min": "live"})
    except Exception as e:
        print(f"[Wolf] Headlines error: {e}")
    return headlines


def _headline_sentiment(title):
    """Keyword fallback used until the LLM refines sentiment."""
    t = title.lower()
    bull = ("surge", "jump", "rally", "gain", "beat", "rise", "soar", "record", "up ", "climbs")
    bear = ("fall", "drop", "miss", "slump", "plunge", "cut", "fear", "down ", "sink", "warn", "loss")
    if any(w in t for w in bull):
        return "bull"
    if any(w in t for w in bear):
        return "bear"
    return "neutral"


async def llm_headline_sentiment(headlines):
    """Refine each headline's sentiment to bull/bear/neutral with one LLM call."""
    if not headlines:
        return headlines
    listing = "\n".join(f"[{i}] {h['t']}" for i, h in enumerate(headlines))
    prompt = (
        "Score each market headline's sentiment as exactly one of: bull, bear, neutral. "
        'Return ONLY a JSON array: [{"i":<index>,"s":"bull|bear|neutral"}].\n\n' + listing
    )
    data = await generate_json(prompt, system_prompt="You are a markets sentiment classifier. Return only JSON.",
                               agent_id=AGENT_ID, use_cache=False)
    if isinstance(data, list):
        for item in data:
            try:
                i = int(item.get("i"))
                s = str(item.get("s", "")).lower()
                if 0 <= i < len(headlines) and s in ("bull", "bear", "neutral"):
                    headlines[i]["s"] = s
            except (TypeError, ValueError):
                continue
    return headlines


async def llm_read(sectors, futures, headlines, vix=None):
    sec_txt = "\n".join(f"  {s['k']}: {s['bias']:+d}" for s in sectors) or "  (no sector data)"
    fut_txt = "\n".join(f"  {f['t']} {f['px']} pivot {f['piv']} (R1 {f['r1']} / S1 {f['s1']})" for f in futures)
    head_txt = "\n".join(f"  - {h['t']}" for h in headlines[:5]) or "  (no headlines)"
    vix_txt = (f"  VIX {vix['level']} ({vix['regime']} volatility, "
               f"{'+' if vix['change'] >= 0 else ''}{vix['change']} on the session)") if vix else "  (no VIX data)"
    prompt = f"""You are a pre-market strategist. Give a directional read of today's market tone
as 3-4 concise bullet points. Hard rules: each bullet is its own idea, MAX 12 words, plain English,
specific — reference /ES or /NQ pivots, 1-2 sectors, and the VIX regime if notable. No filler,
no hype, no run-on sentences.

Return ONLY JSON: {{"bullets": ["First concise bullet", "Second concise bullet", "Third concise bullet"]}}

Sector bias (-100 bearish .. +100 bullish):
{sec_txt}

Volatility:
{vix_txt}

Futures & pivots:
{fut_txt}

Headlines:
{head_txt}"""
    try:
        data = await generate_json(prompt, system_prompt="You are a pre-market strategist. Return only one JSON object.",
                                   agent_id=AGENT_ID, use_cache=False)
        bullets = data.get("bullets") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        out = []
        for b in (bullets or [])[:4]:
            words = str(b).strip().lstrip("•-* ").split()
            if words:
                out.append("• " + " ".join(words[:14]))  # clamp length so it stays concise
        return "\n".join(out)
    except Exception as e:
        print(f"[Wolf] LLM read error: {e}")
        return ""


def _tone(composite):
    """Plain-English market tone (no 'Risk-On/Risk-Off' jargon)."""
    if composite > 15:
        return "Bullish", "Risk appetite — buyers in control", "#16a34a"
    if composite < -15:
        return "Bearish", "Defensive — money rotating to safety", "#e5484d"
    return "Neutral", "Range-bound — no clear edge", "#f59e0b"


# ── persistence ──────────────────────────────────────────────────────────────
def _save(key: str, payload: dict):
    db = SessionLocal()
    try:
        rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key=key).first()
        if rec:
            rec.value = json.dumps(payload)
            rec.updated_at = datetime.utcnow()
        else:
            db.add(AgentData(agent_name=AGENT_ID, key=key, value=json.dumps(payload)))
        db.commit()
    finally:
        db.close()


def _load(key: str):
    db = SessionLocal()
    rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key=key).first()
    db.close()
    return json.loads(rec.value) if rec else None


# ── Email — one brief covering both halves ───────────────────────────────────
def _fmt_future(s):
    label, name = FUTURES.get(s["symbol"], (s["symbol"], ""))
    cls = "up" if s["change_pct"] >= 0 else "down"
    sign = "+" if s["change_pct"] >= 0 else ""
    return (f'<div class="stock-row"><span><b>{label}</b> {name}</span>'
            f'<span>{s["price"]:,}</span>'
            f'<span class="{cls}">{sign}{s["change_pct"]}%</span></div>')


def build_market_html(tape: dict, regime: dict = None) -> str:
    """The daily brief: the regime verdict up top (it frames everything under
    it), then the tape it was computed from."""
    regime = regime or {}
    top_gainers = tape.get("top_gainers", [])
    top_losers = tape.get("top_losers", [])
    metals = tape.get("metals", [])
    currencies = tape.get("currencies", [])
    futures = tape.get("futures", [])
    commentary = tape.get("commentary", "")

    composite = regime.get("composite")
    regime_block = ""
    if composite is not None:
        tone, tone_desc, color = _tone(composite)
        vix = regime.get("vix") or {}
        vix_line = (f"<div style='font-family:monospace;color:#8a909c;margin-top:2px'>"
                    f"VIX {vix.get('level')} · {vix.get('regime')}</div>") if vix else ""
        sec_rows = "".join(
            f"<tr><td style='padding:5px 12px'>{s['k']}</td>"
            f"<td style='padding:5px 12px;font-family:monospace;color:{'#16a34a' if s['bias'] >= 0 else '#e5484d'}'>"
            f"{s['bias']:+d}</td></tr>"
            for s in regime.get("sectors", [])
        )
        regime_block = f"""
          <div style='text-align:center;margin:4px 0 16px;padding:16px;border:1px solid {color};border-radius:12px'>
            <div style='font-size:28px;font-weight:800;color:{color}'>{tone}</div>
            <div style='color:#5b6472;font-size:13px;margin-top:2px'>{tone_desc}</div>
            <div style='font-family:monospace;color:#8a909c;margin-top:4px'>composite {composite:+d}</div>
            {vix_line}
          </div>
          {bullets_to_html(regime.get('read', '')) or ''}
          <h2>🧭 Sector bias</h2>
          <table style='width:100%;border-collapse:collapse'>
            <thead><tr style='text-align:left;color:#8a909c;font-size:11px'>
              <th style='padding:5px 12px'>SECTOR</th><th style='padding:5px 12px'>BIAS</th></tr></thead>
            <tbody>{sec_rows}</tbody>
          </table>"""

    return f"""
    <html>
      <head>
        <meta name="color-scheme" content="light">
        <meta name="supported-color-schemes" content="light">
        <style>
          body {{ font-family: 'Segoe UI', sans-serif; background: #eef2f7; color: #0f172a; padding: 20px; margin: 0; }}
          .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 28px; }}
          h1 {{ color: #2563eb; margin-top: 0; }}
          h2 {{ color: #64748b; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px; }}
          .stock-row {{ display: flex; justify-content: space-between; padding: 10px 14px; background: #f8fafc; border: 1px solid #eef2f7; border-radius: 6px; margin-bottom: 6px; }}
          .up {{ color: #15803d; font-weight: 600; }}
          .down {{ color: #dc2626; font-weight: 600; }}
          .commentary {{ background: #eff6ff; border-left: 3px solid #2563eb; padding: 14px 16px; border-radius: 8px; margin: 16px 0; }}
        </style>
      </head>
      <body>
        <div class="container">
          <h1>📈 Wallstreet Wolf — Market Desk</h1>
          <p style="color:#64748b;">{datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}</p>
          {regime_block}

          <div class="commentary">{bullets_to_html(commentary) or '<span style="color:#94a3b8">No commentary.</span>'}</div>

          <h2>📊 Index Futures</h2>
          {''.join([_fmt_future(s) for s in futures]) or '<p style="color:#94a3b8;">No futures data.</p>'}

          <h2>🟢 Top 5 Gainers</h2>
          {''.join([f'<div class="stock-row"><span>{s["symbol"]}</span><span>${s["price"]}</span><span class="up">+{s["change_pct"]}%</span></div>' for s in top_gainers])}

          <h2>🔴 Top 5 Losers</h2>
          {''.join([f'<div class="stock-row"><span>{s["symbol"]}</span><span>${s["price"]}</span><span class="down">{s["change_pct"]}%</span></div>' for s in top_losers])}

          <h2>🥇 Precious Metals</h2>
          {''.join([f'<div class="stock-row"><span>{"Gold" if s["symbol"]=="GC=F" else "Silver"}</span><span>${s["price"]}</span><span class="{"up" if s["change_pct"]>=0 else "down"}">{s["change_pct"]}%</span></div>' for s in metals])}

          <h2>💱 Currency Pairs</h2>
          {''.join([f'<div class="stock-row"><span>{s["symbol"].replace("=X","")}</span><span>{s["price"]}</span><span class="{"up" if s["change_pct"]>=0 else "down"}">{s["change_pct"]}%</span></div>' for s in currencies])}
        </div>
      </body>
    </html>
    """


def send_market_email(tape: dict, regime: dict):
    if not DAILY_DIGEST_EMAIL:
        return
    composite = (regime or {}).get("composite")
    tone = _tone(composite)[0] if composite is not None else "Brief"
    send_html_email(DAILY_DIGEST_EMAIL,
                    f"📈 Wallstreet Wolf — {tone} — {datetime.utcnow().strftime('%b %d')}",
                    build_market_html(tape, regime), sender_name="Wallstreet Wolf Agent")


def email_preview() -> str:
    tape = _load("market_data")
    if not tape:
        return "<p>No market data yet — run Wallstreet Wolf first.</p>"
    return build_market_html(tape, _load("compass"))


# ── Main job ─────────────────────────────────────────────────────────────────
async def wallstreet_wolf_job():
    orchestrator.update_agent_status(AGENT_ID, "running")
    try:
        # Both halves fetch from Yahoo; run them together rather than on two
        # schedules that drift apart.
        orchestrator.set_progress(AGENT_ID, "Fetching quotes, sectors, pivots & VIX…")
        with tracing.stage(AGENT_ID, "fetch"):
            market_data, sectors, pivot_futures, levels, vix = await asyncio.gather(
                fetch_market_data(),
                asyncio.to_thread(_fetch_sectors_sync),
                asyncio.to_thread(_fetch_pivot_futures_sync),
                asyncio.to_thread(_fetch_levels_sync),
                asyncio.to_thread(_fetch_vix_sync),
            )

        # ── Tape ──
        watchlist = get_watchlist()
        stocks_only = [d for d in market_data if d["symbol"] in watchlist]
        for d in stocks_only:                       # attach a readable company name
            d["name"] = d.get("name") or ticker_name(d["symbol"])
        stocks_only.sort(key=lambda x: x["change_pct"], reverse=True)

        top_gainers = stocks_only[:5]
        top_losers = stocks_only[-5:][::-1]  # worst performer first

        # VWAP / volume profile / support-resistance for the actionable subset
        # only (top movers) — full-watchlist coverage would double the fetch
        # cost for tickers that aren't today's buy/exit candidates anyway.
        with tracing.stage(AGENT_ID, "levels"):
            level_tickers = [s["symbol"] for s in top_gainers + top_losers]
            mover_levels = await asyncio.to_thread(levels_tool.compute_sync, level_tickers) if level_tickers else {}
        for s in top_gainers + top_losers:
            lv = mover_levels.get(s["symbol"])
            if lv:
                s["levels"] = {k: lv[k] for k in
                              ("vwap", "vwap_position", "poc", "nearest_support", "nearest_resistance")}

        futures = [d for d in market_data if d["symbol"] in FUTURES]
        # keep /ES before /NQ
        futures.sort(key=lambda d: list(FUTURES.keys()).index(d["symbol"]))
        metals = [d for d in market_data if d["symbol"] in [m for m in METALS]]
        currencies = [d for d in market_data if d["symbol"] in [c for c in CURRENCIES]]

        gainer_strs = [f"{s['symbol']} (+{s['change_pct']}%)" for s in top_gainers]
        loser_strs = [f"{s['symbol']} ({s['change_pct']}%)" for s in top_losers]
        futures_strs = [f"{FUTURES[s['symbol']][0]} ({'+' if s['change_pct'] >= 0 else ''}{s['change_pct']}%)" for s in futures]

        # ── Regime ──
        orchestrator.set_progress(AGENT_ID, "Scoring headlines & computing the composite…")
        headlines = await fetch_headlines()
        try:
            headlines = await llm_headline_sentiment(headlines)
        except Exception as e:
            print(f"[Wolf] Headline sentiment LLM failed: {e}")

        composite = int(round(sum(s["bias"] for s in sectors) / len(sectors))) if sectors else 0
        # Elevated/low volatility nudges the composite toward caution/confidence.
        if vix:
            if vix["regime"] == "Elevated":
                composite -= 10
            elif vix["regime"] == "Low":
                composite += 5
            composite = max(-100, min(100, composite))

        # Prior snapshot from memory lets the commentary call out what changed
        # rather than just restating today's state. Failure-isolated: memory
        # being down never blocks the run.
        prior_context = ""
        try:
            snaps = memory.recent(AGENT_ID, k=1, kind="daily_snapshot")
            if snaps:
                prior_context = (
                    f" For context, the previous brief was: {snaps[0]['text']} "
                    f"Highlight notable changes versus that brief (reversals, momentum, new leaders)."
                )
        except Exception as e:
            print(f"[Wolf] memory recall failed: {e}")

        # Two LLM calls, each isolated: a failure in either must not lose the
        # data that was already fetched.
        orchestrator.set_progress(AGENT_ID, "Writing the commentary and the regime read…")
        commentary = ""
        try:
            prompt = (
                "Write today's market commentary as 3-4 bullet points. Rules:\n"
                "• One fact per bullet, max 12 words, plain English.\n"
                "• Use ONLY the numbers given below. Do NOT invent reasons, news, "
                "earnings, or macro events (no 'on muted energy data', no 'mixed "
                "manufacturing reports' — you don't have that data).\n"
                "• State the move and direction only, e.g. '/ES down 0.05%, NQ flat' "
                "or 'NVDA led gainers, up 3.1%'.\n"
                "• Each bullet on its own line starting with '• '. No intro or outro.\n\n"
                f"Index futures: {', '.join(futures_strs) or 'N/A'}.\n"
                f"Top gainers: {', '.join(gainer_strs)}.\n"
                f"Top losers: {', '.join(loser_strs)}.\n"
                f"Gold: ${metals[0]['price'] if metals else 'N/A'}, "
                f"Silver: ${metals[1]['price'] if len(metals) > 1 else 'N/A'}."
                f"{prior_context}"
            )
            commentary = await generate_completion(
                prompt,
                system_prompt=("You are a Wall Street analyst writing a terse, factual daily "
                               "market note for US markets. Report only what the numbers show; "
                               "never fabricate causes or news you were not given."),
                agent_id=AGENT_ID,
            )
        except Exception as e:
            print(f"[Wolf] LLM commentary failed: {e}")

        try:
            read = await llm_read(sectors, pivot_futures, headlines, vix)
        except Exception as e:
            print(f"[Wolf] LLM read failed: {e}")
            read = ""

        tape = {
            "watchlist": stocks_only,
            "futures": futures,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "metals": metals,
            "currencies": currencies,
            "commentary": commentary,
        }
        regime = {
            "sectors": sectors,
            "news": headlines,
            "futures": pivot_futures,
            "levels": levels,
            "vix": vix,
            "composite": composite,
            "read": read,
            "fetched_at": datetime.utcnow().isoformat(),
        }
        _save("market_data", tape)
        _save("compass", regime)

        send_market_email(tape, regime)

        # Persist a compact snapshot so tomorrow's commentary can reference it
        try:
            snapshot = (
                f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} — "
                f"Composite {composite:+d}. "
                f"Futures: {', '.join(futures_strs) or 'N/A'}. "
                f"Gainers: {', '.join(gainer_strs)}. Losers: {', '.join(loser_strs)}."
            )
            await memory.remember(AGENT_ID, snapshot, kind="daily_snapshot")
        except Exception as e:
            print(f"[Wolf] memory save failed: {e}")

        orchestrator.update_agent_status(AGENT_ID, "idle")
        print(f"[Wolf] Done — composite {composite:+d}, {len(levels)} levels, {len(sectors)} sectors, "
              f"VIX {vix['level'] if vix else 'n/a'}")
    except Exception as e:
        orchestrator.update_agent_status(AGENT_ID, "error", str(e))
        print(f"[Wolf] Error: {e}")
