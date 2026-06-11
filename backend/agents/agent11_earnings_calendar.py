# ============================================================================
# Agent 11 — Earnings Calendar
# Upcoming earnings for Wolf watchlist: expected move, IV crush signals,
# days-to-earnings, historical beat/miss — essential for TOS options traders
# ============================================================================
import asyncio, datetime, logging, math
from database import save_agent_data, get_agent_data, get_config
from llm_client import generate_completion
from orchestrator import orchestrator
from email_utils import send_html_email

log = logging.getLogger("earnings_cal")

DEFAULT_WATCHLIST = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN","TSLA","META","AMD","AVGO","ORCL",
    "CRM","NFLX","PLTR","SOFI","COIN","SPY","QQQ","GLD","SLV","INTC",
]

def _get_watchlist() -> list[str]:
    raw = get_config("watchlist", "")
    tickers = [t.strip().upper() for t in raw.replace("\n", ",").split(",") if t.strip()]
    return tickers if len(tickers) >= 5 else DEFAULT_WATCHLIST

def _safe(val, default=None):
    try:
        return val if val is not None and val == val else default
    except Exception:
        return default

def _days_until(date_str: str) -> int | None:
    """Return calendar days until earnings date."""
    try:
        target = datetime.datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        delta  = (target - datetime.date.today()).days
        return delta
    except Exception:
        return None

def _expected_move(spot: float, near_call: float, near_put: float) -> float | None:
    """ATM straddle price as expected move percentage."""
    try:
        straddle = near_call + near_put
        return round((straddle / spot) * 100, 1) if spot > 0 else None
    except Exception:
        return None

async def _analyze_ticker(ticker: str) -> dict | None:
    try:
        import yfinance as yf
        loop = asyncio.get_event_loop()

        def _fetch():
            t = yf.Ticker(ticker)
            info = t.info or {}

            # Earnings date
            earnings_dates = None
            dte = None
            earnings_str = None
            try:
                cal = t.calendar
                if cal is not None and not cal.empty:
                    if "Earnings Date" in cal.index:
                        raw = cal.loc["Earnings Date"]
                        earnings_dates = str(raw.iloc[0])[:10] if hasattr(raw, "iloc") else str(raw)[:10]
                        dte = _days_until(earnings_dates)
                        earnings_str = earnings_dates
            except Exception:
                pass

            # Skip if no upcoming earnings or earnings > 90 days away
            if dte is None or dte > 90 or dte < 0:
                return None

            # Spot price
            spot = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
            if spot == 0:
                hist = t.history(period="1d")
                if not hist.empty:
                    spot = float(hist["Close"].iloc[-1])

            # ATM straddle for expected move
            expected_pct = None
            try:
                exps = t.options
                if exps and spot > 0:
                    # Find expiry closest to earnings date
                    target = datetime.datetime.strptime(earnings_str, "%Y-%m-%d").date() if earnings_str else datetime.date.today() + datetime.timedelta(days=dte or 7)
                    best_exp = min(exps, key=lambda e: abs((datetime.datetime.strptime(e, "%Y-%m-%d").date() - target).days))
                    chain = t.option_chain(best_exp)
                    calls, puts = chain.calls, chain.puts

                    # Find ATM
                    atm_call = calls.iloc[(calls["strike"] - spot).abs().argsort()[:1]]
                    atm_put  = puts.iloc[(puts["strike"]  - spot).abs().argsort()[:1]]
                    if not atm_call.empty and not atm_put.empty:
                        cl = float(atm_call.iloc[0].get("lastPrice", 0))
                        pl = float(atm_put.iloc[0].get("lastPrice",  0))
                        expected_pct = _expected_move(spot, cl, pl)
                        # avg IV
                        avg_iv = (float(atm_call.iloc[0].get("impliedVolatility", 0)) + float(atm_put.iloc[0].get("impliedVolatility", 0))) / 2
                    else:
                        avg_iv = 0
            except Exception:
                avg_iv = 0

            # Historical earnings info
            eps_estimate = _safe(info.get("epsCurrentYear"), None)
            eps_actual   = _safe(info.get("epsTrailingTwelveMonths"), None)
            eps_surprise = None
            if eps_estimate and eps_actual:
                try:
                    eps_surprise = round(((eps_actual - eps_estimate) / abs(eps_estimate)) * 100, 1)
                except Exception:
                    pass

            # IV crush signal: high IV pre-earnings is normal; if IV rank high, may be IV crush opportunity
            iv_crush_signal = avg_iv > 0.40 and dte is not None and dte <= 14

            return {
                "ticker":        ticker,
                "spot":          round(spot, 2),
                "earnings_date": earnings_str,
                "dte":           dte,
                "expected_pct":  expected_pct,
                "avg_iv":        round(avg_iv * 100, 1),
                "eps_estimate":  eps_estimate,
                "eps_actual":    eps_actual,
                "eps_surprise":  eps_surprise,
                "iv_crush_flag": iv_crush_signal,
                "company":       info.get("shortName", ticker),
                "sector":        info.get("sector", ""),
            }

        return await loop.run_in_executor(None, _fetch)
    except Exception as e:
        log.debug(f"Earnings analysis failed for {ticker}: {e}")
        return None

async def build_llm_commentary(earnings: list) -> str:
    if not earnings:
        return "No upcoming earnings found for the current watchlist in the next 90 days."
    soon = [e for e in earnings if e["dte"] is not None and e["dte"] <= 14]
    lines = []
    for e in soon[:5]:
        crush = " [IV CRUSH OPP]" if e.get("iv_crush_flag") else ""
        lines.append(f"{e['ticker']} earnings in {e['dte']}d · expected move ±{e.get('expected_pct','?')}%{crush}")
    if not lines:
        lines = [f"{e['ticker']} earnings in {e['dte']}d" for e in earnings[:5]]

    prompt = f"""You are an options trading analyst for a TOS trader. Summarize the upcoming earnings calendar in 3–4 sentences. Highlight IV crush opportunities, large expected moves, and any notable names. Be specific and practical. /no_think

{chr(10).join(lines)}"""
    try:
        return await generate_completion(prompt, agent_id="earnings_cal")
    except Exception:
        return "Several earnings events upcoming. Review the calendar below for IV and expected move details."

def _urgency(dte):
    if dte is None: return 4
    if dte <= 3:  return 0
    if dte <= 7:  return 1
    if dte <= 14: return 2
    return 3

async def earnings_calendar_job():
    log.info("Earnings Calendar starting")
    orchestrator.update_agent_status("earnings_cal", "running")
    try:
        watchlist = _get_watchlist()
        log.info(f"Checking earnings for {len(watchlist)} tickers")

        results = []
        for i in range(0, len(watchlist), 5):
            batch = watchlist[i:i+5]
            batch_res = await asyncio.gather(*[_analyze_ticker(t) for t in batch], return_exceptions=True)
            for r in batch_res:
                if isinstance(r, dict) and r:
                    results.append(r)
            await asyncio.sleep(0.5)

        # Sort by DTE
        results.sort(key=lambda x: x.get("dte") or 999)
        commentary = await build_llm_commentary(results)

        payload = {
            "calendar": {
                "events":      results,
                "this_week":   [e for e in results if (e.get("dte") or 999) <= 7],
                "next_2_weeks":[e for e in results if (e.get("dte") or 999) <= 14],
                "iv_crush_opp":[e for e in results if e.get("iv_crush_flag")],
                "commentary":  commentary,
                "scanned":     len(watchlist),
                "found":       len(results),
                "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        }
        save_agent_data("earnings_cal", payload)
        orchestrator.update_agent_status("earnings_cal", "idle")
        log.info(f"Earnings Calendar complete — {len(results)} upcoming events")
    except Exception as e:
        log.error(f"Earnings Calendar error: {e}", exc_info=True)
        orchestrator.update_agent_status("earnings_cal", "error", str(e))
        raise

def email_preview() -> dict:
    data = get_agent_data("earnings_cal") or {}
    cal = data.get("calendar", {})
    events = cal.get("events", [])[:15]
    commentary = cal.get("commentary", "No data yet.")
    generated_at = cal.get("generated_at", "—")

    rows = ""
    for e in events:
        dte = e.get("dte")
        urgency_color = "#dc2626" if (dte or 99) <= 3 else "#d97706" if (dte or 99) <= 7 else "#2563eb"
        crush = " 🔥" if e.get("iv_crush_flag") else ""
        rows += f"""<tr>
          <td style='padding:7px 12px;font-weight:700;font-family:monospace'>{e['ticker']}</td>
          <td style='padding:7px 12px;color:#555;font-size:12px'>{e.get('company','')}</td>
          <td style='padding:7px 12px;color:{urgency_color};font-weight:700'>{dte}d</td>
          <td style='padding:7px 12px;font-family:monospace'>{e.get('earnings_date','—')}</td>
          <td style='padding:7px 12px;font-weight:700'>±{e.get('expected_pct','?')}%{crush}</td>
          <td style='padding:7px 12px;color:#7c5cf6'>{e.get('avg_iv','—')}%</td>
        </tr>"""

    html = f"""<!DOCTYPE html><html><body style='font-family:Helvetica,sans-serif;background:#f6f7f9;margin:0;padding:0'>
<div style='max-width:640px;margin:24px auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb'>
  <div style='background:linear-gradient(135deg,#065f46,#16a34a);padding:24px 32px'>
    <div style='font-size:22px;font-weight:800;color:#fff'>📅 Earnings Calendar</div>
    <div style='font-size:13px;color:#a7f3d0;margin-top:4px'>{generated_at} · Next 90 days</div>
  </div>
  <div style='padding:20px 32px;background:#f0fdf4;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:14px;line-height:1.6;color:#166534'>{commentary}</div>
  </div>
  {'<div style="padding:20px 32px"><table style="width:100%;border-collapse:collapse;font-size:13px"><tr style="background:#f9fafb"><th style="padding:7px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">TICKER</th><th style="padding:7px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">COMPANY</th><th style="padding:7px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">DTE</th><th style="padding:7px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">DATE</th><th style="padding:7px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">EXP MOVE</th><th style="padding:7px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700">IV</th></tr>' + rows + '</table><div style="font-size:11px;color:#888;margin-top:10px">🔥 = IV Crush opportunity (high IV, DTE ≤ 14)</div></div>' if rows else '<div style="padding:20px 32px;color:#888">No upcoming earnings found in watchlist.</div>'}
  <div style='padding:14px 32px;text-align:center;font-size:11px;color:#aeb4bf'>Not financial advice · Educational use only</div>
</div></body></html>"""
    return {"html": html}
