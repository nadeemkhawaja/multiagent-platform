import asyncio
import time
import json
import re
import hashlib
import httpx
import os
from dotenv import load_dotenv

import anthropic as anthropic_sdk

import tracing

load_dotenv()

# ── Providers ─────────────────────────────────────────────────────────────────
# The platform speaks to four backends. AI_PROVIDER picks the global default;
# individual agents can be routed anywhere via the "agent_models" config
# ({"agent_id": "anthropic:claude-opus-4-8"} / {"agent_id": "local:gemma..."}).
#   local     — any OpenAI-compatible server (vLLM, LM Studio…) at LOCAL_LLM_BASE_URL
#   anthropic — Claude via the official Anthropic SDK
#   openai / grok — OpenAI-compatible cloud APIs
AI_PROVIDER = os.getenv("AI_PROVIDER", "").strip().lower()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
GROK_API_KEY = os.getenv("XAI_API_KEY", os.getenv("GROK_API_KEY", ""))
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4-fast")
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8001/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "16000"))

KNOWN_PROVIDERS = ("local", "openai", "anthropic", "grok")

# Dropdown suggestions for the Settings UI — any model name works via the API.
SUGGESTED_MODELS = {
    "anthropic": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
    "local": [LOCAL_LLM_MODEL] if LOCAL_LLM_MODEL else [],
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "grok": ["grok-4-fast", "grok-3-mini"],
}


class ConfigError(Exception):
    """Provider misconfiguration (e.g. missing API key) — not worth retrying."""


def parse_model_spec(spec: str):
    """'anthropic:claude-opus-4-8' → ('anthropic', 'claude-opus-4-8');
    bare model names default to the local endpoint."""
    if spec and ":" in spec:
        head, rest = spec.split(":", 1)
        if head in KNOWN_PROVIDERS and rest:
            return head, rest
    return "local", spec or LOCAL_LLM_MODEL


def default_model_spec() -> str:
    """Global default 'provider:model'. AI_PROVIDER selects the provider and the
    per-provider model env picks the model; defaults to the local endpoint
    when AI_PROVIDER is unset or unrecognized."""
    prov = AI_PROVIDER if AI_PROVIDER in KNOWN_PROVIDERS else "local"
    model = {"anthropic": ANTHROPIC_MODEL, "local": LOCAL_LLM_MODEL,
             "openai": OPENAI_MODEL, "grok": GROK_MODEL}[prov]
    return f"{prov}:{model}"


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
    return parse_model_spec(spec or default_model_spec())


def _ui_keys() -> dict:
    """API keys saved from the Settings UI (provider_keys config row)."""
    try:
        from database import get_config
        return get_config("provider_keys", {}) or {}
    except Exception:
        return {}


_ENV_KEYS = {"openai": lambda: OPENAI_API_KEY, "anthropic": lambda: ANTHROPIC_API_KEY,
             "grok": lambda: GROK_API_KEY, "local": lambda: LOCAL_LLM_API_KEY}


def get_api_key(provider: str) -> str:
    """Settings-UI key first, then environment — so keys pasted in the
    dashboard take effect immediately without a backend restart."""
    env = _ENV_KEYS.get(provider)
    return _ui_keys().get(provider) or (env() if env else "")


def provider_status() -> dict:
    """Which providers are usable right now (key/endpoint presence, not reachability)."""
    ui = _ui_keys()
    default_prov, default_model = parse_model_spec(default_model_spec())
    out = {
        "local": {"configured": bool(LOCAL_LLM_MODEL), "base_url": LOCAL_LLM_BASE_URL,
                  "source": "env" if LOCAL_LLM_MODEL else None,
                  "model": LOCAL_LLM_MODEL, "needs_key": False},
    }
    bases = {"openai": OPENAI_BASE_URL, "anthropic": ANTHROPIC_BASE_URL, "grok": GROK_BASE_URL}
    for prov in ("anthropic", "openai", "grok"):
        key = get_api_key(prov)
        out[prov] = {
            "configured": bool(key),
            "base_url": bases[prov],
            "source": "ui" if ui.get(prov) else ("env" if _ENV_KEYS[prov]() else None),
            "key_hint": f"…{key[-4:]}" if key else "",
        }
    for prov in out:
        out[prov]["is_default"] = prov == default_prov
    return out

# Single-permit semaphore: only one agent calls the model at a time → fully
# serialized inference, no contention, no circular waits, no deadlocks.
llm_semaphore = asyncio.Semaphore(1)

# Live semaphore state surfaced on the Orchestrator dashboard.
llm_state = {
    "holder": None, "queue": [], "tokens": 0, "rate": 0, "_t0": None,
    "model": default_model_spec(), "calls": 0, "cache_hits": 0, "fallbacks": 0,
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
        "calls": s["calls"], "cache_hits": s["cache_hits"], "fallbacks": s["fallbacks"],
    }


def _cache_key(model, system, prompt, json_mode):
    raw = f"{model}|{json_mode}|{system}|{prompt}"
    return hashlib.sha256(raw.encode()).hexdigest()


def strip_think(text: str) -> str:
    """Remove <think>…</think> reasoning blocks some local models emit."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


# ── Provider backends — each returns (content, tokens_in, tokens_out, rate) ──
async def _call_openai_compatible(client, base_url, api_key, key_name,
                                  model, system_prompt, prompt, json_mode,
                                  require_key=True, json_via_prompt=False):
    """Shared caller for OpenAI-API-compatible providers (OpenAI, Grok/xAI,
    and any local vLLM/LM Studio-style server)."""
    if require_key and not api_key:
        raise ConfigError(f"{key_name} not set — add a key in Settings → AI models or .env")
    system = system_prompt
    if json_mode and json_via_prompt:
        # Local servers don't all support response_format — ask in the prompt.
        system += " Respond with valid JSON only — no prose, no code fences."
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": LLM_MAX_TOKENS,
    }
    if json_mode and not json_via_prompt:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    r = await client.post(
        f"{base_url}/chat/completions",
        json=payload,
        headers=headers,
        # tight connect timeout so an unreachable endpoint fails over to the
        # next provider in seconds, not after a full TCP timeout
        timeout=httpx.Timeout(300.0, connect=8.0),
    )
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage", {}) or {}
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    return (strip_think(content), int(usage.get("prompt_tokens", 0) or 0),
            int(usage.get("completion_tokens", 0) or 0), 0)


async def _call_openai(client, model, system_prompt, prompt, json_mode):
    return await _call_openai_compatible(client, OPENAI_BASE_URL, get_api_key("openai"),
                                         "OPENAI_API_KEY", model, system_prompt, prompt, json_mode)


async def _call_grok(client, model, system_prompt, prompt, json_mode):
    return await _call_openai_compatible(client, GROK_BASE_URL, get_api_key("grok"),
                                         "XAI_API_KEY", model, system_prompt, prompt, json_mode)


async def _call_local(client, model, system_prompt, prompt, json_mode):
    if not LOCAL_LLM_BASE_URL:
        raise ConfigError("LOCAL_LLM_BASE_URL not set — point it at an OpenAI-compatible server in .env")
    return await _call_openai_compatible(client, LOCAL_LLM_BASE_URL, get_api_key("local"),
                                         "LOCAL_LLM_API_KEY", model, system_prompt, prompt,
                                         json_mode, require_key=False, json_via_prompt=True)


def _supports_adaptive_thinking(model: str) -> bool:
    """Adaptive thinking is the recommended mode on Opus 4.6+/Sonnet 4.6+/
    Fable-class models; Haiku-tier models reject it."""
    return "haiku" not in model.lower()


async def _call_anthropic(client, model, system_prompt, prompt, json_mode):
    api_key = get_api_key("anthropic")
    if not api_key:
        raise ConfigError("ANTHROPIC_API_KEY not set — add a key in Settings → AI models or .env")
    system = system_prompt
    if json_mode:
        system += " Respond with valid JSON only — no prose, no code fences."
    kwargs = {}
    if _supports_adaptive_thinking(model):
        kwargs["thinking"] = {"type": "adaptive"}
    # max_retries=0 — generate_completion owns the retry/backoff/fallback loop.
    sdk = anthropic_sdk.AsyncAnthropic(api_key=api_key, base_url=ANTHROPIC_BASE_URL,
                                       max_retries=0)
    try:
        msg = await sdk.messages.create(
            model=model,
            max_tokens=LLM_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
    finally:
        await sdk.close()
    if msg.stop_reason == "refusal":
        raise ConfigError(f"Claude declined this request (refusal): {model}")
    content = "".join(b.text for b in msg.content if b.type == "text")
    usage = msg.usage
    return (content.strip(), int(usage.input_tokens or 0),
            int(usage.output_tokens or 0), 0)


_PROVIDER_CALLS = {"openai": _call_openai, "local": _call_local,
                   "anthropic": _call_anthropic, "grok": _call_grok}


def _candidate_chain(provider: str, model: str) -> list:
    """(provider, model) candidates in order: the resolved primary, then the
    local endpoint — a missing key or cloud outage degrades to the local
    model instead of surfacing an error string to the agent."""
    chain = [(provider, model)]
    if provider != "local" and LOCAL_LLM_MODEL:
        chain.append(("local", LOCAL_LLM_MODEL))
    return chain


async def generate_completion(
    prompt: str,
    system_prompt: str = "You are a helpful AI assistant.",
    agent_id: str = None,
    json_mode: bool = False,
    use_cache: bool = True,
) -> str:
    """Call the agent's resolved LLM through the single-permit semaphore, with
    cache + retry + provider fallback. Provider/model come from the agent_models
    config; the global default is AI_PROVIDER. Token usage is recorded against
    the agent's open run trace."""
    provider, model = resolve_model(agent_id)

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
        try:
            last_err = None
            for ci, (prov, mdl) in enumerate(_candidate_chain(provider, model)):
                llm_state["model"] = f"{prov}:{mdl}"
                if ci > 0:
                    llm_state["fallbacks"] += 1
                    print(f"LLM fallback: {provider}:{model} unavailable → trying {prov}:{mdl} ({last_err})")
                attempts = 3 if ci == 0 else 2  # retry the primary harder than fallbacks
                for attempt in range(attempts):
                    t0 = time.time()
                    try:
                        async with httpx.AsyncClient() as client:
                            content, tokens_in, tokens_out, rate = await _PROVIDER_CALLS[prov](
                                client, mdl, system_prompt, prompt, json_mode
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
                        # Misconfiguration won't fix itself — skip straight to
                        # the next provider in the chain, no retries.
                        last_err = e
                        break
                    except Exception as e:
                        last_err = e
                        await asyncio.sleep(0.6 * (attempt + 1))
            print(f"Error calling LLM after retries + fallbacks: {last_err}")
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
