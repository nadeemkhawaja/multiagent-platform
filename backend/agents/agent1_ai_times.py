import os
import re
import json
from datetime import datetime, timedelta
from googleapiclient.discovery import build

from database import SessionLocal, AgentData
from llm_client import generate_json
from orchestrator import orchestrator
from email_utils import send_html_email

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL")


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
    """LLM picks the best 5 per set, dedupes, writes a 'why it matters' + a digest intro."""
    def fmt(lst):
        return "\n".join(f"[{i}] {v['title']} — {v['channel']}" for i, v in enumerate(lst)) or "(none)"

    prompt = (
        "You are the editor of a US English AI-news video digest. From each candidate list, choose the 5 "
        "MOST newsworthy, non-duplicate videos. Return ONLY JSON of the form: "
        '{"intro":"one engaging sentence","news":[{"i":<index>,"why":"<=12 words"}],'
        '"personality":[{"i":<index>,"why":"<=12 words"}]}. Pick exactly 5 in each list.\n\n'
        f"NEWS CANDIDATES:\n{fmt(news_cand)}\n\nPERSONALITY CANDIDATES:\n{fmt(people_cand)}"
    )
    data = await generate_json(prompt, system_prompt="You are a precise news editor. Return only JSON.",
                               agent_id="ai_times", use_cache=False)

    def pick(cands, key):
        out = []
        if isinstance(data, dict) and isinstance(data.get(key), list):
            for item in data[key]:
                try:
                    i = int(item.get("i"))
                    if 0 <= i < len(cands):
                        out.append({**cands[i], "why": str(item.get("why", ""))[:120]})
                except (TypeError, ValueError):
                    continue
        # fallback / top-up to 5
        seen = {v["url"] for v in out}
        for v in cands:
            if len(out) >= 5:
                break
            if v["url"] not in seen:
                out.append({**v, "why": v.get("why", "")})
                seen.add(v["url"])
        return out[:5]

    intro = data.get("intro", "") if isinstance(data, dict) else ""
    return intro, pick(news_cand, "news"), pick(people_cand, "personality")


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
    if not DAILY_DIGEST_EMAIL:
        print("[AI-Times] No DAILY_DIGEST_EMAIL configured.")
        return
    send_html_email(DAILY_DIGEST_EMAIL, "AI-Times Daily Digest",
                    build_digest_html(news_videos, personality_videos, intro))


def email_preview() -> str:
    db = SessionLocal()
    rec = db.query(AgentData).filter_by(agent_name="ai_times", key="videos").first()
    db.close()
    data = json.loads(rec.value) if rec else {"news": [], "personality": [], "intro": ""}
    return build_digest_html(data.get("news", []), data.get("personality", []), data.get("intro", ""))


async def ai_times_job():
    orchestrator.update_agent_status("ai_times", "running")
    try:
        news_cand = await fetch_candidates("AI news", 12)
        people_cand = await fetch_candidates("AI personality interview", 12)
        intro, news_videos, personality_videos = await curate(news_cand, people_cand)

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

        send_digest_email(news_videos, personality_videos, intro)
        orchestrator.update_agent_status("ai_times", "idle")
        print(f"[AI-Times] Done — {len(news_videos)} news + {len(personality_videos)} personality (LLM-curated)")
    except Exception as e:
        orchestrator.update_agent_status("ai_times", "error", str(e))
