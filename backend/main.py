from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional
import json
import asyncio

from database import init_db, SessionLocal, AgentData
from orchestrator import orchestrator

from agents.agent1_ai_times import ai_times_job
from agents.agent2_mailman import mailman_job
from agents.agent3_wallstreet_wolf import wallstreet_wolf_job
from agents.agent4_devdaily import devdaily_job

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()

    # Register agent jobs for watchdog restart capability
    orchestrator.register_agent_job("ai_times", ai_times_job)
    orchestrator.register_agent_job("mailman", mailman_job)
    orchestrator.register_agent_job("wallstreet_wolf", wallstreet_wolf_job)
    orchestrator.register_agent_job("devdaily", devdaily_job)

    # Schedule agents
    scheduler.add_job(ai_times_job, 'cron', hour=8, minute=0, id='ai_times')
    scheduler.add_job(mailman_job, 'interval', minutes=15, id='mailman')
    scheduler.add_job(wallstreet_wolf_job, 'cron', hour=17, minute=0, id='wallstreet_wolf')
    scheduler.add_job(devdaily_job, 'cron', hour=9, minute=0, id='devdaily')

    scheduler.start()

    # Start watchdog for automatic crashed agent restart
    orchestrator.start_watchdog()

    yield
    # Shutdown
    scheduler.shutdown()


app = FastAPI(title="Auto-Scheduling Platform Orchestrator", lifespan=lifespan)

# Security: Restrict CORS to the frontend origin only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── System Endpoints ───────────────────────────────────────────────

@app.get("/api/system/resources")
async def get_system_resources():
    return orchestrator.get_system_resources()


@app.get("/api/system/agents")
async def get_agents_status():
    return orchestrator.get_agents_status()


# ─── Agent Data Endpoints ───────────────────────────────────────────

@app.get("/api/agent/{agent_name}/data")
async def get_agent_data(agent_name: str):
    db = SessionLocal()
    records = db.query(AgentData).filter_by(agent_name=agent_name).all()
    db.close()

    data = {}
    for r in records:
        try:
            data[r.key] = json.loads(r.value)
        except (json.JSONDecodeError, TypeError):
            data[r.key] = r.value
    return data


# ─── Agent Trigger Endpoints ────────────────────────────────────────

class DevDailyConfig(BaseModel):
    language: Optional[str] = ""
    count: Optional[int] = 5
    topic: Optional[str] = ""


@app.post("/api/agent/{agent_name}/trigger")
async def trigger_agent(agent_name: str, config: Optional[DevDailyConfig] = None):
    if agent_name == "devdaily":
        cfg = config or DevDailyConfig()
        asyncio.create_task(devdaily_job(
            language=cfg.language,
            count=cfg.count,
            topic=cfg.topic
        ))
        return {"status": f"Triggered {agent_name} with config: lang={cfg.language}, count={cfg.count}, topic={cfg.topic}"}

    job_map = {
        "ai_times": ai_times_job,
        "mailman": mailman_job,
        "wallstreet_wolf": wallstreet_wolf_job,
    }

    if agent_name in job_map:
        asyncio.create_task(job_map[agent_name]())
        return {"status": f"Triggered {agent_name}"}

    return {"error": "Agent not found"}


# ─── LLM Test Endpoint ──────────────────────────────────────────────

from llm_client import generate_completion


class PromptRequest(BaseModel):
    prompt: str


@app.post("/api/test-llm")
async def test_llm(request: PromptRequest):
    response = await generate_completion(request.prompt)
    return {"response": response}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
