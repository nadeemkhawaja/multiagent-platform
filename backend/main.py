from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
import asyncio

import httpx

from database import init_db, SessionLocal, AgentData, AgentRun, get_config, set_config, all_config
from orchestrator import orchestrator, AGENT_META, AGENT_ORDER, CORE_AGENTS
from llm_client import (OLLAMA_BASE_URL, LLM_MODEL, get_llm_state, provider_status,
                        parse_model_spec, KNOWN_PROVIDERS, SUGGESTED_MODELS)
from ws import manager
import approvals
import memory
import mcp_client
import paper_broker
import tools as tool_registry

from agents import agent1_ai_times, agent2_mailman, agent3_wallstreet_wolf
from agents import agent4_devdaily, agent5_compass as compass_mod
from agents import agent7_strategy_scout
from agents import agent8_capitol_tracker
from agents import agent9_morning_brief
from agents import agent10_options_flow
from agents import agent11_earnings_calendar
from agents import agent12_cisco_pulse
from agents import agent13_alpha_wolf

ai_times_job        = agent1_ai_times.ai_times_job
mailman_job         = agent2_mailman.mailman_job
wallstreet_wolf_job = agent3_wallstreet_wolf.wallstreet_wolf_job
devdaily_job        = agent4_devdaily.devdaily_job
compass_job         = compass_mod.compass_job
strategy_scout_job  = agent7_strategy_scout.strategy_scout_job
capitol_tracker_job = agent8_capitol_tracker.capitol_tracker_job
morning_brief_job   = agent9_morning_brief.morning_brief_job
options_flow_job    = agent10_options_flow.options_flow_job
earnings_cal_job    = agent11_earnings_calendar.earnings_calendar_job
cisco_pulse_job     = agent12_cisco_pulse.cisco_pulse_job
alpha_wolf_job      = agent13_alpha_wolf.alpha_wolf_job

scheduler = AsyncIOScheduler()

JOBS = {
    "ai_times":        ai_times_job,
    "mailman":         mailman_job,
    "wallstreet_wolf": wallstreet_wolf_job,
    "compass":         compass_job,
    "devdaily":        devdaily_job,
    "strategy_scout":  strategy_scout_job,
    "capitol_tracker": capitol_tracker_job,
    "morning_brief":   morning_brief_job,
    "options_flow":    options_flow_job,
    "earnings_cal":    earnings_cal_job,
    "cisco_pulse":     cisco_pulse_job,
    "alpha_wolf":      alpha_wolf_job,
}
DEFAULT_SCHEDULES = {
    "ai_times":        {"type": "cron",     "hour": 8,  "minute": 0},
    "mailman":         {"type": "interval", "minutes": 60},
    "wallstreet_wolf": {"type": "interval", "minutes": 120},
    "compass":         {"type": "interval", "minutes": 60},
    "devdaily":        {"type": "cron",     "hour": 9,  "minute": 0},
    "strategy_scout":  {"type": "cron",     "hour": 10, "minute": 0},
    "capitol_tracker": {"type": "cron",     "hour": 7,  "minute": 0},
    "morning_brief":   {"type": "cron",     "hour": 6,  "minute": 0},
    "options_flow":    {"type": "interval", "minutes": 120},
    "earnings_cal":    {"type": "interval", "minutes": 360},
    "cisco_pulse":     {"type": "cron",     "hour": 7,  "minute": 30},
    "alpha_wolf":      {"type": "cron",     "hour": 8,  "minute": 30},
}
PREVIEW = {
    "ai_times":        agent1_ai_times.email_preview,
    "mailman":         agent2_mailman.email_preview,
    "wallstreet_wolf": agent3_wallstreet_wolf.email_preview,
    "compass":         compass_mod.email_preview,
    "strategy_scout":  agent7_strategy_scout.email_preview,
    "capitol_tracker": agent8_capitol_tracker.email_preview,
    "morning_brief":   agent9_morning_brief.email_preview,
    "options_flow":    agent10_options_flow.email_preview,
    "earnings_cal":    agent11_earnings_calendar.email_preview,
    "cisco_pulse":     agent12_cisco_pulse.email_preview,
    "alpha_wolf":      agent13_alpha_wolf.email_preview,
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
    # Demo mode (persisted): pause non-core agents so only the four graded
    # agents are scheduled during a recording — no extras firing mid-demo.
    if orchestrator.demo_mode:
        for aid in AGENT_ORDER:
            if aid not in CORE_AGENTS:
                try:
                    scheduler.pause_job(aid)
                except Exception:
                    pass
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


class DemoModeRequest(BaseModel):
    enabled: bool = False


@app.get("/api/demo/mode")
async def get_demo_mode():
    return {"enabled": orchestrator.demo_mode, "core_agents": CORE_AGENTS}


@app.post("/api/demo/mode")
async def set_demo_mode(req: DemoModeRequest):
    """Toggle demo mode. On → pause every non-core agent's schedule so only the
    four graded agents run; off → resume the full fleet."""
    enabled = orchestrator.set_demo_mode(req.enabled)
    extras = [a for a in AGENT_ORDER if a not in CORE_AGENTS]
    for aid in extras:
        try:
            scheduler.pause_job(aid) if enabled else scheduler.resume_job(aid)
        except Exception:
            pass
    return {"enabled": enabled, "core_agents": CORE_AGENTS, "paused": extras if enabled else []}


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


# ─── Per-agent AI assistant ──────────────────────────────────────────
class AssistRequest(BaseModel):
    prompt: str
    include_data: Optional[bool] = True


@app.post("/api/agent/{agent_name}/assist")
async def agent_assist(agent_name: str, body: AssistRequest):
    """Ad-hoc AI help inside an agent tab: answers the user's request using the
    agent's latest stored data as context, on the agent's configured model."""
    if agent_name not in AGENT_META:
        return {"error": "Agent not found"}
    question = (body.prompt or "").strip()
    if not question:
        return {"error": "prompt is required"}

    context = ""
    if body.include_data:
        from database import get_agent_data as load_agent_data
        data = load_agent_data(agent_name) or {}
        context = json.dumps(data, default=str)[:7000]

    meta = AGENT_META[agent_name]
    system = (f"You are the AI assistant embedded in the '{meta['n']}' agent ({meta['desc']}) "
              f"of a multi-agent platform. Help the user with ad-hoc analysis and manual tasks "
              f"using the agent's latest data below. Be concise, concrete, and plain-text.")
    prompt = (f"AGENT DATA (latest stored output of {meta['n']}, JSON, may be truncated):\n"
              f"{context or '(no data yet — the agent has not run)'}\n\n"
              f"USER REQUEST:\n{question}")
    try:
        from llm_client import generate_completion as _gen
        response = await _gen(prompt, system_prompt=system, agent_id=agent_name, use_cache=False)
        # the LLM client returns failures as "Error: …" strings — surface them as errors
        if isinstance(response, str) and response.startswith("Error:"):
            return {"error": response}
        return {"response": response}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


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
        "capitol_politicians": cfg.get("capitol_politicians", ""),
        "capitol_months": cfg.get("capitol_months", "2"),
        "require_email_approval": bool(cfg.get("require_email_approval", False)),
    }


@app.post("/api/config")
async def update_settings(body: Dict[str, Any]):
    for k, v in body.items():
        if k in ("recipient", "key_people", "watchlist", "capitol_politicians",
                 "capitol_months", "require_email_approval"):
            set_config(k, v)
    orchestrator.log_event("Settings updated", "#7c5cf6")
    return await get_settings()


# ─── Alpha Wolf paper trading ────────────────────────────────────────
@app.get("/api/alpha-wolf/portfolio")
async def alpha_wolf_portfolio(refresh: bool = False):
    """Portfolio snapshot: settings, equity summary, open positions, trade log.
    refresh=true re-marks positions at live prices before returning."""
    return await paper_broker.portfolio_view(refresh_prices=refresh)


class ExecutionSettings(BaseModel):
    enabled: Optional[bool] = None
    capital: Optional[float] = None
    position_pct: Optional[float] = None
    max_positions: Optional[int] = None


@app.post("/api/alpha-wolf/execution")
async def alpha_wolf_execution(body: ExecutionSettings):
    settings = paper_broker.save_settings(body.enabled, body.capital,
                                          body.position_pct, body.max_positions)
    if body.enabled is not None:
        orchestrator.log_event(
            f"Alpha Wolf paper-trade execution {'enabled' if settings['enabled'] else 'disabled'}", "#7c3aed")
    return {"status": "saved", "settings": settings}


@app.post("/api/alpha-wolf/portfolio/reset")
async def alpha_wolf_portfolio_reset():
    out = paper_broker.reset_portfolio()
    orchestrator.log_event("Alpha Wolf paper portfolio reset to starting capital", "#7c3aed")
    return out


# ─── Run history & metrics ───────────────────────────────────────────
def _run_to_dict(r: AgentRun) -> dict:
    return {
        "id": r.id, "agent_id": r.agent_id, "status": r.status, "error": r.error,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "duration_s": round((r.finished_at - r.started_at).total_seconds(), 1)
                      if r.started_at and r.finished_at else None,
        "llm_calls": r.llm_calls or 0,
        "tokens_in": r.tokens_in or 0,
        "tokens_out": r.tokens_out or 0,
        "llm_ms": r.llm_ms or 0,
        "stages": json.loads(r.stages) if r.stages else {},
    }


@app.get("/api/agent/{agent_name}/runs")
async def get_agent_runs(agent_name: str, k: int = 20):
    db = SessionLocal()
    rows = (db.query(AgentRun).filter_by(agent_id=agent_name)
            .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
            .limit(min(k, 200)).all())
    db.close()
    return {"runs": [_run_to_dict(r) for r in rows]}


@app.get("/api/metrics")
async def get_metrics(window: int = 50):
    """Per-agent aggregates over each agent's last `window` runs."""
    db = SessionLocal()
    out = {}
    for aid in AGENT_ORDER:
        rows = (db.query(AgentRun).filter_by(agent_id=aid)
                .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
                .limit(min(window, 500)).all())
        if not rows:
            continue
        finished = [r for r in rows if r.finished_at]
        errors = sum(1 for r in rows if r.status == "error")
        durations = [(r.finished_at - r.started_at).total_seconds() for r in finished]
        out[aid] = {
            "name": AGENT_META[aid]["n"],
            "runs": len(rows),
            "errors": errors,
            "success_rate": round((len(rows) - errors) / len(rows), 3),
            "avg_duration_s": round(sum(durations) / len(durations), 1) if durations else None,
            "llm_calls": sum(r.llm_calls or 0 for r in rows),
            "tokens_in": sum(r.tokens_in or 0 for r in rows),
            "tokens_out": sum(r.tokens_out or 0 for r in rows),
            "llm_ms": sum(r.llm_ms or 0 for r in rows),
        }
    db.close()
    return {"window": window, "agents": out}


# ─── LLM providers & per-agent models ────────────────────────────────
@app.get("/api/llm/providers")
async def llm_providers():
    return {
        "default_model": LLM_MODEL,
        "providers": provider_status(),
        "agent_models": get_config("agent_models", {}) or {},
        "suggested_models": SUGGESTED_MODELS,
    }


class AgentModelUpdate(BaseModel):
    agent_id: str
    model: str = ""    # "provider:model" or bare ollama model; empty clears the override


@app.post("/api/llm/models")
async def set_agent_model(body: AgentModelUpdate):
    if body.agent_id not in AGENT_ORDER:
        return {"error": f"unknown agent '{body.agent_id}'"}
    overrides = get_config("agent_models", {}) or {}
    if body.model:
        provider, _ = parse_model_spec(body.model)
        if provider not in KNOWN_PROVIDERS:
            return {"error": f"unknown provider in '{body.model}'"}
        overrides[body.agent_id] = body.model
    else:
        overrides.pop(body.agent_id, None)
    set_config("agent_models", overrides)
    orchestrator.log_event(
        f"{AGENT_META[body.agent_id]['n']} model → {body.model or 'default'}", "#7c5cf6")
    return {"agent_models": overrides}


class ProviderKeyUpdate(BaseModel):
    provider: str
    api_key: str = ""  # empty clears the UI-stored key (.env fallback still applies)


@app.post("/api/llm/keys")
async def set_provider_key(body: ProviderKeyUpdate):
    prov = body.provider.lower().strip()
    if prov not in ("openai", "anthropic", "grok"):
        return {"error": f"unknown provider '{body.provider}'"}
    keys = get_config("provider_keys", {}) or {}
    if body.api_key.strip():
        keys[prov] = body.api_key.strip()
    else:
        keys.pop(prov, None)
    set_config("provider_keys", keys)
    orchestrator.log_event(
        f"{prov} API key {'saved' if body.api_key.strip() else 'cleared'} in Settings", "#7c5cf6")
    return {"providers": provider_status()}


# ─── Tool registry ───────────────────────────────────────────────────
@app.get("/api/tools")
async def list_tools():
    return {"tools": tool_registry.all_tools()}


class ToolCallRequest(BaseModel):
    tool: str
    arguments: Optional[Dict[str, Any]] = None


@app.post("/api/tools/call")
async def call_tool(body: ToolCallRequest):
    try:
        return {"result": await tool_registry.call(body.tool, body.arguments)}
    except tool_registry.ToolError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ─── Approvals (human-in-the-loop) ───────────────────────────────────
@app.get("/api/approvals")
async def get_approvals(status: Optional[str] = None, k: int = 50):
    return {"approvals": approvals.list_approvals(status=status, k=min(k, 200))}


class ApprovalDecision(BaseModel):
    note: Optional[str] = None


@app.post("/api/approvals/{approval_id}/approve")
async def approve(approval_id: int, body: Optional[ApprovalDecision] = None):
    return approvals.decide(approval_id, approved=True, note=body.note if body else None)


@app.post("/api/approvals/{approval_id}/deny")
async def deny(approval_id: int, body: Optional[ApprovalDecision] = None):
    return approvals.decide(approval_id, approved=False, note=body.note if body else None)


# ─── Agent memory ────────────────────────────────────────────────────
@app.get("/api/agent/{agent_name}/memories")
async def get_agent_memories(agent_name: str, k: int = 10, kind: Optional[str] = None):
    return {"memories": memory.recent(agent_name, k=min(k, 100), kind=kind)}


@app.post("/api/agent/{agent_name}/memories/recall")
async def recall_agent_memories(agent_name: str, body: Dict[str, Any]):
    query = str(body.get("query", "")).strip()
    if not query:
        return {"error": "query is required"}
    results = await memory.recall(agent_name, query, k=int(body.get("k", 5)),
                                  kind=body.get("kind"))
    return {"memories": results}


# ─── MCP servers ─────────────────────────────────────────────────────
def _mask_env(cfg: dict) -> dict:
    out = dict(cfg)
    # never expose secret values (env vars, auth headers) — keys only
    if "env" in cfg or "command" in cfg:
        out["env"] = sorted((cfg.get("env") or {}).keys())
    if "headers" in cfg or "url" in cfg:
        out["headers"] = sorted((cfg.get("headers") or {}).keys())
    return out


@app.get("/api/mcp")
async def mcp_status():
    servers = mcp_client.get_servers()
    return {
        "available": mcp_client.MCP_AVAILABLE,
        "servers": {name: _mask_env(cfg) for name, cfg in servers.items()},
    }


@app.get("/api/mcp/servers/{name}/tools")
async def mcp_server_tools(name: str):
    try:
        return {"tools": await mcp_client.list_tools(name)}
    except mcp_client.MCPError as e:
        return {"error": str(e)}


@app.get("/api/mcp/servers/{name}/ping")
async def mcp_server_ping(name: str):
    return await mcp_client.ping(name)


class MCPServerConfig(BaseModel):
    name: str
    command: Optional[str] = None       # local stdio server
    args: Optional[list] = None
    env: Optional[Dict[str, str]] = None
    url: Optional[str] = None           # remote streamable-HTTP server
    headers: Optional[Dict[str, str]] = None
    enabled: bool = True


@app.post("/api/mcp/servers")
async def mcp_add_server(body: MCPServerConfig):
    try:
        cfg = mcp_client.set_server(body.name, body.command, body.args, body.env,
                                    body.enabled, url=body.url, headers=body.headers)
    except mcp_client.MCPError as e:
        return {"error": str(e)}
    orchestrator.log_event(f"MCP server '{body.name}' registered", "#7c5cf6")
    return {"status": "saved", "server": _mask_env(cfg)}


@app.delete("/api/mcp/servers/{name}")
async def mcp_remove_server(name: str):
    if not mcp_client.remove_server(name):
        return {"error": f"server '{name}' not found"}
    orchestrator.log_event(f"MCP server '{name}' removed", "#7c5cf6")
    return {"status": "removed"}


class MCPCallRequest(BaseModel):
    server: str
    tool: str
    arguments: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = None


@app.post("/api/mcp/call")
async def mcp_call(body: MCPCallRequest):
    try:
        return await mcp_client.call_tool(
            body.server, body.tool, body.arguments,
            timeout=body.timeout or mcp_client.DEFAULT_TIMEOUT,
        )
    except mcp_client.MCPError as e:
        return {"error": str(e)}


# ─── Stress Test ─────────────────────────────────────────────────────
@app.post("/api/stress-test")
async def stress_test():
    """Trigger all agents simultaneously for load testing."""
    triggered = []
    for agent_name, job in JOBS.items():
        try:
            if agent_name in running_tasks and not running_tasks[agent_name].done():
                running_tasks[agent_name].cancel()
            if agent_name == "devdaily":
                task = asyncio.create_task(devdaily_job())
            elif agent_name == "mailman":
                task = asyncio.create_task(mailman_job())
            else:
                task = asyncio.create_task(job())
            running_tasks[agent_name] = task
            triggered.append(agent_name)
        except Exception as e:
            print(f"[StressTest] Failed to trigger {agent_name}: {e}")
    orchestrator.log_event(f"🔥 Stress test: {len(triggered)} agents triggered simultaneously", "#dc2626")
    return {"status": "stress_test_started", "triggered": triggered}


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
