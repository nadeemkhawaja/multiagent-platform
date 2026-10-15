// ============================================================================
// api.js — backend client, WebSocket live state, and polling fallback.
// ============================================================================
import { useState, useEffect, useCallback, useRef, useSyncExternalStore } from "react";

// Same origin as the page. The dev server proxies /api and /ws to the backend
// (see vite.config.js), so there is exactly one port to open, one origin to
// trust, and the LAN URL works from a phone without exposing the API port.
// VITE_API_BASE still points the app at a backend elsewhere when you need it.
export const API_BASE = import.meta.env.VITE_API_BASE || "";
const WS_URL = API_BASE
  ? API_BASE.replace(/^http/, "ws") + "/ws"
  : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;

// Timeout budgets. A poll must never outlive its own interval or requests pile
// up; anything that reaches the LLM gets a long leash because the model may be
// a Gemma server on the LAN, which can take minutes on a cold prompt.
const T_POLL = 8000;
const T_DEFAULT = 20000;
const T_LLM = 180000;

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// Single entry point for every call, so timeout, transport failure and non-2xx
// handling are identical everywhere. `jsonPost`/`jsonDelete` previously never
// checked `r.ok` and returned `{}` on failure — meaning a 500 from "save
// config", "trigger agent" or "reset portfolio" was indistinguishable from
// success, and the UI cheerfully reported that it had worked.
async function request(path, { method = "GET", body, timeoutMs = T_DEFAULT } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let r;
  try {
    r = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
  } catch (e) {
    if (e?.name === "AbortError") {
      throw new ApiError(`Timed out after ${Math.round(timeoutMs / 1000)}s — the backend or the model may still be working.`);
    }
    // API_BASE is empty in the normal same-origin setup, which turned this
    // into "Can't reach the backend at . Is it running?" — name the origin the
    // request actually went to instead.
    throw new ApiError(`Can't reach the backend at ${API_BASE || window.location.origin}. Is it running?`);
  } finally {
    clearTimeout(timer);
  }

  if (!r.ok) {
    // FastAPI puts the useful part in `detail`; fall back to raw text so the
    // message names the actual problem instead of a bare status line.
    let detail;
    try {
      const j = await r.clone().json();
      detail = typeof j?.detail === "string" ? j.detail : (j?.message || "");
    } catch {
      detail = (await r.text().catch(() => "")).trim().slice(0, 300);
    }
    throw new ApiError(detail || `${r.status} ${r.statusText || "request failed"}`, r.status);
  }
  return r.json().catch(() => ({}));
}

const jsonGet = (path, timeoutMs) => request(path, { timeoutMs });
const jsonDelete = (path, timeoutMs) => request(path, { method: "DELETE", timeoutMs });
const jsonPost = (path, body, timeoutMs) => request(path, { method: "POST", body, timeoutMs });

// ── Orchestrator live state: WebSocket primary, polling fallback ─────────────
// One connection for the entire app, shared through an external store. This
// used to be a plain hook, so every caller opened its own WebSocket *and* its
// own 2s poll — and with nine components calling useModelLabel() (which wraps
// this), the backend saw several times the traffic it should, with a fresh
// connection churned on every tab switch.
let _snap = { state: null, online: true, transport: "connecting" };
const _subs = new Set();
let _ws = null, _pollId = null, _safetyId = null, _gotWs = false, _stopped = true;

function _set(patch) {
  const next = { ..._snap, ...patch };
  if (next.state === _snap.state && next.online === _snap.online && next.transport === _snap.transport) return;
  _snap = next;
  _subs.forEach((fn) => fn());
}

function _startPoll() {
  if (_pollId) return;
  _set({ transport: "poll" });
  const tick = async () => {
    try { _set({ state: await jsonGet("/api/state", T_POLL), online: true }); }
    catch { _set({ online: false }); }
  };
  tick();
  _pollId = setInterval(tick, 2000);
}
function _stopPoll() { if (_pollId) { clearInterval(_pollId); _pollId = null; } }

function _start() {
  if (!_stopped) return;
  _stopped = false;
  _gotWs = false;
  try {
    _ws = new WebSocket(WS_URL);
    _ws.onopen = () => _set({ transport: "ws" });
    _ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "state") { _gotWs = true; _set({ state: msg.data, online: true }); _stopPoll(); }
      } catch { /* a malformed frame must not kill the socket */ }
    };
    _ws.onclose = () => { if (!_stopped) _startPoll(); };
    _ws.onerror = () => { if (!_stopped) _startPoll(); };
  } catch { _startPoll(); }
  _safetyId = setTimeout(() => { if (!_gotWs && !_stopped) _startPoll(); }, 1500);
}

function _stop() {
  _stopped = true;
  clearTimeout(_safetyId); _safetyId = null;
  _stopPoll();
  try { _ws && _ws.close(); } catch { /* already closing */ }
  _ws = null;
}

function _subscribe(cb) {
  _subs.add(cb);
  _start();
  return () => {
    _subs.delete(cb);
    // Last listener out closes the connection, so an unmounted app stops
    // polling instead of leaking an interval for the page's lifetime.
    if (_subs.size === 0) _stop();
  };
}

export function useSystemState() {
  return useSyncExternalStore(_subscribe, () => _snap, () => _snap);
}

// Short display name for a "provider:model" spec (e.g. "local:google/gemma-4-26B-A4B-it"
// → "Gemma", "anthropic:claude-opus-4-8" → "Claude").
export function friendlyModelName(spec) {
  if (!spec) return "…";
  const model = spec.includes(":") ? spec.split(":").slice(1).join(":") : spec;
  const lower = model.toLowerCase();
  if (lower.includes("gemma")) return "Gemma";
  if (lower.includes("claude") || lower.includes("opus") || lower.includes("sonnet") || lower.includes("haiku")) return "Claude";
  if (lower.includes("gpt")) return "GPT";
  if (lower.includes("grok")) return "Grok";
  if (lower.includes("llama")) return "Llama";
  return model.split("/").pop().split("-")[0];
}

// Live short model name for UI bylines/pills — reads the orchestrator's active model.
export function useModelLabel() {
  const { state } = useSystemState();
  return friendlyModelName(state?.llm?.model);
}

// ── Per-agent data ──────────────────────────────────────────────────────────
export function useAgentData(agentId, intervalMs = 6000) {
  const [data, setData] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const seq = useRef(0);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const next = await jsonGet(`/api/agent/${agentId}/data`);
      // A slow response that a newer poll has already superseded must not
      // overwrite fresher data — at a 6s interval against a busy backend the
      // responses can genuinely arrive out of order.
      if (!alive.current || mine !== seq.current) return;
      setData(next); setError(null); setLoaded(true);
    } catch (e) {
      if (!alive.current || mine !== seq.current) return;
      // Previously swallowed entirely: a 500 on one agent's endpoint left the
      // tab showing stale data with no indication anything was wrong.
      setError(e?.message || "Couldn't load this agent's data.");
      setLoaded(true);
    }
  }, [agentId]);

  useEffect(() => {
    alive.current = true;
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => { alive.current = false; clearInterval(id); };
  }, [refresh, intervalMs]);

  return { data, loaded, error, refresh };
}

// ── Actions ─────────────────────────────────────────────────────────────────
// Anything that can reach the model carries the long budget: a cold prompt on
// the LAN Gemma server can take minutes, and a short timeout would report a
// working run as a failure.
export const triggerAgent = (id, cfg) => jsonPost(`/api/agent/${id}/trigger`, cfg || {}, T_LLM);
export const stopAgent = (id) => jsonPost(`/api/agent/${id}/stop`);

// ── Alpha Wolf paper trading ─────────────────────────────────────────────────
export const getWolfPortfolio = (refresh = false) => jsonGet(`/api/alpha-wolf/portfolio${refresh ? "?refresh=true" : ""}`);
export const setWolfExecution = (body) => jsonPost("/api/alpha-wolf/execution", body);
export const resetWolfPortfolio = () => jsonPost("/api/alpha-wolf/portfolio/reset");
export const getWolfNow = () => jsonGet("/api/alpha-wolf/now");
export const getWolfJournal = (limit = 100) => jsonGet(`/api/alpha-wolf/journal?limit=${limit}`);
export const runWolfRiskCheck = () => jsonPost("/api/alpha-wolf/risk-check", undefined, T_LLM);
export const cancelWolfPending = (orderId) => jsonDelete(`/api/alpha-wolf/pending/${encodeURIComponent(orderId)}`);

// ── Settings / schedules / health / email preview ───────────────────────────
export const getConfig = () => jsonGet("/api/config");
export const saveConfig = (body) => jsonPost("/api/config", body);
export const getSchedules = () => jsonGet("/api/schedules");
export const setSchedule = (agent, body) => jsonPost(`/api/schedules/${agent}`, body);
export const getHealth = () => jsonGet("/api/health");
export const emailPreview = (id) => jsonGet(`/api/agent/${id}/email-preview`);

// ── LLM providers / per-agent models ────────────────────────────────────────
export const getLLMProviders = () => jsonGet("/api/llm/providers");
export const setAgentModel = (agent_id, model) => jsonPost("/api/llm/models", { agent_id, model });
export const setProviderKey = (provider, api_key) => jsonPost("/api/llm/keys", { provider, api_key });

// ── Per-agent AI assistant ──────────────────────────────────────────────────
export const agentAssist = (id, prompt) => jsonPost(`/api/agent/${id}/assist`, { prompt }, T_LLM);

// ── MCP servers ─────────────────────────────────────────────────────────────
export const getMCP = () => jsonGet("/api/mcp");
export const addMCPServer = (body) => jsonPost("/api/mcp/servers", body);
export const removeMCPServer = (name) => jsonDelete(`/api/mcp/servers/${encodeURIComponent(name)}`);
export const pingMCPServer = (name) => jsonGet(`/api/mcp/servers/${encodeURIComponent(name)}/ping`);
export const getMCPTools = (name) => jsonGet(`/api/mcp/servers/${encodeURIComponent(name)}/tools`);
