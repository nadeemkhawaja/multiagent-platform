import os
import json
from datetime import datetime, timedelta
from googleapiclient.discovery import build

from database import SessionLocal, AgentData
from llm_client import generate_completion
from orchestrator import orchestrator
from email_utils import send_html_email

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL")


async def fetch_youtube_videos(query: str, max_results: int = 5):
    if not YOUTUBE_API_KEY:
        print("[AI-Times] Missing YOUTUBE_API_KEY")
        return []

    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        published_after = (datetime.utcnow() - timedelta(days=2)).isoformat() + "Z"

        request = youtube.search().list(
            part="snippet",
            q=query,
            type="video",
            order="viewCount",
            videoDuration="medium",
            maxResults=max_results,
            publishedAfter=published_after,
            relevanceLanguage="en"
        )
        response = request.execute()

        videos = []
        for item in response.get("items", []):
            videos.append({
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "date": item["snippet"]["publishedAt"],
                "thumbnail": item["snippet"]["thumbnails"]["high"]["url"],
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}"
            })
        return videos
    except Exception as e:
        print(f"[AI-Times] Error fetching YouTube videos: {e}")
        return []


def send_digest_email(news_videos, personality_videos):
    """Sends the daily HTML digest email with AI news and personality videos."""
    if not DAILY_DIGEST_EMAIL:
        print("[AI-Times] No DAILY_DIGEST_EMAIL configured.")
        return

    html_content = f"""
    <html>
      <head>
        <style>
          body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }}
          .container {{ max-width: 600px; margin: 0 auto; }}
          h1 {{ color: #60a5fa; }}
          h2 {{ color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
          .video {{ margin-bottom: 16px; padding: 12px; background: #1e293b; border-radius: 8px; }}
          .video a {{ color: #60a5fa; text-decoration: none; font-weight: bold; }}
          .video .meta {{ color: #94a3b8; font-size: 0.85em; margin-top: 4px; }}
        </style>
      </head>
      <body>
        <div class="container">
          <h1>📰 AI-Times Daily Digest</h1>
          <p style="color:#94a3b8;">Generated on {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}</p>

          <h2>🔬 Latest AI News</h2>
          {''.join([f'''
          <div class="video">
            <a href="{v['url']}">{v['title']}</a>
            <div class="meta">{v['channel']} &bull; {v['date'][:10]}</div>
          </div>''' for v in news_videos])}

          <h2>🎤 Personality / Interviews</h2>
          {''.join([f'''
          <div class="video">
            <a href="{v['url']}">{v['title']}</a>
            <div class="meta">{v['channel']} &bull; {v['date'][:10]}</div>
          </div>''' for v in personality_videos])}
        </div>
      </body>
    </html>
    """

    send_html_email(DAILY_DIGEST_EMAIL, "AI-Times Daily Digest", html_content)


async def ai_times_job():
    orchestrator.update_agent_status("ai_times", "running")
    try:
        news_videos = await fetch_youtube_videos("AI news", 5)
        personality_videos = await fetch_youtube_videos("AI personality interview", 5)

        # Save to DB for dashboard
        db = SessionLocal()
        existing = db.query(AgentData).filter_by(agent_name="ai_times", key="videos").first()
        val = json.dumps({"news": news_videos, "personality": personality_videos})

        if existing:
            existing.value = val
        else:
            db.add(AgentData(agent_name="ai_times", key="videos", value=val))
        db.commit()
        db.close()

        # Send real email
        send_digest_email(news_videos, personality_videos)

        orchestrator.update_agent_status("ai_times", "idle")
    except Exception as e:
        orchestrator.update_agent_status("ai_times", "error", str(e))
