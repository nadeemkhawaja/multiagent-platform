import asyncio
import time
import json
import re
import hashlib
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5:4b")

# Single-permit semaphore: only one agent calls the model at a time → fully
# serialized inference, no contention, no circular waits, no deadlocks.
llm_semaphore = asyncio.Semaphore(1)

# Live semaphore state surfaced on the Orchestrator dashboard.
llm_state = {
    "holder": None, "queue": [], "tokens": 0, "rate": 0, "_t0": None,
    "model": LLM_MODEL, "calls": 0, "cache_hits": 0,
}

# Small in-process response cache (identical prompts within TTL skip the model).
_CACHE = {}
_CACHE_TTL = 300  # seconds
_CACHE_MAX = 256


def get_llm_state():
    s = llm_state
    held = round(time.time() - s["_t0"], 1) if s["_t0"] else 0.0
    return {
        "holder": s["holder"], "queue": list(s["queue"]), "tokens": s["tokens"],
        "rate": s["rate"], "heldS": held, "model": s["model"],
        "calls": s["calls"], "cache_hits": s["cache_hits"],
    }


def _cache_key(model, system, prompt, json_mode):
    raw = f"{model}|{json_mode}|{system}|{prompt}"
    return hashlib.sha256(raw.encode()).hexdigest()


def strip_think(text: str) -> str:
    """Remove Qwen <think>…</think> blocks from a response."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


async def generate_completion(
    prompt: str,
    system_prompt: str = "You are a helpful AI assistant.",
    agent_id: str = None,
    json_mode: bool = False,
    use_cache: bool = True,
) -> str:
    """Call the local LLM through the single-permit semaphore, with cache + retry."""
    # `/no_think` keeps Qwen3 fast for structured/utility prompts.
    if "/no_think" not in prompt:
        prompt = prompt + "\n/no_think"

    key = _cache_key(LLM_MODEL, system_prompt, prompt, json_mode)
    if use_cache:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            llm_state["cache_hits"] += 1
            return hit[1]

    if agent_id:
        llm_state["queue"].append(agent_id)
    async with llm_semaphore:
        if agent_id and agent_id in llm_state["queue"]:
            llm_state["queue"].remove(agent_id)
        llm_state["holder"] = agent_id
        llm_state["_t0"] = time.time()
        llm_state["tokens"] = 0
        llm_state["calls"] += 1
        try:
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                # Disable Qwen3's hidden <think> reasoning block. The inline
                # "/no_think" hint is unreliable on this model; this Ollama flag
                # actually suppresses it, cutting ~100–1300 wasted tokens per call.
                "think": False,
            }
            if json_mode:
                payload["format"] = "json"

            last_err = None
            for attempt in range(3):  # retry with backoff on transient errors
                try:
                    async with httpx.AsyncClient() as client:
                        r = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=300.0)
                        r.raise_for_status()
                        data = r.json()
                    tokens = int(data.get("eval_count", 0) or 0)
                    dur_ns = int(data.get("eval_duration", 0) or 0)
                    llm_state["tokens"] = tokens
                    if dur_ns:
                        llm_state["rate"] = round(tokens / (dur_ns / 1e9), 1)
                    content = strip_think(data.get("message", {}).get("content", ""))
                    if use_cache:
                        if len(_CACHE) >= _CACHE_MAX:
                            _CACHE.pop(next(iter(_CACHE)))
                        _CACHE[key] = (time.time(), content)
                    return content
                except Exception as e:
                    last_err = e
                    await asyncio.sleep(0.6 * (attempt + 1))
            print(f"Error calling LLM after retries: {last_err}")
            return f"Error: {last_err}"
        finally:
            llm_state["holder"] = None
            llm_state["_t0"] = None


async def generate_json(prompt: str, system_prompt: str = "Return only valid JSON.",
                        agent_id: str = None, use_cache: bool = True):
    """Generate and parse a JSON response. Returns dict/list, or None on failure."""
    raw = await generate_completion(prompt, system_prompt, agent_id=agent_id,
                                    json_mode=True, use_cache=use_cache)
    raw = strip_think(raw)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"[\[{].*[\]}]", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, TypeError):
                return None
        return None
