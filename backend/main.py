from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager

from database import init_db
from orchestrator import orchestrator

# Import Agents here (to be implemented)
from agents.agent1_ai_times import ai_times_job
from agents.agent2_mailman import mailman_job
from agents.agent3_wallstreet_wolf import wallstreet_wolf_job
from agents.agent4_devdaily import devdaily_job

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    
    # Schedule agents
    scheduler.add_job(ai_times_job, 'cron', hour=8, minute=0, id='ai_times')
    scheduler.add_job(mailman_job, 'interval', minutes=15, id='mailman')
    scheduler.add_job(wallstreet_wolf_job, 'cron', hour=17, minute=0, id='wallstreet_wolf')
    scheduler.add_job(devdaily_job, 'cron', hour=9, minute=0, id='devdaily')
    
    scheduler.start()
    yield
    # Shutdown
    scheduler.shutdown()

app = FastAPI(title="Auto-Scheduling Platform Orchestrator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/system/resources")
async def get_system_resources():
    return orchestrator.get_system_resources()

@app.get("/api/system/agents")
async def get_agents_status():
    return orchestrator.get_agents_status()

# Database fetch endpoint for dashboard
from database import SessionLocal, AgentData
import json

@app.get("/api/agent/{agent_name}/data")
async def get_agent_data(agent_name: str):
    db = SessionLocal()
    records = db.query(AgentData).filter_by(agent_name=agent_name).all()
    db.close()
    
    data = {}
    for r in records:
        try:
            data[r.key] = json.loads(r.value)
        except:
            data[r.key] = r.value
    return data

@app.post("/api/agent/{agent_name}/trigger")
async def trigger_agent(agent_name: str):
    job_map = {
        "ai_times": ai_times_job,
        "mailman": mailman_job,
        "wallstreet_wolf": wallstreet_wolf_job,
        "devdaily": devdaily_job
    }
    
    if agent_name in job_map:
        # Run in background to avoid blocking
        import asyncio
        asyncio.create_task(job_map[agent_name]())
        return {"status": f"Triggered {agent_name}"}
    return {"error": "Agent not found"}

# Dummy test endpoint for LLM
from llm_client import generate_completion
from pydantic import BaseModel

class PromptRequest(BaseModel):
    prompt: str

@app.post("/api/test-llm")
async def test_llm(request: PromptRequest):
    response = await generate_completion(request.prompt)
    return {"response": response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
