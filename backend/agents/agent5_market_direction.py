"""
Agent-4: Compass — Market Bias Engine + Key Levels
==================================================
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
from datetime import datetime

import httpx
import yfinance as yf

from database import SessionLocal, AgentData
from llm_client import generate_completion, generate_json
from orchestrator import orchestrator
from email_utils import send_html_email

AGENT_ID = "compass"
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")

# Sector ETFs → readable sector name
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLY": "Consumer",
    "XLI": "Industrials",
}
FUTURES = {"ES=F": ("/ES", "E-mini S&P 500"), "NQ=F": ("/NQ", "E-mini Nasdaq-100")}
MAJORS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "NFLX"]


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


def fetch_sectors():
    sectors = []
    try:
        tickers = yf.Tickers(" ".join(SECTOR_ETFS.keys()))
        for sym, name in SECTOR_ETFS.items():
            try:
                info = tickers.tickers[sym].fast_info
                price = float(info.last_price)
                prev = float(info.previous_close)
                chg_pct = ((price - prev) / prev * 100) if prev else 0.0
                # map a daily % move to a -100..100 directional lean
                score = int(max(-100, min(100, round(chg_pct * 28))))
                tone = "firm" if score > 15 else "soft" if score < -15 else "mixed"
                sectors.append({
                    "k": name,
                    "bias": score,
                    "why": f"{name} {tone} — {sym} {'+' if chg_pct >= 0 else ''}{chg_pct:.2f}% on the session.",
                })
            except Exception:
                pass
    except Exception as e:
        print(f"[Compass] Sector fetch error: {e}")
    return sectors


def fetch_futures():
    out = []
    for sym, (label, name) in FUTURES.items():
        px, h, l, c = _last_session(sym)
        if px is None:
            continue
        p = _pivots(h, l, c)
        out.append({"t": label, "n": name, "px": px, "bias": _bias(px, p["piv"]), **p})
    return out


def fetch_levels():
    out = []
    for sym in MAJORS:
        px, h, l, c = _last_session(sym)
        if px is None:
            continue
        p = _pivots(h, l, c)
        out.append({"t": sym, "px": px, "piv": p["piv"], "r1": p["r1"], "s1": p["s1"],
                    "bias": _bias(px, p["piv"])})
    return out


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


async def llm_read(sectors, futures, headlines):
    sec_txt = "\n".join(f"  {s['k']}: {s['bias']:+d}" for s in sectors) or "  (no sector data)"
    fut_txt = "\n".join(f"  {f['t']} {f['px']} pivot {f['piv']} (R1 {f['r1']} / S1 {f['s1']})" for f in futures)
    head_txt = "\n".join(f"  - {h['t']}" for h in headlines[:5]) or "  (no headlines)"
    prompt = f"""You are a pre-market strategist. Write a concise 3-4 sentence directional read
of today's market tone. Reference specific /ES or /NQ pivot levels and 1-2 sectors.
Be plain-English and non-hyperbolic.

Sector bias (-100 bearish .. +100 bullish):
{sec_txt}

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


def build_compass_html(payload):
    composite = payload.get("composite", 0)
    tone = "Risk-On" if composite > 15 else "Risk-Off" if composite < -15 else "Mixed"
    color = "#16a34a" if composite > 15 else "#e5484d" if composite < -15 else "#f59e0b"
    sec_rows = "".join(
        f"<tr><td style='padding:6px 12px'>{s['k']}</td>"
        f"<td style='padding:6px 12px;font-family:monospace;color:{'#16a34a' if s['bias'] >= 0 else '#e5484d'}'>"
        f"{s['bias']:+d}</td></tr>"
        for s in payload.get("sectors", [])
    )
    html = f"""
    <html><body style='font-family:Hanken Grotesk,Arial,sans-serif;background:#f6f7f9;color:#16181d;padding:24px'>
      <h2 style='letter-spacing:-.3px'>◎ Compass — Pre-Market Brief</h2>
      <p style='color:#8a909c;font-size:12px'>{datetime.utcnow().strftime('%A, %B %d %Y — %H:%M UTC')}</p>
      <div style='text-align:center;margin:18px 0;padding:18px;border:1px solid {color};border-radius:12px'>
        <div style='font-size:30px;font-weight:800;color:{color}'>{tone}</div>
        <div style='font-family:monospace;color:#8a909c'>composite {composite:+d}</div>
      </div>
      <p style='line-height:1.55'>{payload.get('read', '')}</p>
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
    tone = "Risk-On" if composite > 15 else "Risk-Off" if composite < -15 else "Mixed"
    send_html_email(
        to_email=DAILY_DIGEST_EMAIL,
        subject=f"◎ Compass Brief — {tone} — {datetime.utcnow().strftime('%b %d')}",
        html_body=build_compass_html(payload),
        sender_name="Compass Agent",
    )


def email_preview() -> str:
    db = SessionLocal()
    rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key="compass").first()
    db.close()
    if not rec:
        return "<p>No Compass data yet — run an analysis first.</p>"
    return build_compass_html(json.loads(rec.value))


async def compass_job():
    orchestrator.update_agent_status(AGENT_ID, "running")
    try:
        sectors = fetch_sectors()
        futures = fetch_futures()
        levels = fetch_levels()
        headlines = await fetch_headlines()
        headlines = await llm_headline_sentiment(headlines)

        composite = int(round(sum(s["bias"] for s in sectors) / len(sectors))) if sectors else 0
        read = await llm_read(sectors, futures, headlines)

        payload = {
            "sectors": sectors,
            "news": headlines,
            "futures": futures,
            "levels": levels,
            "composite": composite,
            "read": read,
            "brief": {"scheduled": "07:00"},
            "fetched_at": datetime.utcnow().isoformat(),
        }
        save_to_db(payload)
        send_compass_email(payload)

        orchestrator.update_agent_status(AGENT_ID, "idle")
        print(f"[Compass] Done — composite {composite:+d}, {len(levels)} levels, {len(sectors)} sectors")
    except Exception as e:
        orchestrator.update_agent_status(AGENT_ID, "error", str(e))
        print(f"[Compass] Error: {e}")


# Backwards-compatible alias (older imports / scheduler ids)
market_direction_job = compass_job
