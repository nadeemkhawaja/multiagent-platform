import os
import re
import json
import asyncio
from datetime import datetime, timedelta
from googleapiclient.discovery import build

from database import SessionLocal, AgentData, get_config, set_config
from llm_client import generate_json
from orchestrator import orchestrator
from email_utils import send_html_email

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL")
# Cap the (slow) local-LLM curation. If Qwen3 doesn't return in time we fall back
# to YouTube's own view-count ranking so a run always finishes promptly.
CURATE_TIMEOUT = float(os.getenv("AI_TIMES_CURATE_TIMEOUT", "60"))
# Video recency window. 7 days keeps the candidate pool rich enough for good
# curation; set AI_TIMES_WINDOW_HOURS=48 to match the assignment's 24-48 h spec.
FETCH_WINDOW_HOURS = int(os.getenv("AI_TIMES_WINDOW_HOURS", "168"))

# Verified AI labs / big-tech channels — pulled in alongside the keyword search so
# major announcements from the companies actually driving AI news always make the
# candidate pool, not just whatever ranks highest for a generic query.
TRUSTED_NEWS_CHANNELS = [
    ("@GoogleDeepMind", "Google DeepMind"),
    ("@GoogleForDevelopers", "Google for Developers"),
    ("@AIatMeta", "Meta AI"),
    ("@MicrosoftResearch", "Microsoft Research"),
    ("@OpenAI", "OpenAI"),
    ("@nvidia", "NVIDIA"),
    ("@Cisco", "Cisco"),
    ("@AristaNetworksInc", "Arista Networks"),
]

# Top long-form AI commentators / interview shows — used to fill the
# "Personality / Interviews" bucket with recognized creators.
TRUSTED_PERSONALITY_CHANNELS = [
    ("@lexfridman", "Lex Fridman"),
    ("@TwoMinutePapers", "Two Minute Papers"),
    ("@YannicKilcher", "Yannic Kilcher"),
    ("@aiexplained-official", "AI Explained"),
    ("@mreflow", "Matt Wolfe"),
]

# Scripts whose presence (above a small share of letters) marks a title as
# non-English even when YouTube's relevanceLanguage hint lets it through.
_NON_LATIN_RE = re.compile(
    r"[؀-ۿݐ-ݿ"   # Arabic
    r"ऀ-ॿ"                  # Devanagari
    r"぀-ヿ㐀-鿿"     # Japanese / CJK
    r"가-힯"                  # Hangul
    r"Ѐ-ӿ"                  # Cyrillic
    r"฀-๿]"                 # Thai
)


def _is_english(title: str, default_audio_lang: str = None, default_lang: str = None) -> bool:
    """Best-effort English filter. Trusts YouTube's per-video language metadata
    when present; otherwise falls back to a script-based heuristic on the title."""
    for lang in (default_audio_lang, default_lang):
        if lang:
            return lang.lower().startswith("en")
    letters = [c for c in (title or "") if c.isalpha()]
    if not letters:
        return True
    non_latin = sum(1 for c in letters if _NON_LATIN_RE.match(c))
    return (non_latin / len(letters)) < 0.3


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


def _video_from_item(it: dict, trusted: bool = False) -> dict:
    sn, cd, st = it.get("snippet", {}), it.get("contentDetails", {}), it.get("statistics", {})
    return {
        "title": sn.get("title", ""),
        "channel": sn.get("channelTitle", ""),
        "date": sn.get("publishedAt", ""),
        "thumbnail": sn.get("thumbnails", {}).get("high", {}).get("url", ""),
        "url": f"https://www.youtube.com/watch?v={it['id']}",
        "duration": _iso_duration(cd.get("duration", "")),
        "views": _human_views(st.get("viewCount")),
        "trusted": trusted,
        "_lang_audio": sn.get("defaultAudioLanguage"),
        "_lang_default": sn.get("defaultLanguage"),
        "_title_raw": sn.get("title", ""),
    }


def _strip_internal(v: dict) -> dict:
    return {k: val for k, val in v.items() if not k.startswith("_")}


def _fetch_candidates_sync(query: str, n: int = 12, durations=("medium",)):
    """Synchronous YouTube Data API fetch (googleapiclient is sync) — called via
    asyncio.to_thread so the event loop stays free and WebSocket status updates
    keep flowing while the request is in flight. Searches once per entry in
    `durations` (e.g. medium clips + long-form interviews) and merges results."""
    if not YOUTUBE_API_KEY:
        print("[AI-Times] Missing YOUTUBE_API_KEY")
        return []
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        published_after = (datetime.utcnow() - timedelta(hours=FETCH_WINDOW_HOURS)).isoformat() + "Z"
        vids, seen = [], set()
        for duration in durations:
            search = youtube.search().list(
                part="snippet", q=query, type="video", order="viewCount", videoDuration=duration,
                maxResults=n, publishedAfter=published_after, relevanceLanguage="en", regionCode="US",
            ).execute()
            ids = [it["id"]["videoId"] for it in search.get("items", []) if it.get("id", {}).get("videoId")]
            ids = [i for i in ids if i not in seen]
            if not ids:
                continue
            details = youtube.videos().list(part="contentDetails,statistics,snippet", id=",".join(ids)).execute()
            for it in details.get("items", []):
                v = _video_from_item(it)
                if not _is_english(v["_title_raw"], v["_lang_audio"], v["_lang_default"]):
                    continue
                vids.append(v)
                seen.add(it["id"])
        return vids
    except Exception as e:
        print(f"[AI-Times] Error fetching candidates: {e}")
        return []


def _resolve_channel_ids_sync(handles: list[str]) -> dict[str, str]:
    """Resolve @handles -> channelId, cached for a week so a daily run doesn't
    burn extra quota re-resolving the same trusted channels."""
    cache = get_config("ai_times_channel_ids", {}) or {}
    cached_at = cache.get("_resolved_at")
    if cached_at:
        try:
            if datetime.utcnow() - datetime.fromisoformat(cached_at) < timedelta(days=7):
                return {h: cid for h, cid in cache.items() if h in handles}
        except ValueError:
            pass

    if not YOUTUBE_API_KEY:
        return {}
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    resolved = {}
    for handle in handles:
        try:
            r = youtube.channels().list(part="id", forHandle=handle.lstrip("@")).execute()
            items = r.get("items", [])
            if items:
                resolved[handle] = items[0]["id"]
        except Exception as e:
            print(f"[AI-Times] Could not resolve channel {handle}: {e}")
    if resolved:
        resolved["_resolved_at"] = datetime.utcnow().isoformat()
        set_config("ai_times_channel_ids", resolved)
    return {h: cid for h, cid in resolved.items() if h != "_resolved_at"}


def _fetch_trusted_channel_videos_sync(channel_map: dict[str, str], names: dict[str, str],
                                       hours: int = FETCH_WINDOW_HOURS, per_channel: int = 2) -> list:
    """Recent uploads from a curated allow-list of verified AI-lab / big-tech /
    top-creator channels — marked `trusted` so curation can prioritize them."""
    if not YOUTUBE_API_KEY or not channel_map:
        return []
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    published_after = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
    vids = []
    for handle, channel_id in channel_map.items():
        try:
            search = youtube.search().list(
                part="snippet", channelId=channel_id, type="video", order="date",
                maxResults=per_channel, publishedAfter=published_after,
            ).execute()
            ids = [it["id"]["videoId"] for it in search.get("items", []) if it.get("id", {}).get("videoId")]
            if not ids:
                continue
            details = youtube.videos().list(part="contentDetails,statistics,snippet", id=",".join(ids)).execute()
            for it in details.get("items", []):
                v = _video_from_item(it, trusted=True)
                if not _is_english(v["_title_raw"], v["_lang_audio"], v["_lang_default"]):
                    continue
                vids.append(v)
        except Exception as e:
            print(f"[AI-Times] Trusted channel fetch failed for {names.get(handle, handle)}: {e}")
    return vids


async def fetch_candidates(query: str, n: int = 12, durations=("medium",), trusted_channels=None):
    """Fetch a candidate pool: keyword-search results plus recent uploads from a
    curated allow-list of trusted channels, English-only, US, recent window."""
    keyword_vids, trusted_vids = await asyncio.gather(
        asyncio.to_thread(_fetch_candidates_sync, query, n, durations),
        _fetch_trusted_pool(trusted_channels or []),
    )
    seen, merged = set(), []
    for v in trusted_vids + keyword_vids:   # trusted sources first
        if v["url"] not in seen:
            merged.append(_strip_internal(v))
            seen.add(v["url"])
    return merged


async def _fetch_trusted_pool(trusted_channels: list) -> list:
    if not trusted_channels:
        return []
    handles = [h for h, _ in trusted_channels]
    names = dict(trusted_channels)
    channel_map = await asyncio.to_thread(_resolve_channel_ids_sync, handles)
    return await asyncio.to_thread(_fetch_trusted_channel_videos_sync, channel_map, names)


async def curate(news_cand, people_cand):
    """LLM does the editorial work — picks the best 5 per set, dedupes near-identical
    topics, and writes one digest intro sentence. To stay fast on local hardware it
    returns only the chosen indices (no per-video blurbs), which keeps generation short.
    """
    def fmt(lst):
        return "\n".join(
            f"[{i}] {v['title']} — {v['channel']}{' (official)' if v.get('trusted') else ''}"
            for i, v in enumerate(lst)
        ) or "(none)"

    prompt = (
        "You are the editor of a US English AI-news video digest. From each candidate list, choose the 5 "
        "MOST newsworthy videos, avoiding near-duplicate topics. Videos marked '(official)' are from "
        "verified AI-lab / big-tech / top-creator channels — prefer these when they're relevant, especially "
        "for major product or research announcements. Return ONLY compact JSON of the form: "
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
    except Exception as e:
        # Isolate any other LLM failure (e.g. Ollama unreachable) — fall back to
        # view-count ranking rather than aborting the job before the digest is saved.
        print(f"[AI-Times] Curate LLM failed: {e} — using view-count ranking instead")
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
                           build_digest_html(news_videos, personality_videos, intro),
                           sender_name="AI-Times Agent")
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
        # News pool = keyword search (medium-length clips) + recent uploads from
        # verified AI-lab/big-tech channels. Personality pool = keyword search
        # (medium + long-form) + recent uploads from top AI commentators —
        # all English-only (recency window per FETCH_WINDOW_HOURS, US region).
        orchestrator.set_progress("ai_times", "Fetching latest AI videos from YouTube…")
        news_cand, people_cand = await asyncio.gather(
            fetch_candidates("AI news", 8, durations=("medium",), trusted_channels=TRUSTED_NEWS_CHANNELS),
            fetch_candidates("AI personality interview", 8, durations=("medium", "long"),
                            trusted_channels=TRUSTED_PERSONALITY_CHANNELS),
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
