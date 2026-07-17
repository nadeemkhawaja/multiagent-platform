"""Tests for llm_client provider routing — no network, all HTTP mocked.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

import llm_client
import tracing


# ── model spec parsing ───────────────────────────────────────────────────────
def test_parse_model_spec_defaults_to_ollama():
    assert llm_client.parse_model_spec("qwen3.5:4b") == ("ollama", "qwen3.5:4b")
    assert llm_client.parse_model_spec("llama3") == ("ollama", "llama3")


def test_parse_model_spec_provider_prefixes():
    assert llm_client.parse_model_spec("anthropic:claude-haiku-4-5") == ("anthropic", "claude-haiku-4-5")
    assert llm_client.parse_model_spec("openai:gpt-4o-mini") == ("openai", "gpt-4o-mini")
    assert llm_client.parse_model_spec("grok:grok-4-fast") == ("grok", "grok-4-fast")
    assert llm_client.parse_model_spec("ollama:llama3:8b") == ("ollama", "llama3:8b")


def test_resolve_model_honors_agent_override(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_config",
                        lambda key, default=None: {"wolf": "openai:gpt-test"} if key == "agent_models" else default)
    default = llm_client.parse_model_spec(llm_client.default_model_spec())
    assert llm_client.resolve_model("wolf") == ("openai", "gpt-test")
    assert llm_client.resolve_model("other") == default
    assert llm_client.resolve_model(None) == default


def test_default_model_spec_follows_ai_provider(monkeypatch):
    monkeypatch.setattr(llm_client, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(llm_client, "ANTHROPIC_MODEL", "claude-opus-4-8")
    assert llm_client.default_model_spec() == "anthropic:claude-opus-4-8"
    monkeypatch.setattr(llm_client, "AI_PROVIDER", "local")
    monkeypatch.setattr(llm_client, "LOCAL_LLM_MODEL", "google/gemma-test")
    assert llm_client.default_model_spec() == "local:google/gemma-test"
    monkeypatch.setattr(llm_client, "AI_PROVIDER", "")
    assert llm_client.default_model_spec() == llm_client.LLM_MODEL
    # provider selected but no model configured → fall back to LLM_MODEL
    monkeypatch.setattr(llm_client, "AI_PROVIDER", "local")
    monkeypatch.setattr(llm_client, "LOCAL_LLM_MODEL", "")
    assert llm_client.default_model_spec() == llm_client.LLM_MODEL


def test_provider_status_shape():
    st = llm_client.provider_status()
    assert set(st.keys()) == {"ollama", "local", "openai", "anthropic", "grok"}
    assert st["ollama"]["configured"] is True
    assert st["local"]["needs_key"] is False


def test_candidate_chain_degrades_to_local_then_ollama(monkeypatch):
    monkeypatch.setattr(llm_client, "LOCAL_LLM_MODEL", "gemma-test")
    chain = llm_client._candidate_chain("anthropic", "claude-opus-4-8")
    assert chain == [("anthropic", "claude-opus-4-8"),
                     ("local", "gemma-test"),
                     ("ollama", llm_client._ollama_fallback_model())]
    # local primary skips itself; ollama primary still gets local as a backup
    assert llm_client._candidate_chain("local", "gemma-test") == [
        ("local", "gemma-test"), ("ollama", llm_client._ollama_fallback_model())]
    assert llm_client._candidate_chain("ollama", "qwen3.5:4b") == [
        ("ollama", "qwen3.5:4b"), ("local", "gemma-test")]


# ── API key resolution (Settings UI keys override env, env is fallback) ─────
def test_get_api_key_prefers_ui_key_over_env(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_config",
                        lambda key, default=None: {"grok": "xai-from-ui"} if key == "provider_keys" else default)
    monkeypatch.setattr(llm_client, "GROK_API_KEY", "xai-from-env")
    assert llm_client.get_api_key("grok") == "xai-from-ui"


def test_get_api_key_falls_back_to_env(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_config", lambda key, default=None: default)
    monkeypatch.setattr(llm_client, "OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setattr(llm_client, "ANTHROPIC_API_KEY", "")
    assert llm_client.get_api_key("openai") == "sk-from-env"
    assert llm_client.get_api_key("anthropic") == ""


def test_provider_status_reports_key_source(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_config",
                        lambda key, default=None: {"grok": "xai-ui-key"} if key == "provider_keys" else default)
    monkeypatch.setattr(llm_client, "OPENAI_API_KEY", "sk-env-key")
    monkeypatch.setattr(llm_client, "ANTHROPIC_API_KEY", "")
    st = llm_client.provider_status()
    assert st["grok"]["configured"] is True and st["grok"]["source"] == "ui"
    assert st["grok"]["key_hint"] == "…-key"
    assert st["openai"]["configured"] is True and st["openai"]["source"] == "env"
    assert st["anthropic"]["configured"] is False and st["anthropic"]["source"] is None


def test_ui_key_reaches_request_header(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_config",
                        lambda key, default=None: {"grok": "xai-ui-key"} if key == "provider_keys" else default)
    monkeypatch.setattr(llm_client, "GROK_API_KEY", "")
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("grok", "grok-4-fast"))
    captured = {}
    _patch_post(monkeypatch, {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }, captured)
    out = asyncio.run(llm_client.generate_completion("hello", use_cache=False))
    assert out == "hi"
    assert captured["headers"]["Authorization"] == "Bearer xai-ui-key"


def test_suggested_models_cover_frontier_providers():
    assert set(llm_client.SUGGESTED_MODELS.keys()) == {"grok", "openai", "anthropic", "local"}
    assert "claude-opus-4-8" in llm_client.SUGGESTED_MODELS["anthropic"]


# ── provider routing (mocked HTTP) ───────────────────────────────────────────
class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _patch_post(monkeypatch, payload, captured):
    async def fake_post(self, url, json=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers or {}})
        return FakeResponse(payload)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


def test_generate_completion_routes_to_openai(monkeypatch):
    captured = {}
    _patch_post(monkeypatch, {
        "choices": [{"message": {"content": "openai says hi"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }, captured)
    monkeypatch.setattr(llm_client, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("openai", "gpt-test"))

    out = asyncio.run(llm_client.generate_completion("hello", use_cache=False))
    assert out == "openai says hi"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert "/no_think" not in captured["json"]["messages"][1]["content"]


def test_generate_completion_routes_to_grok(monkeypatch):
    captured = {}
    _patch_post(monkeypatch, {
        "choices": [{"message": {"content": "grok says hi"}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 2},
    }, captured)
    monkeypatch.setattr(llm_client, "GROK_API_KEY", "xai-test")
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("grok", "grok-4-fast"))

    out = asyncio.run(llm_client.generate_completion("hello", use_cache=False))
    assert out == "grok says hi"
    assert captured["url"] == "https://api.x.ai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer xai-test"
    assert captured["json"]["model"] == "grok-4-fast"


def _patch_anthropic_sdk(monkeypatch, captured, text='{"ok": true}'):
    """Fake the official Anthropic SDK client used by _call_anthropic."""
    from types import SimpleNamespace as NS

    class FakeMessages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return NS(stop_reason="end_turn",
                      content=[NS(type="text", text=text)],
                      usage=NS(input_tokens=9, output_tokens=4))

    class FakeSDK:
        def __init__(self, **kw):
            captured["client"] = kw
            self.messages = FakeMessages()

        async def close(self):
            pass

    monkeypatch.setattr(llm_client.anthropic_sdk, "AsyncAnthropic", FakeSDK)


def test_generate_completion_routes_to_anthropic_with_json_mode(monkeypatch):
    captured = {}
    _patch_anthropic_sdk(monkeypatch, captured)
    monkeypatch.setattr(llm_client, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("anthropic", "claude-opus-4-8"))

    out = asyncio.run(llm_client.generate_completion("hello", json_mode=True, use_cache=False))
    assert out == '{"ok": true}'
    assert captured["client"]["api_key"] == "sk-ant-test"
    assert captured["model"] == "claude-opus-4-8"
    assert "JSON" in captured["system"]
    assert captured["thinking"] == {"type": "adaptive"}


def test_anthropic_haiku_omits_adaptive_thinking(monkeypatch):
    captured = {}
    _patch_anthropic_sdk(monkeypatch, captured, text="hi")
    monkeypatch.setattr(llm_client, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("anthropic", "claude-haiku-4-5"))

    out = asyncio.run(llm_client.generate_completion("hello", use_cache=False))
    assert out == "hi"
    assert "thinking" not in captured


def test_generate_completion_routes_to_local_endpoint(monkeypatch):
    captured = {}
    _patch_post(monkeypatch, {
        "choices": [{"message": {"content": "gemma says hi"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }, captured)
    monkeypatch.setattr(llm_client, "LOCAL_LLM_BASE_URL", "http://10.20.1.232:8001/v1")
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("local", "google/gemma-test"))

    out = asyncio.run(llm_client.generate_completion("hello", json_mode=True, use_cache=False))
    assert out == "gemma says hi"
    assert captured["url"] == "http://10.20.1.232:8001/v1/chat/completions"
    assert "Authorization" not in captured["headers"]        # no key required
    assert "response_format" not in captured["json"]         # JSON asked via prompt
    assert "JSON" in captured["json"]["messages"][0]["content"]


def test_generate_completion_ollama_records_tokens_to_trace(monkeypatch):
    captured = {}
    _patch_post(monkeypatch, {
        "message": {"content": "local answer"},
        "prompt_eval_count": 50, "eval_count": 25, "eval_duration": int(1e9),
    }, captured)
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("ollama", "qwen3.5:4b"))

    tracing.start("trace_agent")
    out = asyncio.run(llm_client.generate_completion("hello", agent_id="trace_agent", use_cache=False))
    metrics = tracing.finish("trace_agent")

    assert out == "local answer"
    assert "/no_think" in captured["json"]["messages"][1]["content"]
    assert metrics["llm_calls"] == 1
    assert metrics["tokens_in"] == 50
    assert metrics["tokens_out"] == 25


def test_missing_api_key_falls_back_to_ollama(monkeypatch):
    """A missing Claude key must not error out — the call degrades through the
    fallback chain (local skipped here — unset) and Ollama answers."""
    import database
    monkeypatch.setattr(database, "get_config", lambda key, default=None: default)
    monkeypatch.setattr(llm_client, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(llm_client, "LOCAL_LLM_MODEL", "")
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("anthropic", "claude-test"))
    captured = {}
    _patch_post(monkeypatch, {
        "message": {"content": "ollama caught it"},
        "prompt_eval_count": 5, "eval_count": 3, "eval_duration": int(1e9),
    }, captured)

    slept = {"n": 0}

    async def count_sleep(_seconds):
        slept["n"] += 1
    monkeypatch.setattr(asyncio, "sleep", count_sleep)

    out = asyncio.run(llm_client.generate_completion("hello", use_cache=False))
    assert out == "ollama caught it"
    assert captured["url"].endswith("/api/chat")
    assert slept["n"] == 0   # ConfigError skips straight to the next provider


def test_all_providers_down_returns_error(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_config", lambda key, default=None: default)
    monkeypatch.setattr(llm_client, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(llm_client, "LOCAL_LLM_MODEL", "")
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("anthropic", "claude-test"))

    async def failing_post(self, url, json=None, headers=None, timeout=None):
        raise RuntimeError("network down")
    monkeypatch.setattr(httpx.AsyncClient, "post", failing_post)

    async def no_sleep(_seconds):
        pass
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    out = asyncio.run(llm_client.generate_completion("hello", use_cache=False))
    assert out.startswith("Error:")
