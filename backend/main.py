from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
import asyncio

import httpx

from database import init_db, SessionLocal, AgentData, get_config, set_config, all_config
from orchestrator import orchestrator, AGENT_META, AGENT_ORDER
from llm_client import OLLAMA_BASE_URL, LLM_MODEL, get_llm_state
from ws import manager

from agents import agent1_ai_times, agent2_mailman, agent3_wallstreet_wolf
from agents import agent4_devdaily, agent5_compass as compass_mod, agent6_aegis

ai_times_job = agent1_ai_times.ai_times_job
mailman_job = agent2_mailman.mailman_job
wallstreet_wolf_job = agent3_wallstreet_wolf.wallstreet_wolf_job
devdaily_job = agent4_devdaily.devdaily_job
compass_job = compass_mod.compass_job
aegis_job = agent6_aegis.aegis_job

scheduler = AsyncIOScheduler()

JOBS = {
    "ai_times": ai_times_job, "mailman": mailman_job, "wallstreet_wolf": wallstreet_wolf_job,
    "compass": compass_job, "aegis": aegis_job, "devdaily": devdaily_job,
}
DEFAULT_SCHEDULES = {
    "ai_times":        {"type": "cron", "hour": 8, "minute": 0},
    "mailman":         {"type": "interval", "minutes": 60},
    "wallstreet_wolf": {"type": "interval", "minutes": 60},
    "compass":         {"type": "interval", "minutes": 60},
    "aegis":           {"type": "interval", "minutes": 60},
    "devdaily":        {"type": "cron", "hour": 9, "minute": 0},
}
PREVIEW = {
    "ai_times": agent1_ai_times.email_preview,
    "mailman": agent2_mailman.email_preview,
    "wallstreet_wolf": agent3_wallstreet_wolf.email_preview,
    "compass": compass_mod.email_preview,
    "aegis": agent6_aegis.email_preview,
}


def _apply_schedule(agent_id: str, cfg: dict):
    try:
        scheduler.remove_job(agent_id)
    except Exception:
        pass
    job = JOBS[agent_id]
    if cfg.get("type") == "cron":
        scheduler.add_job(job, "cron", hour=cfg.get("hour", 8), minute=cfg.get("minute", 0), id=agent_id)
    else:
        scheduler.add_job(job, "interval", minutes=cfg.get("minutes", 15), id=agent_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    for aid, job in JOBS.items():
        orchestrator.register_agent_job(aid, job)
        cfg = get_config(f"schedule_{aid}", DEFAULT_SCHEDULES[aid])
        _apply_schedule(aid, cfg)

    scheduler.start()
    orchestrator.start_sampler()
    orchestrator.start_watchdog()
    yield
    scheduler.shutdown()


app = FastAPI(title="Auto-Scheduling Platform Orchestrator", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ─── WebSocket ───────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({"type": "state", "data": orchestrator.get_state()}, default=str))
        while True:
            await websocket.receive_text()  # keep-alive / ignore client msgs
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# ─── System ──────────────────────────────────────────────────────────
@app.get("/api/system/resources")
async def get_system_resources():
    return orchestrator.get_system_resources()


@app.get("/api/system/agents")
async def get_agents_status():
    return orchestrator.get_agents_status()


@app.get("/api/state")
async def get_state():
    return orchestrator.get_state()


@app.get("/api/health")
async def health():
    ollama_ok = False
    models = []
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get(f"{OLLAMA_BASE_URL}/api/tags")
            ollama_ok = r.status_code == 200
            if ollama_ok:
                models = [m.get("name") for m in r.json().get("models", [])]
    except Exception:
        ollama_ok = False
    db_ok = True
    try:
        SessionLocal().execute  # noqa
        db = SessionLocal(); db.query(AgentData).first(); db.close()
    except Exception:
        db_ok = False
    llm = get_llm_state()
    return {
        "status": "ok" if (db_ok) else "degraded",
        "ollama": {"reachable": ollama_ok, "model": LLM_MODEL, "available": models},
        "database": db_ok,
        "llm": {"calls": llm["calls"], "cache_hits": llm["cache_hits"]},
    }


# ─── Demo ────────────────────────────────────────────────────────────
class SpikeRequest(BaseModel):
    resource: Optional[str] = "cpu"


class CrashRequest(BaseModel):
    agent_id: Optional[str] = None


@app.post("/api/demo/spike")
async def demo_spike(req: Optional[SpikeRequest] = None):
    return orchestrator.spike((req.resource if req else None) or "cpu")


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


# ─── Agent data ──────────────────────────────────────────────────────
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


@app.get("/api/agent/{agent_name}/email-preview")
async def email_preview(agent_name: str):
    fn = PREVIEW.get(agent_name)
    if not fn:
        return {"html": "<p>No email preview for this agent.</p>"}
    try:
        return {"html": fn()}
    except Exception as e:
        return {"html": f"<p>Preview error: {e}</p>"}


# ─── Triggers ────────────────────────────────────────────────────────
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
        task = asyncio.create_task(devdaily_job(language=cfg.language, count=cfg.count, topic=cfg.topic))
    elif agent_name == "mailman":
        task = asyncio.create_task(mailman_job(key_people_override=cfg.key_people, send_email=cfg.send_email))
    elif agent_name == "aegis":
        task = asyncio.create_task(aegis_job(brand_override=cfg.brand or None))
    elif agent_name in JOBS:
        task = asyncio.create_task(JOBS[agent_name]())
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


# ─── Schedules (editable from the UI) ────────────────────────────────
@app.get("/api/schedules")
async def get_schedules():
    out = {}
    for aid in AGENT_ORDER:
        cfg = get_config(f"schedule_{aid}", DEFAULT_SCHEDULES[aid])
        job = scheduler.get_job(aid)
        out[aid] = {
            "name": AGENT_META[aid]["n"],
            "config": cfg,
            "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
        }
    return out


class ScheduleUpdate(BaseModel):
    type: str               # 'interval' | 'cron'
    minutes: Optional[int] = None
    hour: Optional[int] = None
    minute: Optional[int] = None


@app.post("/api/schedules/{agent_name}")
async def set_schedule(agent_name: str, body: ScheduleUpdate):
    if agent_name not in JOBS:
        return {"error": "Agent not found"}
    cfg: Dict[str, Any] = {"type": body.type}
    if body.type == "cron":
        cfg["hour"] = body.hour if body.hour is not None else 8
        cfg["minute"] = body.minute if body.minute is not None else 0
    else:
        cfg["minutes"] = max(1, body.minutes or 15)
    set_config(f"schedule_{agent_name}", cfg)
    _apply_schedule(agent_name, cfg)
    orchestrator.log_event(f"{AGENT_META[agent_name]['n']} schedule updated", "#7c5cf6")
    return {"status": "updated", "config": cfg}


# ─── Config (settings) ───────────────────────────────────────────────
@app.get("/api/config")
async def get_settings():
    import os
    cfg = all_config()
    return {
        "recipient": cfg.get("recipient", os.getenv("DAILY_DIGEST_EMAIL", "")),
        "key_people": cfg.get("key_people", os.getenv("KEY_PEOPLE", "")),
        "watchlist": cfg.get("watchlist", ""),
        "aegis_brand": cfg.get("aegis_brand", os.getenv("AEGIS_BRAND", "Anthropic")),
    }


@app.post("/api/config")
async def update_settings(body: Dict[str, Any]):
    for k, v in body.items():
        if k in ("recipient", "key_people", "watchlist", "aegis_brand"):
            set_config(k, v)
    orchestrator.log_event("Settings updated", "#7c5cf6")
    return await get_settings()


# ─── Aegis actions ───────────────────────────────────────────────────
class AegisReply(BaseModel):
    id: str
    reply: Optional[str] = None


@app.post("/api/aegis/approve")
async def aegis_approve(req: AegisReply):
    return agent6_aegis.approve_mention(req.id, req.reply)


@app.post("/api/aegis/dismiss")
async def aegis_dismiss(req: AegisReply):
    return agent6_aegis.dismiss_mention(req.id)


# ─── LLM test ────────────────────────────────────────────────────────
from llm_client import generate_completion


class PromptRequest(BaseModel):
    prompt: str


@app.post("/api/test-llm")
async def test_llm(request: PromptRequest):
    return {"response": await generate_completion(request.prompt)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5174, reload=True)
