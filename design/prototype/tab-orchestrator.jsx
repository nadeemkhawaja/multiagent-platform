// ============================================================================
// tab-orchestrator.jsx — system overview, live gauges, semaphore, alarm demo
// ============================================================================
function fmtUptime(s) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}
function fmtNext(s) {
  if (s <= 0) return "now";
  if (s >= 3600) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  if (s >= 60) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${s}s`;
}

function ResCard({ rk, label, sub }) {
  const s = useSim();
  const r = s.res[rk];
  const hot = r.v >= 90;
  const col = hot ? T.red : T.violet;
  return (
    <Card pad={18}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 12.5, color: T.ink3, fontWeight: 600 }}>{label}</div>
          <div style={{ fontSize: 30, fontWeight: 700, letterSpacing: -1, marginTop: 2, fontFamily: T.mono, color: hot ? T.red : T.ink }}>
            {r.v}<span style={{ fontSize: 16, color: "#b6bcc6" }}>%</span>
          </div>
        </div>
        <Ring val={r.v} color={col} />
      </div>
      <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <span style={{ fontSize: 11.5, color: T.ink4, fontFamily: T.mono }}>{typeof sub === "function" ? sub(s) : sub}</span>
        <Spark data={r.hist} color={col} />
      </div>
    </Card>
  );
}

function AlarmBanner() {
  const s = useSim();
  if (!s.alarm) return null;
  return (
    <div style={{ background: T.redBg, border: `1px solid ${T.red}55`, borderRadius: 14, padding: "16px 20px", display: "flex", alignItems: "center", gap: 16, animation: "omPulse 1.4s ease-in-out infinite" }}>
      <div style={{ width: 40, height: 40, borderRadius: 11, background: T.card, display: "grid", placeItems: "center", fontSize: 20, color: T.red, flex: "0 0 auto" }}>⚠</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 14.5, fontWeight: 700, color: T.red }}>{s.alarm.label} critical — {s.alarm.value}%</div>
        <div style={{ fontSize: 12.5, color: T.red, opacity: 0.85, marginTop: 2 }}><b>Suggested action:</b> {s.alarm.action}</div>
      </div>
      <Btn kind="danger" size="sm" onClick={() => Sim.clearAlarm()}>Acknowledge &amp; resolve</Btn>
    </div>
  );
}

function AgentCard({ a }) {
  const col = AGENT_COLOR[a.id];
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
          {crashed ? "restarting…" : `next ${fmtNext(a.nextS)}`}
        </div>
      </div>
    </div>
  );
}

function Semaphore() {
  const s = useSim();
  const llm = s.llm;
  const holder = s.agents.find((a) => a.id === llm.holder);
  const pct = Math.min(100, (llm.heldS / 6) * 100);
  return (
    <Card pad={20} style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <SectionTitle sub="1 permit · serialized inference, no deadlocks">LLM Semaphore</SectionTitle>
      {holder && (
        <div style={{ background: T.violetBg, border: `1px solid ${T.line}`, borderRadius: 11, padding: 14, display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, background: AGENT_COLOR[holder.id] + "1a", color: AGENT_COLOR[holder.id], display: "grid", placeItems: "center", fontWeight: 700 }}>{holder.glyph}</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{holder.n}</div>
            <div style={{ fontSize: 11, color: T.ink3, fontFamily: T.mono }}>holding · {llm.heldS.toFixed(1)}s · {llm.tokens} tok · {llm.rate} tok/s</div>
          </div>
          <span style={{ fontSize: 10.5, fontWeight: 700, color: T.violet, background: T.violetBg, padding: "4px 8px", borderRadius: 6 }}>ACTIVE</span>
        </div>
      )}
      <div style={{ height: 5, background: T.violetBg, borderRadius: 6, overflow: "hidden", margin: "10px 0 2px" }}>
        <div style={{ width: pct + "%", height: "100%", background: T.violet, transition: "width .6s linear" }} />
      </div>
      <div style={{ fontSize: 11.5, color: T.ink3, fontWeight: 600, margin: "14px 0 8px" }}>Queue · {llm.queue.length} waiting</div>
      {llm.queue.length === 0 && <div style={{ fontSize: 12, color: T.ink4 }}>Queue empty</div>}
      {llm.queue.map((qid, i) => {
        const a = s.agents.find((x) => x.id === qid);
        return (
          <div key={qid} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 4px", borderBottom: i < llm.queue.length - 1 ? `1px solid ${T.line2}` : "none" }}>
            <span style={{ fontSize: 11, color: "#b6bcc6", fontFamily: T.mono, width: 14 }}>{i + 1}</span>
            <div style={{ width: 22, height: 22, borderRadius: 6, background: AGENT_COLOR[qid] + "1a", color: AGENT_COLOR[qid], display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700 }}>{a.glyph}</div>
            <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1 }}>{a.n}</span>
            <span style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono }}>waiting</span>
          </div>
        );
      })}
      <div style={{ marginTop: "auto", paddingTop: 14, fontSize: 11, color: T.ink4, fontFamily: T.mono }}>avg wait 0.9s · mutex healthy</div>
    </Card>
  );
}

function EventLog() {
  const s = useSim();
  return (
    <Card pad={20} style={{ height: "100%" }}>
      <SectionTitle sub="orchestrator activity">Event log</SectionTitle>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {s.events.map((e, i) => (
          <div key={i} style={{ display: "flex", gap: 11, padding: "7px 0", fontSize: 12.5, alignItems: "baseline" }}>
            <span style={{ fontFamily: T.mono, color: "#b6bcc6", fontSize: 11, flex: "0 0 auto" }}>{e.t}</span>
            <Dot c={e.c} s={6} />
            <span style={{ color: T.ink2, textWrap: "pretty" }}>{e.m}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function DemoControls() {
  const s = useSim();
  const liveAgents = s.agents.filter((a) => a.status !== "crashed");
  return (
    <Card pad={18} style={{ background: T.cardAlt, border: `1px dashed ${T.violet}55` }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 700, display: "flex", alignItems: "center", gap: 7 }}><span style={{ fontSize: 15 }}>🧪</span> Demo controls</div>
          <div style={{ fontSize: 12, color: T.ink3, marginTop: 2 }}>Trigger a resource alarm or crash an agent — the orchestrator self-recovers.</div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Btn size="sm" kind="danger" onClick={() => Sim.spike("cpu")}>Spike CPU &gt; 90%</Btn>
          <Btn size="sm" kind="danger" onClick={() => Sim.spike("ram")}>Spike RAM &gt; 90%</Btn>
          <Btn size="sm" kind="danger" onClick={() => Sim.spike("gpu")}>Spike GPU &gt; 90%</Btn>
          <Btn size="sm" onClick={() => liveAgents.length && Sim.crash(liveAgents[Math.floor(Math.random() * liveAgents.length)].id)}>Crash random agent</Btn>
        </div>
      </div>
    </Card>
  );
}

// ---------- Atlas layout: compact metric strip + agent table ----------
function MetricStrip() {
  const s = useSim();
  const items = [
    { k: "cpu", label: "CPU", suf: "%" }, { k: "ram", label: "Memory", suf: "%" },
    { k: "disk", label: "Disk", suf: "%" }, { k: "gpu", label: "GPU · LLM", suf: "%" },
  ];
  return (
    <Card pad={0} style={{ display: "flex", alignItems: "stretch", overflow: "hidden" }}>
      {items.map((it, i) => {
        const r = s.res[it.k]; const hot = r.v >= 90; const col = hot ? T.red : T.violet;
        return (
          <div key={it.k} style={{ display: "flex", alignItems: "center", gap: 14, padding: "18px 22px", flex: 1, borderRight: i < 3 ? `1px solid ${T.line2}` : "none" }}>
            <div>
              <div style={{ fontSize: 10.5, color: T.ink3, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4 }}>{it.label}</div>
              <div style={{ fontSize: 24, fontWeight: 700, fontFamily: T.mono, letterSpacing: -0.5, color: hot ? T.red : T.ink }}>{r.v}<span style={{ fontSize: 13, color: T.ink4 }}>{it.suf}</span></div>
            </div>
            <div style={{ marginLeft: "auto" }}><Spark data={r.hist} color={col} w={76} h={36} /></div>
          </div>
        );
      })}
    </Card>
  );
}

function AgentTable() {
  const s = useSim();
  const cols = "1.8fr 0.9fr 0.6fr 0.7fr 0.7fr 1fr";
  return (
    <Card pad={0} style={{ overflow: "hidden" }}>
      <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.line2}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>Managed agents</div>
        <Pill mono c={T.ink3}>auto-restart on</Pill>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: cols, padding: "10px 20px", fontSize: 10.5, color: T.ink4, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, borderBottom: `1px solid ${T.line2}` }}>
        <span>Agent</span><span>Status</span><span style={{ textAlign: "right" }}>CPU</span><span style={{ textAlign: "right" }}>Mem</span><span style={{ textAlign: "right" }}>Restarts</span><span style={{ textAlign: "right" }}>Next run</span>
      </div>
      {s.agents.map((a) => {
        const col = AGENT_COLOR[a.id]; const crashed = a.status === "crashed";
        return (
          <div key={a.id} style={{ display: "grid", gridTemplateColumns: cols, padding: "14px 20px", alignItems: "center", borderBottom: `1px solid ${T.line2}`, fontSize: 13, background: crashed ? T.redBg : "transparent" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
              <div style={{ width: 30, height: 30, borderRadius: 8, background: col + "1a", color: col, display: "grid", placeItems: "center", fontWeight: 700, fontSize: 13 }}>{a.glyph}</div>
              <div style={{ minWidth: 0 }}><div style={{ fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{a.n}</div><div style={{ fontSize: 11, color: T.ink4 }}>{a.schedule}</div></div>
            </div>
            <StatusPill status={a.status} />
            <span style={{ fontFamily: T.mono, color: T.ink2, textAlign: "right" }}>{a.cpu}%</span>
            <span style={{ fontFamily: T.mono, color: T.ink2, textAlign: "right" }}>{a.mem}m</span>
            <span style={{ fontFamily: T.mono, color: T.ink3, textAlign: "right" }}>{a.restarts}</span>
            <span style={{ fontFamily: T.mono, fontSize: 12, color: T.ink3, textAlign: "right" }}>{crashed ? "restarting…" : fmtNext(a.nextS)}</span>
          </div>
        );
      })}
    </Card>
  );
}

function OrchestratorTab({ theme = "aria" }) {
  const s = useSim();
  const running = s.agents.filter(a => a.status === "running").length;
  return (
    <div>
      <TabHeader icon="◇" color={T.violet} title="Orchestrator" sub={`localhost:8787 · uptime ${fmtUptime(s.uptimeS)} · ${s.threads} threads`}
        actions={<>
          {s.alarm
            ? <Pill c={T.red} bg={T.redBg} bd={T.red + "55"}><Dot c={T.red} />Alarm active</Pill>
            : <Pill c={T.green} bg={T.greenBg} bd={T.green + "55"}><Dot c={T.green} />All systems nominal</Pill>}
          <Pill mono c={T.ink2}>Qwen3 · local</Pill>
        </>} />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>
        <AlarmBanner />
        {theme === "atlas" ? (
          <>
            <MetricStrip />
            <DemoControls />
            <div style={{ display: "grid", gridTemplateColumns: "1.7fr 1fr", gap: 16, alignItems: "start" }}>
              <AgentTable />
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <Semaphore />
                <EventLog />
              </div>
            </div>
          </>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16 }}>
              <ResCard rk="cpu" label="CPU" sub="8 cores · 4.1 GHz" />
              <ResCard rk="ram" label="Memory" sub="9.8 / 16 GB" />
              <ResCard rk="disk" label="Disk" sub="228 / 512 GB" />
              <ResCard rk="gpu" label="GPU · LLM" sub="Qwen3 · 7.0 GB VRAM" />
            </div>
            <DemoControls />
            <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 16, alignItems: "stretch" }}>
              <Card pad={20}>
                <SectionTitle sub="5 managed processes · auto-restart enabled" right={<Pill mono c={T.ink3}>{running} running</Pill>}>Agents</SectionTitle>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  {s.agents.map((a) => <AgentCard key={a.id} a={a} />)}
                </div>
              </Card>
              <Semaphore />
            </div>
            <EventLog />
          </>
        )}
      </div>
    </div>
  );
}

window.OrchestratorTab = OrchestratorTab;
