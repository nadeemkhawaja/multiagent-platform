import os
import json
import asyncio
from datetime import datetime
import yfinance as yf

from database import SessionLocal, AgentData, get_config
from llm_client import generate_completion
from orchestrator import orchestrator
from email_utils import send_html_email

DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")

# Watchlist of 20 user-curated stocks — mega-cap tech, semiconductors/AI infra,
# and crypto-adjacent names. User can override via Settings → watchlist (needs 20+).
DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NFLX",       # mega-cap tech
    "NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU", "SMCI", "CSCO",   # chips & AI infra
    "DELL", "BABA", "PLTR", "GBTC", "COIN",                        # hardware, China tech, crypto
]

# Broad-market index futures — the headline risk gauges traders watch first.
FUTURES = {"ES=F": ("/ES", "S&P 500 E-mini"), "NQ=F": ("/NQ", "Nasdaq-100 E-mini")}
METALS = ["GC=F", "SI=F"]  # Gold, Silver
CURRENCIES = ["EURUSD=X", "GBPUSD=X", "JPY=X"]


def get_watchlist():
    raw = get_config("watchlist", "")
    syms = [s.strip().upper() for s in str(raw).replace("\n", ",").split(",") if s.strip()]
    return syms if len(syms) >= 20 else DEFAULT_WATCHLIST


def _fetch_market_data_sync():
    """Synchronous yfinance fetch — called via asyncio.to_thread to avoid blocking the event loop."""
    WATCHLIST = get_watchlist()
    all_symbols = WATCHLIST + list(FUTURES.keys()) + METALS + CURRENCIES
    tickers = yf.Tickers(" ".join(all_symbols))

    data = []
    for sym in all_symbols:
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
                    print(f"[WallstreetWolf] No data available for {sym}, skipping")
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
            print(f"[WallstreetWolf] Failed to fetch data for {sym}: {e}")

    return data


async def fetch_market_data():
    return await asyncio.to_thread(_fetch_market_data_sync)


def _fmt_future(s):
    label, name = FUTURES.get(s["symbol"], (s["symbol"], ""))
    cls = "up" if s["change_pct"] >= 0 else "down"
    sign = "+" if s["change_pct"] >= 0 else ""
    return (f'<div class="stock-row"><span><b>{label}</b> {name}</span>'
            f'<span>{s["price"]:,}</span>'
            f'<span class="{cls}">{sign}{s["change_pct"]}%</span></div>')


def build_market_html(top_gainers, top_losers, metals, currencies, commentary, futures=None):
    futures = futures or []
    html_content = f"""
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
          .commentary {{ background: #eff6ff; border-left: 3px solid #2563eb; padding: 16px; border-radius: 8px; margin: 16px 0; font-style: italic; }}
        </style>
      </head>
      <body>
        <div class="container">
          <h1>📈 Wallstreet Wolf Daily Brief</h1>
          <p style="color:#64748b;">{datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}</p>

          <div class="commentary">{commentary}</div>

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
    return html_content


def send_market_email(top_gainers, top_losers, metals, currencies, commentary, futures=None):
    if not DAILY_DIGEST_EMAIL:
        return
    html = build_market_html(top_gainers, top_losers, metals, currencies, commentary, futures)
    send_html_email(DAILY_DIGEST_EMAIL, "Wallstreet Wolf Daily Market Brief", html, sender_name="Wallstreet Wolf Agent")


def email_preview() -> str:
    db = SessionLocal()
    rec = db.query(AgentData).filter_by(agent_name="wallstreet_wolf", key="market_data").first()
    db.close()
    if not rec:
        return "<p>No market data yet — run Wallstreet Wolf first.</p>"
    p = json.loads(rec.value)
    return build_market_html(p.get("top_gainers", []), p.get("top_losers", []),
                             p.get("metals", []), p.get("currencies", []), p.get("commentary", ""),
                             p.get("futures", []))


async def wallstreet_wolf_job():
    orchestrator.update_agent_status("wallstreet_wolf", "running")
    try:
        market_data = await fetch_market_data()

        # Separate stocks, metals, currencies
        watchlist = get_watchlist()
        stocks_only = [d for d in market_data if d["symbol"] in watchlist]
        stocks_only.sort(key=lambda x: x["change_pct"], reverse=True)

        top_gainers = stocks_only[:5]
        top_losers = stocks_only[-5:][::-1]  # worst performer first

        futures = [d for d in market_data if d["symbol"] in FUTURES]
        # keep /ES before /NQ
        futures.sort(key=lambda d: list(FUTURES.keys()).index(d["symbol"]))
        metals = [d for d in market_data if d["symbol"] in [m for m in METALS]]
        currencies = [d for d in market_data if d["symbol"] in [c for c in CURRENCIES]]

        gainer_strs = [f"{s['symbol']} (+{s['change_pct']}%)" for s in top_gainers]
        loser_strs = [f"{s['symbol']} ({s['change_pct']}%)" for s in top_losers]
        futures_strs = [f"{FUTURES[s['symbol']][0]} ({'+' if s['change_pct'] >= 0 else ''}{s['change_pct']}%)" for s in futures]

        # Generate LLM commentary — isolated so a failure doesn't abort the data save
        commentary = ""
        try:
            prompt = (
                f"Write a concise 3-sentence daily market commentary. "
                f"Index futures: {', '.join(futures_strs) or 'N/A'}. "
                f"Top gainers today: {', '.join(gainer_strs)}. "
                f"Top losers: {', '.join(loser_strs)}. "
                f"Gold: ${metals[0]['price'] if metals else 'N/A'}, Silver: ${metals[1]['price'] if len(metals) > 1 else 'N/A'}."
            )
            commentary = await generate_completion(
                prompt,
                system_prompt="You are a Wall Street financial analyst writing a brief daily market note in English (US markets)."
            )
        except Exception as e:
            print(f"[WallstreetWolf] LLM commentary failed: {e}")

        payload = {
            "watchlist": stocks_only,
            "futures": futures,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "metals": metals,
            "currencies": currencies,
            "commentary": commentary
        }

        db = SessionLocal()
        existing = db.query(AgentData).filter_by(agent_name="wallstreet_wolf", key="market_data").first()
        val = json.dumps(payload)

        if existing:
            existing.value = val
        else:
            db.add(AgentData(agent_name="wallstreet_wolf", key="market_data", value=val))
        db.commit()
        db.close()

        # Send real email
        send_market_email(top_gainers, top_losers, metals, currencies, commentary, futures)

        orchestrator.update_agent_status("wallstreet_wolf", "idle")
    except Exception as e:
        orchestrator.update_agent_status("wallstreet_wolf", "error", str(e))
