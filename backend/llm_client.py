import asyncio
import time
import json
import re
import hashlib
import httpx
import os
from dotenv import load_dotenv

import tracing

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5:4b")

# Frontier providers are opt-in: configure a key and route an agent to them via
# the "agent_models" config ({"agent_id": "anthropic:claude-haiku-4-5"}).
# Local Ollama stays the default for everything else.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
GROK_API_KEY = os.getenv("XAI_API_KEY", os.getenv("GROK_API_KEY", ""))
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))

KNOWN_PROVIDERS = ("ollama", "openai", "anthropic", "grok")

# Dropdown suggestions for the Settings UI — any model name works via the API.
SUGGESTED_MODELS = {
    "grok": ["grok-4-fast", "grok-3-mini"],
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "anthropic": ["claude-haiku-4-5", "claude-sonnet-4-6"],
}


class ConfigError(Exception):
    """Provider misconfiguration (e.g. missing API key) — not worth retrying."""


def parse_model_spec(spec: str):
    """'anthropic:claude-haiku-4-5' → ('anthropic', 'claude-haiku-4-5');
    bare model names ('qwen3:8b') default to ollama."""
    if spec and ":" in spec:
        head, rest = spec.split(":", 1)
        if head in KNOWN_PROVIDERS and rest:
            return head, rest
    return "ollama", spec


def resolve_model(agent_id: str = None):
    """Per-agent model from the agent_models config, else the global default."""
    spec = None
    if agent_id:
        try:
            from database import get_config
            overrides = get_config("agent_models", {}) or {}
            spec = overrides.get(agent_id)
        except Exception:
            spec = None
    return parse_model_spec(spec or LLM_MODEL)


def provider_status() -> dict:
    """Which providers are usable right now (key presence, not reachability)."""
    return {
        "ollama": {"configured": True, "base_url": OLLAMA_BASE_URL},
        "openai": {"configured": bool(OPENAI_API_KEY), "base_url": OPENAI_BASE_URL},
        "anthropic": {"configured": bool(ANTHROPIC_API_KEY), "base_url": ANTHROPIC_BASE_URL},
        "grok": {"configured": bool(GROK_API_KEY), "base_url": GROK_BASE_URL},
    }

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


# ── Provider backends — each returns (content, tokens_in, tokens_out, rate) ──
async def _call_ollama(client, model, system_prompt, prompt, json_mode):
    payload = {
        "model": model,
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
    r = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=300.0)
    r.raise_for_status()
    data = r.json()
    tokens_in = int(data.get("prompt_eval_count", 0) or 0)
    tokens_out = int(data.get("eval_count", 0) or 0)
    dur_ns = int(data.get("eval_duration", 0) or 0)
    rate = round(tokens_out / (dur_ns / 1e9), 1) if dur_ns else 0
    content = strip_think(data.get("message", {}).get("content", ""))
    return content, tokens_in, tokens_out, rate


async def _call_openai_compatible(client, base_url, api_key, key_name,
                                  model, system_prompt, prompt, json_mode):
    """Shared caller for OpenAI-API-compatible providers (OpenAI, Grok/xAI)."""
    if not api_key:
        raise ConfigError(f"{key_name} not set")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": LLM_MAX_TOKENS,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    r = await client.post(
        f"{base_url}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=120.0,
    )
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage", {})
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    return content.strip(), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), 0


async def _call_openai(client, model, system_prompt, prompt, json_mode):
    return await _call_openai_compatible(client, OPENAI_BASE_URL, OPENAI_API_KEY,
                                         "OPENAI_API_KEY", model, system_prompt, prompt, json_mode)


async def _call_grok(client, model, system_prompt, prompt, json_mode):
    return await _call_openai_compatible(client, GROK_BASE_URL, GROK_API_KEY,
                                         "XAI_API_KEY", model, system_prompt, prompt, json_mode)


async def _call_anthropic(client, model, system_prompt, prompt, json_mode):
    if not ANTHROPIC_API_KEY:
        raise ConfigError("ANTHROPIC_API_KEY not set")
    system = system_prompt
    if json_mode:
        system += " Respond with valid JSON only — no prose, no code fences."
    payload = {
        "model": model,
        "max_tokens": LLM_MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    r = await client.post(
        f"{ANTHROPIC_BASE_URL}/v1/messages",
        json=payload,
        headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
        timeout=120.0,
    )
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage", {})
    content = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return content.strip(), int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)), 0


_PROVIDER_CALLS = {"ollama": _call_ollama, "openai": _call_openai,
                   "anthropic": _call_anthropic, "grok": _call_grok}


async def generate_completion(
    prompt: str,
    system_prompt: str = "You are a helpful AI assistant.",
    agent_id: str = None,
    json_mode: bool = False,
    use_cache: bool = True,
) -> str:
    """Call the agent's resolved LLM through the single-permit semaphore, with
    cache + retry. Provider/model come from the agent_models config; default is
    local Ollama. Token usage is recorded against the agent's open run trace."""
    provider, model = resolve_model(agent_id)

    # `/no_think` keeps Qwen3 fast for structured/utility prompts (Ollama only).
    if provider == "ollama" and "/no_think" not in prompt:
        prompt = prompt + "\n/no_think"

    key = _cache_key(f"{provider}:{model}", system_prompt, prompt, json_mode)
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
        llm_state["model"] = f"{provider}:{model}" if provider != "ollama" else model
        try:
            last_err = None
            for attempt in range(3):  # retry with backoff on transient errors
                t0 = time.time()
                try:
                    async with httpx.AsyncClient() as client:
                        content, tokens_in, tokens_out, rate = await _PROVIDER_CALLS[provider](
                            client, model, system_prompt, prompt, json_mode
                        )
                    llm_state["tokens"] = tokens_out
                    if rate:
                        llm_state["rate"] = rate
                    if agent_id:
                        tracing.record_llm(agent_id, tokens_in, tokens_out,
                                           int((time.time() - t0) * 1000))
                    if use_cache:
                        if len(_CACHE) >= _CACHE_MAX:
                            _CACHE.pop(next(iter(_CACHE)))
                        _CACHE[key] = (time.time(), content)
                    return content
                except ConfigError as e:
                    # Misconfiguration won't fix itself — fail fast, no retries.
                    print(f"LLM provider misconfigured: {e}")
                    return f"Error: {e}"
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
