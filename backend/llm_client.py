import asyncio
import time
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5:4b")

# Global Semaphore to ensure only one agent calls the LLM at a time.
# A single permit means inference is fully serialized — no contention, no
# circular waits, no deadlocks. Every call acquires it before touching Ollama.
llm_semaphore = asyncio.Semaphore(1)

# Live semaphore state surfaced on the Orchestrator dashboard's "LLM Semaphore"
# panel. The orchestrator reads this dict to render holder / queue / tokens.
llm_state = {
    "holder": None,     # agent_id currently holding the permit
    "queue": [],        # agent_ids waiting for the permit
    "tokens": 0,        # tokens produced by the in-flight / last call
    "rate": 0,          # tokens / second of the last call
    "_t0": None,        # monotonic start time of the current hold (None = idle)
    "model": LLM_MODEL,
}


def get_llm_state():
    """Snapshot the semaphore state for the dashboard (heldS computed live)."""
    s = llm_state
    held = round(time.time() - s["_t0"], 1) if s["_t0"] else 0.0
    return {
        "holder": s["holder"],
        "queue": list(s["queue"]),
        "tokens": s["tokens"],
        "rate": s["rate"],
        "heldS": held,
        "model": s["model"],
    }


async def generate_completion(
    prompt: str,
    system_prompt: str = "You are a helpful AI assistant.",
    agent_id: str = None,
) -> str:
    """
    Calls the local LLM. Acquires the global semaphore first to prevent deadlocks.
    `agent_id` (optional) lets the dashboard show which agent holds / waits for the permit.
    """
    if agent_id:
        llm_state["queue"].append(agent_id)
    async with llm_semaphore:
        if agent_id and agent_id in llm_state["queue"]:
            llm_state["queue"].remove(agent_id)
        llm_state["holder"] = agent_id
        llm_state["_t0"] = time.time()
        llm_state["tokens"] = 0
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                }
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json=payload,
                    timeout=300.0,
                )
                response.raise_for_status()
                data = response.json()
                # Capture token telemetry for the semaphore panel.
                tokens = int(data.get("eval_count", 0) or 0)
                dur_ns = int(data.get("eval_duration", 0) or 0)
                llm_state["tokens"] = tokens
                if dur_ns:
                    llm_state["rate"] = round(tokens / (dur_ns / 1e9), 1)
                return data.get("message", {}).get("content", "")
        except Exception as e:
            print(f"Error calling LLM: {e}")
            return f"Error: {e}"
        finally:
            # Always release the hold from the dashboard's perspective.
            llm_state["holder"] = None
            llm_state["_t0"] = None
