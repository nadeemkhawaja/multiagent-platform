import os
import re
import json
import asyncio
from datetime import datetime, timedelta
from googleapiclient.discovery import build

from database import SessionLocal, AgentData
from llm_client import generate_json
from orchestrator import orchestrator
from email_utils import send_html_email

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL")
# Cap the (slow) local-LLM curation. If Qwen3 doesn't return in time we fall back
# to YouTube's own view-count ranking so a run always finishes promptly.
CURATE_TIMEOUT = float(os.getenv("AI_TIMES_CURATE_TIMEOUT", "60"))


def _iso_duration(s: str) -> str:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return ""
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return f"{h}:{mi:02d}:{se:02d}" if h else f"{mi}:{se:02d}"


def _human_views(n) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


async def fetch_candidates(query: str, n: int = 12):
    """Fetch a candidate pool with real duration + view counts (US / English, last 7 days)."""
    if not YOUTUBE_API_KEY:
        print("[AI-Times] Missing YOUTUBE_API_KEY")
        return []
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        published_after = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
        search = youtube.search().list(
            part="snippet", q=query, type="video", order="viewCount", videoDuration="medium",
            maxResults=n, publishedAfter=published_after, relevanceLanguage="en", regionCode="US",
        ).execute()
        ids = [it["id"]["videoId"] for it in search.get("items", []) if it.get("id", {}).get("videoId")]
        if not ids:
            return []
        details = youtube.videos().list(part="contentDetails,statistics,snippet", id=",".join(ids)).execute()
        vids = []
        for it in details.get("items", []):
            sn, cd, st = it.get("snippet", {}), it.get("contentDetails", {}), it.get("statistics", {})
            vids.append({
                "title": sn.get("title", ""),
                "channel": sn.get("channelTitle", ""),
                "date": sn.get("publishedAt", ""),
                "thumbnail": sn.get("thumbnails", {}).get("high", {}).get("url", ""),
                "url": f"https://www.youtube.com/watch?v={it['id']}",
                "duration": _iso_duration(cd.get("duration", "")),
                "views": _human_views(st.get("viewCount")),
            })
        return vids
    except Exception as e:
        print(f"[AI-Times] Error fetching candidates: {e}")
        return []


async def curate(news_cand, people_cand):
    """LLM does the editorial work — picks the best 5 per set, dedupes near-identical
    topics, and writes one digest intro sentence. To stay fast on local hardware it
    returns only the chosen indices (no per-video blurbs), which keeps generation short.
    """
    def fmt(lst):
        return "\n".join(f"[{i}] {v['title']} — {v['channel']}" for i, v in enumerate(lst)) or "(none)"

    prompt = (
        "You are the editor of a US English AI-news video digest. From each candidate list, choose the 5 "
        "MOST newsworthy videos, avoiding near-duplicate topics. Return ONLY compact JSON of the form: "
        '{"intro":"one engaging sentence","news":[<index>,<index>,<index>,<index>,<index>],'
        '"personality":[<index>,<index>,<index>,<index>,<index>]}. '
        "Each array holds exactly 5 candidate indices. Do not add any other keys or text.\n\n"
        f"NEWS CANDIDATES:\n{fmt(news_cand)}\n\nPERSONALITY CANDIDATES:\n{fmt(people_cand)}"
    )
    llm_ok = True
    try:
        data = await asyncio.wait_for(
            generate_json(prompt, system_prompt="You are a precise news editor. Return only JSON.",
                          agent_id="ai_times", use_cache=False),
            timeout=CURATE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print(f"[AI-Times] Curate LLM exceeded {CURATE_TIMEOUT:.0f}s — using view-count ranking instead")
        data = None
        llm_ok = False

    def pick(cands, key):
        out, seen = [], set()
        # Accept either a list of indices [3,1,7] or legacy [{"i":3}, ...].
        if isinstance(data, dict) and isinstance(data.get(key), list):
            for item in data[key]:
                try:
                    i = int(item.get("i")) if isinstance(item, dict) else int(item)
                except (TypeError, ValueError):
                    continue
                if 0 <= i < len(cands) and cands[i]["url"] not in seen:
                    out.append(dict(cands[i]))
                    seen.add(cands[i]["url"])
        # fallback / top-up to 5 using candidate order (YouTube view-count rank)
        for v in cands:
            if len(out) >= 5:
                break
            if v["url"] not in seen:
                out.append(dict(v))
                seen.add(v["url"])
        return out[:5]

    intro = data.get("intro", "") if isinstance(data, dict) else ""
    return intro, pick(news_cand, "news"), pick(people_cand, "personality"), llm_ok


def build_digest_html(news_videos, personality_videos, intro=""):
    def rows(vids):
        return "".join(f'''
          <div class="video">
            <a href="{v.get('url','')}">{v.get('title','')}</a>
            <div class="meta">{v.get('channel','')} &bull; {v.get('date','')[:10]} &bull; {v.get('views','')}
              {f"&bull; {v['duration']}" if v.get('duration') else ''}</div>
            {f'<div class="why">{v["why"]}</div>' if v.get('why') else ''}
          </div>''' for v in vids)

    return f"""
    <html><head><style>
      body {{ font-family:'Segoe UI',Tahoma,sans-serif; background:#0f172a; color:#f8fafc; padding:20px; }}
      .container {{ max-width:600px; margin:0 auto; }}
      h1 {{ color:#60a5fa; }} h2 {{ color:#94a3b8; border-bottom:1px solid #334155; padding-bottom:8px; }}
      .intro {{ color:#cbd5e1; font-style:italic; margin:8px 0 16px; }}
      .video {{ margin-bottom:16px; padding:12px; background:#1e293b; border-radius:8px; }}
      .video a {{ color:#60a5fa; text-decoration:none; font-weight:bold; }}
      .video .meta {{ color:#94a3b8; font-size:.85em; margin-top:4px; }}
      .video .why {{ color:#a5b4fc; font-size:.85em; margin-top:6px; }}
    </style></head><body><div class="container">
      <h1>📰 AI-Times Daily Digest</h1>
      <p style="color:#94a3b8;">Generated {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}</p>
      {f'<div class="intro">{intro}</div>' if intro else ''}
      <h2>🔬 Latest AI News</h2>{rows(news_videos)}
      <h2>🎤 Personality / Interviews</h2>{rows(personality_videos)}
    </div></body></html>
    """


def send_digest_email(news_videos, personality_videos, intro=""):
    """Returns (sent: bool, recipient: str). sent=False if no recipient/credentials."""
    if not DAILY_DIGEST_EMAIL:
        print("[AI-Times] No DAILY_DIGEST_EMAIL configured.")
        return False, ""
    sent = send_html_email(DAILY_DIGEST_EMAIL, "AI-Times Daily Digest",
                           build_digest_html(news_videos, personality_videos, intro))
    return bool(sent), DAILY_DIGEST_EMAIL


def email_preview() -> str:
    db = SessionLocal()
    rec = db.query(AgentData).filter_by(agent_name="ai_times", key="videos").first()
    db.close()
    data = json.loads(rec.value) if rec else {"news": [], "personality": [], "intro": ""}
    return build_digest_html(data.get("news", []), data.get("personality", []), data.get("intro", ""))


async def ai_times_job():
    orchestrator.update_agent_status("ai_times", "running")
    try:
        # 1) Fetch both candidate pools concurrently (was sequential — ~2x faster).
        orchestrator.set_progress("ai_times", "Fetching latest AI videos from YouTube…")
        news_cand, people_cand = await asyncio.gather(
            fetch_candidates("AI news", 8),
            fetch_candidates("AI personality interview", 8),
        )

        # 2) Curate with the local LLM (the slow step — serialized Qwen3 inference).
        orchestrator.set_progress("ai_times", f"Curating top 5 + 5 with Qwen3 (up to {CURATE_TIMEOUT:.0f}s)…")
        intro, news_videos, personality_videos, llm_ok = await curate(news_cand, people_cand)

        # 3) Persist the snapshot.
        orchestrator.set_progress("ai_times", "Saving digest…")
        db = SessionLocal()
        existing = db.query(AgentData).filter_by(agent_name="ai_times", key="videos").first()
        val = json.dumps({"news": news_videos, "personality": personality_videos,
                          "intro": intro, "generated_at": datetime.utcnow().isoformat()})
        if existing:
            existing.value = val
        else:
            db.add(AgentData(agent_name="ai_times", key="videos", value=val))
        db.commit()
        db.close()

        # 4) Email the HTML digest.
        orchestrator.set_progress("ai_times", "Sending digest email…")
        sent, recipient = send_digest_email(news_videos, personality_videos, intro)

        n, m = len(news_videos), len(personality_videos)
        rank = "LLM-curated" if llm_ok else "view-ranked (LLM timed out)"
        if sent:
            result = f"✓ Digest emailed to {recipient} · {n} news + {m} personality · {rank}"
        else:
            result = f"✓ Digest ready · {n} news + {m} personality · {rank} · email skipped (no recipient/SMTP configured)"
        orchestrator.set_progress("ai_times", None, result=result)
        orchestrator.update_agent_status("ai_times", "idle")
        print(f"[AI-Times] Done — {n} news + {m} personality · {rank} · emailed={sent}")
    except Exception as e:
        orchestrator.update_agent_status("ai_times", "error", str(e))
