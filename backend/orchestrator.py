import psutil
import threading
from typing import Dict, Any

class Orchestrator:
    def __init__(self):
        self.agents_status = {
            "ai_times": {"status": "stopped", "last_run": None, "error": None},
            "mailman": {"status": "stopped", "last_run": None, "error": None},
            "wallstreet_wolf": {"status": "stopped", "last_run": None, "error": None},
            "devdaily": {"status": "stopped", "last_run": None, "error": None},
        }
    
    def get_system_resources(self) -> Dict[str, Any]:
        """
        Fetches live system resources (CPU, RAM, Disk, Threads).
        """
        cpu_percent = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Determine number of threads in current process
        process = psutil.Process()
        threads = process.num_threads()

        return {
            "cpu_percent": cpu_percent,
            "ram_percent": ram.percent,
            "disk_percent": disk.percent,
            "active_threads": threads,
            "alarm": cpu_percent > 90 or ram.percent > 90 or disk.percent > 90
        }
    
    def update_agent_status(self, agent_name: str, status: str, error: str = None):
        if agent_name in self.agents_status:
            self.agents_status[agent_name]["status"] = status
            if error:
                self.agents_status[agent_name]["error"] = error
            
    def get_agents_status(self):
        return self.agents_status

orchestrator = Orchestrator()
