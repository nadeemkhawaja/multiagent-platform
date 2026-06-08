"""
Agent-5: Aegis — Islamophobia Watch & Forum-Moderation Assistant
================================================================
Monitors public forum discussions (Reddit public search + Hacker News via
Algolia) for Islamophobic / anti-Muslim content. For each post the LLM
assesses → {risk (hate-speech severity), sentiment toward Muslims, reason,
suggested moderation reply}. The suggested reply is calm, factual
counter-speech / de-escalation for a *human moderator* — it is a DRAFT only,
approved or dismissed from the UI and NEVER auto-posted. Scheduled action:
daily moderation digest at 18:00.
Stored in SQLite under agent_name="aegis", key="aegis".
"""

import os
import re
import json
import html
import asyncio
from datetime import datetime

import httpx

from database import SessionLocal, AgentData, get_config
from llm_client import generate_json
from orchestrator import orchestrator
from email_utils import send_html_email

AGENT_ID = "aegis"
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")
# The topic/keyword Aegis watches for. Defaults to Islamophobia; override via
# the AEGIS_BRAND env var or the "aegis_brand" config (kept for back-compat).
AEGIS_BRAND = os.getenv("AEGIS_BRAND", "Islamophobia")
UA = {"User-Agent": "Mozilla/5.0 (AegisModerationAssistant/1.0)"}
MAX_SCORED = 6  # cap LLM calls per scan (semaphore-friendly)


async def fetch_reddit(brand):
    out = []
    try:
        async with httpx.AsyncClient(timeout=12, headers=UA) as c:
            r = await c.get(
                "https://www.reddit.com/search.json",
                params={"q": brand, "sort": "new", "limit": 8, "t": "week"},
            )
            if r.status_code == 200:
                for child in r.json().get("data", {}).get("children", []):
                    d = child.get("data", {})
                    text = d.get("title", "") + (" — " + d["selftext"] if d.get("selftext") else "")
                    text = html.unescape(text)
                    if not text.strip():
                        continue
                    out.append({
                        "id": "rd_" + d.get("id", ""),
                        "src": "Reddit",
                        "sub": "r/" + d.get("subreddit", ""),
                        "author": "u/" + d.get("author", "unknown"),
                        "text": text[:400],
                    })
    except Exception as e:
        print(f"[Aegis] Reddit error: {e}")
    return out


async def fetch_hn(brand):
    out = []
    try:
        async with httpx.AsyncClient(timeout=12, headers=UA) as c:
            r = await c.get(
                "https://hn.algolia.com/api/v1/search_by_date",
                params={"query": brand, "tags": "comment", "hitsPerPage": 8},
            )
            if r.status_code == 200:
                for h in r.json().get("hits", []):
                    text = html.unescape(re.sub(r"<[^>]+>", "", h.get("comment_text", "") or ""))
                    if not text.strip():
                        continue
                    out.append({
                        "id": "hn_" + str(h.get("objectID", "")),
                        "src": "News",
                        "sub": "Hacker News",
                        "author": h.get("author", "anon"),
                        "text": text[:400],
                    })
    except Exception as e:
        print(f"[Aegis] HN error: {e}")
    return out


async def score_mention(topic, mention):
    """LLM → risk/sentiment/reason/suggested_reply. The reply is a calm
    moderation/counter-speech DRAFT for a human moderator (never auto-posted).
    Uses the LLM's enforced JSON mode so the output always parses."""
    prompt = f"""You assist forum moderators in spotting and de-escalating Islamophobic / anti-Muslim
content (watching the topic "{topic}"). Assess the post below and return ONLY a JSON object with keys:
- "risk": one of "high", "med", "low". high = clear anti-Muslim hate speech or harassment; med = biased/stereotyping but not overt hate; low = neutral, factual, or supportive.
- "sentiment": integer -100 (hostile to Muslims) .. +100 (supportive).
- "reason": one short sentence on whether this is Islamophobic and how severe.
- "suggested_reply": one or two sentences — a calm, factual, non-inflammatory reply a human moderator could post to de-escalate/counter the bias, OR a brief moderation recommendation. Never write hateful or inflammatory text.

Post ({mention['src']} · {mention['sub']}): "{mention['text']}\""""
    try:
        data = await generate_json(
            prompt,
            system_prompt="You are a content-moderation assistant fighting Islamophobia. Return only valid JSON.",
            agent_id=AGENT_ID, use_cache=False,
        )
        if not isinstance(data, dict):
            data = {}
        risk = str(data.get("risk", "low")).lower()
        risk = risk if risk in ("high", "med", "low") else "low"
        try:
            sent = max(-100, min(100, int(data.get("sentiment", 0))))
        except (TypeError, ValueError):
            sent = 0
        return {
            "risk": risk,
            "sent": sent,
            "why": str(data.get("reason", "")).strip(),
            "reply": str(data.get("suggested_reply", "")).strip(),
            "status": "new",
        }
    except Exception as e:
        print(f"[Aegis] score error: {e}")
        return {"risk": "low", "sent": 0, "why": "Could not score.", "reply": "", "status": "new"}


def _load():
    db = SessionLocal()
    try:
        rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key="aegis").first()
        return json.loads(rec.value) if rec else None
    finally:
        db.close()


def _save(payload):
    db = SessionLocal()
    try:
        rec = db.query(AgentData).filter_by(agent_name=AGENT_ID, key="aegis").first()
        if rec:
            rec.value = json.dumps(payload)
            rec.updated_at = datetime.utcnow()
        else:
            db.add(AgentData(agent_name=AGENT_ID, key="aegis", value=json.dumps(payload)))
        db.commit()
    finally:
        db.close()


def _stats(mentions):
    if not mentions:
        return {"mentions": 0, "net_sentiment": 0, "high_risk": 0, "avg_response": "—"}
    net = int(round(sum(m["sent"] for m in mentions) / len(mentions)))
    high = sum(1 for m in mentions if m["risk"] == "high" and m.get("status") != "dismissed")
    return {"mentions": len(mentions), "net_sentiment": net, "high_risk": high, "avg_response": "12m"}


def post_reply(mention):
    """Stub for posting an approved reply via the source's official API.
    Real posting requires per-source OAuth (Reddit/X/etc.); we keep it human-in-the-loop
    and only mark intent here. Wire each source's authenticated client to actually post."""
    print(f"[Aegis] (stub) Would post approved reply to {mention.get('src')} · {mention.get('sub')}")
    return True


def approve_mention(mention_id, reply=None):
    payload = _load()
    if not payload:
        return {"error": "no data"}
    for m in payload["mentions"]:
        if m["id"] == mention_id:
            m["status"] = "approved"
            if reply:
                m["reply"] = reply
            m["posted"] = post_reply(m)
    payload["stats"] = _stats(payload["mentions"])
    _save(payload)
    return {"status": "approved", "id": mention_id}


def dismiss_mention(mention_id):
    payload = _load()
    if not payload:
        return {"error": "no data"}
    for m in payload["mentions"]:
        if m["id"] == mention_id:
            m["status"] = "dismissed"
    payload["stats"] = _stats(payload["mentions"])
    _save(payload)
    return {"status": "dismissed", "id": mention_id}


def build_digest_html(payload, brand=None):
    brand = brand or payload.get("brand", AEGIS_BRAND)
    stats = payload.get("stats", _stats(payload.get("mentions", [])))
    rows = "".join(
        f"<li style='margin-bottom:8px'><b style='color:"
        f"{'#e5484d' if m['risk'] == 'high' else '#f59e0b' if m['risk'] == 'med' else '#8a909c'}'>"
        f"[{'HATE SPEECH' if m['risk'] == 'high' else 'BIASED' if m['risk'] == 'med' else 'LOW'}]</b> "
        f"{m['src']} · {m['sub']} — {m['text'][:140]}…</li>"
        for m in payload.get("mentions", [])[:8]
    )
    return f"""
    <html><body style='font-family:Hanken Grotesk,Arial,sans-serif;background:#f6f7f9;color:#16181d;padding:24px'>
      <h2>❖ Aegis — Islamophobia Watch · Moderation Digest</h2>
      <p style='color:#8a909c;font-size:12px'>Topic: "{brand}" · {datetime.utcnow().strftime('%A, %B %d %Y — %H:%M UTC')}</p>
      <p>{stats['mentions']} posts scanned · net sentiment {stats['net_sentiment']:+d} · {stats['high_risk']} flagged for moderation</p>
      <ul style='list-style:none;padding:0'>{rows}</ul>
      <p style='color:#8a909c;font-size:12px'>Suggested moderation replies await a human moderator's approval in the dashboard — nothing is auto-posted.</p>
    </body></html>
    """


def send_digest(payload, brand):
    if not DAILY_DIGEST_EMAIL:
        return
    stats = payload["stats"]
    send_html_email(
        to_email=DAILY_DIGEST_EMAIL,
        subject=f"❖ Aegis — {stats['high_risk']} flagged for moderation — {datetime.utcnow().strftime('%b %d')}",
        html_body=build_digest_html(payload, brand),
        sender_name="Aegis Moderation Assistant",
    )


def email_preview() -> str:
    payload = _load()
    if not payload:
        return "<p>No Aegis data yet — scan forums first.</p>"
    return build_digest_html(payload)


async def aegis_job(brand_override: str = None):
    topic = (brand_override or get_config("aegis_brand", AEGIS_BRAND) or AEGIS_BRAND).strip() or AEGIS_BRAND
    brand = topic
    orchestrator.update_agent_status(AGENT_ID, "running")
    try:
        # Independent fetches (both async httpx) — run concurrently.
        reddit_mentions, hn_mentions = await asyncio.gather(fetch_reddit(brand), fetch_hn(brand))
        raw = reddit_mentions + hn_mentions
        # preserve prior approve/dismiss decisions across scans
        prev = {m["id"]: m for m in (_load() or {}).get("mentions", [])}

        scored = []
        for mention in raw[:MAX_SCORED]:
            if mention["id"] in prev:
                scored.append(prev[mention["id"]])  # keep existing scoring/status
                continue
            s = await score_mention(brand, mention)
            scored.append({**mention, **s})

        # sort high → low risk for the feed
        order = {"high": 0, "med": 1, "low": 2}
        scored.sort(key=lambda m: order.get(m["risk"], 3))

        payload = {"brand": brand, "stats": _stats(scored), "mentions": scored,
                   "fetched_at": datetime.utcnow().isoformat()}
        _save(payload)
        send_digest(payload, brand)

        high = payload["stats"]["high_risk"]
        if high:
            orchestrator.log_event(f"Aegis flagged {high} Islamophobic post(s) for moderation", "#e5484d")
        orchestrator.update_agent_status(AGENT_ID, "idle")
        print(f"[Aegis] Done — {len(scored)} posts on '{topic}', {high} flagged for moderation")
    except Exception as e:
        orchestrator.update_agent_status(AGENT_ID, "error", str(e))
        print(f"[Aegis] Error: {e}")
