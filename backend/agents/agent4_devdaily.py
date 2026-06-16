import os
import json
import asyncio
from datetime import datetime, timedelta
import httpx

from database import SessionLocal, AgentData
from llm_client import generate_completion
from orchestrator import orchestrator
from email_utils import send_html_email

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")


async def fetch_github_trending(language: str = "", count: int = 5):
    """Fetch trending GitHub repos. Supports language filter and count config."""
    last_week = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
    query = f"created:>{last_week}"
    if language:
        query += f" language:{language}"

    url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page={count}"

    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=15.0)
            response.raise_for_status()
            items = response.json().get("items", [])[:count]
            return [
                {
                    "name": item["full_name"],
                    "description": item.get("description", "No description"),
                    "stars": item["stargazers_count"],
                    "url": item["html_url"],
                    "language": item.get("language", "Unknown")
                } for item in items
            ]
        except Exception as e:
            print(f"[GitHub Trending] Error fetching GitHub trending: {e}")
            return []


async def fetch_devto_articles(topic: str = "", count: int = 5):
    """Fetch Dev.to articles. Supports topic filter and count config."""
    url = f"https://dev.to/api/articles?top=1&per_page={count}"
    if topic:
        url += f"&tag={topic}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=15.0)
            response.raise_for_status()
            items = response.json()
            return [
                {
                    "title": item["title"],
                    "description": item.get("description", ""),
                    "url": item["url"],
                    "reactions": item.get("public_reactions_count", 0)
                } for item in items[:count]
            ]
        except Exception as e:
            print(f"[GitHub Trending] Error fetching Dev.to articles: {e}")
            return []


def send_devdaily_email(github_repos, devto_articles, llm_summary):
    """Sends the GitHub Trending digest email."""
    if not DAILY_DIGEST_EMAIL:
        return

    html_content = f"""
    <html>
      <head>
        <style>
          body {{ font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }}
          .container {{ max-width: 600px; margin: 0 auto; }}
          h1 {{ color: #10b981; }}
          h2 {{ color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
          .item {{ padding: 12px; background: #1e293b; border-radius: 8px; margin-bottom: 8px; }}
          .item a {{ color: #60a5fa; text-decoration: none; font-weight: bold; }}
          .item .meta {{ color: #94a3b8; font-size: 0.85em; margin-top: 4px; }}
          .summary {{ background: #1e293b; border-left: 3px solid #10b981; padding: 16px; border-radius: 8px; margin: 16px 0; }}
        </style>
      </head>
      <body>
        <div class="container">
          <h1>💻 GitHub Trending Digest</h1>
          <p style="color:#94a3b8;">{datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}</p>

          <div class="summary">{llm_summary}</div>

          <h2>🔥 GitHub Trending</h2>
          {''.join([f'''
          <div class="item">
            <a href="{r['url']}">{r['name']}</a> <span style="color:#f59e0b;">⭐ {r['stars']}</span>
            <div class="meta">{r.get('language', '')} — {r['description']}</div>
          </div>''' for r in github_repos])}

          <h2>📝 Dev.to Top Articles</h2>
          {''.join([f'''
          <div class="item">
            <a href="{a['url']}">{a['title']}</a> <span style="color:#ef4444;">❤️ {a['reactions']}</span>
            <div class="meta">{a['description']}</div>
          </div>''' for a in devto_articles])}
        </div>
      </body>
    </html>
    """

    send_html_email(DAILY_DIGEST_EMAIL, "GitHub Trending Developer Digest", html_content, sender_name="GitHub Trending Agent")


async def devdaily_job(language: str = "", count: int = 5, topic: str = ""):
    """
    Main GitHub Trending job. Supports user-configurable parameters:
    - language: filter GitHub repos by language (e.g., 'python')
    - count: number of results to fetch (default 5)
    - topic: filter Dev.to articles by topic/tag (e.g., 'ai')
    """
    orchestrator.update_agent_status("devdaily", "running")
    try:
        # Independent fetches (both async httpx) — run concurrently.
        github_repos, devto_articles = await asyncio.gather(
            fetch_github_trending(language=language, count=count),
            fetch_devto_articles(topic=topic, count=count),
        )

        # Prepare content for LLM summary — isolated so a failure doesn't abort
        # the job before the digest (already fetched) gets saved.
        llm_summary = ""
        try:
            repo_names = [f"{r['name']} ({r.get('language', 'N/A')})" for r in github_repos]
            article_titles = [a["title"] for a in devto_articles]
            prompt = (
                f"Summarize today's best developer learning opportunities as 3-5 bullet points. Each bullet starts with '• ' on its own line, max 12 words, crisp and specific. No paragraphs, no intro/outro text. "
                f"Top GitHub repos: {', '.join(repo_names)}. "
                f"Top Dev.to articles: {', '.join(article_titles)}. "
                f"Focus on key trends and actionable takeaways."
            )
            llm_summary = await generate_completion(
                prompt,
                system_prompt="You are an expert developer advocate writing a daily learning digest."
            )
        except Exception as e:
            print(f"[GitHub Trending] LLM summary failed: {e}")

        payload = {
            "github_repos": github_repos,
            "devto_articles": devto_articles,
            "llm_summary": llm_summary,
            "config": {"language": language, "count": count, "topic": topic}
        }

        db = SessionLocal()
        existing = db.query(AgentData).filter_by(agent_name="devdaily", key="digest").first()
        val = json.dumps(payload)

        if existing:
            existing.value = val
        else:
            db.add(AgentData(agent_name="devdaily", key="digest", value=val))
        db.commit()
        db.close()

        # Send real email
        send_devdaily_email(github_repos, devto_articles, llm_summary)

        orchestrator.update_agent_status("devdaily", "idle")
    except Exception as e:
        orchestrator.update_agent_status("devdaily", "error", str(e))
