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
from agents.agent5_market_direction import compass_job
from agents.agent6_aegis import aegis_job, approve_mention, dismiss_mention

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    orchestrator.register_agent_job("ai_times", ai_times_job)
    orchestrator.register_agent_job("mailman", mailman_job)
    orchestrator.register_agent_job("wallstreet_wolf", wallstreet_wolf_job)
    orchestrator.register_agent_job("compass", compass_job)
    orchestrator.register_agent_job("aegis", aegis_job)
    orchestrator.register_agent_job("devdaily", devdaily_job)

    # Schedules (match the design's cadence)
    scheduler.add_job(ai_times_job,         'cron',     hour=8,  minute=0,  id='ai_times')
    scheduler.add_job(mailman_job,          'interval', minutes=15,         id='mailman')
    scheduler.add_job(wallstreet_wolf_job,  'interval', minutes=5,          id='wallstreet_wolf')
    scheduler.add_job(compass_job,          'interval', minutes=30,         id='compass')
    scheduler.add_job(aegis_job,            'interval', minutes=10,         id='aegis')
    scheduler.add_job(devdaily_job,         'cron',     hour=9,  minute=0,  id='devdaily')

    scheduler.start()
    orchestrator.start_watchdog()

    yield
    scheduler.shutdown()


app = FastAPI(title="Auto-Scheduling Platform Orchestrator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── System Endpoints ────────────────────────────────────────────────

@app.get("/api/system/resources")
async def get_system_resources():
    return orchestrator.get_system_resources()


@app.get("/api/system/agents")
async def get_agents_status():
    return orchestrator.get_agents_status()


@app.get("/api/state")
async def get_state():
    """Full orchestrator snapshot consumed by the dashboard (res, agents, llm, events, alarm)."""
    return orchestrator.get_state()


# ─── Demo Endpoints (drive the dashboard's alarm/crash buttons) ──────

class SpikeRequest(BaseModel):
    resource: Optional[str] = "cpu"


class CrashRequest(BaseModel):
    agent_id: Optional[str] = None


@app.post("/api/demo/spike")
async def demo_spike(req: Optional[SpikeRequest] = None):
    r = (req.resource if req else None) or "cpu"
    return orchestrator.spike(r)


@app.post("/api/demo/crash")
async def demo_crash(req: Optional[CrashRequest] = None):
    import random
    aid = req.agent_id if req else None
    if not aid:
        live = [k for k, v in orchestrator.get_agents_status().items() if v["status"] != "error"]
        aid = random.choice(live) if live else None
    if not aid:
        return {"error": "no agent to crash"}
    return orchestrator.crash(aid)


# ─── Agent Data Endpoints ────────────────────────────────────────────

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


# ─── Agent Trigger Endpoints ─────────────────────────────────────────
running_tasks = {}


class AgentTriggerConfig(BaseModel):
    language: Optional[str] = ""
    count: Optional[int] = 5
    topic: Optional[str] = ""
    key_people: Optional[str] = ""
    send_email: Optional[bool] = False
    brand: Optional[str] = ""


@app.post("/api/agent/{agent_name}/trigger")
async def trigger_agent(agent_name: str, config: Optional[AgentTriggerConfig] = None):
    cfg = config or AgentTriggerConfig()

    if agent_name in running_tasks and not running_tasks[agent_name].done():
        running_tasks[agent_name].cancel()

    if agent_name == "devdaily":
        task = asyncio.create_task(devdaily_job(
            language=cfg.language, count=cfg.count, topic=cfg.topic
        ))
    elif agent_name == "mailman":
        task = asyncio.create_task(mailman_job(
            key_people_override=cfg.key_people, send_email=cfg.send_email
        ))
    elif agent_name == "aegis":
        task = asyncio.create_task(aegis_job(brand_override=cfg.brand or None))
    else:
        job_map = {
            "ai_times":        ai_times_job,
            "wallstreet_wolf": wallstreet_wolf_job,
            "compass":         compass_job,
        }
        if agent_name in job_map:
            task = asyncio.create_task(job_map[agent_name]())
        else:
            return {"error": "Agent not found"}

    running_tasks[agent_name] = task
    return {"status": f"Triggered {agent_name}"}


@app.post("/api/agent/{agent_name}/stop")
async def stop_agent(agent_name: str):
    if agent_name in running_tasks and not running_tasks[agent_name].done():
        running_tasks[agent_name].cancel()
        orchestrator.update_agent_status(agent_name, "idle")
        return {"status": f"Stopped {agent_name}"}
    return {"status": f"{agent_name} is not running"}


# ─── Aegis Actions (human-in-the-loop reply approval) ────────────────

class AegisReply(BaseModel):
    id: str
    reply: Optional[str] = None


@app.post("/api/aegis/approve")
async def aegis_approve(req: AegisReply):
    return approve_mention(req.id, req.reply)


@app.post("/api/aegis/dismiss")
async def aegis_dismiss(req: AegisReply):
    return dismiss_mention(req.id)


# ─── LLM Test Endpoint ───────────────────────────────────────────────

from llm_client import generate_completion


class PromptRequest(BaseModel):
    prompt: str


@app.post("/api/test-llm")
async def test_llm(request: PromptRequest):
    response = await generate_completion(request.prompt)
    return {"response": response}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5174, reload=True)
