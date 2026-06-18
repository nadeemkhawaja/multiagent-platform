"""
Agent-6: Strategy Scout — Trending Trading-Strategy Radar
========================================================
Scans where retail + active traders actually discuss strategy:
  • Reddit trading subreddits (r/algotrading, r/Daytrading, r/swingtrading,
    r/options, r/Forex, r/stocks) — top posts of the week
  • TradingView public "Ideas" feed
The LLM then distills the raw chatter into a ranked list of the TOP trading
strategies being talked about right now — each with a name, type, timeframe
and a plain-English summary. Scheduled action: daily digest at 10:00.
Stored in SQLite under agent_name="strategy_scout", key="scout".
"""

import os
import re
import json
import html
import asyncio
from datetime import datetime

import httpx

from database import SessionLocal, AgentData
from llm_client import generate_json
from orchestrator import orchestrator
from email_utils import send_html_email

AGENT_ID = "strategy_scout"
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
SUBREDDITS = ["algotrading", "Daytrading", "swingtrading", "options", "Forex", "stocks"]
TOP_N = 6  # number of distilled strategies


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


# ── Reddit (top.json with .rss fallback — datacenter IPs often 403 on .json) ──
async def _reddit_sub(client, sub):
    try:
        r = await client.get(f"https://www.reddit.com/r/{sub}/top.json", params={"t": "week", "limit": 6})
        if r.status_code == 200:
            out = []
            for ch in r.json().get("data", {}).get("children", []):
                d = ch.get("data", {})
                if d.get("stickied"):
                    continue
                out.append({
                    "src": "Reddit", "sub": "r/" + sub,
                    "title": _clean(d.get("title", ""))[:200],
                    "score": d.get("score"), "comments": d.get("num_comments"),
                    "url": "https://www.reddit.com" + d.get("permalink", ""),
                    "text": _clean(d.get("selftext", ""))[:300],
                })
            return out
    except Exception as e:
        print(f"[StrategyScout] reddit json {sub}: {e}")
    # RSS fallback (works without auth)
    try:
        r = await client.get(f"https://www.reddit.com/r/{sub}/top/.rss", params={"t": "week"})
        out = []
        if r.status_code == 200:
            for block in re.findall(r"<entry>(.*?)</entry>", r.text, re.DOTALL):
                tm = re.search(r"<title>(.*?)</title>", block, re.DOTALL)
                lm = re.search(r'<link[^>]+href="([^"]+)"', block)
                if tm:
                    out.append({
                        "src": "Reddit", "sub": "r/" + sub,
                        "title": _clean(tm.group(1))[:200],
                        "score": None, "comments": None,
                        "url": lm.group(1) if lm else "", "text": "",
                    })
        return out[:6]
    except Exception as e:
        print(f"[StrategyScout] reddit rss {sub}: {e}")
        return []


async def fetch_reddit():
    async with httpx.AsyncClient(timeout=14, headers=UA, follow_redirects=True) as c:
        results = await asyncio.gather(*[_reddit_sub(c, s) for s in SUBREDDITS])
    out = []
    for r in results:
        out.extend(r)
    return out


# ── TradingView public Ideas feed (HTML) ─────────────────────────────────────
async def fetch_tradingview():
    out = []
    try:
        async with httpx.AsyncClient(timeout=15, headers=UA, follow_redirects=True) as c:
            r = await c.get("https://www.tradingview.com/ideas/")
            if r.status_code == 200:
                names = re.findall(r'"image_url":"[^"]*","name":"([^"]{8,140})"', r.text)
                if not names:
                    names = re.findall(r'class="title[^"]*"[^>]*>([^<]{8,140})<', r.text)
                seen = set()
                for n in names:
                    n = _clean(n)
                    if " " not in n or n in seen:   # skip bare tickers / dupes
                        continue
                    seen.add(n)
                    out.append({"src": "TradingView", "sub": "Ideas", "title": n,
                                "score": None, "comments": None,
                                "url": "https://www.tradingview.com/ideas/", "text": ""})
                    if len(out) >= 12:
                        break
    except Exception as e:
        print(f"[StrategyScout] tradingview: {e}")
    return out


# ── LLM distillation → ranked strategies ─────────────────────────────────────
async def distill_strategies(items):
    if not items:
        return []
    listing = "\n".join(f"- [{it['src']}/{it['sub']}] {it['title']}" for it in items[:32])
    prompt = f"""Below are trending trading posts and chart ideas from Reddit and TradingView.
Identify the TOP {TOP_N} actionable trading strategies people are discussing right now.
Group similar posts into one strategy. Return ONLY a JSON array; each element:
{{"name":"<short strategy name>","type":"<momentum|mean-reversion|breakout|trend-following|options|scalping|swing|other>","timeframe":"<intraday|swing|position|n/a>","summary":"<2 plain-English sentences on the idea and how it's traded>","source":"<Reddit|TradingView|both>"}}

Trending posts:
{listing}"""
    data = await generate_json(
        prompt, system_prompt="You are a trading-strategy analyst. Return only a JSON array.",
        agent_id=AGENT_ID, use_cache=False,
    )
    out = []
    if isinstance(data, list):
        for s in data[:TOP_N]:
            if not isinstance(s, dict):
                continue
            out.append({
                "name": str(s.get("name", "Untitled strategy")).strip()[:80],
                "type": str(s.get("type", "other")).strip().lower()[:20],
                "timeframe": str(s.get("timeframe", "n/a")).strip().lower()[:16],
                "summary": str(s.get("summary", "")).strip()[:400],
                "source": str(s.get("source", "")).strip()[:20],
            })
    return out


# ── LLM synthesis → ONE simple plan ──────────────────────────────────────────
# The user doesn't want six competing ideas; they want a single call to action.
# We collapse all the distilled strategies into exactly one stance.
PLAN_ACTIONS = {"enter long": "Enter Long", "stay put": "Stay Put", "enter short": "Enter Short"}


async def synthesize_plan(strategies):
    """Weigh all distilled strategies into one decision: long / flat / short."""
    if not strategies:
        return None
    listing = "\n".join(
        f"- {s['name']} ({s['type']}, {s['timeframe']}): {s['summary']}" for s in strategies
    )
    prompt = f"""You are a trading-desk lead. Below are the top strategies traders are
discussing right now. Weigh them TOGETHER into ONE simple plan for a swing trader.
Pick exactly one action: "Enter Long", "Stay Put", or "Enter Short".
Return ONLY JSON:
{{"action":"Enter Long|Stay Put|Enter Short","confidence":"low|medium|high","rationale":"<=20 words, why the balance of strategies points there"}}

Strategies:
{listing}"""
    try:
        data = await generate_json(
            prompt, system_prompt="You are a decisive trading-desk lead. Return only one JSON object.",
            agent_id=AGENT_ID, use_cache=False,
        )
    except Exception as e:
        print(f"[StrategyScout] plan synthesis failed: {e}")
        return None
    if not isinstance(data, dict):
        return None
    action = PLAN_ACTIONS.get(str(data.get("action", "")).strip().lower(), "Stay Put")
    conf = str(data.get("confidence", "medium")).strip().lower()
    if conf not in ("low", "medium", "high"):
        conf = "medium"
    return {
        "action": action,
        "confidence": conf,
        "rationale": str(data.get("rationale", "")).strip()[:200],
    }


# ── persistence ──────────────────────────────────────────────────────────────
def _save(payload):
    db = SessionLocal()
    try:
        rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key="scout").first()
        if rec:
            rec.value = json.dumps(payload)
            rec.updated_at = datetime.utcnow()
        else:
            db.add(AgentData(agent_name=AGENT_ID, key="scout", value=json.dumps(payload)))
        db.commit()
    finally:
        db.close()


# ── email digest ─────────────────────────────────────────────────────────────
TYPE_COLORS = {"momentum": "#16a34a", "breakout": "#2563eb", "mean-reversion": "#9333ea",
               "trend-following": "#0d9488", "options": "#dc2626", "scalping": "#f59e0b",
               "swing": "#0ea5e9"}


PLAN_COLORS = {"Enter Long": "#16a34a", "Stay Put": "#64748b", "Enter Short": "#dc2626"}


def _plan_html(plan):
    if not plan:
        return ""
    action = plan.get("action", "Stay Put")
    col = PLAN_COLORS.get(action, "#64748b")
    conf = plan.get("confidence", "medium")
    rationale = plan.get("rationale", "")
    return (
        f'<div style="background:{col}12;border:1px solid {col}55;border-left:5px solid {col};'
        f'border-radius:10px;padding:16px 18px;margin:0 0 18px">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.5px">Today\'s play · all strategies combined</div>'
        f'<div style="font-size:24px;font-weight:800;color:{col};margin:4px 0 2px">{action}'
        f'<span style="font-size:12px;font-weight:600;color:#64748b;margin-left:8px">{conf} confidence</span></div>'
        f'{f"<div style=\'font-size:13px;color:#475569;line-height:1.5\'>{rationale}</div>" if rationale else ""}'
        f'</div>'
    )


def build_html(payload):
    strategies = payload.get("strategies", [])
    discussions = payload.get("discussions", [])
    plan = payload.get("plan")
    strat_rows = "".join(
        f"""<div style="background:#f8fafc;border:1px solid #eef2f7;border-radius:8px;padding:14px;margin-bottom:8px">
          <div style="font-weight:700;font-size:15px;color:#0f172a">{i+1}. {s['name']}
            <span style="font-size:11px;font-weight:600;color:#2563eb;background:#eff6ff;padding:2px 8px;border-radius:6px;margin-left:6px">{s['type']}</span>
            <span style="font-size:11px;color:#64748b;margin-left:4px">{s['timeframe']} · {s['source']}</span></div>
          <div style="font-size:13px;color:#475569;margin-top:6px;line-height:1.5">{s['summary']}</div>
        </div>""" for i, s in enumerate(strategies)
    ) or '<p style="color:#94a3b8">No strategies distilled this run.</p>'
    disc_rows = "".join(
        f'<li style="margin-bottom:6px"><b style="color:#0ea5e9">{d["src"]} · {d["sub"]}</b> — '
        f'<a href="{d["url"]}" style="color:#0f172a;text-decoration:none">{d["title"]}</a></li>'
        for d in discussions[:12]
    )
    return f"""
    <html><head><meta name="color-scheme" content="light"></head>
      <body style="font-family:'Segoe UI',sans-serif;background:#eef2f7;color:#0f172a;padding:20px;margin:0">
        <div style="max-width:620px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:28px">
          <h1 style="color:#0ea5e9;margin-top:0">✦ Strategy Scout</h1>
          <p style="color:#64748b">{datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')} · top strategies trending on Reddit + TradingView</p>
          {_plan_html(plan)}
          <h2 style="color:#64748b;border-bottom:1px solid #e2e8f0;padding-bottom:8px">🏆 Top Strategies</h2>
          {strat_rows}
          <h2 style="color:#64748b;border-bottom:1px solid #e2e8f0;padding-bottom:8px">🔥 Trending Discussions</h2>
          <ul style="list-style:none;padding:0;font-size:13px;line-height:1.5">{disc_rows}</ul>
        </div>
      </body></html>
    """


def send_digest(payload):
    if not DAILY_DIGEST_EMAIL:
        return
    send_html_email(DAILY_DIGEST_EMAIL, "✦ Strategy Scout — Top Trading Strategies",
                    build_html(payload), sender_name="Strategy Scout Agent")


def email_preview() -> str:
    db = SessionLocal()
    rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key="scout").first()
    db.close()
    if not rec:
        return "<p>No Strategy Scout data yet — run a scan first.</p>"
    return build_html(json.loads(rec.value))


# ── job ──────────────────────────────────────────────────────────────────────
async def strategy_scout_job():
    orchestrator.update_agent_status(AGENT_ID, "running")
    try:
        reddit, tv = await asyncio.gather(fetch_reddit(), fetch_tradingview())
        # rank reddit by score where available, keep TV after
        reddit.sort(key=lambda d: (d.get("score") or 0), reverse=True)
        items = reddit + tv

        strategies = []
        try:
            strategies = await distill_strategies(items)
        except Exception as e:
            print(f"[StrategyScout] distill failed: {e}")

        plan = await synthesize_plan(strategies)

        payload = {
            "strategies": strategies,
            "plan": plan,
            "discussions": items[:24],
            "sources": {"reddit": len(reddit), "tradingview": len(tv)},
            "fetched_at": datetime.utcnow().isoformat(),
        }
        _save(payload)
        send_digest(payload)

        orchestrator.update_agent_status(AGENT_ID, "idle")
        orchestrator.log_event(f"Strategy Scout distilled {len(strategies)} top strategies "
                               f"from {len(items)} posts", "#0ea5e9")
        print(f"[StrategyScout] Done — {len(strategies)} strategies from "
              f"{len(reddit)} Reddit + {len(tv)} TradingView posts")
    except Exception as e:
        orchestrator.update_agent_status(AGENT_ID, "error", str(e))
        print(f"[StrategyScout] Error: {e}")
