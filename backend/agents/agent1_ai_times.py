import os
import json
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from googleapiclient.discovery import build

from database import SessionLocal, AgentData
from llm_client import generate_completion
from orchestrator import orchestrator

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL")

async def fetch_youtube_videos(query: str, max_results: int = 5):
    if not YOUTUBE_API_KEY:
        print("Missing YOUTUBE_API_KEY")
        return []
    
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        published_after = (datetime.utcnow() - timedelta(days=2)).isoformat() + "Z"
        
        request = youtube.search().list(
            part="snippet",
            q=query,
            type="video",
            order="date",
            maxResults=max_results,
            publishedAfter=published_after
        )
        response = request.execute()
        
        videos = []
        for item in response.get("items", []):
            videos.append({
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "date": item["snippet"]["publishedAt"],
                "thumbnail": item["snippet"]["thumbnails"]["default"]["url"],
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}"
            })
        return videos
    except Exception as e:
        print(f"Error fetching YouTube videos: {e}")
        return []

def send_digest_email(news_videos, personality_videos):
    if not DAILY_DIGEST_EMAIL:
        return

    html_content = f"""
    <html>
      <body>
        <h2>AI-Times Daily Digest</h2>
        <h3>Latest AI News</h3>
        <ul>
            {''.join([f"<li><a href='{v['url']}'>{v['title']}</a> by {v['channel']}</li>" for v in news_videos])}
        </ul>
        <h3>Latest AI Personality Interviews</h3>
        <ul>
            {''.join([f"<li><a href='{v['url']}'>{v['title']}</a> by {v['channel']}</li>" for v in personality_videos])}
        </ul>
      </body>
    </html>
    """
    
    # In a real scenario, configure SMTP here
    print(f"Would send email to {DAILY_DIGEST_EMAIL} with HTML content.")

async def ai_times_job():
    orchestrator.update_agent_status("ai_times", "running")
    try:
        news_videos = await fetch_youtube_videos("AI news", 5)
        personality_videos = await fetch_youtube_videos("AI personality interview", 5)
        
        # Save to DB for dashboard
        db = SessionLocal()
        
        # We store as JSON strings in the key-value store
        existing = db.query(AgentData).filter_by(agent_name="ai_times", key="videos").first()
        val = json.dumps({"news": news_videos, "personality": personality_videos})
        
        if existing:
            existing.value = val
        else:
            new_data = AgentData(agent_name="ai_times", key="videos", value=val)
            db.add(new_data)
        db.commit()
        db.close()
        
        # Send Email
        send_digest_email(news_videos, personality_videos)
        
        orchestrator.update_agent_status("ai_times", "idle")
    except Exception as e:
        orchestrator.update_agent_status("ai_times", "error", str(e))
