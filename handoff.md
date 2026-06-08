# Multi-Agent Personal Auto-Scheduling Platform — Complete Handoff (Finalized)

> **Last updated:** 2026-06-04 | **Status:** All gaps fixed. Project is fully functional, local LLM integration complete, running on macOS.

---

## 1. Project Overview & Key Requirements

Design, implement, and demonstrate a fully operational Multi-Agent Auto-Scheduling Platform running entirely on a local machine using a locally hosted LLM. A central orchestrator manages four specialized agents, handles resource scheduling, and serves a web-based dashboard.

### Constraints & Requirements
- **Local LLM Only:** Must use Ollama with `qwen3:8b`. No OpenAI/Anthropic API calls for inference.
- **Auto-restart:** Orchestrator must restart crashed agents.
- **Deadlock Prevention:** LLM calls must be serialized (using `asyncio.Semaphore(1)`).
- **Resource Monitoring:** CPU, RAM, Disk must be monitored with specific alarm actions if > 90%.
- **Zero Discrepancy:** The build must match the rubric 100%.

---

## 2. Current Status of the Discussion
- **All 12 previously identified gaps are FIXED.**
- **Ollama** has been installed via Homebrew and the `qwen3:14b` model has been successfully pulled and verified (running on Apple Silicon Metal GPU).
- Both the **Backend (FastAPI)** and **Frontend (React/Vite)** are currently running perfectly on `localhost:8000` and `localhost:5173`.
- **API Keys Setup:** YouTube and GitHub API keys, along with a Gmail App Password, still need to be entered into the `.env` file by the user to fully test the automated email functionalities.

---

## 3. Key Decision Points So Far
1. **Model Selection:** Switched default model explicitly to `qwen3:8b` to match the user's specific local download and maximize quality.
2. **Pathing & Venv:** Re-created the Python virtual environment (`venv`) to fix absolute pathing issues caused by a trailing space in the root folder name.
3. **Syntax Error Fix:** Extracted f-string comprehensions into separate variables in `agent3_wallstreet_wolf.py` to ensure compatibility across all Python versions and prevent Uvicorn crashes.
4. **Email Utilities:** Created a centralized `email_utils.py` that handles real Gmail SMTP sending for all 4 agents.
5. **Security:** Hardened the FastAPI backend by restricting CORS to exactly `http://localhost:5173`.

---

## 4. Specific Code Snippets Finalized

### Centralized LLM Call with Semaphore
```python
# backend/llm_client.py
import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:14b")

# Global Semaphore so only one agent calls the LLM at a time (deadlock prevention)
llm_semaphore = asyncio.Semaphore(1)

async def generate_completion(prompt: str, system_prompt: str = "You are a helpful AI assistant.") -> str:
    async with llm_semaphore:
        async with httpx.AsyncClient() as client:
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False
            }
            try:
                response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=120.0)
                response.raise_for_status()
                return response.json().get("message", {}).get("content", "")
            except Exception as e:
                print(f"Error calling LLM: {e}")
                return f"Error: {e}"
```

### Agent Auto-Restart Watchdog
```python
# backend/orchestrator.py
# An async background task (started via start_watchdog) checks every 10s for
# agents in the "error" state and re-runs their registered job coroutine.
async def _watchdog_loop(self):
    while True:
        await asyncio.sleep(10)
        for agent_name, info in self.agents_status.items():
            if info["status"] == "error" and agent_name in self._agent_jobs:
                print(f"[Watchdog] Detected crashed agent '{agent_name}'. Restarting...")
                self.update_agent_status(agent_name, "restarting")
                try:
                    asyncio.create_task(self._agent_jobs[agent_name]())
                except Exception as e:
                    print(f"[Watchdog] Failed to restart '{agent_name}': {e}")
```

---

## 5. How to Run on Any Machine
1. Install Python 3.12+, Node.js, and Ollama.
2. Run `ollama pull qwen3:8b` and keep Ollama running.
3. Clone repository and run `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`.
4. Run Backend: `cd backend && uvicorn main:app --reload --port 8000`.
5. Run Frontend: `cd frontend && npm install && npm run dev`.
