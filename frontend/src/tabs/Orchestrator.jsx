// ============================================================================
// Orchestrator.jsx — Mission Control: agent overview + system gauges + ops
// Merged from Home + Orchestrator. Single entry point for the whole platform.
// ============================================================================
import { useState, useEffect, useRef } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, Dot, Ring, SectionTitle, TabHeader, Btn } from "../theme/ui";
import { CpuIcon, RamIcon, DiskIcon, GpuIcon, NetIcon } from "../theme/icons";
import { API_BASE, setDemoMode, spikeResource, crashAgent, getMetrics } from "../state/api";

// ── All agents the Home overview knows about ─────────────────────────────────
const ALL_AGENTS = [
  { id: "ai_times",        label: "AI-Times",         glyph: "▶", desc: "Latest AI videos" },
  { id: "mailman",         label: "Mailman",           glyph: "✉", desc: "Inbox classifier" },
  { id: "wallstreet_wolf", label: "Wolf",              glyph: "$", desc: "Stock watchlist" },
  { id: "compass",         label: "Compass",           glyph: "◎", desc: "Market signals" },
  { id: "devdaily",        label: "GitHub Trending",   glyph: "⌥", desc: "Dev repos" },
  { id: "strategy_scout",  label: "Strategy Scout",    glyph: "✦", desc: "Trading research" },
  { id: "capitol_tracker", label: "Capitol Tracker",   glyph: "🏛", desc: "Congress trades" },
  { id: "morning_brief",   label: "Morning Brief",     glyph: "☀", desc: "Daily digest" },
  { id: "options_flow",    label: "Options Flow",      glyph: "⚡", desc: "Unusual activity" },
  { id: "earnings_cal",    label: "Earnings Calendar", glyph: "📅", desc: "Upcoming earnings" },
  { id: "cisco_pulse",     label: "Cisco Pulse",       glyph: "◈", desc: "NetOps intel" },
  { id: "alpha_wolf",      label: "Alpha Wolf",        glyph: "🐺", desc: "Master strategist" },
];
// The four graded agents — demo mode narrows the overview grid to just these.
const CORE_AGENTS = ["ai_times", "mailman", "wallstreet_wolf", "devdaily"];
const STATUS_BG = { running: "#eafaf0", idle: "transparent", crashed: "#fdeced", queued: "#fef5e7" };

// Compact clickable card used in the agent grid
function AgentOverviewCard({ agent, sysAgent, onNavigate }) {
  const col = AGENT_COLOR[agent.id] || T.violet;
  const status = sysAgent?.status || "idle";
  const sc = status === "running" ? T.green : status === "crashed" ? T.red : status === "queued" ? T.amber : T.ink4;
  return (
    <div onClick={() => onNavigate(agent.id)}
      style={{ background: T.card, border: `1px solid ${status === "crashed" ? T.red + "55" : T.line}`, borderRadius: 12, padding: "12px 14px", cursor: "pointer", transition: "all .15s", display: "flex", gap: 10, alignItems: "center" }}
      onMouseEnter={(e) => e.currentTarget.style.borderColor = col + "66"}
      onMouseLeave={(e) => e.currentTarget.style.borderColor = status === "crashed" ? T.red + "55" : T.line}>
      <div style={{ width: 34, height: 34, borderRadius: 9, background: col + "18", color: col, display: "grid", placeItems: "center", fontSize: 15, flex: "0 0 auto" }}>{agent.glyph}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{agent.label}</div>
        <div style={{ fontSize: 10.5, color: T.ink4 }}>{sysAgent?.schedule || agent.desc}</div>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 9.5, fontWeight: 700, color: sc, background: STATUS_BG[status] || T.cardAlt, padding: "2px 7px", borderRadius: 5, border: `1px solid ${sc}22` }}>{status}</div>
      </div>
    </div>
  );
}

function fmtUptime(s) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}
const accent = (id) => AGENT_COLOR[id] || T.violet;

// System metrics shown on the Orchestrator. `warn` is the green→red threshold.
const METRICS = [
  { k: "cpu",  label: "CPU",       sub: "processor load",  icon: CpuIcon,  unit: "%",    cap: 100, warn: 85 },
  { k: "ram",  label: "Memory",    sub: "system RAM",      icon: RamIcon,  unit: "%",    cap: 100, warn: 88 },
  { k: "disk", label: "Disk",      sub: "root volume",     icon: DiskIcon, unit: "%",    cap: 100, warn: 90 },
  { k: "gpu",  label: "GPU · LLM", sub: "Qwen3 inference", icon: GpuIcon,  unit: "%",    cap: 100, warn: 85 },
  { k: "net",  label: "Network",   sub: "throughput",      icon: NetIcon,  unit: "Mb/s", cap: 100, warn: 60 },
];
const fmtVal = (v, unit) => (unit === "%" ? Math.round(v) : (v || 0).toFixed(1));

// Measure a container's pixel width so charts fill it crisply (no SVG stretch).
function useElWidth(fallback = 240) {
  const ref = useRef(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    if (!ref.current || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((e) => { const cw = e[0].contentRect.width; if (cw) setW(Math.round(cw)); });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

let _gid = 0;
// Area chart whose line turns red on any segment that crosses the threshold.
function ThresholdChart({ data, threshold, cap = 100, color = T.green, w = 240, h = 44 }) {
  if (!data || !data.length) return <div style={{ height: h }} />;
  const n = data.length;
  const hi = (Math.max(cap, threshold * 1.1, ...data) || 1) * 1.06;
  const X = (i) => (n === 1 ? w : (i / (n - 1)) * w);
  const Y = (v) => h - (Math.min(Math.max(v, 0), hi) / hi) * (h - 6) - 3;
  const pts = data.map((v, i) => [X(i), Y(v)]);
  const lineD = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const ty = Y(threshold);
  const last = data[n - 1], hot = last >= threshold, endCol = hot ? T.red : color;
  const gid = `tc${(_gid = (_gid + 1) % 1e6)}`;
  return (
    <svg width={w} height={h} style={{ display: "block", overflow: "visible" }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={endCol} stopOpacity="0.22" />
          <stop offset="100%" stopColor={endCol} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${lineD} L${w} ${h} L0 ${h} Z`} fill={`url(#${gid})`} />
      <line x1="0" y1={ty} x2={w} y2={ty} stroke={T.red} strokeWidth="1" strokeDasharray="3 3" opacity="0.4" />
      {pts.slice(1).map((p, i) => {
        const a = pts[i], over = data[i] >= threshold || data[i + 1] >= threshold;
        return <line key={i} x1={a[0]} y1={a[1]} x2={p[0]} y2={p[1]} stroke={over ? T.red : color} strokeWidth="1.9" strokeLinecap="round" />;
      })}
      <circle cx={pts[n - 1][0]} cy={pts[n - 1][1]} r="4.5" fill={endCol} opacity="0.18" />
      <circle cx={pts[n - 1][0]} cy={pts[n - 1][1]} r="2.4" fill={endCol} />
    </svg>
  );
}

function ResCard({ m, r }) {
  const [ref, w] = useElWidth();
  const v = r.v;
  const hot = v >= m.warn;
  const col = hot ? T.red : T.green;
  const ringPct = Math.min(100, (v / m.cap) * 100);
  const Icon = m.icon;
  return (
    <Card pad={13} style={{ position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 3, background: col, opacity: hot ? 0.9 : 0.5 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <div style={{ width: 34, height: 34, borderRadius: 9, background: col + "16", color: col, display: "grid", placeItems: "center", flex: "0 0 auto" }}>
          <Icon size={18} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 11, color: T.ink3, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>{m.label}</div>
          <div style={{ fontSize: 10.5, color: T.ink4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.sub}</div>
        </div>
        <Ring val={ringPct} size={34} stroke={4} color={col} track={T.line2} />
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 12 }}>
        <span style={{ fontSize: 25, fontWeight: 800, letterSpacing: -1, fontFamily: T.mono, color: hot ? T.red : T.ink }}>{fmtVal(v, m.unit)}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: T.ink4 }}>{m.unit}</span>
        <span style={{ marginLeft: "auto", fontSize: 9.5, fontWeight: 700, color: col, background: col + "16", padding: "3px 8px", borderRadius: 6 }}>{hot ? "CRITICAL" : "NOMINAL"}</span>
      </div>
      <div ref={ref} style={{ width: "100%", marginTop: 10 }}>
        <ThresholdChart data={r.hist} threshold={m.warn} cap={m.cap} w={w} h={36} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
        <span style={{ fontSize: 9.5, fontFamily: T.mono, color: T.ink4 }}>last {r.hist.length} samples</span>
        <span style={{ fontSize: 9.5, fontFamily: T.mono, color: T.ink4 }}>threshold {m.warn}{m.unit === "%" ? "%" : " Mb/s"}</span>
      </div>
    </Card>
  );
}

function AlarmBanner({ alarm, onAck }) {
  if (!alarm) return null;
  return (
    <div style={{ background: T.redBg, border: `1px solid ${T.red}55`, borderRadius: 14, padding: "16px 20px", display: "flex", alignItems: "center", gap: 16, animation: "omPulse 1.4s ease-in-out infinite" }}>
      <div style={{ width: 40, height: 40, borderRadius: 11, background: T.card, display: "grid", placeItems: "center", fontSize: 20, color: T.red, flex: "0 0 auto" }}>⚠</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 14.5, fontWeight: 700, color: T.red }}>{alarm.label} critical — {alarm.value}%</div>
        <div style={{ fontSize: 12.5, color: T.red, opacity: 0.85, marginTop: 2 }}><b>Suggested action:</b> {alarm.action}</div>
      </div>
      <Btn kind="danger" size="sm" onClick={onAck}>Acknowledge &amp; resolve</Btn>
    </div>
  );
}

function Semaphore({ s }) {
  const llm = s.llm || { queue: [], heldS: 0, tokens: 0, rate: 0, holder: null };
  const holder = s.agents.find((a) => a.id === llm.holder);
  const pct = Math.min(100, (llm.heldS / 6) * 100);
  return (
    <Card pad={20} style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <SectionTitle sub="1 permit · serialized inference, no deadlocks">LLM Semaphore</SectionTitle>
      {holder ? (
        <div style={{ background: T.violetBg, border: `1px solid ${T.line}`, borderRadius: 11, padding: 14, display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, background: accent(holder.id) + "1a", color: accent(holder.id), display: "grid", placeItems: "center", fontWeight: 700 }}>{holder.glyph}</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{holder.n}</div>
            <div style={{ fontSize: 11, color: T.ink3, fontFamily: T.mono }}>holding · {llm.heldS.toFixed(1)}s · {llm.tokens} tok · {llm.rate} tok/s</div>
          </div>
          <span style={{ fontSize: 10.5, fontWeight: 700, color: T.violet, background: T.violetBg, padding: "4px 8px", borderRadius: 6 }}>ACTIVE</span>
        </div>
      ) : (
        <div style={{ background: T.cardAlt, border: `1px solid ${T.line}`, borderRadius: 11, padding: 14, fontSize: 12.5, color: T.ink3 }}>
          Permit free · model idle
        </div>
      )}
      <div style={{ height: 5, background: T.violetBg, borderRadius: 6, overflow: "hidden", margin: "10px 0 2px" }}>
        <div style={{ width: pct + "%", height: "100%", background: T.violet, transition: "width .6s linear" }} />
      </div>
      <div style={{ fontSize: 11.5, color: T.ink3, fontWeight: 600, margin: "14px 0 8px" }}>Queue · {llm.queue.length} waiting</div>
      {llm.queue.length === 0 && <div style={{ fontSize: 12, color: T.ink4 }}>Queue empty</div>}
      {llm.queue.map((qid, i) => {
        const a = s.agents.find((x) => x.id === qid) || { glyph: "•", n: qid };
        return (
          <div key={qid + i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 4px", borderBottom: i < llm.queue.length - 1 ? `1px solid ${T.line2}` : "none" }}>
            <span style={{ fontSize: 11, color: "#b6bcc6", fontFamily: T.mono, width: 14 }}>{i + 1}</span>
            <div style={{ width: 22, height: 22, borderRadius: 6, background: accent(qid) + "1a", color: accent(qid), display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700 }}>{a.glyph}</div>
            <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1 }}>{a.n}</span>
            <span style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono }}>waiting</span>
          </div>
        );
      })}
      <div style={{ marginTop: "auto", paddingTop: 14, fontSize: 11, color: T.ink4, fontFamily: T.mono }}>{(s.llm && s.llm.model) || "Qwen3"} · mutex healthy</div>
    </Card>
  );
}

function StressTestButton({ agents = [] }) {
  const [phase, setPhase] = useState("idle"); // idle | running | done
  const [result, setResult] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef(null);

  const run = async () => {
    setPhase("running"); setResult(null); setElapsed(0);
    timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    try {
      const r = await fetch(`${API_BASE}/api/stress-test`, { method: "POST" });
      const data = await r.json();
      setResult(data); setPhase("done");
      clearInterval(timerRef.current);
      setTimeout(() => setPhase("idle"), 10000);
    } catch (e) {
      setResult({ error: String(e) }); setPhase("done");
      clearInterval(timerRef.current);
      setTimeout(() => setPhase("idle"), 6000);
    }
  };
  useEffect(() => () => clearInterval(timerRef.current), []);

  const triggered = result?.triggered || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <button onClick={run} disabled={phase === "running"} style={{
          display: "flex", alignItems: "center", gap: 8, padding: "10px 22px",
          borderRadius: 10, border: `1.5px solid ${T.red}`,
          background: phase === "running" ? T.redBg : T.red,
          color: phase === "running" ? T.red : "#fff",
          fontWeight: 700, fontSize: 13.5, cursor: phase === "running" ? "not-allowed" : "pointer",
          transition: "all .18s", fontFamily: T.sans,
        }}>
          <span style={{ fontSize: 16, display: "inline-block", animation: phase === "running" ? "omSpin .8s linear infinite" : "none" }}>
            {phase === "running" ? "↻" : "🔥"}
          </span>
          {phase === "running" ? `Running all agents… ${elapsed}s` : "Stress Test — Run All Agents"}
        </button>
        {phase === "done" && result && !result.error && (
          <span style={{ fontSize: 12.5, color: T.green, fontWeight: 600 }}>✓ {triggered.length} agents triggered</span>
        )}
        {phase === "done" && result?.error && (
          <span style={{ fontSize: 12.5, color: T.red, fontWeight: 600 }}>Error: {result.error}</span>
        )}
      </div>

      {/* Live per-agent status grid (shown while running or just done) */}
      {phase !== "idle" && agents.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {agents.map((a) => {
            const isTriggered = triggered.includes(a.id);
            const isRunning = a.status === "running";
            const col = isRunning ? T.green : isTriggered ? T.amber : T.ink3;
            const bg = isRunning ? T.greenBg : isTriggered ? T.amberBg : T.cardAlt;
            return (
              <div key={a.id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 10px", borderRadius: 8, background: bg, border: `1px solid ${col}44` }}>
                <span style={{ fontSize: 13 }}>{a.glyph}</span>
                <span style={{ fontSize: 11.5, fontWeight: 600, color: col, fontFamily: T.sans }}>{a.n}</span>
                <span style={{ fontSize: 10, color: col, fontFamily: T.mono }}>{isRunning ? "running" : isTriggered ? "triggered" : a.status}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Demo Controls: demo-mode toggle + simulate-load + crash-agent ────────────
function DemoControls({ s }) {
  const demo = !!s.demo;
  const [busy, setBusy] = useState(false);
  const toggle = async () => { setBusy(true); try { await setDemoMode(!demo); } finally { setTimeout(() => setBusy(false), 400); } };
  // In demo mode, crash a *visible* core agent so the auto-restart is on screen.
  const crashOne = () => {
    if (!demo) return crashAgent();
    const live = (s.agents || []).filter((a) => CORE_AGENTS.includes(a.id) && a.status !== "crashed");
    crashAgent(live.length ? live[Math.floor(Math.random() * live.length)].id : undefined);
  };
  const ActBtn = ({ label, onClick, color }) => (
    <button onClick={onClick} style={{
      padding: "8px 14px", borderRadius: 9, border: `1px solid ${color}55`, background: color + "12",
      color, fontWeight: 700, fontSize: 12.5, cursor: "pointer", fontFamily: T.sans,
    }}>{label}</button>
  );
  return (
    <div style={{ background: T.card, border: `1px solid ${T.violet}44`, borderRadius: 14, padding: "18px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: T.violet }}>◐</span> Demo Controls
            <span style={{ fontSize: 11, fontWeight: 600, color: T.ink4 }}>— for a clean 10-minute recording</span>
          </div>
          <div style={{ fontSize: 11.5, color: T.ink4, marginTop: 4 }}>
            {demo ? "Showing the 4 graded agents · extras hidden and paused" : "Full fleet visible · every agent scheduled"}
          </div>
        </div>
        <button onClick={toggle} disabled={busy} title="Toggle demo mode" style={{
          display: "flex", alignItems: "center", gap: 9, padding: "7px 13px", borderRadius: 999,
          border: `1px solid ${demo ? T.violet : T.line}`, background: demo ? T.violet + "16" : T.cardAlt,
          color: demo ? T.violet : T.ink3, fontWeight: 700, fontSize: 12.5, cursor: busy ? "wait" : "pointer", fontFamily: T.sans,
        }}>
          <span style={{ width: 30, height: 16, borderRadius: 999, background: demo ? T.violet : "#c4c9d4", position: "relative", transition: "all .2s", flex: "0 0 auto" }}>
            <span style={{ position: "absolute", top: 2, left: demo ? 16 : 2, width: 12, height: 12, borderRadius: 999, background: "#fff", transition: "all .2s" }} />
          </span>
          Demo mode {demo ? "ON" : "OFF"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
        <ActBtn label="⚠ Simulate CPU > 90%" onClick={() => spikeResource("cpu")} color={T.red} />
        <ActBtn label="⚠ Simulate RAM > 90%" onClick={() => spikeResource("ram")} color="#ea580c" />
        <ActBtn label="⚠ Simulate GPU > 90%" onClick={() => spikeResource("gpu")} color="#7c5cf6" />
        <ActBtn label="✕ Crash a random agent" onClick={crashOne} color={T.red} />
      </div>
      <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 10, fontFamily: T.mono }}>
        Spike → alarm banner with a suggested corrective action (auto-clears ~12 s). Crash → watchdog auto-restarts the agent ~4 s later.
      </div>
    </div>
  );
}

const SKELETON = {
  uptimeS: 0, threads: 0,
  res: { cpu: { v: 0, hist: [] }, ram: { v: 0, hist: [] }, disk: { v: 0, hist: [] }, gpu: { v: 0, hist: [] }, net: { v: 0, hist: [] } },
  agents: [], llm: { holder: null, queue: [], heldS: 0, tokens: 0, rate: 0 }, events: [], alarm: null,
};

function fmtTokens(n) {
  if (!n) return "—";
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n);
}

function RunMetrics() {
  const [metrics, setMetrics] = useState(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try { const m = await getMetrics(); if (alive) setMetrics(m); } catch { /* backend offline */ }
    };
    tick();
    const id = setInterval(tick, 30000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const rows = Object.entries(metrics?.agents || {});
  const th = { padding: "6px 10px", textAlign: "left", fontSize: 10.5, color: T.ink4, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 };
  const td = { padding: "7px 10px", fontSize: 12.5, fontFamily: T.mono, borderTop: `1px solid ${T.line2}` };

  return (
    <Card pad={20}>
      <SectionTitle sub={`per-agent telemetry over each agent's last ${metrics?.window ?? 50} runs`}>Run metrics</SectionTitle>
      {rows.length === 0 ? (
        <div style={{ fontSize: 12.5, color: T.ink3 }}>No completed runs yet — metrics appear after agents run.</div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Agent</th><th style={th}>Runs</th><th style={th}>Success</th>
            <th style={th}>Avg time</th><th style={th}>LLM calls</th><th style={th}>Tokens in</th><th style={th}>Tokens out</th>
          </tr></thead>
          <tbody>
            {rows.map(([aid, m]) => {
              const col = AGENT_COLOR[aid] || T.violet;
              const ok = m.success_rate >= 0.9;
              return (
                <tr key={aid}>
                  <td style={{ ...td, fontFamily: T.sans, fontWeight: 700 }}>
                    <span style={{ color: col, marginRight: 7 }}>●</span>{m.name}
                  </td>
                  <td style={td}>{m.runs}</td>
                  <td style={{ ...td, color: ok ? T.green : T.amber, fontWeight: 700 }}>{Math.round(m.success_rate * 100)}%</td>
                  <td style={td}>{m.avg_duration_s != null ? `${m.avg_duration_s}s` : "—"}</td>
                  <td style={td}>{m.llm_calls || "—"}</td>
                  <td style={td}>{fmtTokens(m.tokens_in)}</td>
                  <td style={td}>{fmtTokens(m.tokens_out)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function Orchestrator({ sys, online, theme = "aria", onNavigate }) {
  const [ackd, setAckd] = useState(false);
  const s = sys || SKELETON;
  const running = s.agents.filter((a) => a.status === "running").length;
  const alarm = ackd ? null : s.alarm;
  const nav = onNavigate || (() => {});
  const demo = !!s.demo;
  const shownAgents = demo ? ALL_AGENTS.filter((a) => CORE_AGENTS.includes(a.id)) : ALL_AGENTS;

  return (
    <div>
      <TabHeader icon="◇" color={T.violet} title="Orchestrator"
        sub={`localhost:5174 · uptime ${fmtUptime(s.uptimeS)} · ${s.threads} threads`}
        actions={<>
          {!online
            ? <Pill c={T.amber} bg={T.amberBg} bd={T.amber + "55"}><Dot c={T.amber} />Backend offline</Pill>
            : alarm
              ? <Pill c={T.red} bg={T.redBg} bd={T.red + "55"}><Dot c={T.red} />Alarm active</Pill>
              : <Pill c={T.green} bg={T.greenBg} bd={T.green + "55"}><Dot c={T.green} />All systems nominal</Pill>}
          <Pill mono c={T.ink2}>{(s.llm && s.llm.model) || "Qwen3"} · local</Pill>
          <Pill mono c={T.ink3}>{running} running</Pill>
        </>} />

      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>

        {/* ── Resource metric cards (live system metrics · updates every 5s) ── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
          {METRICS.map((m) => <ResCard key={m.k} m={m} r={s.res[m.k] || { v: 0, hist: [] }} />)}
        </div>

        {/* ── Agent overview grid (clickable) ──────────────────────────────── */}
        <div>
          <SectionTitle sub="click any card to open that agent's tab">{shownAgents.length} {demo ? "graded agents · demo mode" : "managed agents · auto-restart enabled"}</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 10, marginTop: 8 }}>
            {shownAgents.map((a) => (
              <AgentOverviewCard key={a.id} agent={a} sysAgent={s.agents.find((x) => x.id === a.id)} onNavigate={nav} />
            ))}
          </div>
        </div>

        {/* ── Demo controls ───────────────────────────────────────────────── */}
        <DemoControls s={s} />

        {/* ── Alarm ───────────────────────────────────────────────────────── */}
        <AlarmBanner alarm={alarm} onAck={() => { setAckd(true); setTimeout(() => setAckd(false), 12000); }} />

        {/* ── Stress test ─────────────────────────────────────────────────── */}
        <div style={{ background: T.card, border: `1px solid ${T.red}44`, borderRadius: 14, padding: "18px 22px" }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: T.red }}>🔥</span> Stress Test
            <span style={{ fontSize: 11, fontWeight: 600, color: T.ink4, marginLeft: 4 }}>— fire all agents simultaneously to verify load handling</span>
          </div>
          <StressTestButton agents={s.agents} />
        </div>

        {/* ── LLM semaphore — assignment requirement: 1 permit, no deadlocks ── */}
        <Semaphore s={s} />

        {/* ── Per-run telemetry (tokens, latency, success rate) ────────────── */}
        <RunMetrics />
      </div>
    </div>
  );
}
