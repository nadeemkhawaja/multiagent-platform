// ============================================================================
// Orchestrator.jsx — system overview, live gauges, LLM semaphore, alarm demo.
// Aria (calm cards) and Atlas (ops table) layouts. Wired to /api/state.
// ============================================================================
import { useState } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, Dot, StatusPill, Ring, Spark, SectionTitle, TabHeader, Btn } from "../theme/ui";
import { spikeResource, crashAgent } from "../state/api";

function fmtUptime(s) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}
const accent = (id) => AGENT_COLOR[id] || T.violet;

function ResCard({ r, label, sub }) {
  const hot = r.v >= 90;
  const col = hot ? T.red : T.violet;
  return (
    <Card pad={18}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 12.5, color: T.ink3, fontWeight: 600 }}>{label}</div>
          <div style={{ fontSize: 30, fontWeight: 700, letterSpacing: -1, marginTop: 2, fontFamily: T.mono, color: hot ? T.red : T.ink }}>
            {Math.round(r.v)}<span style={{ fontSize: 16, color: "#b6bcc6" }}>%</span>
          </div>
        </div>
        <Ring val={r.v} color={col} />
      </div>
      <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <span style={{ fontSize: 11.5, color: T.ink4, fontFamily: T.mono }}>{sub}</span>
        <Spark data={r.hist} color={col} />
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

function DemoControls({ s }) {
  const liveAgents = s.agents.filter((a) => a.status !== "crashed");
  return (
    <Card pad={18} style={{ background: T.cardAlt, border: `1px dashed ${T.violet}55` }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 700, display: "flex", alignItems: "center", gap: 7 }}><span style={{ fontSize: 15 }}>🧪</span> Demo controls</div>
          <div style={{ fontSize: 12, color: T.ink3, marginTop: 2 }}>Trigger a resource alarm or crash an agent — the orchestrator self-recovers.</div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Btn size="sm" kind="danger" onClick={() => spikeResource("cpu")}>Spike CPU &gt; 90%</Btn>
          <Btn size="sm" kind="danger" onClick={() => spikeResource("ram")}>Spike RAM &gt; 90%</Btn>
          <Btn size="sm" kind="danger" onClick={() => spikeResource("gpu")}>Spike GPU &gt; 90%</Btn>
          <Btn size="sm" onClick={() => liveAgents.length && crashAgent(liveAgents[Math.floor(Math.random() * liveAgents.length)].id)}>Crash random agent</Btn>
        </div>
      </div>
    </Card>
  );
}

// ---------- Atlas layout ----------
function MetricStrip({ s }) {
  const items = [
    { k: "cpu", label: "CPU" }, { k: "ram", label: "Memory" },
    { k: "disk", label: "Disk" }, { k: "gpu", label: "GPU · LLM" },
  ];
  return (
    <Card pad={0} style={{ display: "flex", alignItems: "stretch", overflow: "hidden" }}>
      {items.map((it, i) => {
        const r = s.res[it.k]; const hot = r.v >= 90; const col = hot ? T.red : T.violet;
        return (
          <div key={it.k} style={{ display: "flex", alignItems: "center", gap: 14, padding: "18px 22px", flex: 1, borderRight: i < 3 ? `1px solid ${T.line2}` : "none" }}>
            <div>
              <div style={{ fontSize: 10.5, color: T.ink3, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4 }}>{it.label}</div>
              <div style={{ fontSize: 24, fontWeight: 700, fontFamily: T.mono, letterSpacing: -0.5, color: hot ? T.red : T.ink }}>{Math.round(r.v)}<span style={{ fontSize: 13, color: T.ink4 }}>%</span></div>
            </div>
            <div style={{ marginLeft: "auto" }}><Spark data={r.hist} color={col} w={76} h={36} /></div>
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
  res: { cpu: { v: 0, hist: [] }, ram: { v: 0, hist: [] }, disk: { v: 0, hist: [] }, gpu: { v: 0, hist: [] } },
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
            <DemoControls s={s} />
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
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16 }}>
              <ResCard r={s.res.cpu} label="CPU" sub="processor load" />
              <ResCard r={s.res.ram} label="Memory" sub="system RAM" />
              <ResCard r={s.res.disk} label="Disk" sub="root volume" />
              <ResCard r={s.res.gpu} label="GPU · LLM" sub="Qwen3 inference" />
            </div>
            <DemoControls s={s} />
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
