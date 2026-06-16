"""
Agent-4: Wallstreet Compass — Market Bias Engine + Key Levels
=============================================================
Real external data via Yahoo Finance:
  • Sector directional bias from the 6 sector ETFs (XLK/XLE/XLF/XLV/XLY/XLI)
  • Classic floor-trader pivot levels (Pivot / R1-R2 / S1-S2) for /ES & /NQ futures
    and the 10 majors (NVDA, MSFT, AAPL, AMZN, GOOGL, META, TSLA, AMD, AVGO, NFLX)
  • Top financial headlines (GNews / Yahoo RSS) with sentiment
LLM step: a single Qwen3 call writes the composite "read".
Scheduled action: pre-market brief email at 07:00.
Stored in SQLite under agent_name="compass", key="compass".
"""

import os
import re
import json
import asyncio
from datetime import datetime

import httpx
import yfinance as yf

from database import SessionLocal, AgentData
from llm_client import generate_completion, generate_json
from orchestrator import orchestrator
from email_utils import send_html_email

AGENT_ID = "compass"
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")

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
FUTURES = {"ES=F": ("/ES", "E-mini S&P 500"), "NQ=F": ("/NQ", "E-mini Nasdaq-100")}
MAJORS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "NFLX", "BTC-USD"]


# ── pivot math (computed, not LLM) ───────────────────────────────────────────
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
        print(f"[Compass] {sym} fetch error: {e}")
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
                print(f"[Compass] {sym} sector error: {e}")
    except Exception as e:
        print(f"[Compass] Sector fetch error: {e}")
    return sectors


def _fetch_futures_sync():
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
        print(f"[Compass] VIX fetch error: {e}")
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
        print(f"[Compass] Headlines error: {e}")
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
as 3-5 bullet points. Each bullet starts with '• ' on its own line, max 12 words, crisp and
specific. Reference /ES or /NQ pivot levels, 1-2 sectors, and the VIX regime if notable.
Plain-English, non-hyperbolic. No paragraphs, no intro/outro text.

Sector bias (-100 bearish .. +100 bullish):
{sec_txt}

Volatility:
{vix_txt}

Futures & pivots:
{fut_txt}

Headlines:
{head_txt}
/no_think"""
    try:
        out = await generate_completion(prompt, agent_id=AGENT_ID)
        return re.sub(r"<think>.*?</think>", "", out, flags=re.DOTALL).strip()
    except Exception as e:
        print(f"[Compass] LLM error: {e}")
        return ""


def save_to_db(payload):
    db = SessionLocal()
    try:
        rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key="compass").first()
        if rec:
            rec.value = json.dumps(payload)
            rec.updated_at = datetime.utcnow()
        else:
            db.add(AgentData(agent_name=AGENT_ID, key="compass", value=json.dumps(payload)))
        db.commit()
    finally:
        db.close()


def _tone(composite):
    """Plain-English market tone (no 'Risk-On/Risk-Off' jargon)."""
    if composite > 15:
        return "Bullish", "Risk appetite — buyers in control", "#16a34a"
    if composite < -15:
        return "Bearish", "Defensive — money rotating to safety", "#e5484d"
    return "Neutral", "Range-bound — no clear edge", "#f59e0b"


def build_compass_html(payload):
    composite = payload.get("composite", 0)
    tone, tone_desc, color = _tone(composite)
    sec_rows = "".join(
        f"<tr><td style='padding:6px 12px'>{s['k']}</td>"
        f"<td style='padding:6px 12px;font-family:monospace;color:{'#16a34a' if s['bias'] >= 0 else '#e5484d'}'>"
        f"{s['bias']:+d}</td></tr>"
        for s in payload.get("sectors", [])
    )
    html = f"""
    <html><body style='font-family:Hanken Grotesk,Arial,sans-serif;background:#f6f7f9;color:#16181d;padding:24px'>
      <h2 style='letter-spacing:-.3px'>◎ Wallstreet Compass — Pre-Market Brief</h2>
      <p style='color:#8a909c;font-size:12px'>{datetime.utcnow().strftime('%A, %B %d %Y — %H:%M UTC')}</p>
      <div style='text-align:center;margin:18px 0;padding:18px;border:1px solid {color};border-radius:12px'>
        <div style='font-size:30px;font-weight:800;color:{color}'>{tone}</div>
        <div style='color:#5b6472;font-size:13px;margin-top:2px'>{tone_desc}</div>
        <div style='font-family:monospace;color:#8a909c;margin-top:4px'>composite {composite:+d}</div>
      </div>
      <p style='line-height:1.55;white-space:pre-line'>{payload.get('read', '')}</p>
      <table style='width:100%;border-collapse:collapse;margin-top:12px'>
        <thead><tr style='text-align:left;color:#8a909c;font-size:11px'>
          <th style='padding:6px 12px'>SECTOR</th><th style='padding:6px 12px'>BIAS</th></tr></thead>
        <tbody>{sec_rows}</tbody>
      </table>
    </body></html>
    """
    return html


def send_compass_email(payload):
    if not DAILY_DIGEST_EMAIL:
        return
    composite = payload.get("composite", 0)
    tone, _desc, _color = _tone(composite)
    send_html_email(
        to_email=DAILY_DIGEST_EMAIL,
        subject=f"◎ Wallstreet Compass Brief — {tone} — {datetime.utcnow().strftime('%b %d')}",
        html_body=build_compass_html(payload),
        sender_name="Wallstreet Compass Agent",
    )


def email_preview() -> str:
    db = SessionLocal()
    rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key="compass").first()
    db.close()
    if not rec:
        return "<p>No Wallstreet Compass data yet — run an analysis first.</p>"
    return build_compass_html(json.loads(rec.value))


async def compass_job():
    orchestrator.update_agent_status(AGENT_ID, "running")
    try:
        # Run all blocking yfinance fetches in parallel threads
        sectors, futures, levels, vix = await asyncio.gather(
            asyncio.to_thread(_fetch_sectors_sync),
            asyncio.to_thread(_fetch_futures_sync),
            asyncio.to_thread(_fetch_levels_sync),
            asyncio.to_thread(_fetch_vix_sync),
        )
        headlines = await fetch_headlines()
        try:
            headlines = await llm_headline_sentiment(headlines)
        except Exception as e:
            print(f"[Compass] Headline sentiment LLM failed: {e}")

        composite = int(round(sum(s["bias"] for s in sectors) / len(sectors))) if sectors else 0
        # Elevated/low volatility nudges the composite toward caution/confidence.
        if vix:
            if vix["regime"] == "Elevated":
                composite -= 10
            elif vix["regime"] == "Low":
                composite += 5
            composite = max(-100, min(100, composite))
        try:
            read = await llm_read(sectors, futures, headlines, vix)
        except Exception as e:
            print(f"[Compass] LLM read failed: {e}")
            read = ""

        payload = {
            "sectors": sectors,
            "news": headlines,
            "futures": futures,
            "levels": levels,
            "vix": vix,
            "composite": composite,
            "read": read,
            "brief": {"scheduled": "07:00"},
            "fetched_at": datetime.utcnow().isoformat(),
        }
        save_to_db(payload)
        send_compass_email(payload)

        orchestrator.update_agent_status(AGENT_ID, "idle")
        print(f"[Compass] Done — composite {composite:+d}, {len(levels)} levels, {len(sectors)} sectors, "
              f"VIX {vix['level'] if vix else 'n/a'}")
    except Exception as e:
        orchestrator.update_agent_status(AGENT_ID, "error", str(e))
        print(f"[Compass] Error: {e}")
