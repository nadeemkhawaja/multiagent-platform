// ============================================================================
// api.js — backend client, WebSocket live state, and polling fallback.
// ============================================================================
import { useState, useEffect, useCallback } from "react";

const HOST = window.location.hostname;
const PORT = 5174;
export const API_BASE = `http://${HOST}:${PORT}`;
const WS_URL = `ws://${HOST}:${PORT}/ws`;

async function jsonGet(path) {
  const r = await fetch(`${API_BASE}${path}`);
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}
async function jsonPost(path, body) {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json().catch(() => ({}));
}

// ── Orchestrator live state: WebSocket primary, polling fallback ─────────────
export function useSystemState() {
  const [state, setState] = useState(null);
  const [online, setOnline] = useState(true);
  const [transport, setTransport] = useState("connecting");

  useEffect(() => {
    let ws, pollId, closed = false, gotWs = false;
    const startPoll = () => {
      if (pollId) return;
      setTransport("poll");
      const tick = async () => {
        try { setState(await jsonGet("/api/state")); setOnline(true); }
        catch { setOnline(false); }
      };
      tick();
      pollId = setInterval(tick, 2000);
    };
    const stopPoll = () => { if (pollId) { clearInterval(pollId); pollId = null; } };

    try {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => setTransport("ws");
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "state") { gotWs = true; setState(msg.data); setOnline(true); stopPoll(); }
        } catch { /* ignore */ }
      };
      ws.onclose = () => { if (!closed) startPoll(); };
      ws.onerror = () => { startPoll(); };
    } catch { startPoll(); }

    // if WS hasn't delivered quickly, poll in the meantime
    const safety = setTimeout(() => { if (!gotWs) startPoll(); }, 1500);
    return () => { closed = true; clearTimeout(safety); stopPoll(); try { ws && ws.close(); } catch { /* */ } };
  }, []);

  return { state, online, transport };
}

// ── Per-agent data ──────────────────────────────────────────────────────────
export function useAgentData(agentId, intervalMs = 6000) {
  const [data, setData] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const refresh = useCallback(async () => {
    try { setData(await jsonGet(`/api/agent/${agentId}/data`)); setLoaded(true); }
    catch { setLoaded(true); }
  }, [agentId]);
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);
  return { data, loaded, refresh };
}

// ── Actions ─────────────────────────────────────────────────────────────────
export const triggerAgent = (id, cfg) => jsonPost(`/api/agent/${id}/trigger`, cfg || {});
export const stopAgent = (id) => jsonPost(`/api/agent/${id}/stop`);
export const spikeResource = (resource) => jsonPost("/api/demo/spike", { resource });
export const crashAgent = (agent_id) => jsonPost("/api/demo/crash", agent_id ? { agent_id } : {});
export const getDemoMode = () => jsonGet("/api/demo/mode");
export const setDemoMode = (enabled) => jsonPost("/api/demo/mode", { enabled });
export const aegisApprove = (id, reply) => jsonPost("/api/aegis/approve", { id, reply });
export const aegisDismiss = (id) => jsonPost("/api/aegis/dismiss", { id });

// ── Alpha Wolf paper trading ─────────────────────────────────────────────────
export const getWolfPortfolio = (refresh = false) => jsonGet(`/api/alpha-wolf/portfolio${refresh ? "?refresh=true" : ""}`);
export const setWolfExecution = (body) => jsonPost("/api/alpha-wolf/execution", body);
export const resetWolfPortfolio = () => jsonPost("/api/alpha-wolf/portfolio/reset");

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

// ── Run metrics ─────────────────────────────────────────────────────────────
export const getMetrics = (window = 50) => jsonGet(`/api/metrics?window=${window}`);
