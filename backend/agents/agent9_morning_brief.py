# ============================================================================
# Agent 9 — Morning Brief
# Aggregates Wolf, Capitol Tracker, AI-Times from SQLite + wttr.in weather
# Qwen3 narrative summary → HTML email digest at 06:00 daily
# ============================================================================
import asyncio, json, datetime, logging
from database import save_agent_data, get_agent_data, get_config
from llm_client import generate_completion
from email_utils import send_html_email
from tools.weather import current_weather
import memory

log = logging.getLogger("morning_brief")

CITY = "Murphy+TX"   # weather location

# ---------------------------------------------------------------------------
async def fetch_weather() -> dict:
    """Weather via the shared tools/weather.py tool (wttr.in, no API key)."""
    try:
        return await current_weather(CITY)
    except Exception as e:
        log.warning(f"Weather fetch failed: {e}")
        return {"summary": "Weather unavailable", "temp_f": None, "desc": "Unknown"}

def _read_agent(agent_id: str) -> dict:
    """Safely read latest agent data from SQLite."""
    try:
        return get_agent_data(agent_id) or {}
    except Exception:
        return {}

async def build_llm_narrative(weather: dict, wolf_snap: dict, capitol_snap: dict, aitimes_snap: dict) -> str:
    """Ask Qwen3 to write a short morning narrative."""
    wolf_top = ""
    if wolf_snap.get("market_data"):
        gainers = wolf_snap["market_data"].get("top_gainers", [])[:3]
        losers  = wolf_snap["market_data"].get("top_losers",  [])[:3]
        wolf_top = "Top gainers: " + ", ".join(f"{g.get('symbol', g.get('ticker','?'))} +{g.get('change_pct', g.get('pct', 0)):.1f}%" for g in gainers)
        wolf_top += " | Top losers: " + ", ".join(f"{l.get('symbol', l.get('ticker','?'))} {l.get('change_pct', l.get('pct', 0)):.1f}%" for l in losers)

    capitol_top = ""
    if capitol_snap.get("tracker"):
        trades = capitol_snap["tracker"].get("trades", [])[:5]
        capitol_top = "Recent congressional trades: " + "; ".join(
            f"{t.get('politician','?')} {t.get('type','?')} {t.get('ticker','?')}" for t in trades
        )

    ai_top = ""
    if aitimes_snap.get("videos"):
        vids = aitimes_snap["videos"][:3]
        ai_top = "Top AI news: " + "; ".join(v.get("title", "") for v in vids)

    # Yesterday's brief from memory → today's narrative leads with what's new
    # instead of repeating items already reported. Failure-isolated.
    prior = ""
    try:
        briefs = memory.recent("morning_brief", k=1, kind="brief")
        if briefs:
            prior = f"\nYesterday's brief said: \"{briefs[0]['text']}\"\nDo not repeat unchanged items from yesterday — lead with what is new or different.\n"
    except Exception as e:
        log.warning(f"memory recall failed: {e}")

    prompt = f"""You are a personal morning brief assistant. Write a concise, friendly 3–4 sentence morning narrative for a Cisco Solutions Architect in Murphy, TX who also actively trades stocks and options.

Weather today: {weather.get('summary', 'unknown')}
Market snapshot: {wolf_top or 'no market data yet'}
Congressional trading: {capitol_top or 'no trade data yet'}
AI news: {ai_top or 'no news yet'}
{prior}
Write a short, confident paragraph summarizing these highlights. Be specific. No bullet points. /no_think"""

    try:
        return await generate_completion(prompt, agent_id="morning_brief")
    except Exception as e:
        log.warning(f"LLM narrative failed: {e}")
        return f"Good morning! Weather in Murphy: {weather.get('summary', 'unavailable')}. Check Wolf for market moves and Capitol Tracker for congressional trades."

def build_html_email(weather: dict, wolf_snap: dict, capitol_snap: dict, aitimes_snap: dict, narrative: str, generated_at: str) -> str:
    """Build full HTML digest email."""
    wolf  = wolf_snap.get("wolf", {})
    tracker = capitol_snap.get("tracker", {})
    videos  = (aitimes_snap.get("videos") or [])[:4]

    gainers = wolf.get("gainers", [])[:5]
    losers  = wolf.get("losers",  [])[:5]
    trades  = tracker.get("trades", [])[:6]

    def mover_rows(stocks, color):
        rows = ""
        for s in stocks:
            rows += f"<tr><td style='padding:6px 12px;font-weight:700;font-family:monospace'>{s.get('ticker','')}</td><td style='padding:6px 12px;font-family:monospace;color:{color};font-weight:600'>{'+' if s.get('pct',0)>0 else ''}{s.get('pct',0):.2f}%</td><td style='padding:6px 12px;color:#555'>${s.get('price',0):.2f}</td></tr>"
        return rows

    video_cards = ""
    for v in videos:
        video_cards += f"""
        <div style='display:flex;gap:12px;margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #eee'>
          <img src='{v.get('thumbnail','')}' style='width:80px;height:52px;object-fit:cover;border-radius:6px;flex-shrink:0' />
          <div><a href='{v.get('url','')}' style='font-size:13px;font-weight:600;color:#1a1a2e;text-decoration:none'>{v.get('title','')}</a>
          <div style='font-size:11px;color:#888;margin-top:2px'>{v.get('channel','')} · {v.get('published','')}</div></div>
        </div>"""

    trade_rows = ""
    for t in trades:
        tc = "#16a34a" if "purchase" in t.get("type","").lower() or "buy" in t.get("type","").lower() else "#dc2626"
        trade_rows += f"<tr><td style='padding:6px 12px;font-weight:700;font-family:monospace'>{t.get('ticker','—')}</td><td style='padding:6px 12px'>{t.get('politician','')}</td><td style='padding:6px 12px;color:{tc};font-weight:600'>{t.get('type','')}</td><td style='padding:6px 12px;color:#555'>{t.get('transaction_date','')}</td></tr>"

    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'></head>
<body style='margin:0;padding:0;background:#f6f7f9;font-family:"Hanken Grotesk",Helvetica,sans-serif'>
<div style='max-width:620px;margin:24px auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb'>

  <!-- Header -->
  <div style='background:linear-gradient(135deg,#1a1a2e,#16213e);padding:28px 32px'>
    <div style='font-size:22px;font-weight:800;color:#fff;letter-spacing:-0.5px'>☀ Morning Brief</div>
    <div style='font-size:13px;color:#a0a8c0;margin-top:4px'>{generated_at} · Murphy, TX</div>
  </div>

  <!-- Weather -->
  <div style='background:#eff6ff;padding:18px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:14px;color:#1e40af'>🌤 {weather.get("desc","—")} — {weather.get("temp_f","??")}°F (feels {weather.get("feels_f","??")}°F) · Humidity {weather.get("humidity","??")}% · Wind {weather.get("wind_mph","??")} mph</div>
  </div>

  <!-- Narrative -->
  <div style='padding:24px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:12px;font-weight:700;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px'>Your brief</div>
    <div style='font-size:14.5px;line-height:1.65;color:#2d3748'>{narrative}</div>
  </div>

  <!-- Market movers -->
  <div style='padding:24px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:12px;font-weight:700;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:14px'>📈 Market snapshot</div>
    <div style='display:flex;gap:16px'>
      <div style='flex:1'>
        <div style='font-size:11px;font-weight:700;color:#16a34a;margin-bottom:6px'>TOP GAINERS</div>
        <table style='width:100%;border-collapse:collapse'>{''.join(f"<tr><td style='padding:5px 0;font-weight:700;font-family:monospace;font-size:12px'>{g.get('ticker','')}</td><td style='color:#16a34a;font-family:monospace;font-size:12px'>+{g.get('pct',0):.2f}%</td></tr>" for g in gainers)}</table>
      </div>
      <div style='flex:1'>
        <div style='font-size:11px;font-weight:700;color:#dc2626;margin-bottom:6px'>TOP LOSERS</div>
        <table style='width:100%;border-collapse:collapse'>{''.join(f"<tr><td style='padding:5px 0;font-weight:700;font-family:monospace;font-size:12px'>{l.get('ticker','')}</td><td style='color:#dc2626;font-family:monospace;font-size:12px'>{l.get('pct',0):.2f}%</td></tr>" for l in losers)}</table>
      </div>
    </div>
  </div>

  <!-- Capitol trades -->
  {f'''<div style='padding:24px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:12px;font-weight:700;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:14px'>🏛 Congressional trades</div>
    <table style='width:100%;border-collapse:collapse;font-size:12.5px'>
      <tr style='background:#f9fafb'><th style='padding:6px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700'>TICKER</th><th style='padding:6px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700'>POLITICIAN</th><th style='padding:6px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700'>TYPE</th><th style='padding:6px 12px;text-align:left;font-size:10px;color:#8a909c;font-weight:700'>DATE</th></tr>
      {trade_rows}
    </table>
  </div>''' if trades else ''}

  <!-- AI videos -->
  {f'''<div style='padding:24px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:12px;font-weight:700;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:14px'>▶ AI news</div>
    {video_cards}
  </div>''' if videos else ''}

  <!-- Footer -->
  <div style='padding:16px 32px;text-align:center;font-size:11px;color:#aeb4bf'>
    Multi-Agent Platform · Morning Brief · Educational use only. Not financial advice.
  </div>
</div>
</body></html>"""

async def morning_brief_job():
    log.info("Morning Brief starting")
    try:
        weather       = await fetch_weather()
        wolf_snap     = _read_agent("wallstreet_wolf")
        capitol_snap  = _read_agent("capitol_tracker")
        aitimes_snap  = _read_agent("ai_times")
        narrative     = await build_llm_narrative(weather, wolf_snap, capitol_snap, aitimes_snap)
        now           = datetime.datetime.now().strftime("%A, %B %-d · %I:%M %p")

        payload = {
            "brief": {
                "weather": weather.get("summary"),
                "weather_detail": weather,
                "narrative": narrative,
                "wolf_gainers":  [{"ticker": s.get("symbol", s.get("ticker", "")), "pct": s.get("change_pct", s.get("pct", 0)), "price": s.get("price", 0)} for s in (wolf_snap.get("market_data") or {}).get("top_gainers", [])[:5]],
                "wolf_losers":   [{"ticker": s.get("symbol", s.get("ticker", "")), "pct": s.get("change_pct", s.get("pct", 0)), "price": s.get("price", 0)} for s in (wolf_snap.get("market_data") or {}).get("top_losers",  [])[:5]],
                "capitol_trades": (capitol_snap.get("tracker") or {}).get("trades", [])[:6],
                "ai_videos":     (aitimes_snap.get("videos") or [])[:4],
                "generated_at":  now,
            }
        }
        save_agent_data("morning_brief", payload)

        # Remember today's narrative so tomorrow's brief can avoid repeating it
        try:
            await memory.remember("morning_brief", narrative, kind="brief",
                                  meta={"generated_at": now})
        except Exception as e:
            log.warning(f"memory save failed: {e}")

        # Send email
        recipient = get_config("recipient", "")
        if recipient:
            html = build_html_email(weather, wolf_snap, capitol_snap, aitimes_snap, narrative, now)
            send_html_email(recipient, f"☀ Morning Brief — {now}", html)

        log.info("Morning Brief complete")
    except Exception as e:
        log.error(f"Morning Brief error: {e}", exc_info=True)
        raise

def email_preview() -> dict:
    data = get_agent_data("morning_brief") or {}
    brief = data.get("brief", {})
    wolf_snap    = {"wolf": {"gainers": brief.get("wolf_gainers",[]), "losers": brief.get("wolf_losers",[])}}
    capitol_snap = {"tracker": {"trades": brief.get("capitol_trades",[])}}
    aitimes_snap = {"videos": brief.get("ai_videos",[])}
    weather_d    = brief.get("weather_detail", {"summary": brief.get("weather",""), "temp_f": None, "feels_f": None, "humidity": None, "wind_mph": None, "desc": ""})
    narrative    = brief.get("narrative", "No brief generated yet.")
    generated_at = brief.get("generated_at", "—")
    html = build_html_email(weather_d, wolf_snap, capitol_snap, aitimes_snap, narrative, generated_at)
    return {"html": html}
