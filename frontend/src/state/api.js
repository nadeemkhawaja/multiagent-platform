// ============================================================================
// api.js — backend client + polling hooks.
// Works on localhost and any network IP.
// ============================================================================
import { useState, useEffect, useCallback } from "react";

export const API_BASE = `http://${window.location.hostname}:5174`;

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

// ── Orchestrator live state (polls /api/state) ──────────────────────────────
export function useSystemState(intervalMs = 2000) {
  const [state, setState] = useState(null);
  const [online, setOnline] = useState(true);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const d = await jsonGet("/api/state");
        if (alive) { setState(d); setOnline(true); }
      } catch {
        if (alive) setOnline(false);
      }
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => { alive = false; clearInterval(id); };
  }, [intervalMs]);
  return { state, online };
}

// ── Per-agent data (polls /api/agent/{id}/data) ─────────────────────────────
export function useAgentData(agentId, intervalMs = 6000) {
  const [data, setData] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const d = await jsonGet(`/api/agent/${agentId}/data`);
      setData(d); setLoaded(true);
    } catch { setLoaded(true); }
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
export const aegisApprove = (id, reply) => jsonPost("/api/aegis/approve", { id, reply });
export const aegisDismiss = (id) => jsonPost("/api/aegis/dismiss", { id });
