from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import asyncio

import httpx

# get_agent_data is aliased: the route handler below is also named
# get_agent_data, and since Python resolves globals at call time the endpoint
# shadows the import for every caller inside this module.
from database import (init_db, SessionLocal, AgentData, AgentRun, get_config, set_config,
                      all_config, get_agent_data as load_agent_data,
                      reap_stale_runs, prune_history)
from orchestrator import orchestrator, AGENT_META, AGENT_ORDER, CORE_AGENTS
from llm_client import (LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL, get_llm_state, provider_status,
                        parse_model_spec, default_model_spec,
                        KNOWN_PROVIDERS, SUGGESTED_MODELS)
from ws import manager
import approvals
import memory
import mcp_client
import alpaca_broker as broker
import tools as tool_registry

from agents import agent3_wallstreet_wolf
from agents import agent13_alpha_wolf
from agents import agent14_technologia

wallstreet_wolf_job = agent3_wallstreet_wolf.wallstreet_wolf_job
alpha_wolf_job      = agent13_alpha_wolf.alpha_wolf_job
technologia_job     = agent14_technologia.technologia_job

# Market time, not laptop time. An unpinned AsyncIOScheduler uses the host
# timezone, so alpha_wolf's "08:30" cron fired at 08:30 CDT — 09:30 ET, the
# opening bell rather than the hour before it — and would silently move again on
# a machine set to another zone. Every agent already reasons in ET internally
# (ZoneInfo("America/New_York")); only the scheduler disagreed.
ET = ZoneInfo("America/New_York")
scheduler = AsyncIOScheduler(timezone=ET)

JOBS = {
    "wallstreet_wolf": wallstreet_wolf_job,
    "technologia":     technologia_job,
    "alpha_wolf":      alpha_wolf_job,
}
# Jobs whose scheduled run self-gates on the clock, so a manual Run must say so.
FORCEABLE_JOBS = {"technologia"}
# The three cadences are one design, not three independent ones:
#   Technologia  every 30 min, 08:00-16:15 ET — computes the cards.
#   Alpha Wolf   08:30 ET      — synthesizes the master plan ONCE, on cards it
#                                refreshes first (see ensure_fresh_cards) rather
#                                than on whatever the last run happened to leave.
#   Pulse        every 30 min, 08:00-16:30 ET — re-folds the latest cards into
#                                that same plan, re-prices, re-sizes, executes.
# The plan is therefore written once a day and kept current all day; a card the
# funnel produces at 10:40 is in Alpha Wolf's plan by 11:10 at the latest.
DEFAULT_SCHEDULES = {
    "wallstreet_wolf": {"type": "interval", "minutes": 120},
    "technologia":     {"type": "interval", "minutes": 30},
    "alpha_wolf":      {"type": "cron",     "hour": 8,  "minute": 30},
}
PREVIEW = {
    "wallstreet_wolf": agent3_wallstreet_wolf.email_preview,
    "technologia":     agent14_technologia.email_preview,
    "alpha_wolf":      agent13_alpha_wolf.email_preview,
}


def _apply_schedule(agent_id: str, cfg: dict):
    try:
        scheduler.remove_job(agent_id)
    except Exception:
        pass
    job = JOBS[agent_id]
    if cfg.get("type") == "cron":
        # Alpha Wolf places real (paper) orders — never worth running its plan
        # synthesis on a day the market can't trade anyway. IntervalTrigger has
        # no day_of_week concept, so this only applies to the cron branch.
        weekdays_only = {"day_of_week": "mon-fri"} if agent_id == "alpha_wolf" else {}
        # A once-a-day cron is one minute of exposure per day: if the process is
        # down, asleep or restarting at 08:30, APScheduler's 1-second default
        # grace drops the run and the day has no plan at all. That is exactly how
        # the plan went seven days stale while the agent looked healthy. Two hours
        # of grace, coalesced so a long outage still produces one run and not a
        # backlog.
        scheduler.add_job(job, "cron", hour=cfg.get("hour", 8), minute=cfg.get("minute", 0),
                          id=agent_id, misfire_grace_time=2 * 60 * 60, coalesce=True,
                          **weekdays_only)
    else:
        # Jitter so two interval agents cannot stay phase-locked. Wolf at 120min
        # and Technologia at 30min were registered in the same startup and landed
        # in the same second every two hours, doubling the upstream load at the
        # worst moment.
        scheduler.add_job(job, "interval", minutes=cfg.get("minutes", 15), id=agent_id,
                          jitter=90, misfire_grace_time=300, coalesce=True)


async def _catch_up_missed_plan():
    """Run Alpha Wolf's daily plan if today's slot passed without one.

    The plan is the agent's core artifact and it was rebuilt exactly once a day
    at a fixed minute. Miss that minute — a restart, a closed laptop — and the
    plan silently stayed as it was: it was seven days old while `pulse` and
    `portfolio` kept writing fresh rows, so every freshness signal in the UI said
    the agent was fine.
    """
    await asyncio.sleep(5)  # let the event loop and DB settle first
    try:
        now = datetime.now(ET)
        if now.weekday() >= 5:
            return
        # The plan run ends in broker.execute_plan(), so this can place
        # orders — restarting the backend must never do that on its own outside
        # the session. Inside market hours a missed plan is worth rebuilding;
        # outside them there is nothing to act on anyway and tomorrow's cron
        # will handle it.
        if not broker._market_open_now():
            return
        cfg = get_config("schedule_alpha_wolf", DEFAULT_SCHEDULES["alpha_wolf"])
        if cfg.get("type") != "cron":
            return
        slot = now.replace(hour=cfg.get("hour", 8), minute=cfg.get("minute", 30),
                           second=0, microsecond=0)
        if now < slot:
            return  # the scheduler will handle it normally
        plan = (load_agent_data("alpha_wolf") or {}).get("plan") or {}
        stamp = str(plan.get("generated_at") or "")
        if stamp.startswith(now.strftime("%Y-%m-%d")):
            return  # already ran today
        orchestrator.log_event("Alpha Wolf plan missing for today — running now", "#f59e0b")
        await JOBS["alpha_wolf"]()
    except Exception as e:
        print(f"[Startup] plan catch-up failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    for aid, job in JOBS.items():
        orchestrator.register_agent_job(aid, job)
        cfg = get_config(f"schedule_{aid}", DEFAULT_SCHEDULES[aid])
        _apply_schedule(aid, cfg)

    scheduler.start()
    # Reap runs abandoned by a previous process. Without this they sit at
    # status=running forever — 124 of them had accumulated — and any "is this
    # agent healthy" check reads a dead run as a live one.
    reap_stale_runs()
    prune_history()
    # If today's cron slot has already passed and the plan never ran, run it now.
    # A daily cron plus an overnight restart meant the day simply had no plan, and
    # nothing anywhere said so.
    asyncio.create_task(_catch_up_missed_plan())
    # Alpha Wolf pulse: in-session live check-in every 30 min (self-gates to
    # market hours) — syncs Technologia's newest cards into the master plan,
    # then alerts on new cards, slot openings, entry-zone and stop/target hits.
    scheduler.add_job(agent13_alpha_wolf.pulse_job, "interval", minutes=30, id="alpha_wolf_pulse",
                      jitter=60, misfire_grace_time=300, coalesce=True)
    # Paper-broker risk check: every 10 min during market hours, exit any open
    # position whose stop-loss or profit target has been crossed.
    scheduler.add_job(broker.risk_check, "interval", minutes=10, id="alpha_wolf_risk")
    # Demo mode (persisted): pause non-core agents so only the four graded
    # agents are scheduled during a recording — no extras firing mid-demo.
    if orchestrator.demo_mode:
        for aid in AGENT_ORDER:
            if aid not in CORE_AGENTS:
                try:
                    scheduler.pause_job(aid)
                except Exception:
                    pass
    orchestrator.start_broadcast()
    orchestrator.start_watchdog()
    yield
    scheduler.shutdown()


# Docs live under /api so they reach the browser through the dev server's
# single proxied prefix — the backend port itself is not exposed.
app = FastAPI(title="Auto-Scheduling Platform Orchestrator", lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
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
@app.get("/api/system/agents")
async def get_agents_status():
    return orchestrator.get_agents_status()


@app.get("/api/state")
async def get_state():
    return orchestrator.get_state()


@app.get("/api/health")
async def health():
    local_ok = False
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get(f"{LOCAL_LLM_BASE_URL}/models")
            local_ok = r.status_code == 200
    except Exception:
        local_ok = False
    db_ok = True
    try:
        SessionLocal().execute  # noqa
        db = SessionLocal(); db.query(AgentData).first(); db.close()
    except Exception:
        db_ok = False
    llm = get_llm_state()
    return {
        "status": "ok" if (db_ok) else "degraded",
        "local": {"reachable": local_ok, "model": LOCAL_LLM_MODEL, "base_url": LOCAL_LLM_BASE_URL},
        "database": db_ok,
        "llm": {"calls": llm["calls"], "cache_hits": llm["cache_hits"]},
    }


# ─── Demo ────────────────────────────────────────────────────────────
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


@app.post("/api/agent/{agent_name}/trigger")
async def trigger_agent(agent_name: str, config: Optional[AgentTriggerConfig] = None):
    cfg = config or AgentTriggerConfig()
    if agent_name in running_tasks and not running_tasks[agent_name].done():
        running_tasks[agent_name].cancel()

    if agent_name in JOBS:
        # A human pressing Run means it, so bypass any self-gating the job does on
        # the clock. Without this, triggering Technologia after the close would
        # look like a no-op button.
        job = JOBS[agent_name]
        task = asyncio.create_task(
            job(force=True) if agent_name in FORCEABLE_JOBS else job())
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
        if agent_name == "alpha_wolf":
            # Stored data can be stale (positions_meta only updates on the next
            # scheduled run/risk-check) — pull a live-refreshed portfolio view
            # so Lufi can correctly answer "did X hit target / is it closed".
            try:
                data = {**data, "portfolio": await broker.portfolio_view(refresh_prices=True)}
            except Exception:
                pass
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
        "watchlist": cfg.get("watchlist", ""),
    }


@app.post("/api/config")
async def update_settings(body: Dict[str, Any]):
    for k, v in body.items():
        if k in ("recipient", "watchlist"):
            set_config(k, v)
    orchestrator.log_event("Settings updated", "#7c5cf6")
    return await get_settings()


# ─── Alpha Wolf paper trading ────────────────────────────────────────
@app.get("/api/alpha-wolf/portfolio")
async def alpha_wolf_portfolio(refresh: bool = False):
    """Portfolio snapshot: settings, equity summary, open positions, trade log.
    refresh=true re-marks positions at live prices before returning."""
    return await broker.portfolio_view(refresh_prices=refresh)


class ExecutionSettings(BaseModel):
    enabled: Optional[bool] = None
    capital: Optional[float] = None
    position_pct: Optional[float] = None
    max_positions: Optional[int] = None
    max_hold_days: Optional[int] = None
    max_daily_loss_pct: Optional[float] = None
    risk_pct: Optional[float] = None
    min_rr: Optional[float] = None
    one_trade_per_symbol: Optional[bool] = None
    # The funnel's own grade replaces the LLM's self-rated confidence, which
    # used to gate execution — see docs/STRATEGY_REVIEW.md.
    min_grade: Optional[str] = None
    allow_shorts: Optional[bool] = None
    max_new_trades_per_day: Optional[int] = None


@app.post("/api/alpha-wolf/execution")
async def alpha_wolf_execution(body: ExecutionSettings):
    settings = broker.save_settings(body.enabled, body.capital,
                                          body.position_pct, body.max_positions, body.max_hold_days,
                                          body.max_daily_loss_pct, risk_pct=body.risk_pct,
                                          min_rr=body.min_rr,
                                          one_trade_per_symbol=body.one_trade_per_symbol,
                                          min_grade=body.min_grade,
                                          allow_shorts=body.allow_shorts,
                                          max_new_trades_per_day=body.max_new_trades_per_day)
    if body.enabled is not None:
        orchestrator.log_event(
            f"Alpha Wolf paper-trade execution {'enabled' if settings['enabled'] else 'disabled'}", "#7c3aed")
    if body.allow_shorts:
        orchestrator.log_event("Alpha Wolf: SHORTS re-enabled — the short side lost "
                               "$2,160 of the first account's $2,331", "#dc2626")
    return {"status": "saved", "settings": settings}


@app.post("/api/alpha-wolf/portfolio/reset")
async def alpha_wolf_portfolio_reset(local_only: bool = True):
    """Start over.

    `local_only` (the default) wipes everything this app stores about trading —
    portfolio, journal, trade log, position metadata, working orders, the plan
    and the risk baselines — and re-baselines return% against whatever the
    connected Alpaca account currently holds. It does NOT place or cancel a
    single order, which is what you want when the account itself is new or was
    replaced.

    `local_only=false` additionally asks Alpaca to cancel all open orders and
    close all open positions first. That submits real (paper) orders, so it is
    opt-in rather than the default.
    """
    out = await broker.reset_state(close_at_broker=not local_only)
    orchestrator.log_event(
        "Alpha Wolf reset — local trading state cleared"
        + ("" if local_only else " and broker positions flattened"), "#7c3aed")
    return out


@app.get("/api/alpha-wolf/now")
async def alpha_wolf_now():
    """Live decision snapshot: market clock, the entry window, and each funnel
    card scored against live quotes (WAIT / ACT / STOPPED / TARGET_HIT)."""
    return await agent13_alpha_wolf.decision_now()


@app.post("/api/alpha-wolf/pulse")
async def alpha_wolf_pulse(email: bool = True):
    """Run the in-session pulse check now (bypasses the market-hours gate)."""
    return await agent13_alpha_wolf.pulse_job(force=True, send_email=email)


@app.get("/api/alpha-wolf/journal")
async def alpha_wolf_journal(limit: int = 100):
    """Closed-trade journal + performance stats (win rate, profit factor,
    avg win/loss, P&L by exit reason)."""
    return broker.journal_view(limit=limit)


@app.post("/api/alpha-wolf/risk-check")
async def alpha_wolf_risk_check():
    """Run the stop/target enforcement pass now (bypasses the market-hours gate)."""
    return await broker.risk_check(force=True)


@app.delete("/api/alpha-wolf/pending/{order_id}")
async def alpha_wolf_cancel_pending(order_id: str):
    """Cancel one working entry order (a limit/stop entry that hasn't filled)."""
    out = await broker.cancel_pending(order_id)
    orchestrator.log_event("Alpha Wolf: working entry order cancelled from the UI", "#7c3aed")
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
    spec = default_model_spec()
    return {
        "default_model": spec,
        "default_provider": parse_model_spec(spec)[0],
        "providers": provider_status(),
        "agent_models": get_config("agent_models", {}) or {},
        "suggested_models": SUGGESTED_MODELS,
    }


class AgentModelUpdate(BaseModel):
    agent_id: str
    model: str = ""    # "provider:model" or a bare model name (local); empty clears the override


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
    if prov not in ("openai", "anthropic", "grok", "local"):
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
# ─── LLM test ────────────────────────────────────────────────────────
from llm_client import generate_completion


class PromptRequest(BaseModel):
    prompt: str


@app.post("/api/test-llm")
async def test_llm(request: PromptRequest):
    return {"response": await generate_completion(request.prompt)}


if __name__ == "__main__":
    import uvicorn
    # Loopback only: the dev server proxies to it, so the API never needs to be
    # reachable from the network on a port of its own.
    uvicorn.run("main:app", host="127.0.0.1", port=5174, reload=True)
