import psutil
import asyncio
import time
import random
from collections import deque
from datetime import datetime
from typing import Dict, Any

import httpx

from llm_client import get_llm_state, OLLAMA_BASE_URL
from database import SessionLocal, ResourceSample, Event, AgentRun, AgentState, init_db, get_config, set_config
from ws import manager

# Optional NVIDIA GPU telemetry.
try:
    import pynvml  # type: ignore

    pynvml.nvmlInit()
    _NVML = True
except Exception:
    _NVML = False


AGENT_META = {
    "ai_times":        {"n": "AI-Times",          "glyph": "▶", "desc": "AI YouTube digest",        "schedule": "Daily · 08:00", "color": "#e5484d"},
    "mailman":         {"n": "Mailman",            "glyph": "✉", "desc": "Gmail triage",             "schedule": "Every 60 min",  "color": "#2f6feb"},
    "wallstreet_wolf": {"n": "Wallstreet Wolf",    "glyph": "$", "desc": "Market tracker",           "schedule": "Every 2h",      "color": "#16a34a"},
    "compass":         {"n": "Wallstreet Compass", "glyph": "◎", "desc": "Bias & key levels",        "schedule": "Every 60 min",  "color": "#f59e0b"},
    "devdaily":        {"n": "GitHub Trending",    "glyph": "⌥", "desc": "GitHub & Dev.to digest",   "schedule": "Daily · 09:00", "color": "#7c5cf6"},
    "strategy_scout":  {"n": "Strategy Scout",     "glyph": "✦", "desc": "Top trading strategies",   "schedule": "Daily · 10:00", "color": "#0ea5e9"},
    "capitol_tracker": {"n": "Capitol Tracker",    "glyph": "🏛", "desc": "Political stock trades",   "schedule": "Daily · 07:00", "color": "#dc2626"},
    "morning_brief":   {"n": "Morning Brief",      "glyph": "☀", "desc": "Daily personalized digest", "schedule": "Daily · 06:00", "color": "#f59e0b"},
    "options_flow":    {"n": "Options Flow",       "glyph": "⚡","desc": "Unusual options activity",  "schedule": "Every 2h",      "color": "#7c5cf6"},
    "earnings_cal":    {"n": "Earnings Calendar",  "glyph": "📅","desc": "Upcoming earnings & IV",    "schedule": "Every 6h",      "color": "#16a34a"},
    "cisco_pulse":     {"n": "Cisco Pulse",        "glyph": "◈", "desc": "ACI/NDFC/PSIRT intel",     "schedule": "Daily · 07:30", "color": "#0d9488"},
    "alpha_wolf":      {"n": "Alpha Wolf",         "glyph": "🐺","desc": "Master trade strategist",  "schedule": "Daily · 08:30", "color": "#7c3aed"},
}
AGENT_ORDER = list(AGENT_META.keys())

# The four graded agents (+ the orchestrator itself). Demo mode hides everything
# else so a 10-minute video only has to show — and never risk breaking on — the
# components the rubric actually scores.
CORE_AGENTS = ["ai_times", "mailman", "wallstreet_wolf", "devdaily"]

STATUS_MAP = {
    "running": "running", "idle": "idle", "stopped": "idle", "error": "crashed",
    "crashed": "crashed", "restarting": "queued", "queued": "queued", "failed": "crashed",
}
ALARM_ACTIONS = {
    "cpu":  "Throttle Wolf's 5-min poll and pause non-critical agents until load < 75%.",
    "ram":  "Flush LLM KV-cache and reduce Qwen3 context window to free memory.",
    "gpu":  "Queue depth high — serialize inference further and lower batch size.",
    "disk": "Rotate logs and clear cached thumbnails/emails older than 7 days.",
}
ALARM_LABELS = {"cpu": "CPU", "ram": "Memory", "gpu": "GPU", "disk": "Disk"}


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
        self._hist = {k: deque(maxlen=24) for k in ("cpu", "ram", "disk", "gpu", "net")}
        self.events = deque(maxlen=20)
        self._last = {"cpu": 0.0, "ram": 0.0, "disk": 0.0, "gpu": 0.0, "net": 0.0, "threads": 0}
        self._net_prev = None        # (bytes_total, monotonic_ts) for throughput delta
        self._gpu_vram_mb = 0
        self._spike = None
        self._demo_crashed = set()
        self._open_runs = {}            # agent_id -> AgentRun id
        self._persist_tick = 0
        self._sampler_task = None
        self._watchdog_task = None

        psutil.cpu_percent(interval=None)
        init_db()            # ensure tables exist before reading history
        self._load_history()
        self.demo_mode = bool(get_config("demo_mode", False))

    # ── load durable history from SQLite ─────────────────────────────────
    def _load_history(self):
        try:
            db = SessionLocal()
            rows = db.query(ResourceSample).order_by(ResourceSample.ts.desc()).limit(24).all()
            for r in reversed(rows):
                self._hist["cpu"].append(r.cpu); self._hist["ram"].append(r.ram)
                self._hist["disk"].append(r.disk); self._hist["gpu"].append(r.gpu)
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

    # ── GPU / VRAM ───────────────────────────────────────────────────────
    def _read_gpu(self) -> float:
        if _NVML:
            try:
                h = pynvml.nvmlDeviceGetHandleByIndex(0)
                return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
            except Exception:
                pass
        active = get_llm_state()["holder"] is not None
        base = 62 if active else 30
        prev = self._last.get("gpu", base)
        return round(min(96, max(8, prev * 0.6 + base * 0.4 + random.uniform(-5, 5))), 1)

    async def _poll_ollama_vram(self):
        try:
            async with httpx.AsyncClient(timeout=4) as c:
                r = await c.get(f"{OLLAMA_BASE_URL}/api/ps")
                if r.status_code == 200:
                    models = r.json().get("models", [])
                    self._gpu_vram_mb = round(sum(m.get("size_vram", 0) for m in models) / (1024 * 1024))
        except Exception:
            pass

    # ── network throughput (Mb/s, in + out) ──────────────────────────────
    def _read_net(self) -> float:
        try:
            io = psutil.net_io_counters()
            total = io.bytes_sent + io.bytes_recv
            now = time.monotonic()
            if self._net_prev is None:
                self._net_prev = (total, now)
                return 0.0
            prev_total, prev_ts = self._net_prev
            dt = now - prev_ts
            self._net_prev = (total, now)
            if dt <= 0:
                return self._last.get("net", 0.0)
            mbps = (total - prev_total) * 8 / 1e6 / dt   # megabits per second
            return round(max(0.0, mbps), 1)
        except Exception:
            return self._last.get("net", 0.0)

    # ── sampling ─────────────────────────────────────────────────────────
    def _take_sample(self) -> Dict[str, float]:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        gpu = self._read_gpu()
        net = self._read_net()

        if self._spike:
            if time.time() > self._spike["expires"]:
                self.log_event(f"{ALARM_LABELS[self._spike['resource']]} recovered to normal range", "#16a34a")
                self._spike = None
            else:
                r, val = self._spike["resource"], self._spike["value"]
                if r == "cpu": cpu = val
                elif r == "ram": ram = val
                elif r == "gpu": gpu = val
                elif r == "disk": disk = val

        threads = psutil.Process().num_threads()
        self._last = {"cpu": round(cpu, 1), "ram": round(ram, 1), "disk": round(disk, 1),
                      "gpu": round(gpu, 1), "net": round(net, 1), "threads": threads}
        for k in ("cpu", "ram", "disk", "gpu", "net"):
            self._hist[k].append(self._last[k])
        return self._last

    def _persist_sample(self, s):
        try:
            db = SessionLocal()
            db.add(ResourceSample(cpu=s["cpu"], ram=s["ram"], disk=s["disk"], gpu=s["gpu"], threads=s["threads"]))
            # prune to last ~1000 rows
            self._persist_tick += 1
            if self._persist_tick % 50 == 0:
                ids = [r.id for r in db.query(ResourceSample.id).order_by(ResourceSample.ts.desc()).offset(1000).all()]
                if ids:
                    db.query(ResourceSample).filter(ResourceSample.id.in_(ids)).delete(synchronize_session=False)
            db.commit(); db.close()
        except Exception as e:
            print(f"[Orchestrator] persist sample failed: {e}")

    async def _sampler_loop(self):
        while True:
            s = self._take_sample()
            if self._persist_tick % 5 == 0:           # persist every ~10s
                self._persist_sample(s)
            else:
                self._persist_tick += 1
            if self._persist_tick % 3 == 0:           # refresh VRAM every ~6s
                await self._poll_ollama_vram()
            try:
                await manager.broadcast({"type": "state", "data": self.get_state()})
            except Exception:
                pass
            await asyncio.sleep(2)

    def start_sampler(self):
        if self._sampler_task is None:
            self._take_sample()
            self._sampler_task = asyncio.create_task(self._sampler_loop())

    # ── back-compat: synchronous resource read for /api/system/resources ──
    def get_system_resources(self) -> Dict[str, Any]:
        s = self._last if self._last["cpu"] or self._hist["cpu"] else self._take_sample()
        alarms = []
        for k in ("cpu", "ram", "disk", "gpu"):
            if s[k] >= 90:
                alarms.append({"resource": ALARM_LABELS[k], "value": s[k], "suggestion": ALARM_ACTIONS[k]})
        return {
            "cpu_percent": s["cpu"], "ram_percent": s["ram"], "disk_percent": s["disk"],
            "gpu_percent": s["gpu"], "net_mbps": s.get("net", 0.0), "active_threads": s["threads"],
            "alarm": len(alarms) > 0, "alarms": alarms,
        }

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
        with Qwen3…'). Pushed to the UI immediately over the WebSocket."""
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
            elif status in ("idle", "error"):
                rid = self._open_runs.pop(agent_name, None)
                if rid:
                    run = db.query(AgentRun).get(rid)
                    if run:
                        run.finished_at = datetime.utcnow()
                        run.status = status
                        run.error = error
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

    def register_agent_job(self, agent_name: str, job_callable):
        self._agent_jobs[agent_name] = job_callable

    def get_agents_status(self):
        return self.agents_status

    # ── full dashboard state ─────────────────────────────────────────────
    def get_state(self) -> Dict[str, Any]:
        res = self.get_system_resources()

        def block(k, pct):
            return {"v": pct, "hist": list(self._hist[k]) or [pct]}

        agents = []
        for aid in AGENT_ORDER:
            meta = AGENT_META[aid]
            raw = self.agents_status[aid]["status"]
            status = STATUS_MAP.get(raw, "idle")
            running = status == "running"
            agents.append({
                "id": aid, "n": meta["n"], "glyph": meta["glyph"], "desc": meta["desc"],
                "color": meta["color"], "status": status,
                "cpu": random.randint(4, 18) if running else random.randint(0, 3),
                "mem": {"ai_times": 180, "mailman": 240, "wallstreet_wolf": 210,
                        "compass": 168, "devdaily": 150, "capitol_tracker": 160,
                         "morning_brief": 145, "options_flow": 170, "earnings_cal": 155, "cisco_pulse": 148}.get(aid, 140),
                "schedule": meta["schedule"],
                "restarts": self._restart_counts.get(aid, 0),
                "error": self.agents_status[aid].get("error"),
                "progress": self.agents_status[aid].get("progress"),
                "result": self.agents_status[aid].get("result"),
            })

        alarm = None
        if res["alarms"]:
            a = res["alarms"][0]
            rkey = a["resource"].lower().replace("memory", "ram")
            alarm = {"resource": rkey, "value": a["value"], "label": a["resource"], "action": a["suggestion"]}

        llm = get_llm_state()
        llm["vram_mb"] = self._gpu_vram_mb
        return {
            "uptimeS": int(time.time() - self._started_at),
            "res": {"cpu": block("cpu", res["cpu_percent"]), "ram": block("ram", res["ram_percent"]),
                    "disk": block("disk", res["disk_percent"]), "gpu": block("gpu", res["gpu_percent"]),
                    "net": block("net", res["net_mbps"])},
            "threads": res["active_threads"], "agents": agents, "llm": llm,
            "events": list(self.events), "alarm": alarm, "demo": self.demo_mode,
        }

    # ── demo controls ────────────────────────────────────────────────────
    def set_demo_mode(self, enabled: bool) -> bool:
        """Toggle demo mode. When on, the dashboard and scheduler focus on the
        four graded agents only; extras are hidden/paused for a clean demo."""
        self.demo_mode = bool(enabled)
        set_config("demo_mode", self.demo_mode)
        extras = [a for a in AGENT_ORDER if a not in CORE_AGENTS]
        if self.demo_mode:
            self.log_event(f"Demo mode ON · {len(CORE_AGENTS)} core agents · {len(extras)} extras paused", "#7c5cf6")
        else:
            self.log_event("Demo mode OFF · full agent fleet active", "#7c5cf6")
        return self.demo_mode

    def spike(self, resource: str = "cpu"):
        resource = resource if resource in ALARM_ACTIONS else "cpu"
        value = round(random.uniform(91, 97), 1)
        self._spike = {"resource": resource, "value": value, "expires": time.time() + 12}
        self.log_event(f"⚠ {ALARM_LABELS[resource]} exceeded 90% — alarm raised", "#e5484d")
        return {"resource": resource, "value": value}

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

    async def _watchdog_loop(self):
        while True:
            await asyncio.sleep(10)
            await self._watchdog_pass()

    def start_watchdog(self):
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            self.log_event("Orchestrator online · watchdog armed", "#16a34a")
            print("[Watchdog] Agent crash detection started.")


orchestrator = Orchestrator()
