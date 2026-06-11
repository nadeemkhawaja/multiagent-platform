# ============================================================================
# Agent 10 — Options Flow Tracker
# Monitors unusual options activity on Wolf watchlist tickers
# IV percentile, unusual volume, P/C ratio, large premium blocks
# Built for TOS (Think or Swim) traders
# ============================================================================
import asyncio, datetime, logging, math
from database import save_agent_data, get_agent_data, get_config
from llm_client import generate_completion
from orchestrator import orchestrator
from email_utils import send_html_email

log = logging.getLogger("options_flow")

DEFAULT_WATCHLIST = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN","TSLA","META","AMD","AVGO","ORCL",
    "CRM","NFLX","PLTR","SOFI","COIN","SPY","QQQ","IWM","GLD","SLV",
]

# Signal thresholds
MIN_VOLUME = 100          # minimum contracts for consideration
UNUSUAL_VOL_MULT = 2.5    # volume > X * open_interest = unusual
HIGH_IV_PCT = 70          # IV percentile threshold for "elevated"
LARGE_PREMIUM_K = 100     # $100K+ premium = "large block"

def _get_watchlist() -> list[str]:
    raw = get_config("watchlist", "")
    tickers = [t.strip().upper() for t in raw.replace("\n", ",").split(",") if t.strip()]
    return tickers if len(tickers) >= 5 else DEFAULT_WATCHLIST

def _safe_float(val, default=0.0) -> float:
    try:
        return float(val)
    except Exception:
        return default

def _realized_vol(hist) -> float:
    """Annualized realized volatility from ~2 months of daily close-to-close returns."""
    try:
        closes = hist["Close"].dropna()
        if len(closes) < 5:
            return 0.0
        returns = closes.pct_change().dropna()
        if returns.empty:
            return 0.0
        return float(returns.std() * math.sqrt(252))
    except Exception:
        return 0.0

async def _analyze_ticker(ticker: str) -> dict | None:
    """Run options analysis for one ticker using yfinance."""
    try:
        import yfinance as yf
        loop = asyncio.get_event_loop()

        def _fetch():
            t = yf.Ticker(ticker)
            info = t.info or {}
            exps = t.options
            if not exps:
                return None
            # Use nearest and next-nearest expiry
            target_exps = exps[:min(2, len(exps))]
            all_calls, all_puts = [], []
            for exp in target_exps:
                chain = t.option_chain(exp)
                all_calls.append(chain.calls)
                all_puts.append(chain.puts)

            import pandas as pd
            calls = pd.concat(all_calls, ignore_index=True) if all_calls else pd.DataFrame()
            puts  = pd.concat(all_puts,  ignore_index=True) if all_puts  else pd.DataFrame()

            spot = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
            if spot == 0 and not calls.empty:
                spot = _safe_float(calls.iloc[0].get("lastPrice", 0)) + _safe_float(calls.iloc[0].get("strike", 0))

            def analyze_side(df, side):
                if df.empty:
                    return [], 0, 0.0
                df = df.copy()
                df["vol"]     = df["volume"].fillna(0).astype(float)
                df["oi"]      = df["openInterest"].fillna(1).astype(float).clip(lower=1)
                df["iv"]      = df["impliedVolatility"].fillna(0).astype(float)
                df["premium"] = df["vol"] * df["lastPrice"].fillna(0).astype(float) * 100
                df["vol_oi"]  = df["vol"] / df["oi"]
                unusual = df[(df["vol"] >= MIN_VOLUME) & (df["vol_oi"] >= UNUSUAL_VOL_MULT)]
                top = unusual.nlargest(3, "premium")
                rows = []
                for _, r in top.iterrows():
                    rows.append({
                        "side": side,
                        "strike": float(r.get("strike", 0)),
                        "expiry": str(r.get("contractSymbol", ""))[-8:-2],
                        "vol":    int(r.get("vol", 0)),
                        "oi":     int(r.get("oi", 0)),
                        "iv":     float(r.get("iv", 0)),
                        "premium_k": round(float(r.get("premium", 0)) / 1000, 1),
                        "last":   float(r.get("lastPrice", 0)),
                    })
                total_vol = float(df["vol"].sum())
                avg_iv    = float(df["iv"].mean())
                return rows, total_vol, avg_iv

            call_signals, call_vol, call_iv = analyze_side(calls, "call")
            put_signals,  put_vol,  put_iv  = analyze_side(puts,  "put")

            pc_ratio = put_vol / call_vol if call_vol > 0 else 0
            avg_iv   = (call_iv + put_iv) / 2 if (call_iv + put_iv) > 0 else 0

            # IV rank: compare current avg IV to realized (historical) volatility.
            # avg_iv == realized_vol -> ~50%ile; richer/cheaper IV shifts the rank up/down.
            hist = t.history(period="2mo")
            realized_vol = _realized_vol(hist)
            if realized_vol <= 0:
                # Fallback when history is unavailable: rough 52w-range based estimate.
                week52_hi = _safe_float(info.get("fiftyTwoWeekHigh", 0))
                week52_lo = _safe_float(info.get("fiftyTwoWeekLow",  spot))
                realized_vol = (week52_hi - week52_lo) / max(week52_lo, 1) * 0.4
            iv_pct = min(99, max(1, int((avg_iv / max(realized_vol, 0.01)) * 50)))

            signals = call_signals + put_signals
            signals.sort(key=lambda x: x["premium_k"], reverse=True)

            large_premium = [s for s in signals if s["premium_k"] >= LARGE_PREMIUM_K]
            elevated_iv   = avg_iv >= 0.35 or iv_pct >= HIGH_IV_PCT

            return {
                "ticker":      ticker,
                "spot":        round(spot, 2),
                "call_vol":    int(call_vol),
                "put_vol":     int(put_vol),
                "pc_ratio":    round(pc_ratio, 2),
                "avg_iv":      round(avg_iv * 100, 1),
                "iv_pct":      iv_pct,
                "signals":     signals[:6],
                "large_blocks": large_premium,
                "elevated_iv": elevated_iv,
                "unusual":     len(signals) > 0,
                "type":        "call" if call_vol > put_vol else "put",
            }

        result = await loop.run_in_executor(None, _fetch)
        return result
    except Exception as e:
        log.debug(f"Options analysis failed for {ticker}: {e}")
        return None

async def build_llm_commentary(top_signals: list) -> str:
    if not top_signals:
        return "No unusual options activity detected across the watchlist today."
    lines = []
    for s in top_signals[:5]:
        lines.append(f"{s['ticker']}: IV {s['avg_iv']}% (rank ~{s['iv_pct']}%ile), P/C {s['pc_ratio']:.2f}, {s['call_vol']+s['put_vol']:,} contracts")
    prompt = f"""You are an options trading analyst. Summarize the following unusual options activity for a TOS trader in 3–4 sentences. Note implied volatility levels, put/call ratios, and what the activity might suggest. Be specific and actionable. /no_think

{chr(10).join(lines)}"""
    try:
        return await generate_completion(prompt, agent_id="options_flow")
    except Exception:
        return "Unusual options activity detected. Review the signals below for potential setups."

async def options_flow_job():
    log.info("Options Flow starting")
    orchestrator.update_agent_status("options_flow", "running")
    try:
        watchlist = _get_watchlist()
        log.info(f"Scanning {len(watchlist)} tickers for options flow")

        # Process in batches of 5 to avoid overloading
        results = []
        for i in range(0, len(watchlist), 5):
            batch = watchlist[i:i+5]
            batch_results = await asyncio.gather(*[_analyze_ticker(t) for t in batch], return_exceptions=True)
            for r in batch_results:
                if isinstance(r, dict) and r:
                    results.append(r)
            await asyncio.sleep(1)

        # Rank by unusualness
        unusual = [r for r in results if r.get("unusual")]
        unusual.sort(key=lambda x: (x.get("iv_pct", 0) + x.get("call_vol", 0)/1000), reverse=True)

        # Top 5 for highlight
        top5 = unusual[:5]
        commentary = await build_llm_commentary(top5)

        now = datetime.datetime.now()
        payload = {
            "flow": {
                "signals":    unusual[:20],
                "top5":       top5,
                "commentary": commentary,
                "scanned":    len(results),
                "unusual_count": len(unusual),
                "generated_at": now.strftime("%Y-%m-%d %H:%M"),
                "market_date":  now.strftime("%Y-%m-%d"),
            }
        }
        save_agent_data("options_flow", payload)
        orchestrator.update_agent_status("options_flow", "idle")
        log.info(f"Options Flow complete — {len(unusual)} unusual signals from {len(results)} tickers")
    except Exception as e:
        log.error(f"Options Flow error: {e}", exc_info=True)
        orchestrator.update_agent_status("options_flow", "error", str(e))
        raise

def email_preview() -> dict:
    data = get_agent_data("options_flow") or {}
    flow = data.get("flow", {})
    top5 = flow.get("top5", [])
    commentary = flow.get("commentary", "No data yet.")
    generated_at = flow.get("generated_at", "—")

    rows = ""
    for s in top5:
        iv_color = "#dc2626" if s.get("elevated_iv") else "#16a34a"
        rows += f"""<tr>
          <td style='padding:8px 12px;font-weight:700;font-family:monospace'>{s['ticker']}</td>
          <td style='padding:8px 12px;font-family:monospace'>${s.get('spot',0):.2f}</td>
          <td style='padding:8px 12px;color:{iv_color};font-weight:700'>{s.get('avg_iv',0):.1f}%</td>
          <td style='padding:8px 12px;font-family:monospace'>{s.get('iv_pct',0)}%ile</td>
          <td style='padding:8px 12px;font-family:monospace'>{s.get('pc_ratio',0):.2f}</td>
          <td style='padding:8px 12px;color:{'#7c5cf6' if s.get('type')=='call' else '#dc2626'};font-weight:700'>{s.get('type','').upper()}</td>
        </tr>"""

    html = f"""<!DOCTYPE html><html><body style='font-family:Helvetica,sans-serif;background:#f6f7f9;margin:0;padding:0'>
<div style='max-width:620px;margin:24px auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb'>
  <div style='background:linear-gradient(135deg,#4c1d95,#7c5cf6);padding:24px 32px'>
    <div style='font-size:22px;font-weight:800;color:#fff'>⚡ Options Flow</div>
    <div style='font-size:13px;color:#c4b5fd;margin-top:4px'>{generated_at} · Unusual activity scanner</div>
  </div>
  <div style='padding:20px 32px;background:#f5f3ff;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:14px;line-height:1.6;color:#3730a3'>{commentary}</div>
  </div>
  {'<div style="padding:20px 32px"><table style="width:100%;border-collapse:collapse;font-size:13px"><tr style="background:#f9fafb"><th style="padding:8px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">TICKER</th><th style="padding:8px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">SPOT</th><th style="padding:8px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">IV</th><th style="padding:8px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">IV RANK</th><th style="padding:8px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">P/C</th><th style="padding:8px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">BIAS</th></tr>' + rows + '</table></div>' if rows else '<div style="padding:20px 32px;color:#888">No unusual activity detected today.</div>'}
  <div style='padding:14px 32px;text-align:center;font-size:11px;color:#aeb4bf'>Not financial advice · Educational use only</div>
</div></body></html>"""
    return {"html": html}
