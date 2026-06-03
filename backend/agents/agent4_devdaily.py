import os
import json
import httpx
from datetime import datetime, timedelta
from database import SessionLocal, AgentData
from llm_client import generate_completion
from orchestrator import orchestrator

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

async def fetch_github_trending():
    # GitHub REST API doesn't have a direct "trending" endpoint, so we search for repos created in the last 7 days sorted by stars
    last_week = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
    query = f"created:>{last_week}"
    url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc"
    
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
        
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            items = response.json().get("items", [])[:5]
            return [
                {
                    "name": item["full_name"],
                    "description": item["description"],
                    "stars": item["stargazers_count"],
                    "url": item["html_url"]
                } for item in items
            ]
        except Exception as e:
            print(f"Error fetching GitHub trending: {e}")
            return []

async def fetch_devto_articles():
    url = "https://dev.to/api/articles?top=1&per_page=5"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            items = response.json()
            return [
                {
                    "title": item["title"],
                    "description": item["description"],
                    "url": item["url"],
                    "reactions": item["public_reactions_count"]
                } for item in items
            ]
        except Exception as e:
            print(f"Error fetching Dev.to articles: {e}")
            return []

async def devdaily_job():
    orchestrator.update_agent_status("devdaily", "running")
    try:
        github_repos = await fetch_github_trending()
        devto_articles = await fetch_devto_articles()
        
        # Prepare content for LLM summary
        repo_names = [r["name"] for r in github_repos]
        article_titles = [a["title"] for a in devto_articles]
        
        prompt = f"Write a 3-sentence summary of today's best learning opportunities based on these top GitHub repos: {repo_names} and top Dev.to articles: {article_titles}."
        llm_summary = await generate_completion(prompt, system_prompt="You are an expert developer advocate.")
        
        payload = {
            "github_repos": github_repos,
            "devto_articles": devto_articles,
            "llm_summary": llm_summary
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
        
        print("Would send DevDaily digest email.")
        
        orchestrator.update_agent_status("devdaily", "idle")
    except Exception as e:
        orchestrator.update_agent_status("devdaily", "error", str(e))
