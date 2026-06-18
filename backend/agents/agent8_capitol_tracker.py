"""
Agent-8: Capitol Tracker — Congressional Stock Trade Monitor
============================================================
Fetches public STOCK Act disclosures from House and Senate stock-watcher APIs.
Filters for a configurable list of key politicians (default: Pelosi, Trump family,
Romney, Crenshaw, etc.) within a configurable lookback window (default: 2 months).
The LLM adds brief commentary on notable patterns or conflicts of interest.

Data sources (public, no auth required):
  House : https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json
  Senate: https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json

Stored in SQLite under agent_name="capitol_tracker", key="tracker".
Scheduled: daily 07:00.
"""

import os
import ast
import json
import asyncio
from collections import Counter
from datetime import datetime, timedelta, date
from typing import Optional

import httpx

from database import SessionLocal, AgentData, get_config
from llm_client import generate_json
from orchestrator import orchestrator
from email_utils import send_html_email, bullets_to_html

AGENT_ID = "capitol_tracker"
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")

# Default politicians to track (name fragments, case-insensitive)
# Based on top congressional traders by volume + notable profiles
DEFAULT_POLITICIANS = [
    "Pelosi",
    "Trump",
    "McCormick",
    "Issa",
    "Shreve",
    "Gottheimer",
    "Khanna",
    "McCaul",
    "Blumenthal",
    "Cisneros",
    "Fields",
    "Romney",
    "Tuberville",
    "Crenshaw",
    "Moore",
    "Cruz",
    "McClain",
    "Boozman",
    "Suozzi",
    "Greene",
    "Ricketts",
    "Walberg",
    "Doggett",
    "Lee",
]

# Curated seed trades from OGE/STOCK Act filings (used as fallback if APIs are unavailable)
SEED_TRADES = [
    {
        "chamber": "Executive", "politician": "Donald Trump",
        "ticker": "NVDA", "asset": "NVIDIA Corporation",
        "type": "Purchase", "amount": "$500K+",
        "transaction_date": "2026-01-06", "disclosure_date": "2026-02-20",
        "district": "", "estimated_avg_price": "$188.87",
        "open_price": "$190.49", "close_price": "$187.24",
        "holder": "Financial Advisors",
    },
    {
        "chamber": "Executive", "politician": "Donald Trump",
        "ticker": "NVDA", "asset": "NVIDIA Corporation",
        "type": "Purchase", "amount": "$1M–$5M",
        "transaction_date": "2026-02-10", "disclosure_date": "2026-03-27",
        "district": "", "estimated_avg_price": "$190.03",
        "open_price": "$191.39", "close_price": "$188.66",
        "holder": "Financial Advisors",
    },
    {
        "chamber": "Executive", "politician": "Donald Trump",
        "ticker": "BA", "asset": "Boeing Company",
        "type": "Purchase", "amount": "$1M–$5M",
        "transaction_date": "2026-02-10", "disclosure_date": "2026-03-27",
        "district": "", "estimated_avg_price": "$243.73",
        "open_price": "$244.92", "close_price": "$242.53",
        "holder": "Financial Advisors",
    },
    {
        "chamber": "House", "politician": "Nancy Pelosi",
        "ticker": "AAPL", "asset": "Apple Inc. (Call Options)",
        "type": "Purchase (Calls)", "amount": "$250K–$500K",
        "transaction_date": "2025-12-30", "disclosure_date": "2026-01-30",
        "district": "CA-11", "estimated_avg_price": "$272.95",
        "open_price": "$272.81", "close_price": "$273.08",
        "holder": "Paul Pelosi (Spouse)",
    },
    {
        "chamber": "House", "politician": "Nancy Pelosi",
        "ticker": "NVDA", "asset": "NVIDIA Corporation (Options Exercised)",
        "type": "Exercise", "amount": "$250K–$500K",
        "transaction_date": "2026-01-16", "disclosure_date": "2026-02-20",
        "district": "CA-11", "estimated_avg_price": "$187.64",
        "open_price": "$189.05", "close_price": "$186.23",
        "holder": "Paul Pelosi (Spouse)",
    },
    {
        "chamber": "House", "politician": "Nancy Pelosi",
        "ticker": "GOOGL", "asset": "Alphabet Inc. (Options Exercised)",
        "type": "Exercise", "amount": "$500K–$1M",
        "transaction_date": "2026-01-16", "disclosure_date": "2026-02-20",
        "district": "CA-11", "estimated_avg_price": "$332.19",
        "open_price": "$334.37", "close_price": "$330.00",
        "holder": "Paul Pelosi (Spouse)",
    },
    {
        "chamber": "House", "politician": "Nancy Pelosi",
        "ticker": "AMZN", "asset": "Amazon.com Inc. (Options Exercised)",
        "type": "Exercise", "amount": "$500K–$1M",
        "transaction_date": "2026-01-16", "disclosure_date": "2026-02-20",
        "district": "CA-11", "estimated_avg_price": "$239.08",
        "open_price": "$239.04", "close_price": "$239.12",
        "holder": "Paul Pelosi (Spouse)",
    },
    {
        "chamber": "House", "politician": "Nancy Pelosi",
        "ticker": "AB", "asset": "AllianceBernstein (Shares)",
        "type": "Purchase", "amount": "$1M–$5M",
        "transaction_date": "2026-01-16", "disclosure_date": "2026-02-20",
        "district": "CA-11", "estimated_avg_price": "$38.84",
        "open_price": "$39.52", "close_price": "$38.16",
        "holder": "Paul Pelosi (Spouse)",
    },
    {
        "chamber": "House", "politician": "Nancy Pelosi",
        "ticker": "NVDA", "asset": "NVIDIA Corporation (Call Options)",
        "type": "Purchase (Calls)", "amount": "$250K–$500K",
        "transaction_date": "2026-01-16", "disclosure_date": "2026-02-20",
        "district": "CA-11", "estimated_avg_price": "$189.21",
        "open_price": "$189.05", "close_price": "$189.37",
        "holder": "Paul Pelosi (Spouse)",
    },
    {
        "chamber": "House", "politician": "Nancy Pelosi",
        "ticker": "VST", "asset": "Vistra Corp",
        "type": "Purchase", "amount": "$100K–$250K",
        "transaction_date": "2026-01-16", "disclosure_date": "2026-02-20",
        "district": "CA-11", "estimated_avg_price": "$161.67",
        "open_price": "", "close_price": "$161.67",
        "holder": "Paul Pelosi (Spouse)",
    },
    {
        "chamber": "House", "politician": "Nancy Pelosi",
        "ticker": "TEM", "asset": "Tempus AI",
        "type": "Purchase", "amount": "$50K–$100K",
        "transaction_date": "2026-01-16", "disclosure_date": "2026-02-20",
        "district": "CA-11", "estimated_avg_price": "$64.72",
        "open_price": "", "close_price": "$64.72",
        "holder": "Paul Pelosi (Spouse)",
    },
    {
        "chamber": "House", "politician": "Nancy Pelosi",
        "ticker": "AAPL", "asset": "Apple Inc. (Call Options)",
        "type": "Purchase (Calls)", "amount": "$250K–$500K",
        "transaction_date": "2025-12-30", "disclosure_date": "2026-01-30",
        "district": "CA-11", "estimated_avg_price": "$272.36",
        "open_price": "$272.81", "close_price": "$271.91",
        "holder": "Paul Pelosi (Spouse)",
    },
    {
        "chamber": "House", "politician": "Nancy Pelosi",
        "ticker": "AAPL", "asset": "Apple Inc. (Shares — Sale)",
        "type": "Sale", "amount": "$5M–$25M",
        "transaction_date": "2025-12-30", "disclosure_date": "2026-01-30",
        "district": "CA-11", "estimated_avg_price": "$272.36",
        "open_price": "$272.81", "close_price": "$271.91",
        "holder": "Paul Pelosi (Spouse)",
    },
    # Tim Moore
    {
        "chamber": "House", "politician": "Tim Moore",
        "ticker": "T", "asset": "AT&T Inc.",
        "type": "Purchase", "amount": "$15K–$50K",
        "transaction_date": "2026-05-18", "disclosure_date": "2026-06-01",
        "district": "NC", "estimated_avg_price": "$24.43",
        "open_price": "", "close_price": "$24.43", "holder": "",
    },
    {
        "chamber": "House", "politician": "Tim Moore",
        "ticker": "IHG", "asset": "Intercontinental Hotels",
        "type": "Purchase", "amount": "$1K–$15K",
        "transaction_date": "2026-05-07", "disclosure_date": "2026-05-22",
        "district": "NC", "estimated_avg_price": "$146.95",
        "open_price": "", "close_price": "$146.95", "holder": "",
    },
    {
        "chamber": "House", "politician": "Tim Moore",
        "ticker": "RYCEY", "asset": "Rolls-Royce Holdings",
        "type": "Purchase", "amount": "$1K–$15K",
        "transaction_date": "2026-05-07", "disclosure_date": "2026-05-22",
        "district": "NC", "estimated_avg_price": "$16.95",
        "open_price": "", "close_price": "$16.95", "holder": "",
    },
    # Lisa McClain
    {
        "chamber": "House", "politician": "Lisa McClain",
        "ticker": "BBAI", "asset": "BigBear.ai Holdings",
        "type": "Purchase", "amount": "$15K–$50K",
        "transaction_date": "2026-02-06", "disclosure_date": "2026-02-21",
        "district": "MI", "estimated_avg_price": "$4.72",
        "open_price": "", "close_price": "$4.72", "holder": "",
    },
    {
        "chamber": "House", "politician": "Lisa McClain",
        "ticker": "—", "asset": "Apptronik Inc. (Private Equity)",
        "type": "Purchase", "amount": "$50K–$100K",
        "transaction_date": "2026-01-12", "disclosure_date": "2026-01-27",
        "district": "MI", "estimated_avg_price": "N/A (Private)",
        "open_price": "", "close_price": "", "holder": "",
    },
    {
        "chamber": "House", "politician": "Lisa McClain",
        "ticker": "—", "asset": "xAI (Private Placement)",
        "type": "Purchase", "amount": "$100K–$250K",
        "transaction_date": "2025-12-15", "disclosure_date": "2026-01-29",
        "district": "MI", "estimated_avg_price": "N/A (Private)",
        "open_price": "", "close_price": "", "holder": "",
    },
    # Josh Gottheimer
    {
        "chamber": "House", "politician": "Josh Gottheimer",
        "ticker": "MSFT", "asset": "Microsoft Corp (Call Options)",
        "type": "Purchase (Calls)", "amount": "$500K–$1M",
        "transaction_date": "2026-05-19", "disclosure_date": "2026-06-03",
        "district": "NJ-05", "estimated_avg_price": "",
        "open_price": "", "close_price": "Market Close", "holder": "",
    },
    {
        "chamber": "House", "politician": "Josh Gottheimer",
        "ticker": "AMD", "asset": "Advanced Micro Devices",
        "type": "Purchase", "amount": "$1K–$15K",
        "transaction_date": "2026-05-05", "disclosure_date": "2026-05-20",
        "district": "NJ-05", "estimated_avg_price": "",
        "open_price": "", "close_price": "Market Close", "holder": "",
    },
    # Cleo Fields
    {
        "chamber": "House", "politician": "Cleo Fields",
        "ticker": "AAPL", "asset": "Apple Inc.",
        "type": "Purchase", "amount": "$1K–$15K",
        "transaction_date": "2026-05-14", "disclosure_date": "2026-05-29",
        "district": "LA", "estimated_avg_price": "",
        "open_price": "", "close_price": "Market Close", "holder": "",
    },
    # John Boozman (Senate)
    {
        "chamber": "Senate", "politician": "John Boozman",
        "ticker": "CAT", "asset": "Caterpillar Inc.",
        "type": "Purchase", "amount": "$1K–$15K",
        "transaction_date": "2026-01-29", "disclosure_date": "2026-02-13",
        "district": "AR", "estimated_avg_price": "",
        "open_price": "", "close_price": "Market Close", "holder": "",
    },
    {
        "chamber": "Senate", "politician": "John Boozman",
        "ticker": "PYPL", "asset": "PayPal Holdings",
        "type": "Purchase", "amount": "$1K–$15K",
        "transaction_date": "2026-01-29", "disclosure_date": "2026-02-13",
        "district": "AR", "estimated_avg_price": "",
        "open_price": "", "close_price": "Market Close", "holder": "",
    },
]

# 2025 Calendar Year Performance Rankings
PERFORMANCE_RANKINGS = [
    {"name": "Rep. Tim Moore", "chamber": "House", "party": "R", "return_pct": 52.0, "driver": "Small-cap micro-caps & cyclical timing"},
    {"name": "Sen. Ted Cruz", "chamber": "Senate", "party": "R", "return_pct": 50.0, "driver": "Equity holdings (Goldman Sachs liquidation)"},
    {"name": "Rep. Lisa McClain", "chamber": "House", "party": "R", "return_pct": 37.0, "driver": "Technology & early private equity exposure"},
    {"name": "Rep. Pete Ricketts", "chamber": "House", "party": "R", "return_pct": 37.0, "driver": "Industrial, agricultural, and enterprise"},
    {"name": "Rep. Thomas Suozzi", "chamber": "House", "party": "D", "return_pct": 35.0, "driver": "Financial services & precision equity swings"},
    {"name": "Rep. Marjorie Taylor Greene", "chamber": "House", "party": "R", "return_pct": 33.0, "driver": "Defense contractors & tech basket"},
    {"name": "Rep. Nancy Pelosi", "chamber": "House", "party": "D", "return_pct": 18.0, "driver": "Leveraged Tech LEAPs (NVIDIA, Apple)"},
    {"name": "S&P 500 Index", "chamber": "Benchmark", "party": "Index", "return_pct": 16.6, "driver": "Market benchmark"},
]

DEFAULT_LOOKBACK_MONTHS = 2

HOUSE_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"

UA = {"User-Agent": "Mozilla/5.0 (CapitolTrackerAgent/1.0; educational use)"}


def _parse_date(d_str: str) -> Optional[date]:
    """Try multiple date formats used by the stock watcher APIs."""
    if not d_str:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(d_str.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _normalize_amount(raw: str) -> str:
    """Convert amount range codes to readable strings."""
    mapping = {
        "$1,001 - $15,000": "$1K–$15K",
        "$15,001 - $50,000": "$15K–$50K",
        "$50,001 - $100,000": "$50K–$100K",
        "$100,001 - $250,000": "$100K–$250K",
        "$250,001 - $500,000": "$250K–$500K",
        "$500,001 - $1,000,000": "$500K–$1M",
        "$1,000,001 - $5,000,000": "$1M–$5M",
        "$5,000,001 - $25,000,000": "$5M–$25M",
        "$25,000,001 - $50,000,000": "$25M–$50M",
    }
    return mapping.get(raw, raw or "—")


async def fetch_house() -> list:
    try:
        async with httpx.AsyncClient(timeout=20, headers=UA) as c:
            r = await c.get(HOUSE_URL)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        print(f"[Capitol] House fetch error: {e}")
    return []


async def fetch_senate() -> list:
    try:
        async with httpx.AsyncClient(timeout=20, headers=UA) as c:
            r = await c.get(SENATE_URL)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        print(f"[Capitol] Senate fetch error: {e}")
    return []


def _filter_house(raw: list, names: list[str], since: date) -> list:
    out = []
    for t in raw:
        rep = t.get("representative", "") or ""
        tdate = _parse_date(t.get("transaction_date", ""))
        if not tdate or tdate < since:
            continue
        if not any(n.lower() in rep.lower() for n in names):
            continue
        out.append({
            "chamber": "House",
            "politician": rep.strip(),
            "ticker": (t.get("ticker", "") or "").strip(),
            "asset": (t.get("asset_description", "") or t.get("ticker", "")).strip(),
            "type": (t.get("type", "") or "").strip(),
            "amount": _normalize_amount(t.get("amount", "") or ""),
            "transaction_date": tdate.isoformat(),
            "disclosure_date": (t.get("disclosure_date", "") or ""),
            "district": (t.get("district", "") or "").strip(),
        })
    return out


def _filter_senate(raw: list, names: list[str], since: date) -> list:
    out = []
    for t in raw:
        senator = t.get("senator", "") or ""
        tdate = _parse_date(t.get("transaction_date", "") or t.get("date", ""))
        if not tdate or tdate < since:
            continue
        if not any(n.lower() in senator.lower() for n in names):
            continue
        out.append({
            "chamber": "Senate",
            "politician": senator.strip(),
            "ticker": (t.get("ticker", "") or "").strip(),
            "asset": (t.get("asset_description", "") or t.get("ticker", "")).strip(),
            "type": (t.get("type", "") or "").strip(),
            "amount": _normalize_amount(t.get("amount", "") or ""),
            "transaction_date": tdate.isoformat(),
            "disclosure_date": (t.get("disclosure_date", "") or ""),
            "district": (t.get("state", "") or "").strip(),
        })
    return out


def _coerce_bullets(val) -> str:
    """Normalize whatever the LLM returns into clean '• ...'-per-line bullets.

    The model sometimes hands back a JSON *array* for the commentary instead of a
    string, which then gets stringified to "['a', 'b']" and rendered literally —
    brackets, quotes and all. This collapses lists, stringified lists, and plain
    multi-line text into one consistent bulleted format for both app and email."""
    # Already a list/tuple of bullets.
    if isinstance(val, (list, tuple)):
        items = [str(x).strip().lstrip("•-* ").strip() for x in val]
        return "\n".join(f"• {x}" for x in items if x)
    s = str(val or "").strip()
    if not s:
        return ""
    # Stringified list, e.g. "['a', 'b']".
    if s[0] in "[(" and s[-1] in ")]":
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)):
                return _coerce_bullets(parsed)
        except (ValueError, SyntaxError):
            pass
    # Plain multi-line text — re-emit each non-empty line as a bullet.
    lines = [ln.strip().lstrip("•-* ").strip() for ln in s.replace("•", "\n").splitlines()]
    return "\n".join(f"• {ln}" for ln in lines if ln)


async def build_llm_commentary(trades: list) -> str:
    if not trades:
        return "No trades found for the tracked politicians in the selected time window."
    top = trades[:12]
    summary = "\n".join(
        f"- {t['politician']} ({t['chamber']}): {t['type']} {t['ticker'] or t['asset']} {t['amount']} on {t['transaction_date']}"
        for t in top
    )
    prompt = f"""You are a political finance analyst. Review these congressional stock trades and write
exactly 3-4 short bullet points on notable patterns, possible conflicts of interest, or anything
investors should note. Each bullet max 12 words, factual and crisp — no paragraphs, no intro/outro.

Recent trades:
{summary}

Return ONLY a JSON object: {{"commentary": ["<bullet 1>", "<bullet 2>", "<bullet 3>"]}}
where commentary is an ARRAY of short bullet strings."""
    try:
        data = await generate_json(
            prompt,
            system_prompt="You are a political finance analyst. Return only valid JSON.",
            agent_id=AGENT_ID,
            use_cache=True,
        )
        if isinstance(data, dict):
            return _coerce_bullets(data.get("commentary", ""))
        if isinstance(data, list):
            return _coerce_bullets(data)
        return ""
    except Exception as e:
        print(f"[Capitol] LLM error: {e}")
        return ""


def _load():
    db = SessionLocal()
    try:
        rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key="tracker").first()
        return json.loads(rec.value) if rec else None
    finally:
        db.close()


def _save(payload):
    db = SessionLocal()
    try:
        rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key="tracker").first()
        if rec:
            rec.value = json.dumps(payload)
            rec.updated_at = datetime.utcnow()
        else:
            db.add(AgentData(agent_name=AGENT_ID, key="tracker", value=json.dumps(payload)))
        db.commit()
    finally:
        db.close()


def _stats(trades: list) -> dict:
    purchases = sum(1 for t in trades if "purchase" in t.get("type", "").lower() or "buy" in t.get("type", "").lower())
    sales = sum(1 for t in trades if "sale" in t.get("type", "").lower() or "sell" in t.get("type", "").lower())
    pols = list(dict.fromkeys(t["politician"] for t in trades))
    ticker_counts = Counter(t["ticker"] for t in trades if t.get("ticker"))
    top_tickers = [{"ticker": tk, "count": n} for tk, n in ticker_counts.most_common(5)]
    return {
        "total": len(trades),
        "purchases": purchases,
        "sales": sales,
        "net_activity": purchases - sales,
        "politicians_found": len(pols),
        "politicians_list": pols[:10],
        "top_tickers": top_tickers,
    }


def build_digest_html(payload: dict) -> str:
    trades = payload.get("trades", [])
    stats = payload.get("stats", {})
    commentary = payload.get("commentary", "")
    fetched = payload.get("fetched_at", "")
    politicians = payload.get("politicians", [])
    months = payload.get("months", 2)

    rows = "".join(
        f"<tr style='border-bottom:1px solid #e5e7eb'>"
        f"<td style='padding:8px 12px;font-weight:600'>{t['politician']}</td>"
        f"<td style='padding:8px 12px;color:#6b7280'>{t['chamber']}</td>"
        f"<td style='padding:8px 12px;font-family:monospace;font-weight:700'>{t['ticker'] or '—'}</td>"
        f"<td style='padding:8px 12px'>{t['asset'][:40]}</td>"
        f"<td style='padding:8px 12px;color:{'#16a34a' if 'purchase' in t['type'].lower() or 'buy' in t['type'].lower() else '#dc2626'}'>{t['type']}</td>"
        f"<td style='padding:8px 12px;font-family:monospace'>{t['amount']}</td>"
        f"<td style='padding:8px 12px;color:#6b7280;font-size:12px'>{t['transaction_date']}</td>"
        f"</tr>"
        for t in trades[:20]
    )
    return f"""
    <html><body style='font-family:Arial,sans-serif;background:#f9fafb;color:#111827;padding:24px;max-width:900px;margin:auto'>
      <h2 style='color:#dc2626'>🏛 Capitol Tracker — Congressional Stock Trades</h2>
      <p style='color:#6b7280;font-size:12px'>Tracking: {', '.join(politicians)} · Last {months} months · {fetched[:19]} UTC</p>
      <p><b>{stats.get('total',0)}</b> trades found — <b style='color:#16a34a'>{stats.get('purchases',0)} purchases</b> · <b style='color:#dc2626'>{stats.get('sales',0)} sales</b> · net {stats.get('net_activity',0):+d} · {stats.get('politicians_found',0)} politicians</p>
      {f'<p style="color:#6b7280;font-size:12px">Most-traded tickers: ' + ', '.join(f"{tt['ticker']} ({tt['count']})" for tt in stats.get('top_tickers', [])) + '</p>' if stats.get('top_tickers') else ''}
      {f'<div style="background:#fef3c7;padding:12px 14px;border-radius:8px;margin:8px 0">{bullets_to_html(commentary, color="#713f12")}</div>' if commentary else ''}
      <table style='width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden'>
        <thead><tr style='background:#f3f4f6'>
          <th style='padding:10px 12px;text-align:left'>Politician</th>
          <th style='padding:10px 12px;text-align:left'>Chamber</th>
          <th style='padding:10px 12px;text-align:left'>Ticker</th>
          <th style='padding:10px 12px;text-align:left'>Asset</th>
          <th style='padding:10px 12px;text-align:left'>Type</th>
          <th style='padding:10px 12px;text-align:left'>Amount</th>
          <th style='padding:10px 12px;text-align:left'>Date</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p style='color:#9ca3af;font-size:11px;margin-top:16px'>Source: housestockwatcher.com / senatestockwatcher.com · STOCK Act public disclosures</p>
    </body></html>
    """


def email_preview() -> str:
    payload = _load()
    if not payload:
        return "<p>No Capitol Tracker data yet — run the agent first.</p>"
    return build_digest_html(payload)


async def capitol_tracker_job(politicians_override: list = None, months_override: int = None):
    orchestrator.update_agent_status(AGENT_ID, "running")
    try:
        # Load config
        raw_pols = politicians_override or get_config("capitol_politicians", "")
        if raw_pols and isinstance(raw_pols, str):
            politicians = [p.strip() for p in raw_pols.split(",") if p.strip()]
        elif isinstance(raw_pols, list):
            politicians = raw_pols
        else:
            politicians = DEFAULT_POLITICIANS

        months_raw = months_override or get_config("capitol_months", DEFAULT_LOOKBACK_MONTHS)
        try:
            months = int(months_raw)
        except (TypeError, ValueError):
            months = DEFAULT_LOOKBACK_MONTHS

        since = (datetime.utcnow() - timedelta(days=months * 30)).date()

        orchestrator.log_event(f"Capitol Tracker: fetching disclosures since {since.isoformat()}", "#dc2626")

        # Fetch both chambers concurrently
        house_raw, senate_raw = await asyncio.gather(fetch_house(), fetch_senate())

        house_trades = _filter_house(house_raw, politicians, since)
        senate_trades = _filter_senate(senate_raw, politicians, since)

        api_trades = house_trades + senate_trades

        # Merge with seed trades (curated OGE filings); deduplicate by key
        def _trade_key(t):
            return f"{t['politician']}|{t['ticker']}|{t['transaction_date']}"

        api_keys = {_trade_key(t) for t in api_trades}
        # Filter seed trades to those within the lookback window and matching politicians
        seed_in_window = [
            t for t in SEED_TRADES
            if _parse_date(t["transaction_date"]) and _parse_date(t["transaction_date"]) >= since
            and any(n.lower() in t["politician"].lower() for n in politicians)
            and _trade_key(t) not in api_keys
        ]

        all_trades = sorted(
            api_trades + seed_in_window,
            key=lambda t: t["transaction_date"],
            reverse=True,
        )

        commentary = await build_llm_commentary(all_trades)
        stats = _stats(all_trades)

        payload = {
            "politicians": politicians,
            "months": months,
            "since": since.isoformat(),
            "trades": all_trades,
            "stats": stats,
            "commentary": commentary,
            "performance_rankings": PERFORMANCE_RANKINGS,
            "sp500_2025": 16.6,
            "fetched_at": datetime.utcnow().isoformat(),
        }
        _save(payload)

        # Send daily email
        if DAILY_DIGEST_EMAIL and all_trades:
            send_html_email(
                to_email=DAILY_DIGEST_EMAIL,
                subject=f"🏛 Capitol Tracker — {stats['total']} trades · {datetime.utcnow().strftime('%b %d')}",
                html_body=build_digest_html(payload),
                sender_name="Capitol Tracker",
            )

        orchestrator.update_agent_status(AGENT_ID, "idle")
        orchestrator.log_event(f"Capitol Tracker: {stats['total']} trades found for {stats['politicians_found']} politicians", "#dc2626")
        print(f"[Capitol] Done — {stats['total']} trades, {stats['politicians_found']} politicians found")

    except Exception as e:
        orchestrator.update_agent_status(AGENT_ID, "error", str(e))
        print(f"[Capitol] Error: {e}")
