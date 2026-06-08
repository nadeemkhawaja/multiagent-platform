// ============================================================================
// Orchestrator.jsx — system overview, live gauges, LLM semaphore, alarm demo.
// Aria (calm cards) and Atlas (ops table) layouts. Wired to /api/state.
// ============================================================================
import { useState, useEffect, useRef } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, Dot, StatusPill, Ring, SectionTitle, TabHeader, Btn } from "../theme/ui";
import { CpuIcon, RamIcon, DiskIcon, GpuIcon, NetIcon } from "../theme/icons";

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
    <Card pad={16} style={{ position: "relative", overflow: "hidden" }}>
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
        <span style={{ fontSize: 30, fontWeight: 800, letterSpacing: -1, fontFamily: T.mono, color: hot ? T.red : T.ink }}>{fmtVal(v, m.unit)}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: T.ink4 }}>{m.unit}</span>
        <span style={{ marginLeft: "auto", fontSize: 9.5, fontWeight: 700, color: col, background: col + "16", padding: "3px 8px", borderRadius: 6 }}>{hot ? "CRITICAL" : "NOMINAL"}</span>
      </div>
      <div ref={ref} style={{ width: "100%", marginTop: 10 }}>
        <ThresholdChart data={r.hist} threshold={m.warn} cap={m.cap} w={w} h={44} />
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

function AgentCard({ a }) {
  const col = accent(a.id);
  const crashed = a.status === "crashed";
  return (
    <div style={{ border: `1px solid ${crashed ? T.red + "55" : T.line}`, borderRadius: 12, padding: 14, display: "flex", gap: 12, alignItems: "center", background: crashed ? T.redBg : T.card, transition: "all .2s" }}>
      <div style={{ width: 38, height: 38, borderRadius: 10, background: col + "1a", color: col, display: "grid", placeItems: "center", fontSize: 16, fontWeight: 700, flex: "0 0 auto" }}>{a.glyph}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>{a.n}</div>
        <div style={{ fontSize: 11.5, color: T.ink4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{a.desc}</div>
      </div>
      <div style={{ textAlign: "right", flex: "0 0 auto" }}>
        <StatusPill status={a.status} />
        <div style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono, marginTop: 3 }}>
          {crashed ? "restarting…" : a.schedule}
        </div>
      </div>
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

function EventLog({ s }) {
  return (
    <Card pad={20} style={{ height: "100%" }}>
      <SectionTitle sub="orchestrator activity">Event log</SectionTitle>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {(s.events || []).map((e, i) => (
          <div key={i} style={{ display: "flex", gap: 11, padding: "7px 0", fontSize: 12.5, alignItems: "baseline" }}>
            <span style={{ fontFamily: T.mono, color: "#b6bcc6", fontSize: 11, flex: "0 0 auto" }}>{e.t}</span>
            <Dot c={e.c} s={6} />
            <span style={{ color: T.ink2 }}>{e.m}</span>
          </div>
        ))}
        {(!s.events || s.events.length === 0) && <div style={{ fontSize: 12, color: T.ink4 }}>No events yet.</div>}
      </div>
    </Card>
  );
}

// ---------- Atlas layout ----------
function MetricStrip({ s }) {
  return (
    <Card pad={0} style={{ display: "flex", alignItems: "stretch", overflow: "hidden", flexWrap: "wrap" }}>
      {METRICS.map((m, i) => {
        const r = s.res[m.k] || { v: 0, hist: [] };
        const hot = r.v >= m.warn; const col = hot ? T.red : T.green;
        const Icon = m.icon;
        return (
          <div key={m.k} style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px", flex: "1 1 170px", borderRight: i < METRICS.length - 1 ? `1px solid ${T.line2}` : "none" }}>
            <div style={{ width: 30, height: 30, borderRadius: 8, background: col + "16", color: col, display: "grid", placeItems: "center", flex: "0 0 auto" }}><Icon size={16} /></div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 10, color: T.ink3, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4 }}>{m.label}</div>
              <div style={{ fontSize: 21, fontWeight: 800, fontFamily: T.mono, letterSpacing: -0.5, color: hot ? T.red : T.ink }}>{fmtVal(r.v, m.unit)}<span style={{ fontSize: 11, color: T.ink4 }}>{m.unit === "%" ? "%" : " " + m.unit}</span></div>
            </div>
            <div style={{ marginLeft: "auto" }}><ThresholdChart data={r.hist} threshold={m.warn} cap={m.cap} w={72} h={34} /></div>
          </div>
        );
      })}
    </Card>
  );
}

function AgentTable({ s }) {
  const cols = "1.8fr 0.9fr 0.6fr 0.7fr 0.7fr 1fr";
  return (
    <Card pad={0} style={{ overflow: "hidden" }}>
      <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.line2}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>Managed agents</div>
        <Pill mono c={T.ink3}>auto-restart on</Pill>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: cols, padding: "10px 20px", fontSize: 10.5, color: T.ink4, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, borderBottom: `1px solid ${T.line2}` }}>
        <span>Agent</span><span>Status</span><span style={{ textAlign: "right" }}>CPU</span><span style={{ textAlign: "right" }}>Mem</span><span style={{ textAlign: "right" }}>Restarts</span><span style={{ textAlign: "right" }}>Schedule</span>
      </div>
      {s.agents.map((a) => {
        const col = accent(a.id); const crashed = a.status === "crashed";
        return (
          <div key={a.id} style={{ display: "grid", gridTemplateColumns: cols, padding: "14px 20px", alignItems: "center", borderBottom: `1px solid ${T.line2}`, fontSize: 13, background: crashed ? T.redBg : "transparent" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
              <div style={{ width: 30, height: 30, borderRadius: 8, background: col + "1a", color: col, display: "grid", placeItems: "center", fontWeight: 700, fontSize: 13 }}>{a.glyph}</div>
              <div style={{ minWidth: 0 }}><div style={{ fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{a.n}</div><div style={{ fontSize: 11, color: T.ink4 }}>{a.desc}</div></div>
            </div>
            <StatusPill status={a.status} />
            <span style={{ fontFamily: T.mono, color: T.ink2, textAlign: "right" }}>{a.cpu}%</span>
            <span style={{ fontFamily: T.mono, color: T.ink2, textAlign: "right" }}>{a.mem}m</span>
            <span style={{ fontFamily: T.mono, color: T.ink3, textAlign: "right" }}>{a.restarts}</span>
            <span style={{ fontFamily: T.mono, fontSize: 11.5, color: T.ink3, textAlign: "right" }}>{crashed ? "restarting…" : a.schedule}</span>
          </div>
        );
      })}
    </Card>
  );
}

const SKELETON = {
  uptimeS: 0, threads: 0,
  res: { cpu: { v: 0, hist: [] }, ram: { v: 0, hist: [] }, disk: { v: 0, hist: [] }, gpu: { v: 0, hist: [] }, net: { v: 0, hist: [] } },
  agents: [], llm: { holder: null, queue: [], heldS: 0, tokens: 0, rate: 0 }, events: [], alarm: null,
};

export default function Orchestrator({ sys, online, theme = "aria" }) {
  const [ackd, setAckd] = useState(false);
  const s = sys || SKELETON;
  const running = s.agents.filter((a) => a.status === "running").length;
  const alarm = ackd ? null : s.alarm;
  if (!sys && online) { /* still loading first sample */ }

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
        </>} />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>
        <AlarmBanner alarm={alarm} onAck={() => { setAckd(true); setTimeout(() => setAckd(false), 12000); }} />
        {theme === "atlas" ? (
          <>
            <MetricStrip s={s} />
            <div style={{ display: "grid", gridTemplateColumns: "1.7fr 1fr", gap: 16, alignItems: "start" }}>
              <AgentTable s={s} />
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <Semaphore s={s} />
                <EventLog s={s} />
              </div>
            </div>
          </>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(168px, 1fr))", gap: 14 }}>
              {METRICS.map((m) => <ResCard key={m.k} m={m} r={s.res[m.k] || { v: 0, hist: [] }} />)}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 16, alignItems: "stretch" }}>
              <Card pad={20}>
                <SectionTitle sub={`${s.agents.length} managed processes · auto-restart enabled`} right={<Pill mono c={T.ink3}>{running} running</Pill>}>Agents</SectionTitle>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  {s.agents.map((a) => <AgentCard key={a.id} a={a} />)}
                </div>
              </Card>
              <Semaphore s={s} />
            </div>
            <EventLog s={s} />
          </>
        )}
      </div>
    </div>
  );
}
