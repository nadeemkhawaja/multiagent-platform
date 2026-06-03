import os
import json
from datetime import datetime
import yfinance as yf

from database import SessionLocal, AgentData
from llm_client import generate_completion
from orchestrator import orchestrator
from email_utils import send_html_email

DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")

# Watchlist of 20+ stocks
WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "NFLX",
    "JPM", "V", "WMT", "JNJ", "PG", "MA", "HD", "UNH", "DIS", "BAC", "PYPL", "ADBE"
]

METALS = ["GC=F", "SI=F"]  # Gold, Silver
CURRENCIES = ["EURUSD=X", "GBPUSD=X", "JPY=X"]


async def fetch_market_data():
    all_symbols = WATCHLIST + METALS + CURRENCIES
    tickers = yf.Tickers(" ".join(all_symbols))

    data = []
    for sym in all_symbols:
        try:
            ticker = tickers.tickers[sym]
            info = ticker.fast_info

            last_price = info.last_price
            prev_close = info.previous_close
            change = last_price - prev_close
            change_pct = (change / prev_close) * 100 if prev_close else 0

            # Fetch 5-day historical data for sparkline/context
            hist = ticker.history(period="5d")
            history_prices = hist['Close'].tolist() if not hist.empty else []

            data.append({
                "symbol": sym,
                "price": round(last_price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "history": [round(p, 2) for p in history_prices[-5:]]
            })
        except Exception as e:
            print(f"[WallstreetWolf] Failed to fetch data for {sym}: {e}")

    return data


def send_market_email(top_gainers, top_losers, metals, currencies, commentary):
    """Sends the daily market brief HTML email."""
    if not DAILY_DIGEST_EMAIL:
        return

    html_content = f"""
    <html>
      <head>
        <style>
          body {{ font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }}
          .container {{ max-width: 600px; margin: 0 auto; }}
          h1 {{ color: #60a5fa; }}
          h2 {{ color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
          .stock-row {{ display: flex; justify-content: space-between; padding: 8px 12px; background: #1e293b; border-radius: 6px; margin-bottom: 4px; }}
          .up {{ color: #10b981; }}
          .down {{ color: #ef4444; }}
          .commentary {{ background: #1e293b; border-left: 3px solid #3b82f6; padding: 16px; border-radius: 8px; margin: 16px 0; font-style: italic; }}
        </style>
      </head>
      <body>
        <div class="container">
          <h1>📈 Wallstreet Wolf Daily Brief</h1>
          <p style="color:#94a3b8;">{datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}</p>

          <div class="commentary">{commentary}</div>

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

    send_html_email(DAILY_DIGEST_EMAIL, "Wallstreet Wolf Daily Market Brief", html_content)


async def wallstreet_wolf_job():
    orchestrator.update_agent_status("wallstreet_wolf", "running")
    try:
        market_data = await fetch_market_data()

        # Separate stocks, metals, currencies
        stocks_only = [d for d in market_data if d["symbol"] in WATCHLIST]
        stocks_only.sort(key=lambda x: x["change_pct"], reverse=True)

        top_gainers = stocks_only[:5]
        top_losers = stocks_only[-5:]

        metals = [d for d in market_data if d["symbol"] in [m for m in METALS]]
        currencies = [d for d in market_data if d["symbol"] in [c for c in CURRENCIES]]

        # Generate LLM Commentary
        prompt = (
            f"Write a concise 3-sentence daily market commentary. "
            f"Top gainers today: {', '.join([f'{s[\"symbol\"]} (+{s[\"change_pct\"]}%)' for s in top_gainers])}. "
            f"Top losers: {', '.join([f'{s[\"symbol\"]} ({s[\"change_pct\"]}%)' for s in top_losers])}. "
            f"Gold: ${metals[0]['price'] if metals else 'N/A'}, Silver: ${metals[1]['price'] if len(metals) > 1 else 'N/A'}."
        )
        commentary = await generate_completion(
            prompt,
            system_prompt="You are a Wall Street financial analyst writing a brief daily market note."
        )

        payload = {
            "watchlist": stocks_only,
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
        send_market_email(top_gainers, top_losers, metals, currencies, commentary)

        orchestrator.update_agent_status("wallstreet_wolf", "idle")
    except Exception as e:
        orchestrator.update_agent_status("wallstreet_wolf", "error", str(e))
