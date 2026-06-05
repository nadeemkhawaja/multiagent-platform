import psutil
import asyncio
import time
import random
from collections import deque
from datetime import datetime
from typing import Dict, Any

from llm_client import get_llm_state

# Optional NVIDIA GPU telemetry for the LLM card.
try:
    import pynvml  # type: ignore

    pynvml.nvmlInit()
    _NVML = True
except Exception:
    _NVML = False


# ── Agent presentation metadata (drives nav, cards, accent colors) ───────────
AGENT_META = {
    "ai_times":        {"n": "AI-Times",        "glyph": "▶", "desc": "AI YouTube digest",      "schedule": "Daily · 08:00", "color": "#e5484d"},
    "mailman":         {"n": "Mailman",         "glyph": "✉", "desc": "Gmail triage",           "schedule": "Every 15 min",  "color": "#2f6feb"},
    "wallstreet_wolf": {"n": "Wallstreet Wolf", "glyph": "$", "desc": "Market tracker",         "schedule": "Every 5 min",   "color": "#16a34a"},
    "compass":         {"n": "Compass",         "glyph": "◎", "desc": "Bias & key levels",      "schedule": "Every 30 min",  "color": "#f59e0b"},
    "aegis":           {"n": "Aegis",           "glyph": "❖", "desc": "Reputation guardian",    "schedule": "Every 10 min",  "color": "#0d9488"},
    "devdaily":        {"n": "DevDaily",        "glyph": "⌥", "desc": "GitHub & Dev.to digest", "schedule": "Daily · 09:00", "color": "#7c5cf6"},
}
AGENT_ORDER = list(AGENT_META.keys())

# backend status → dashboard status vocabulary (running/idle/queued/crashed)
STATUS_MAP = {
    "running":    "running",
    "idle":       "idle",
    "stopped":    "idle",
    "error":      "crashed",
    "crashed":    "crashed",
    "restarting": "queued",
    "queued":     "queued",
    "failed":     "crashed",
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
            aid: {"status": "stopped", "last_run": None, "error": None}
            for aid in AGENT_ORDER
        }
        self._agent_jobs = {}        # callable references for restart
        self._watchdog_task = None
        self._restart_counts = {}    # restart attempts per agent
        self.MAX_RESTARTS = 3

        self._started_at = time.time()
        # rolling resource history for sparklines (last 24 samples)
        self._hist = {k: deque(maxlen=24) for k in ("cpu", "ram", "disk", "gpu")}
        self.events = deque(maxlen=20)
        # demo state
        self._spike = None           # {"resource","value","expires"}
        self._demo_crashed = set()   # agents crashed via the demo button

        # prime CPU sampler so the first reading isn't 0.0
        psutil.cpu_percent(interval=None)

    # ── resource sampling ────────────────────────────────────────────────
    def _read_gpu(self) -> float:
        if _NVML:
            try:
                h = pynvml.nvmlDeviceGetHandleByIndex(0)
                return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
            except Exception:
                pass
        # No NVML — approximate from whether the LLM permit is held.
        active = get_llm_state()["holder"] is not None
        base = 60 if active else 38
        return round(min(95, max(8, base + random.uniform(-6, 6))), 1)

    def _sample(self) -> Dict[str, float]:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        gpu = self._read_gpu()

        # apply an active demo spike (pins one resource > 90% briefly)
        if self._spike:
            if time.time() > self._spike["expires"]:
                self.log_event(f"{ALARM_LABELS[self._spike['resource']]} recovered to normal range", "#16a34a")
                self._spike = None
            else:
                r = self._spike["resource"]
                val = self._spike["value"]
                if r == "cpu":
                    cpu = val
                elif r == "ram":
                    ram = val
                elif r == "gpu":
                    gpu = val
                elif r == "disk":
                    disk = val

        sample = {"cpu": round(cpu, 1), "ram": round(ram, 1), "disk": round(disk, 1), "gpu": round(gpu, 1)}
        for k, v in sample.items():
            self._hist[k].append(v)
        return sample

    def get_system_resources(self) -> Dict[str, Any]:
        """Live resources + per-resource alarms with suggested corrective actions."""
        s = self._sample()
        alarms = []
        for k in ("cpu", "ram", "disk", "gpu"):
            if s[k] >= 90:
                alarms.append({
                    "resource": ALARM_LABELS[k],
                    "value": s[k],
                    "suggestion": ALARM_ACTIONS[k],
                })
        return {
            "cpu_percent": s["cpu"],
            "ram_percent": s["ram"],
            "disk_percent": s["disk"],
            "gpu_percent": s["gpu"],
            "active_threads": psutil.Process().num_threads(),
            "alarm": len(alarms) > 0,
            "alarms": alarms,
        }

    # ── event log ────────────────────────────────────────────────────────
    def log_event(self, message: str, color: str = "#5b6472"):
        self.events.appendleft({"t": datetime.now().strftime("%H:%M"), "m": message, "c": color})

    # ── agent status ─────────────────────────────────────────────────────
    def update_agent_status(self, agent_name: str, status: str, error: str = None):
        if agent_name in self.agents_status:
            prev = self.agents_status[agent_name]["status"]
            self.agents_status[agent_name]["status"] = status
            if status == "idle":
                self.agents_status[agent_name]["last_run"] = datetime.utcnow().isoformat()
                self.agents_status[agent_name]["error"] = None
                self._restart_counts[agent_name] = 0
                self._demo_crashed.discard(agent_name)
            if error:
                self.agents_status[agent_name]["error"] = error
            if status != prev:
                meta = AGENT_META.get(agent_name, {})
                name = meta.get("n", agent_name)
                if status == "running":
                    self.log_event(f"{name} run started", "#5b6472")
                elif status == "idle":
                    self.log_event(f"{name} run completed", "#16a34a")
                elif status == "error":
                    self.log_event(f"✕ {name} crashed — orchestrator recovering", "#e5484d")

    def register_agent_job(self, agent_name: str, job_callable):
        self._agent_jobs[agent_name] = job_callable

    def get_agents_status(self):
        return self.agents_status

    # ── full dashboard state (matches the prototype's Sim.state shape) ────
    def get_state(self) -> Dict[str, Any]:
        res_block = self.get_system_resources()

        def block(k, pct):
            return {"v": pct, "hist": list(self._hist[k]) or [pct]}

        agents = []
        for aid in AGENT_ORDER:
            meta = AGENT_META[aid]
            raw = self.agents_status[aid]["status"]
            status = STATUS_MAP.get(raw, "idle")
            running = status == "running"
            agents.append({
                "id": aid,
                "n": meta["n"],
                "glyph": meta["glyph"],
                "desc": meta["desc"],
                "color": meta["color"],
                "status": status,
                "cpu": random.randint(4, 18) if running else random.randint(0, 3),
                "mem": {"ai_times": 180, "mailman": 240, "wallstreet_wolf": 210,
                        "compass": 168, "aegis": 132, "devdaily": 150}.get(aid, 140),
                "nextS": 0,
                "schedule": meta["schedule"],
                "restarts": self._restart_counts.get(aid, 0),
            })

        alarm = None
        if res_block["alarms"]:
            a = res_block["alarms"][0]
            rkey = a["resource"].lower().replace("memory", "ram")
            alarm = {"resource": rkey, "value": a["value"], "label": a["resource"], "action": a["suggestion"]}

        return {
            "uptimeS": int(time.time() - self._started_at),
            "res": {
                "cpu":  block("cpu", res_block["cpu_percent"]),
                "ram":  block("ram", res_block["ram_percent"]),
                "disk": block("disk", res_block["disk_percent"]),
                "gpu":  block("gpu", res_block["gpu_percent"]),
            },
            "threads": res_block["active_threads"],
            "agents": agents,
            "llm": get_llm_state(),
            "events": list(self.events),
            "alarm": alarm,
        }

    # ── demo controls (wired to the dashboard's demo buttons) ─────────────
    def spike(self, resource: str = "cpu"):
        resource = resource if resource in ALARM_ACTIONS else "cpu"
        value = round(random.uniform(91, 97), 1)
        self._spike = {"resource": resource, "value": value, "expires": time.time() + 10}
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

    def crash(self, agent_name: str):
        """Demo crash: flip an agent to crashed; the orchestrator self-recovers ~4s later."""
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

    # ── watchdog: restart genuinely crashed agents (non-demo) ─────────────
    async def _watchdog_loop(self):
        while True:
            await asyncio.sleep(10)
            for agent_name, info in self.agents_status.items():
                if info["status"] == "error" and agent_name in self._demo_crashed:
                    continue  # demo crashes recover on their own timer
                if info["status"] == "error" and agent_name in self._agent_jobs:
                    attempts = self._restart_counts.get(agent_name, 0)
                    if attempts >= self.MAX_RESTARTS:
                        if info["status"] != "failed":
                            print(f"[Watchdog] '{agent_name}' failed {attempts} times. Manual restart required.")
                            self.agents_status[agent_name]["status"] = "failed"
                        continue
                    self._restart_counts[agent_name] = attempts + 1
                    print(f"[Watchdog] Restarting '{agent_name}' (attempt {attempts + 1}/{self.MAX_RESTARTS})...")
                    self.update_agent_status(agent_name, "restarting")
                    try:
                        asyncio.create_task(self._agent_jobs[agent_name]())
                    except Exception as e:
                        print(f"[Watchdog] Failed to restart '{agent_name}': {e}")

    def start_watchdog(self):
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            self.log_event("Orchestrator online · watchdog armed", "#16a34a")
            print("[Watchdog] Agent crash detection started.")


orchestrator = Orchestrator()
