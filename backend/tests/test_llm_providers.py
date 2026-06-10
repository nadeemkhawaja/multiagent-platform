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
    assert llm_client.resolve_model("wolf") == ("openai", "gpt-test")
    assert llm_client.resolve_model("other") == llm_client.parse_model_spec(llm_client.LLM_MODEL)
    assert llm_client.resolve_model(None) == llm_client.parse_model_spec(llm_client.LLM_MODEL)


def test_provider_status_shape():
    st = llm_client.provider_status()
    assert set(st.keys()) == {"ollama", "openai", "anthropic", "grok"}
    assert st["ollama"]["configured"] is True


def test_suggested_models_cover_frontier_providers():
    assert set(llm_client.SUGGESTED_MODELS.keys()) == {"grok", "openai", "anthropic"}


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


def test_generate_completion_routes_to_anthropic_with_json_mode(monkeypatch):
    captured = {}
    _patch_post(monkeypatch, {
        "content": [{"type": "text", "text": '{"ok": true}'}],
        "usage": {"input_tokens": 9, "output_tokens": 4},
    }, captured)
    monkeypatch.setattr(llm_client, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("anthropic", "claude-test"))

    out = asyncio.run(llm_client.generate_completion("hello", json_mode=True, use_cache=False))
    assert out == '{"ok": true}'
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert "JSON" in captured["json"]["system"]


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


def test_missing_api_key_fails_fast_without_retries(monkeypatch):
    monkeypatch.setattr(llm_client, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(llm_client, "resolve_model", lambda agent_id=None: ("anthropic", "claude-test"))

    slept = {"n": 0}

    async def count_sleep(_seconds):
        slept["n"] += 1
    monkeypatch.setattr(asyncio, "sleep", count_sleep)

    out = asyncio.run(llm_client.generate_completion("hello", use_cache=False))
    assert out.startswith("Error:")
    assert "ANTHROPIC_API_KEY" in out
    assert slept["n"] == 0   # ConfigError short-circuits the retry loop
