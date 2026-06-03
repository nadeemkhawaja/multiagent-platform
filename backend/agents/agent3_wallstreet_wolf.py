import yfinance as yf
import json
from database import SessionLocal, AgentData
from llm_client import generate_completion
from orchestrator import orchestrator

# Watchlist of 20+ stocks, ETFs, indices
WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "NFLX",
    "JPM", "V", "WMT", "JNJ", "PG", "MA", "HD", "UNH", "DIS", "BAC", "PYPL", "ADBE"
]

METALS = ["GC=F", "SI=F"] # Gold, Silver
CURRENCIES = ["EURUSD=X", "GBPUSD=X", "JPY=X"]

async def fetch_market_data():
    all_symbols = WATCHLIST + METALS + CURRENCIES
    tickers = yf.Tickers(" ".join(all_symbols))
    
    data = []
    for sym in all_symbols:
        try:
            ticker = tickers.tickers[sym]
            info = ticker.fast_info
            
            # fast_info provides last_price, previous_close
            last_price = info.last_price
            prev_close = info.previous_close
            change = last_price - prev_close
            change_pct = (change / prev_close) * 100 if prev_close else 0
            
            data.append({
                "symbol": sym,
                "price": round(last_price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2)
            })
        except Exception as e:
            print(f"Failed to fetch data for {sym}: {e}")
            
    return data

async def wallstreet_wolf_job():
    orchestrator.update_agent_status("wallstreet_wolf", "running")
    try:
        market_data = await fetch_market_data()
        
        # Filter stocks for top gainers/losers
        stocks_only = [d for d in market_data if d["symbol"] in WATCHLIST]
        stocks_only.sort(key=lambda x: x["change_pct"], reverse=True)
        
        top_gainers = stocks_only[:5]
        top_losers = stocks_only[-5:]
        
        metals = [d for d in market_data if d["symbol"] in METALS]
        currencies = [d for d in market_data if d["symbol"] in CURRENCIES]
        
        # Generate LLM Commentary
        prompt = f"Write a 3-sentence daily market commentary based on these top gainers: {[s['symbol'] for s in top_gainers]} and top losers: {[s['symbol'] for s in top_losers]}."
        commentary = await generate_completion(prompt, system_prompt="You are an expert financial analyst.")
        
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
        
        # Simulate sending email
        print("Would send daily market brief email with HTML content.")
        
        orchestrator.update_agent_status("wallstreet_wolf", "idle")
    except Exception as e:
        orchestrator.update_agent_status("wallstreet_wolf", "error", str(e))
