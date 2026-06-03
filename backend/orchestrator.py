import psutil
import asyncio
from datetime import datetime
from typing import Dict, Any


class Orchestrator:
    def __init__(self):
        self.agents_status = {
            "ai_times": {"status": "stopped", "last_run": None, "error": None},
            "mailman": {"status": "stopped", "last_run": None, "error": None},
            "wallstreet_wolf": {"status": "stopped", "last_run": None, "error": None},
            "devdaily": {"status": "stopped", "last_run": None, "error": None},
        }
        self._agent_jobs = {}  # Stores callable references for restart
        self._watchdog_task = None

    def get_system_resources(self) -> Dict[str, Any]:
        """
        Fetches live system resources (CPU, RAM, Disk, Threads).
        Returns per-resource alarm details with suggested corrective actions.
        """
        cpu_percent = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        process = psutil.Process()
        threads = process.num_threads()

        # Build per-resource alarm list
        alarms = []
        if cpu_percent > 90:
            alarms.append({
                "resource": "CPU",
                "value": cpu_percent,
                "suggestion": "Close CPU-intensive applications or reduce agent polling frequency."
            })
        if ram.percent > 90:
            alarms.append({
                "resource": "RAM",
                "value": ram.percent,
                "suggestion": "Close unused browser tabs and applications to free memory."
            })
        if disk.percent > 90:
            alarms.append({
                "resource": "Disk",
                "value": disk.percent,
                "suggestion": "Clear temporary files, logs, or old downloads to free disk space."
            })

        return {
            "cpu_percent": cpu_percent,
            "ram_percent": ram.percent,
            "disk_percent": disk.percent,
            "active_threads": threads,
            "alarm": len(alarms) > 0,
            "alarms": alarms
        }

    def update_agent_status(self, agent_name: str, status: str, error: str = None):
        if agent_name in self.agents_status:
            self.agents_status[agent_name]["status"] = status
            if status == "idle":
                self.agents_status[agent_name]["last_run"] = datetime.utcnow().isoformat()
                self.agents_status[agent_name]["error"] = None
            if error:
                self.agents_status[agent_name]["error"] = error

    def register_agent_job(self, agent_name: str, job_callable):
        """Register the async callable for an agent so watchdog can restart it."""
        self._agent_jobs[agent_name] = job_callable

    def get_agents_status(self):
        return self.agents_status

    async def _watchdog_loop(self):
        """
        Runs every 10 seconds. Detects crashed agents (status == 'error')
        and automatically restarts them without restarting the full platform.
        """
        while True:
            await asyncio.sleep(10)
            for agent_name, info in self.agents_status.items():
                if info["status"] == "error" and agent_name in self._agent_jobs:
                    print(f"[Watchdog] Detected crashed agent '{agent_name}'. Restarting...")
                    self.update_agent_status(agent_name, "restarting")
                    try:
                        asyncio.create_task(self._agent_jobs[agent_name]())
                        print(f"[Watchdog] Successfully restarted '{agent_name}'.")
                    except Exception as e:
                        print(f"[Watchdog] Failed to restart '{agent_name}': {e}")

    def start_watchdog(self):
        """Start the watchdog background task."""
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            print("[Watchdog] Agent crash detection started.")


orchestrator = Orchestrator()
