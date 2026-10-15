import asyncio
import json
import time
from collections import deque
from datetime import datetime
from typing import Dict, Any

import tracing
from llm_client import get_llm_state
from database import SessionLocal, Event, AgentRun, AgentState, init_db, get_config, set_config
from ws import manager


AGENT_META = {
    "wallstreet_wolf": {"n": "Wallstreet Wolf",    "glyph": "$", "desc": "Tape, regime & key levels", "schedule": "Every 60 min",  "color": "#16a34a"},
    "technologia":     {"n": "Technologia",        "glyph": "◭", "desc": "VP/VWAP/MFI technical signals", "schedule": "Every 30 min", "color": "#4f46e5"},
    "alpha_wolf":      {"n": "Alpha Wolf",         "glyph": "🐺","desc": "Plans & executes trades",  "schedule": "Daily · 08:30", "color": "#7c3aed"},
}
AGENT_ORDER = list(AGENT_META.keys())

# The agent_data key that holds each agent's real output. Freshness of THIS row is
# what says an agent is working — not its run status, and not a sibling key. Alpha
# Wolf writes `pulse` and `portfolio` on a 30-minute timer whatever else happens,
# so watching those would have reported a healthy agent for the entire week its
# `plan` was stale.
AGENT_DATA_KEYS = {
    "wallstreet_wolf": "market_data",
    "technologia": "signals",
    "alpha_wolf": "plan",
}

# The graded agents (+ the orchestrator itself). Demo mode hides everything
# else so a 10-minute video only has to show — and never risk breaking on — the
# components the rubric actually scores.
CORE_AGENTS = ["wallstreet_wolf", "alpha_wolf"]

STATUS_MAP = {
    "running": "running", "idle": "idle", "stopped": "idle", "error": "crashed",
    "crashed": "crashed", "restarting": "queued", "queued": "queued", "failed": "crashed",
}


class Orchestrator:
    def __init__(self):
        self.agents_status = {
            aid: {"status": "stopped", "last_run": None, "error": None,
                  "progress": None, "result": None}
            for aid in AGENT_ORDER
        }
        self._agent_jobs = {}
        self._restart_counts = {}
        self.MAX_RESTARTS = 3

        self._started_at = time.time()
        self.events = deque(maxlen=20)
        self._demo_crashed = set()
        self._open_runs = {}            # agent_id -> AgentRun id
        self._broadcast_task = None
        self._watchdog_task = None
        self._stale_flagged = {}        # agent_id -> already warned about staleness

        init_db()            # ensure tables exist before reading history
        self._load_history()
        self.demo_mode = bool(get_config("demo_mode", False))

    # ── load durable history from SQLite ─────────────────────────────────
    def _load_history(self):
        try:
            db = SessionLocal()
            evs = db.query(Event).order_by(Event.ts.desc()).limit(20).all()
            for e in evs:
                self.events.append({"t": e.ts.strftime("%H:%M"), "m": e.message, "c": e.color})
            for st in db.query(AgentState).all():
                if st.agent_id in self.agents_status:
                    self._restart_counts[st.agent_id] = st.restarts or 0
                    self.agents_status[st.agent_id]["last_run"] = st.last_run.isoformat() if st.last_run else None
                    self.agents_status[st.agent_id]["error"] = st.last_error
            db.close()
        except Exception as e:
            print(f"[Orchestrator] history load skipped: {e}")

    # ── dashboard state push ─────────────────────────────────────────────
    # Agent status changes also broadcast on transition (see update_agent_status);
    # this loop is the periodic backstop that keeps uptime and the LLM panel live.
    async def _broadcast_loop(self):
        while True:
            try:
                await manager.broadcast({"type": "state", "data": self.get_state()})
            except Exception:
                pass
            await asyncio.sleep(2)

    def start_broadcast(self):
        if self._broadcast_task is None:
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())

    # ── events ───────────────────────────────────────────────────────────
    def log_event(self, message: str, color: str = "#5b6472"):
        self.events.appendleft({"t": datetime.now().strftime("%H:%M"), "m": message, "c": color})
        try:
            db = SessionLocal()
            db.add(Event(message=message, color=color))
            db.commit(); db.close()
        except Exception:
            pass

    # ── agent status + run history ───────────────────────────────────────
    def _save_agent_state(self, agent_name):
        try:
            db = SessionLocal()
            st = db.query(AgentState).filter_by(agent_id=agent_name).first()
            info = self.agents_status[agent_name]
            lr = None
            if info.get("last_run"):
                try:
                    lr = datetime.fromisoformat(info["last_run"])
                except Exception:
                    lr = None
            if not st:
                st = AgentState(agent_id=agent_name)
                db.add(st)
            st.restarts = self._restart_counts.get(agent_name, 0)
            st.last_run = lr
            st.last_error = info.get("error")
            db.commit(); db.close()
        except Exception:
            pass

    def set_progress(self, agent_name: str, message: str, result: str = None):
        """Live, human-readable progress for the agent's own tab (e.g. 'Curating
        with the local model…'). Pushed to the UI immediately over the WebSocket."""
        if agent_name not in self.agents_status:
            return
        self.agents_status[agent_name]["progress"] = message
        if result is not None:
            self.agents_status[agent_name]["result"] = result
        try:
            asyncio.create_task(manager.broadcast({"type": "state", "data": self.get_state()}))
        except RuntimeError:
            pass  # no running loop (e.g. called from a sync context)

    def update_agent_status(self, agent_name: str, status: str, error: str = None):
        if agent_name not in self.agents_status:
            return
        prev = self.agents_status[agent_name]["status"]
        self.agents_status[agent_name]["status"] = status
        if status == "running":
            # fresh run — clear the previous outcome and show a starting state
            self.agents_status[agent_name]["result"] = None
            self.agents_status[agent_name]["progress"] = "Starting…"
        if status in ("idle", "error", "failed"):
            self.agents_status[agent_name]["progress"] = None
        if status == "idle":
            self.agents_status[agent_name]["last_run"] = datetime.utcnow().isoformat()
            self.agents_status[agent_name]["error"] = None
            self._restart_counts[agent_name] = 0
            self._demo_crashed.discard(agent_name)
        if error:
            self.agents_status[agent_name]["error"] = error

        # run-history bookkeeping
        try:
            db = SessionLocal()
            if status == "running":
                run = AgentRun(agent_id=agent_name, status="running")
                db.add(run); db.commit()
                self._open_runs[agent_name] = run.id
                tracing.start(agent_name)
            elif status in ("idle", "error"):
                rid = self._open_runs.pop(agent_name, None)
                metrics = tracing.finish(agent_name)
                if rid:
                    run = db.query(AgentRun).get(rid)
                    if run:
                        run.finished_at = datetime.utcnow()
                        run.status = status
                        run.error = error
                        if metrics:
                            run.llm_calls = metrics["llm_calls"]
                            run.tokens_in = metrics["tokens_in"]
                            run.tokens_out = metrics["tokens_out"]
                            run.llm_ms = metrics["llm_ms"]
                            run.stages = json.dumps(metrics["stages"]) if metrics["stages"] else None
                        db.commit()
            db.close()
        except Exception:
            pass

        if status != prev:
            meta = AGENT_META.get(agent_name, {})
            name = meta.get("n", agent_name)
            if status == "running":
                self.log_event(f"{name} run started", "#5b6472")
            elif status == "idle":
                self.log_event(f"{name} run completed", "#16a34a")
            elif status == "error":
                self.log_event(f"✕ {name} crashed: {error or 'error'} — recovering", "#e5484d")
        self._save_agent_state(agent_name)

        # push the change to the dashboard immediately — without this, short
        # runs can start and finish between two 2s sampler broadcasts and the
        # status dot never visibly changes (e.g. during a stress test)
        try:
            asyncio.create_task(manager.broadcast({"type": "state", "data": self.get_state()}))
        except RuntimeError:
            pass  # no running loop (sync context, e.g. tests)

    def register_agent_job(self, agent_name: str, job_callable):
        self._agent_jobs[agent_name] = job_callable

    def get_agents_status(self):
        return self.agents_status

    # ── full dashboard state ─────────────────────────────────────────────
    def get_state(self) -> Dict[str, Any]:
        agents = []
        for aid in AGENT_ORDER:
            meta = AGENT_META[aid]
            raw = self.agents_status[aid]["status"]
            status = STATUS_MAP.get(raw, "idle")
            running = status == "running"
            agents.append({
                "id": aid, "n": meta["n"], "glyph": meta["glyph"], "desc": meta["desc"],
                "color": meta["color"], "status": status,
                "schedule": meta["schedule"],
                "restarts": self._restart_counts.get(aid, 0),
                "error": self.agents_status[aid].get("error"),
                "progress": self.agents_status[aid].get("progress"),
                "result": self.agents_status[aid].get("result"),
            })

        return {
            "uptimeS": int(time.time() - self._started_at),
            "agents": agents, "llm": get_llm_state(),
            "events": list(self.events), "demo": self.demo_mode,
        }

    # ── demo controls ────────────────────────────────────────────────────
    def set_demo_mode(self, enabled: bool) -> bool:
        """Toggle demo mode. When on, the dashboard and scheduler focus on the
        three graded agents only; extras are hidden/paused for a clean demo."""
        self.demo_mode = bool(enabled)
        set_config("demo_mode", self.demo_mode)
        extras = [a for a in AGENT_ORDER if a not in CORE_AGENTS]
        if self.demo_mode:
            self.log_event(f"Demo mode ON · {len(CORE_AGENTS)} core agents · {len(extras)} extras paused", "#7c5cf6")
        else:
            self.log_event("Demo mode OFF · full agent fleet active", "#7c5cf6")
        return self.demo_mode

    async def _demo_recover(self, agent_name: str):
        await asyncio.sleep(4)
        if agent_name in self._demo_crashed:
            self._restart_counts[agent_name] = self._restart_counts.get(agent_name, 0) + 1
            self.agents_status[agent_name]["status"] = "idle"
            self.agents_status[agent_name]["error"] = None
            self._demo_crashed.discard(agent_name)
            meta = AGENT_META.get(agent_name, {})
            self.log_event(f"Orchestrator restarted {meta.get('n', agent_name)} (auto-recovery)", "#16a34a")
            self._save_agent_state(agent_name)

    def crash(self, agent_name: str):
        if agent_name not in self.agents_status:
            return {"error": "Agent not found"}
        self._demo_crashed.add(agent_name)
        self.agents_status[agent_name]["status"] = "error"
        self.agents_status[agent_name]["error"] = "Demo crash (exit 1)"
        meta = AGENT_META.get(agent_name, {})
        self.log_event(f"✕ {meta.get('n', agent_name)} crashed (exit 1) — orchestrator recovering", "#e5484d")
        try:
            asyncio.create_task(self._demo_recover(agent_name))
        except RuntimeError:
            pass
        return {"status": f"Crashed {agent_name}"}

    # ── watchdog ─────────────────────────────────────────────────────────
    async def _watchdog_pass(self):
        """One sweep over all agents, restarting crashed ones (up to MAX_RESTARTS,
        then disabling them). Split out from _watchdog_loop so it can be exercised
        directly in tests without waiting on the real poll interval."""
        for agent_name, info in self.agents_status.items():
            if info["status"] == "error" and agent_name in self._demo_crashed:
                continue
            if info["status"] == "error" and agent_name in self._agent_jobs:
                attempts = self._restart_counts.get(agent_name, 0)
                if attempts >= self.MAX_RESTARTS:
                    if info["status"] != "failed":
                        print(f"[Watchdog] '{agent_name}' failed {attempts}x. Manual restart required.")
                        self.agents_status[agent_name]["status"] = "failed"
                        self.log_event(f"{AGENT_META.get(agent_name, {}).get('n', agent_name)} disabled after {attempts} failures", "#e5484d")
                    continue
                self._restart_counts[agent_name] = attempts + 1
                print(f"[Watchdog] Restarting '{agent_name}' ({attempts + 1}/{self.MAX_RESTARTS})...")
                self.update_agent_status(agent_name, "restarting")
                try:
                    asyncio.create_task(self._agent_jobs[agent_name]())
                except Exception as e:
                    print(f"[Watchdog] Failed to restart '{agent_name}': {e}")

    # How long an agent's stored output may go unrefreshed before it is called
    # stale, per agent. Generous multiples of each cadence — this is meant to
    # catch "stopped producing", not a single late tick.
    STALE_AFTER_HOURS = {"technologia": 24, "wallstreet_wolf": 12, "alpha_wolf": 30}

    def staleness_report(self) -> dict:
        """Which agents have stopped producing, regardless of how healthy they look.

        The status-based checks above only fire on an in-memory `error`, which
        misses the failure that actually happened: Alpha Wolf's plan sat seven days
        old while its pulse and portfolio kept writing fresh rows, so every signal
        in the UI said the agent was fine. Freshness of OUTPUT is the thing worth
        watching — an agent that runs on schedule and produces nothing is not
        healthy, it is broken in a quieter way.
        """
        from database import get_agent_data, SessionLocal, AgentData

        out = {}
        db = SessionLocal()
        try:
            for agent_name, limit_h in self.STALE_AFTER_HOURS.items():
                key = AGENT_DATA_KEYS.get(agent_name)
                row = (db.query(AgentData)
                       .filter_by(agent_name=agent_name, key=key)
                       .order_by(AgentData.updated_at.desc()).first()) if key else None
                if row is None or row.updated_at is None:
                    out[agent_name] = {"stale": True, "age_hours": None,
                                       "why": "has never produced output"}
                    continue
                age = (datetime.utcnow() - row.updated_at).total_seconds() / 3600.0
                out[agent_name] = {
                    "stale": age > limit_h, "age_hours": round(age, 1),
                    "limit_hours": limit_h,
                    "why": (f"{key} last updated {round(age, 1)}h ago, over its {limit_h}h limit"
                            if age > limit_h else "fresh"),
                }
        finally:
            db.close()
        return out

    async def _staleness_pass(self):
        """Surface stale output once per transition, not once per sweep."""
        try:
            report = self.staleness_report()
        except Exception as e:
            print(f"[Watchdog] staleness check failed: {e}")
            return
        for agent_name, info in report.items():
            was = self._stale_flagged.get(agent_name, False)
            if info["stale"] and not was:
                name = AGENT_META.get(agent_name, {}).get("n", agent_name)
                self.log_event(f"⚠ {name} has produced nothing for "
                               f"{info['age_hours']}h — check its schedule", "#f59e0b")
                print(f"[Watchdog] STALE: {agent_name} — {info['why']}")
            self._stale_flagged[agent_name] = info["stale"]

    async def _watchdog_loop(self):
        ticks = 0
        while True:
            await asyncio.sleep(10)
            await self._watchdog_pass()
            ticks += 1
            # Every 30 minutes; the DB read is cheap but pointless at 10s.
            if ticks % 180 == 0:
                await self._staleness_pass()

    def start_watchdog(self):
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            self.log_event("Orchestrator online · watchdog armed", "#16a34a")
            print("[Watchdog] Agent crash detection started.")


orchestrator = Orchestrator()
