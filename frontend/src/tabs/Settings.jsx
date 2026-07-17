// ============================================================================
// Settings.jsx — editable schedules, agent config, and a health panel.
// ============================================================================
import { useState, useEffect, useCallback } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, Dot, Btn, SectionTitle, TabHeader, Appearance } from "../theme/ui";
import { getConfig, saveConfig, getSchedules, setSchedule, getHealth, getLLMProviders, setAgentModel, setProviderKey,
         getMCP, addMCPServer, removeMCPServer, pingMCPServer, getMCPTools } from "../state/api";

const inputStyle = () => ({
  width: "100%", marginTop: 6, border: `1px solid ${T.line}`, borderRadius: 9, padding: "9px 12px",
  fontFamily: T.sans, fontSize: 13, background: T.card, color: T.ink, outline: "none", boxSizing: "border-box",
});

function Field({ label, children, hint }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ fontSize: 11, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</label>
      {children}
      {hint && <div style={{ fontSize: 11, color: T.ink4, marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

function ScheduleRow({ agent, info, onSave }) {
  const col = AGENT_COLOR[agent] || T.violet;
  const [type, setType] = useState(info.config.type);
  const [minutes, setMinutes] = useState(info.config.minutes ?? 15);
  const [hour, setHour] = useState(info.config.hour ?? 8);
  const [minute, setMinute] = useState(info.config.minute ?? 0);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    const body = type === "cron"
      ? { type, hour: Number(hour), minute: Number(minute) }
      : { type, minutes: Number(minutes) };
    await onSave(agent, body);
    setSaving(false);
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr 1.4fr auto", gap: 12, alignItems: "center", padding: "12px 0", borderBottom: `1px solid ${T.line2}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <span style={{ width: 26, height: 26, borderRadius: 7, background: col + "1a", color: col, display: "grid", placeItems: "center", fontWeight: 700, fontSize: 12 }}>●</span>
        <span style={{ fontSize: 13, fontWeight: 700 }}>{info.name}</span>
      </div>
      <select value={type} onChange={(e) => setType(e.target.value)} style={{ ...inputStyle(), marginTop: 0 }}>
        <option value="interval">Interval</option>
        <option value="cron">Daily (cron)</option>
      </select>
      {type === "interval" ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: T.ink3 }}>every</span>
          <input type="number" min="1" value={minutes} onChange={(e) => setMinutes(e.target.value)} style={{ ...inputStyle(), marginTop: 0, width: 80 }} />
          <span style={{ fontSize: 12, color: T.ink3 }}>min</span>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: T.ink3 }}>at</span>
          <input type="number" min="0" max="23" value={hour} onChange={(e) => setHour(e.target.value)} style={{ ...inputStyle(), marginTop: 0, width: 64 }} />
          <span style={{ fontSize: 12, color: T.ink3 }}>:</span>
          <input type="number" min="0" max="59" value={minute} onChange={(e) => setMinute(e.target.value)} style={{ ...inputStyle(), marginTop: 0, width: 64 }} />
        </div>
      )}
      <Btn size="sm" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</Btn>
    </div>
  );
}

const PROVIDER_LABEL = {
  anthropic: "Claude (Anthropic)",
  local: "Local endpoint (vLLM/LM Studio)",
  ollama: "Ollama",
  grok: "Grok (xAI)",
  openai: "OpenAI",
};
const KEY_PLACEHOLDER = { grok: "xai-…", openai: "sk-…", anthropic: "sk-ant-…", local: "usually not needed" };

function ProviderKeyRow({ prov, st, onSave }) {
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => { setBusy(true); await onSave(prov, val.trim()); setVal(""); setBusy(false); };
  const clear = async () => { setBusy(true); await onSave(prov, ""); setBusy(false); };

  const status = !st.configured ? "no key"
    : st.source === "ui" ? `key saved ${st.key_hint || ""} · active now`
    : `key from .env ${st.key_hint || ""}`;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.2fr 2fr auto auto", gap: 10, alignItems: "center", padding: "9px 0", borderBottom: `1px solid ${T.line2}` }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 700 }}>{PROVIDER_LABEL[prov] || prov}</div>
        <div style={{ fontSize: 10.5, color: st.configured ? T.green : T.ink4, marginTop: 2 }}>{status}</div>
      </div>
      <input type="password" autoComplete="off" value={val} onChange={(e) => setVal(e.target.value)}
        placeholder={st.configured ? "Replace key…" : `Paste key (${KEY_PLACEHOLDER[prov] || "…"})`}
        style={{ ...inputStyle(), marginTop: 0 }} />
      <Btn size="sm" onClick={save} disabled={busy || !val.trim()}>{busy ? "…" : "Save"}</Btn>
      <Btn size="sm" onClick={clear} disabled={busy || st.source !== "ui"}>Clear</Btn>
    </div>
  );
}

function ModelRow({ agent, name, llm, onSave }) {
  const col = AGENT_COLOR[agent] || T.violet;
  const current = llm.agent_models?.[agent] || "";
  const [saving, setSaving] = useState(false);
  const [customMode, setCustomMode] = useState(false);
  const [customVal, setCustomVal] = useState("");

  const options = [];
  for (const [prov, models] of Object.entries(llm.suggested_models || {})) {
    const configured = llm.providers?.[prov]?.configured;
    options.push({
      label: PROVIDER_LABEL[prov] || prov,
      configured,
      specs: models.map((m) => `${prov}:${m}`),
    });
  }
  const known = new Set(options.flatMap((g) => g.specs));

  const change = async (e) => {
    if (e.target.value === "__custom__") { setCustomVal(current); setCustomMode(true); return; }
    setSaving(true);
    await onSave(agent, e.target.value);
    setSaving(false);
  };
  const saveCustom = async () => {
    setSaving(true);
    await onSave(agent, customVal.trim());
    setSaving(false);
    setCustomMode(false);
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.2fr 2fr auto", gap: 12, alignItems: "center", padding: "10px 0", borderBottom: `1px solid ${T.line2}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <span style={{ width: 26, height: 26, borderRadius: 7, background: col + "1a", color: col, display: "grid", placeItems: "center", fontWeight: 700, fontSize: 12 }}>●</span>
        <span style={{ fontSize: 13, fontWeight: 700 }}>{name}</span>
      </div>
      {customMode ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input value={customVal} onChange={(e) => setCustomVal(e.target.value)} autoFocus
            placeholder="provider:model — e.g. grok:grok-4, openai:o3-mini, or any Ollama model"
            style={{ ...inputStyle(), marginTop: 0 }}
            onKeyDown={(e) => { if (e.key === "Enter") saveCustom(); if (e.key === "Escape") setCustomMode(false); }} />
          <Btn size="sm" onClick={saveCustom} disabled={saving || !customVal.trim()}>Save</Btn>
          <Btn size="sm" onClick={() => setCustomMode(false)}>✕</Btn>
        </div>
      ) : (
        <select value={current} onChange={change} style={{ ...inputStyle(), marginTop: 0 }}>
          <option value="">Default · {llm.default_model}</option>
          {!known.has(current) && current && <option value={current}>{current} (custom)</option>}
          {options.map((g) => (
            <optgroup key={g.label} label={g.configured ? g.label : `${g.label} — no API key`}>
              {g.specs.map((spec) => (
                <option key={spec} value={spec} disabled={!g.configured}>{spec.split(":").slice(1).join(":")}</option>
              ))}
            </optgroup>
          ))}
          <option value="__custom__">Custom model…</option>
        </select>
      )}
      <span style={{ fontSize: 11, color: T.ink4, minWidth: 56 }}>{saving ? "Saving…" : current ? current.split(":")[0] : "default"}</span>
    </div>
  );
}

function MCPServerRow({ name, cfg, onRemove }) {
  const [ping, setPing] = useState(null);
  const [tools, setTools] = useState(null);
  const [busy, setBusy] = useState(false);

  const doPing = async () => {
    setBusy(true); setPing(null);
    setPing(await pingMCPServer(name).catch((e) => ({ reachable: false, error: String(e) })));
    setBusy(false);
  };
  const doTools = async () => {
    if (tools) { setTools(null); return; }   // toggle off
    setBusy(true);
    const r = await getMCPTools(name).catch((e) => ({ error: String(e) }));
    setTools(r.error ? { error: r.error } : { list: r.tools || [] });
    setBusy(false);
  };

  return (
    <div style={{ padding: "11px 0", borderBottom: `1px solid ${T.line2}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ width: 26, height: 26, borderRadius: 7, background: T.violet + "1a", color: T.violet, display: "grid", placeItems: "center", fontWeight: 700, fontSize: 12 }}>⌁</span>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>{name} {!cfg.enabled && <span style={{ fontSize: 10, color: T.ink4 }}>(disabled)</span>}</div>
          <div style={{ fontSize: 11, color: T.ink3, fontFamily: T.mono }}>{cfg.command} {(cfg.args || []).join(" ")}</div>
          {(cfg.env || []).length > 0 && (
            <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 2 }}>env: {(cfg.env || []).join(", ")}</div>
          )}
        </div>
        <Btn size="sm" onClick={doPing} disabled={busy}>{busy ? "…" : "Ping"}</Btn>
        <Btn size="sm" onClick={doTools} disabled={busy}>{tools ? "Hide tools" : "Tools"}</Btn>
        <Btn size="sm" onClick={() => onRemove(name)} disabled={busy}>Remove</Btn>
      </div>
      {ping && (
        <div style={{ fontSize: 11.5, marginTop: 6, color: ping.reachable ? T.green : T.red }}>
          {ping.reachable ? `● reachable · ${ping.tools} tool${ping.tools === 1 ? "" : "s"}` : `○ unreachable — ${ping.error || "no response"}`}
        </div>
      )}
      {tools && (
        <div style={{ marginTop: 8, padding: "10px 12px", background: T.cardAlt, border: `1px solid ${T.line}`, borderRadius: 9 }}>
          {tools.error ? (
            <div style={{ fontSize: 11.5, color: T.red }}>{tools.error}</div>
          ) : tools.list.length === 0 ? (
            <div style={{ fontSize: 11.5, color: T.ink4 }}>No tools exposed.</div>
          ) : tools.list.map((t, i) => (
            <div key={i} style={{ padding: "5px 0", borderBottom: i < tools.list.length - 1 ? `1px solid ${T.line2}` : "none" }}>
              <span style={{ fontFamily: T.mono, fontSize: 11.5, fontWeight: 700, color: T.violet }}>{t.name}</span>
              {t.description && <span style={{ fontSize: 11, color: T.ink3 }}> — {String(t.description).slice(0, 140)}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MCPCard() {
  const [mcp, setMcp] = useState(null);
  const [form, setForm] = useState({ name: "", command: "", args: "", env: "" });
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setMcp(await getMCP().catch(() => null));
  }, []);
  useEffect(() => { load(); }, [load]);

  const setF = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const add = async () => {
    setError(null);
    if (!form.name.trim() || !form.command.trim()) { setError("Name and command are required."); return; }
    const env = {};
    for (const line of form.env.split("\n")) {
      const t = line.trim();
      if (!t) continue;
      const i = t.indexOf("=");
      if (i < 1) { setError(`Bad env line: "${t}" — use KEY=VALUE, one per line.`); return; }
      env[t.slice(0, i).trim()] = t.slice(i + 1).trim();
    }
    setAdding(true);
    const r = await addMCPServer({
      name: form.name.trim(), command: form.command.trim(),
      args: form.args.trim() ? form.args.trim().split(/\s+/) : [],
      env, enabled: true,
    }).catch((e) => ({ error: String(e) }));
    setAdding(false);
    if (r.error) { setError(r.error); return; }
    setForm({ name: "", command: "", args: "", env: "" });
    load();
  };

  const remove = async (name) => {
    if (!window.confirm(`Remove MCP server "${name}"?`)) return;
    await removeMCPServer(name);
    load();
  };

  const servers = Object.entries(mcp?.servers || {});
  return (
    <Card pad={15}>
      <SectionTitle sub="Connect Model Context Protocol servers — their tools become callable by the platform">MCP servers</SectionTitle>
      {!mcp ? (
        <div style={{ fontSize: 12.5, color: T.ink3 }}>Loading…</div>
      ) : (
        <>
          {!mcp.available && (
            <div style={{ fontSize: 12, color: T.amber, background: T.amberBg, border: `1px solid ${T.amber}44`, borderRadius: 9, padding: "9px 12px", marginBottom: 10 }}>
              The <span style={{ fontFamily: T.mono }}>mcp</span> Python package isn't installed on the backend —
              servers can be registered but not called. Install with <span style={{ fontFamily: T.mono }}>pip install mcp</span>.
            </div>
          )}
          {servers.length === 0
            ? <div style={{ fontSize: 12.5, color: T.ink4, padding: "6px 0 12px" }}>No MCP servers registered yet.</div>
            : servers.map(([name, cfg]) => <MCPServerRow key={name} name={name} cfg={cfg} onRemove={remove} />)}

          <div style={{ fontSize: 11, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4, margin: "16px 0 2px" }}>Add server</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
            <Field label="Name" hint="Identifier, e.g. filesystem, github">
              <input value={form.name} onChange={(e) => setF("name", e.target.value)} placeholder="filesystem" style={inputStyle()} />
            </Field>
            <Field label="Command" hint="Executable that starts the server (stdio)">
              <input value={form.command} onChange={(e) => setF("command", e.target.value)} placeholder="npx" style={inputStyle()} />
            </Field>
            <Field label="Arguments" hint="Space-separated">
              <input value={form.args} onChange={(e) => setF("args", e.target.value)} placeholder="-y @modelcontextprotocol/server-filesystem /tmp" style={inputStyle()} />
            </Field>
            <Field label="Environment" hint="KEY=VALUE, one per line — values are never shown back">
              <textarea rows={2} value={form.env} onChange={(e) => setF("env", e.target.value)} placeholder={"GITHUB_TOKEN=ghp_…"} style={{ ...inputStyle(), resize: "vertical", lineHeight: 1.55 }} />
            </Field>
          </div>
          {error && <div style={{ fontSize: 12, color: T.red, marginBottom: 8 }}>{error}</div>}
          <Btn size="sm" kind="primary" onClick={add} disabled={adding}>{adding ? "Adding…" : "Add MCP server"}</Btn>
        </>
      )}
    </Card>
  );
}

export default function Settings({ mode, setMode }) {
  const [config, setConfig] = useState(null);
  const [schedules, setSchedules] = useState(null);
  const [health, setHealth] = useState(null);
  const [llm, setLlm] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  const load = useCallback(async () => {
    setConfig(await getConfig().catch(() => ({})));
    setSchedules(await getSchedules().catch(() => ({})));
    setHealth(await getHealth().catch(() => null));
    setLlm(await getLLMProviders().catch(() => null));
  }, []);
  useEffect(() => { load(); }, [load]);

  const onModelSave = async (agent, model) => {
    await setAgentModel(agent, model);
    setLlm(await getLLMProviders().catch(() => llm));
  };

  const onKeySave = async (provider, key) => {
    await setProviderKey(provider, key);
    setLlm(await getLLMProviders().catch(() => llm));
  };

  const saveSettings = async () => {
    const c = await saveConfig(config);
    setConfig(c); setSavedAt(new Date().toLocaleTimeString());
  };
  const onScheduleSave = async (agent, body) => { await setSchedule(agent, body); setSchedules(await getSchedules()); };
  const setField = (k, v) => setConfig((c) => ({ ...c, [k]: v }));

  return (
    <div>
      <TabHeader icon="⚙" color={T.violet} title="Settings" sub="Schedules · agent config · system health"
        actions={<Btn size="sm" kind="primary" onClick={saveSettings}>Save settings</Btn>} />
      <div className="om-stagger" style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 9 }}>
        {/* Appearance */}
        {mode && setMode && (
          <Card pad={15}>
            <SectionTitle sub="Color mode">Appearance</SectionTitle>
            <Appearance mode={mode} setMode={setMode} />
          </Card>
        )}

        {/* Health */}
        <Card pad={15}>
          <SectionTitle sub="Live dependency status">System health</SectionTitle>
          {health ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
              <HealthStat label="Status" value={health.status} ok={health.status === "ok"} />
              <HealthStat label="Ollama" value={health.ollama.reachable ? "reachable" : "offline"} ok={health.ollama.reachable} />
              <HealthStat label="Model" value={health.ollama.model} ok={health.ollama.available?.length > 0} />
              <HealthStat label="Database" value={health.database ? "ok" : "error"} ok={health.database} />
            </div>
          ) : <div style={{ fontSize: 12.5, color: T.ink3 }}>Loading…</div>}
          {health && <div style={{ marginTop: 12, fontSize: 11.5, color: T.ink4, fontFamily: T.mono }}>
            LLM calls: {health.llm.calls} · cache hits: {health.llm.cache_hits}
          </div>}
        </Card>

        {/* Agent config */}
        <Card pad={15}>
          <SectionTitle sub="Applied on the next agent run" right={savedAt && <Pill c={T.green} bg={T.greenBg}><Dot c={T.green} />Saved {savedAt}</Pill>}>Agent configuration</SectionTitle>
          {config && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
              <Field label="Digest recipient email" hint="Where agent emails are sent">
                <input value={config.recipient || ""} onChange={(e) => setField("recipient", e.target.value)} placeholder="you@gmail.com" style={inputStyle()} />
              </Field>
              <Field label="Mailman key people" hint="Comma-separated names/emails to alert on">
                <input value={config.key_people || ""} onChange={(e) => setField("key_people", e.target.value)} placeholder="Sarah Chen, marcus@acme.io" style={inputStyle()} />
              </Field>
              <Field label="Wolf watchlist (20+ tickers)" hint="Comma-separated tickers · falls back to defaults if < 20">
                <textarea rows={4} value={config.watchlist || ""} onChange={(e) => setField("watchlist", e.target.value)} placeholder={"AAPL, MSFT, NVDA, GOOGL,\nAMZN, TSLA, META, AMD, …"} style={{ ...inputStyle(), resize: "vertical", lineHeight: 1.55 }} />
              </Field>
              <Field label="Capitol Tracker politicians" hint="Comma-separated last names or full names — one per line OK">
                <textarea rows={5} value={config.capitol_politicians || ""} onChange={(e) => setField("capitol_politicians", e.target.value)} placeholder={"Pelosi, Trump, Cruz, McClain,\nMoore, McCormick, Greene, Issa, …"} style={{ ...inputStyle(), resize: "vertical", lineHeight: 1.55 }} />
              </Field>
              <Field label="Capitol Tracker lookback window" hint={`${config.capitol_months || 2} month${(config.capitol_months || 2) === 1 ? "" : "s"} of STOCK Act disclosures`}>
                <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 8 }}>
                  <input type="range" min="1" max="12" step="1" value={config.capitol_months || 2} onChange={(e) => setField("capitol_months", Number(e.target.value))} style={{ flex: 1, accentColor: T.violet }} />
                  <span style={{ fontFamily: T.mono, fontWeight: 700, fontSize: 16, minWidth: 36, textAlign: "center" }}>{config.capitol_months || 2}<span style={{ fontSize: 11, fontWeight: 600, color: T.ink4, marginLeft: 2 }}>mo</span></span>
                </div>
              </Field>
            </div>
          )}
        </Card>

        {/* AI models */}
        <Card pad={15}>
          <SectionTitle sub={`Default: ${llm?.default_model || "…"} — route any agent to Claude, the local endpoint, or Ollama (applies on its next run)`}>AI models</SectionTitle>
          {llm ? (
            <>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
                {Object.entries(llm.providers || {}).map(([prov, st]) => (
                  <Pill key={prov} c={st.configured ? T.green : T.ink4} bg={st.configured ? T.greenBg : T.line2}>
                    <Dot c={st.configured ? T.green : T.ink4} />{prov}{st.configured ? "" : " · no key"}
                  </Pill>
                ))}
              </div>
              <div style={{ fontSize: 11, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4, margin: "6px 0 2px" }}>Provider API keys</div>
              {["anthropic", "grok", "openai"].map((prov) => (
                <ProviderKeyRow key={prov} prov={prov} st={llm.providers?.[prov] || {}} onSave={onKeySave} />
              ))}
              {llm.providers?.local && (
                <div style={{ fontSize: 11, color: T.ink4, marginTop: 6 }}>
                  Local endpoint: <span style={{ fontFamily: T.mono }}>{llm.providers.local.base_url}</span>
                  {llm.providers.local.model
                    ? <> serving <span style={{ fontFamily: T.mono }}>{llm.providers.local.model}</span> — no API key needed.</>
                    : <> — set <span style={{ fontFamily: T.mono }}>LOCAL_LLM_MODEL</span> in .env to enable it.</>}
                </div>
              )}
              <div style={{ fontSize: 11, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4, margin: "16px 0 2px" }}>Model per agent</div>
              {schedules && Object.entries(schedules).map(([agent, info]) => (
                <ModelRow key={agent} agent={agent} name={info.name} llm={llm} onSave={onModelSave} />
              ))}
              <div style={{ fontSize: 11, color: T.ink4, marginTop: 10 }}>
                Keys saved here apply immediately — no restart. <span style={{ fontFamily: T.mono }}>.env</span> vars
                (<span style={{ fontFamily: T.mono }}>ANTHROPIC_API_KEY</span>, <span style={{ fontFamily: T.mono }}>XAI_API_KEY</span>,
                <span style={{ fontFamily: T.mono }}> OPENAI_API_KEY</span>) still work as a fallback.
                Agents without an override use the default <span style={{ fontFamily: T.mono }}>{llm.default_model}</span>;
                if a cloud provider is down or has no key, calls automatically fall back to the local endpoint, then Ollama.
              </div>
            </>
          ) : <div style={{ fontSize: 12.5, color: T.ink3 }}>Loading…</div>}
        </Card>

        {/* MCP servers */}
        <MCPCard />

        {/* Schedules */}
        <Card pad={15}>
          <SectionTitle sub="Change how often each agent runs (persisted)">Schedules</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr 1.4fr auto", gap: 12, padding: "0 0 8px", fontSize: 10.5, color: T.ink4, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, borderBottom: `1px solid ${T.line2}` }}>
            <span>Agent</span><span>Type</span><span>Cadence</span><span></span>
          </div>
          {schedules && Object.entries(schedules).map(([agent, info]) => (
            <ScheduleRow key={agent} agent={agent} info={info} onSave={onScheduleSave} />
          ))}
        </Card>
      </div>
    </div>
  );
}

function HealthStat({ label, value, ok }) {
  return (
    <Card pad={16} style={{ background: T.cardAlt }}>
      <div style={{ fontSize: 12, color: T.ink3, fontWeight: 600 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
        <Dot c={ok ? T.green : T.red} s={9} />
        <span style={{ fontSize: 14, fontWeight: 700, color: ok ? T.ink : T.red }}>{value}</span>
      </div>
    </Card>
  );
}
