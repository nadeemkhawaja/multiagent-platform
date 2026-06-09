# ============================================================================
# Agent 13 — Alpha Wolf (Master Agent)
# Leads the pack: ingests the cached output of six trading sub-agents
# (Wallstreet Wolf, Wallstreet Compass, Strategy Scout, Capitol Tracker,
# Options Flow, Earnings Calendar), then makes ONE local-LLM call to
# synthesize a ranked Daily + Weekly trade game-plan. Educational only.
# ============================================================================
import os
import datetime
import logging

from database import save_agent_data, get_agent_data, get_config
from llm_client import generate_json
from orchestrator import orchestrator
from email_utils import send_html_email

log = logging.getLogger("alpha_wolf")

AGENT_ID = "alpha_wolf"
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")

# The pack Alpha Wolf commands. Keyed by backend agent_id → the AgentData key
# each one persists under.
SUB_AGENTS = {
    "wallstreet_wolf": "market_data",
    "compass":         "compass",
    "strategy_scout":  "scout",
    "capitol_tracker": "tracker",
    "options_flow":    "flow",
    "earnings_cal":    "calendar",
}

DISCLAIMER = ("Educational analysis only — not financial advice. Alpha Wolf aggregates signals "
              "and never places trades. Do your own research and manage risk.")


# ── Compact summaries of each sub-agent's latest output (fed to the LLM) ──────
def _wolf_summary(d: dict) -> str:
    md = (d or {}).get("market_data", {}) or {}
    g = md.get("top_gainers", [])[:5]
    l = md.get("top_losers", [])[:5]
    gain = ", ".join(f"{s.get('symbol')} {s.get('change_pct')}%" for s in g) or "n/a"
    lose = ", ".join(f"{s.get('symbol')} {s.get('change_pct')}%" for s in l) or "n/a"
    return f"Top gainers: {gain}. Top losers: {lose}. Wolf read: {str(md.get('commentary',''))[:300]}"


def _compass_summary(d: dict) -> str:
    c = (d or {}).get("compass", {}) or {}
    sectors = c.get("sectors", []) or []
    sec = ", ".join(f"{s.get('k')} {s.get('bias'):+d}" for s in sectors
                    if isinstance(s.get("bias"), int)) or "n/a"
    return (f"Composite bias: {c.get('composite','?')} (-100 bearish..+100 bullish). "
            f"Sector bias: {sec}. Compass read: {str(c.get('read',''))[:300]}")


def _scout_summary(d: dict) -> str:
    s = (d or {}).get("scout", {}) or {}
    strats = s.get("strategies", [])[:6]
    listed = "; ".join(f"{x.get('name')} ({x.get('type')}/{x.get('timeframe')})" for x in strats)
    return "Trending strategies: " + (listed or "n/a")


def _capitol_summary(d: dict) -> str:
    t = (d or {}).get("tracker", {}) or {}
    trades = t.get("trades", [])[:10]
    def _last(name): return (name or "?").split()[-1] if name else "?"
    tr = ", ".join(f"{_last(x.get('politician'))} {str(x.get('type',''))[:4]} {x.get('ticker') or '—'}"
                   for x in trades) or "n/a"
    return f"Recent congressional trades: {tr}. Note: {str(t.get('commentary',''))[:200]}"


def _options_summary(d: dict) -> str:
    f = (d or {}).get("flow", {}) or {}
    top = f.get("top5", []) or f.get("signals", []) or []
    sig = ", ".join(f"{x.get('ticker')} {x.get('type','')} IV%ile {x.get('iv_pct','?')}"
                    for x in top[:6]) or "n/a"
    return f"Unusual options flow: {sig}. Note: {str(f.get('commentary',''))[:200]}"


def _earnings_summary(d: dict) -> str:
    c = (d or {}).get("calendar", {}) or {}
    tw = c.get("this_week", []) or []
    ev = ", ".join(f"{e.get('ticker')} {e.get('earnings_date','')} exp±{e.get('expected_pct','?')}%"
                   for e in tw[:8]) or "none this week"
    return f"Earnings this week: {ev}. IV-crush setups flagged: {len(c.get('iv_crush_opp', []))}."


def _gather():
    data = {aid: get_agent_data(aid) for aid in SUB_AGENTS}
    summaries = {
        "MARKET":     _wolf_summary(data["wallstreet_wolf"]),
        "REGIME":     _compass_summary(data["compass"]),
        "STRATEGIES": _scout_summary(data["strategy_scout"]),
        "CONGRESS":   _capitol_summary(data["capitol_tracker"]),
        "OPTIONS":    _options_summary(data["options_flow"]),
        "EARNINGS":   _earnings_summary(data["earnings_cal"]),
    }
    sources_used = [aid for aid, key in SUB_AGENTS.items() if (data.get(aid) or {}).get(key)]
    return summaries, sources_used


# ── LLM synthesis → structured Daily + Weekly plan ───────────────────────────
async def _synthesize(summaries: dict) -> dict:
    context = "\n".join(f"- {k}: {v}" for k, v in summaries.items())
    prompt = f"""You are Alpha Wolf, the lead strategist commanding a pack of six specialist agents.
Each agent below reports a different slice of the market:
- MARKET     = today's movers + the Wolf's read (Wallstreet Wolf)
- REGIME     = sector bias + overall market regime (Wallstreet Compass)
- STRATEGIES = setups other traders are actively running (Strategy Scout)
- CONGRESS   = recent congressional buys/sells (Capitol Tracker)
- OPTIONS    = unusual options flow / positioning (Options Flow)
- EARNINGS   = upcoming earnings catalysts (Earnings Calendar)

INTEL:
{context}

Your job: CROSS-REFERENCE all six feeds and build ONE clear, actionable game-plan. Your
highest-conviction calls are names where MULTIPLE feeds line up — e.g. a bullish regime + unusual
call flow + congressional buying + a near-term catalyst on the same ticker. Tell the trader exactly
what to do, what to watch, and what to avoid. Be specific with tickers, levels and triggers. Never
guarantee outcomes; always frame the risk.

Return ONLY valid JSON with this exact shape:
{{
  "headline": "one punchy sentence — the single most important move or stance right now",
  "stance": "RISK-ON|RISK-OFF|NEUTRAL",
  "regime": "one sentence on the overall market regime and key driver",
  "confluence": ["TICKER — which feeds agree and why it's high-conviction"],
  "daily": {{
    "bias": "BULLISH|BEARISH|NEUTRAL",
    "summary": "2-3 sentences on today's plan",
    "ideas": [{{"ticker":"SYM","direction":"long|short|neutral","thesis":"why — cite which agents support it","trigger":"entry condition/level","risk":"what invalidates it"}}]
  }},
  "weekly": {{
    "bias": "BULLISH|BEARISH|NEUTRAL",
    "summary": "2-3 sentences on the week",
    "themes": ["theme 1","theme 2"],
    "ideas": [{{"ticker":"SYM","direction":"long|short|neutral","thesis":"why — cite which agents support it","catalyst":"event/why this week","risk":"what invalidates it"}}]
  }},
  "avoid": ["what to stay away from right now and why"],
  "catalysts": ["upcoming catalyst 1","catalyst 2"],
  "risk_notes": "position sizing and overall risk guidance"
}}
Give 2-4 ideas per plan, 1-3 confluence calls, 1-3 avoids. /no_think"""
    plan = await generate_json(
        prompt,
        system_prompt="You are a disciplined trading strategist who fuses many signals into one plan. Return only valid JSON.",
        agent_id=AGENT_ID,
    )
    return plan if isinstance(plan, dict) else {}


# ── Main job ─────────────────────────────────────────────────────────────────
async def alpha_wolf_job():
    orchestrator.update_agent_status(AGENT_ID, "running")
    try:
        orchestrator.set_progress(AGENT_ID, "Gathering intel from the pack…")
        summaries, sources_used = _gather()

        orchestrator.set_progress(AGENT_ID, "Synthesizing the game-plan with Qwen3…")
        plan = await _synthesize(summaries)
        if not plan:
            plan = {
                "headline": "Not enough intel yet — run the pack, then re-run Alpha Wolf.",
                "stance": "NEUTRAL",
                "regime": "Not enough sub-agent data yet — run the pack (Wolf, Compass, Strategy Scout, "
                          "Capitol Tracker, Options Flow, Earnings) first, then re-run Alpha Wolf.",
                "confluence": [], "daily": {}, "weekly": {}, "avoid": [], "catalysts": [], "risk_notes": "",
            }
        plan["disclaimer"] = DISCLAIMER
        plan["inputs"] = summaries
        plan["sources_used"] = sources_used
        plan["generated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        save_agent_data(AGENT_ID, {"plan": plan})

        recipient = get_config("recipient", "") or DAILY_DIGEST_EMAIL
        if recipient:
            send_html_email(recipient, "🐺 Alpha Wolf — Daily + Weekly Trade Plan",
                            _build_email(plan), sender_name="Alpha Wolf")

        orchestrator.update_agent_status(AGENT_ID, "idle")
        orchestrator.log_event(f"Alpha Wolf synthesized a plan from {len(sources_used)}/6 sub-agents", "#7c3aed")
        log.info(f"Alpha Wolf complete — {len(sources_used)} sources")
    except Exception as e:
        log.error(f"Alpha Wolf error: {e}", exc_info=True)
        orchestrator.update_agent_status(AGENT_ID, "error", str(e))


# ── Email HTML ───────────────────────────────────────────────────────────────
def _idea_rows(ideas: list, weekly: bool = False) -> str:
    if not ideas:
        return "<div style='font-size:13px;color:#888;padding:8px 0'>No specific ideas this run.</div>"
    rows = ""
    for x in ideas[:4]:
        d = str(x.get("direction", "")).lower()
        dc = "#16a34a" if d == "long" else "#dc2626" if d == "short" else "#6b7280"
        third_label = "Catalyst" if weekly else "Trigger"
        third_val = x.get("catalyst", "") if weekly else x.get("trigger", "")
        rows += f"""
        <div style='padding:12px 0;border-bottom:1px solid #f0f0f0'>
          <div style='display:flex;align-items:center;gap:8px'>
            <span style='font-family:monospace;font-weight:800;font-size:14px;color:#1a1a2e'>{x.get('ticker','—')}</span>
            <span style='font-size:10px;font-weight:800;color:{dc};background:{dc}14;padding:2px 8px;border-radius:4px;text-transform:uppercase'>{d or 'n/a'}</span>
          </div>
          <div style='font-size:12.5px;color:#444;margin-top:4px;line-height:1.45'>{x.get('thesis','')}</div>
          <div style='font-size:11.5px;color:#666;margin-top:3px'><b>{third_label}:</b> {third_val} &nbsp;·&nbsp; <b>Risk:</b> {x.get('risk','')}</div>
        </div>"""
    return rows


def _bias_pill(bias: str) -> str:
    b = str(bias or "NEUTRAL").upper()
    c = "#16a34a" if b == "BULLISH" else "#dc2626" if b == "BEARISH" else "#6b7280"
    return f"<span style='font-size:11px;font-weight:800;color:{c};background:{c}16;padding:3px 10px;border-radius:6px'>{b}</span>"


def _build_email(plan: dict) -> str:
    daily = plan.get("daily", {}) or {}
    weekly = plan.get("weekly", {}) or {}
    catalysts = plan.get("catalysts", []) or []
    themes = weekly.get("themes", []) or []
    confluence = plan.get("confluence", []) or []
    avoid = plan.get("avoid", []) or []
    cat_html = "".join(f"<li style='margin:3px 0'>{c}</li>" for c in catalysts[:6]) or "<li>None flagged</li>"
    conf_html = "".join(f"<li style='margin:3px 0'>{c}</li>" for c in confluence[:4])
    avoid_html = "".join(f"<li style='margin:3px 0'>{c}</li>" for c in avoid[:4]) or "<li>Nothing flagged</li>"
    theme_html = " · ".join(themes[:4]) or "—"
    stance = str(plan.get("stance", "NEUTRAL")).upper()
    stance_c = "#16a34a" if stance == "RISK-ON" else "#dc2626" if stance == "RISK-OFF" else "#6b7280"
    return f"""<!DOCTYPE html><html><body style='font-family:Helvetica,sans-serif;background:#f6f7f9;margin:0;padding:0'>
<div style='max-width:660px;margin:24px auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb'>
  <div style='background:linear-gradient(135deg,#4c1d95,#7c3aed);padding:26px 32px'>
    <div style='font-size:23px;font-weight:800;color:#fff'>🐺 Alpha Wolf</div>
    <div style='font-size:13px;color:#ddd6fe;margin-top:4px'>Master game-plan · {plan.get('generated_at','')} · synthesized from {len(plan.get('sources_used', []))}/6 agents</div>
  </div>

  <div style='padding:18px 32px;background:#f5f3ff;border-bottom:1px solid #e5e7eb'>
    <div style='display:flex;align-items:center;gap:10px;margin-bottom:8px'>
      <span style='font-size:10px;font-weight:800;color:#fff;background:{stance_c};padding:3px 10px;border-radius:6px'>{stance}</span>
      <span style='font-size:15px;font-weight:800;color:#4c1d95'>{plan.get('headline','')}</span>
    </div>
    <div style='font-size:13px;line-height:1.55;color:#3730a3'><b>Regime:</b> {plan.get('regime','')}</div>
    {f"<div style='margin-top:10px'><div style='font-size:11px;font-weight:700;color:#7c3aed;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px'>Confluence (high conviction)</div><ul style='margin:0;padding-left:18px;font-size:12.5px;color:#3730a3'>{conf_html}</ul></div>" if conf_html else ""}
  </div>

  <div style='padding:20px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:13px;font-weight:800;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px'>Daily Plan {_bias_pill(daily.get('bias'))}</div>
    <div style='font-size:13px;color:#444;line-height:1.5;margin-bottom:6px'>{daily.get('summary','')}</div>
    {_idea_rows(daily.get('ideas', []))}
  </div>

  <div style='padding:20px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:13px;font-weight:800;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px'>Weekly Plan {_bias_pill(weekly.get('bias'))}</div>
    <div style='font-size:13px;color:#444;line-height:1.5;margin-bottom:4px'>{weekly.get('summary','')}</div>
    <div style='font-size:11.5px;color:#7c3aed;margin-bottom:6px'><b>Themes:</b> {theme_html}</div>
    {_idea_rows(weekly.get('ideas', []), weekly=True)}
  </div>

  <div style='padding:18px 32px;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:12px;font-weight:700;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px'>Catalysts to watch</div>
    <ul style='margin:0;padding-left:18px;font-size:12.5px;color:#444'>{cat_html}</ul>
    <div style='font-size:12px;font-weight:700;color:#dc2626;text-transform:uppercase;letter-spacing:.5px;margin:12px 0 6px'>Avoid</div>
    <ul style='margin:0;padding-left:18px;font-size:12.5px;color:#444'>{avoid_html}</ul>
    <div style='font-size:12.5px;color:#444;margin-top:10px'><b>Risk:</b> {plan.get('risk_notes','')}</div>
  </div>

  <div style='padding:14px 32px;font-size:10.5px;color:#aeb4bf;line-height:1.5'>{plan.get('disclaimer', DISCLAIMER)}</div>
</div></body></html>"""


def email_preview() -> dict:
    data = get_agent_data(AGENT_ID) or {}
    plan = data.get("plan", {})
    if not plan:
        return {"html": "<p>No Alpha Wolf plan yet. Run the sub-agents, then run Alpha Wolf.</p>"}
    return {"html": _build_email(plan)}
