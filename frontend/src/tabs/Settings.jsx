// ============================================================================
// Settings.jsx — editable schedules, agent config, and a health panel.
// ============================================================================
import { useState, useEffect, useCallback } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, Dot, Btn, SectionTitle, TabHeader, Appearance } from "../theme/ui";
import { getConfig, saveConfig, getSchedules, setSchedule, getHealth } from "../state/api";

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

export default function Settings({ theme, setTheme, mode, setMode }) {
  const [config, setConfig] = useState(null);
  const [schedules, setSchedules] = useState(null);
  const [health, setHealth] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  const load = useCallback(async () => {
    setConfig(await getConfig().catch(() => ({})));
    setSchedules(await getSchedules().catch(() => ({})));
    setHealth(await getHealth().catch(() => null));
  }, []);
  useEffect(() => { load(); }, [load]);

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
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>
        {/* Appearance */}
        {theme && setTheme && mode && setMode && (
          <Card pad={20}>
            <SectionTitle sub="Theme and color mode">Appearance</SectionTitle>
            <Appearance theme={theme} setTheme={setTheme} mode={mode} setMode={setMode} />
          </Card>
        )}

        {/* Health */}
        <Card pad={20}>
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
        <Card pad={20}>
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

        {/* Schedules */}
        <Card pad={20}>
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
