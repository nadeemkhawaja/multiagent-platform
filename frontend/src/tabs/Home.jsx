// ============================================================================
// Home.jsx — Mission Control dashboard
// Aggregates live status from all agents into one command-center view
// ============================================================================
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, Dot, Ring, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData } from "../state/api";

const AGENTS = [
  { id: "ai_times",        label: "AI-Times",          glyph: "▶", desc: "Latest AI videos" },
  { id: "mailman",         label: "Mailman",            glyph: "✉", desc: "Inbox classifier" },
  { id: "wallstreet_wolf", label: "Wolf",               glyph: "$", desc: "Stock watchlist" },
  { id: "compass",         label: "Compass",            glyph: "◎", desc: "Market signals" },
  { id: "devdaily",        label: "GitHub Trending",    glyph: "⌥", desc: "Dev repos" },
  { id: "strategy_scout",  label: "Strategy Scout",     glyph: "✦", desc: "Trading research" },
  { id: "capitol_tracker", label: "Capitol Tracker",    glyph: "🏛", desc: "Congress trades" },
  { id: "morning_brief",   label: "Morning Brief",      glyph: "☀", desc: "Daily digest" },
  { id: "options_flow",    label: "Options Flow",       glyph: "⚡", desc: "Unusual activity" },
  { id: "earnings_cal",    label: "Earnings Calendar",  glyph: "📅", desc: "Upcoming earnings" },
  { id: "cisco_pulse",     label: "Cisco Pulse",        glyph: "◈", desc: "NetOps intel" },
];

const STATUS_COL = { running: T.green, idle: T.ink4, crashed: T.red, queued: T.amber };
const STATUS_BG  = { running: "#eafaf0", idle: T.cardAlt, crashed: "#fdeced", queued: "#fef5e7" };

function AgentStatusCard({ agent, sysAgent, onClick }) {
  const col = AGENT_COLOR[agent.id] || T.violet;
  const status = sysAgent?.status || "idle";
  const sc = STATUS_COL[status] || T.ink4;
  const sb = STATUS_BG[status] || T.cardAlt;
  return (
    <div onClick={onClick} style={{ background: T.card, border: `1px solid ${status === "crashed" ? T.red + "55" : T.line}`, borderRadius: 12, padding: "13px 16px", cursor: "pointer", transition: "all .15s", display: "flex", gap: 11, alignItems: "center" }}
      onMouseEnter={(e) => e.currentTarget.style.borderColor = col + "66"}
      onMouseLeave={(e) => e.currentTarget.style.borderColor = status === "crashed" ? T.red + "55" : T.line}>
      <div style={{ width: 36, height: 36, borderRadius: 9, background: col + "18", color: col, display: "grid", placeItems: "center", fontSize: 16, flex: "0 0 auto" }}>{agent.glyph}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{agent.label}</div>
        <div style={{ fontSize: 11, color: T.ink4 }}>{agent.desc}</div>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: sc, background: sb, padding: "2px 7px", borderRadius: 5 }}>{status}</div>
        {sysAgent && <div style={{ fontSize: 9.5, color: T.ink4, fontFamily: T.mono, marginTop: 2 }}>{sysAgent.schedule}</div>}
      </div>
    </div>
  );
}

function MiniGauge({ label, val, warn = 85, unit = "%" }) {
  const hot = val >= warn;
  const col = hot ? T.red : T.green;
  return (
    <div style={{ textAlign: "center" }}>
      <Ring val={Math.min(100, (val / 100) * 100)} size={52} stroke={5} color={col} track={T.line2}>
        <span style={{ fontSize: 11, fontWeight: 700, fontFamily: T.mono, color: hot ? T.red : T.ink }}>{Math.round(val)}</span>
      </Ring>
      <div style={{ fontSize: 10, color: T.ink4, marginTop: 4, fontWeight: 600 }}>{label}</div>
    </div>
  );
}

function WolfSnippet({ onClick }) {
  const { data } = useAgentData("wallstreet_wolf");
  const gainers = (data?.wolf?.gainers || []).slice(0, 3);
  const losers  = (data?.wolf?.losers  || []).slice(0, 3);
  if (!gainers.length) return <div style={{ fontSize: 12, color: T.ink4, padding: "8px 0" }}>No data yet — run Wallstreet Wolf</div>;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: T.green, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 5 }}>Top gainers</div>
        {gainers.map((s) => (
          <div key={s.ticker} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: 12.5, borderBottom: `1px solid ${T.line2}` }}>
            <span style={{ fontWeight: 700, fontFamily: T.mono }}>{s.ticker}</span>
            <span style={{ color: T.green, fontFamily: T.mono }}>+{(s.pct || 0).toFixed(2)}%</span>
          </div>
        ))}
      </div>
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: T.red, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 5 }}>Top losers</div>
        {losers.map((s) => (
          <div key={s.ticker} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: 12.5, borderBottom: `1px solid ${T.line2}` }}>
            <span style={{ fontWeight: 700, fontFamily: T.mono }}>{s.ticker}</span>
            <span style={{ color: T.red, fontFamily: T.mono }}>{(s.pct || 0).toFixed(2)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CapitolSnippet({ onClick }) {
  const { data } = useAgentData("capitol_tracker");
  const trades = (data?.tracker?.trades || []).slice(0, 5);
  if (!trades.length) return <div style={{ fontSize: 12, color: T.ink4, padding: "8px 0" }}>No data yet — run Capitol Tracker</div>;
  return (
    <div>
      {trades.map((t, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0", fontSize: 12, borderBottom: `1px solid ${T.line2}` }}>
          <span style={{ fontWeight: 700, fontFamily: T.mono, minWidth: 44 }}>{t.ticker || "—"}</span>
          <span style={{ flex: 1, color: T.ink3, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.politician}</span>
          <span style={{ fontSize: 10.5, fontWeight: 700, color: /purchase|buy|exercise/i.test(t.type) ? T.green : T.red, background: /purchase|buy|exercise/i.test(t.type) ? "#f0fdf4" : "#fef2f2", padding: "2px 7px", borderRadius: 4 }}>{t.type?.slice(0, 8)}</span>
        </div>
      ))}
    </div>
  );
}

function BriefSnippet() {
  const { data } = useAgentData("morning_brief");
  const brief = data?.brief;
  if (!brief) return <div style={{ fontSize: 12, color: T.ink4, padding: "8px 0" }}>No brief yet — runs at 06:00 daily</div>;
  return (
    <div>
      {brief.weather && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, fontSize: 12.5 }}>
          <span style={{ fontSize: 18 }}>☁</span>
          <span style={{ color: T.ink2 }}>{brief.weather}</span>
        </div>
      )}
      {brief.summary && <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.55 }}>{brief.summary.slice(0, 200)}{brief.summary.length > 200 ? "…" : ""}</div>}
    </div>
  );
}

function OptionsSnippet({ onClick }) {
  const { data } = useAgentData("options_flow");
  const signals = (data?.flow?.signals || []).slice(0, 4);
  if (!signals.length) return <div style={{ fontSize: 12, color: T.ink4, padding: "8px 0" }}>No data yet — run Options Flow</div>;
  return (
    <div>
      {signals.map((s, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0", fontSize: 12, borderBottom: `1px solid ${T.line2}` }}>
          <span style={{ fontWeight: 700, fontFamily: T.mono, minWidth: 44, color: AGENT_COLOR.options_flow }}>{s.ticker}</span>
          <span style={{ fontSize: 10, background: "#f1edfe", color: T.violet, padding: "2px 6px", borderRadius: 4, fontWeight: 700 }}>{s.type || "call"}</span>
          <span style={{ flex: 1, color: T.ink3, fontSize: 11 }}>IV {s.iv_pct?.toFixed(0)}%ile</span>
          <span style={{ fontSize: 10.5, color: T.ink2, fontFamily: T.mono }}>{s.signal || ""}</span>
        </div>
      ))}
    </div>
  );
}

export default function Home({ sys, online, onNavigate }) {
  const agents   = sys?.agents || [];
  const res      = sys?.res || {};
  const events   = (sys?.events || []).slice(0, 6);
  const running  = agents.filter((a) => a.status === "running").length;

  const cpu  = res.cpu?.v  || 0;
  const ram  = res.ram?.v  || 0;
  const disk = res.disk?.v || 0;
  const gpu  = res.gpu?.v  || 0;

  return (
    <div>
      <TabHeader icon="⌂" color={T.violet} title="Home"
        sub="Mission control — all agents at a glance"
        actions={<>
          <Pill c={online ? T.green : T.amber} bg={online ? "#eafaf0" : "#fef5e7"}>
            <Dot c={online ? T.green : T.amber} />{online ? "Backend live" : "Backend offline"}
          </Pill>
          <Pill mono c={T.ink3}>{running} running</Pill>
        </>}
      />

      <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 18 }}>

        {/* System gauges */}
        <Card pad={14}>
          <SectionTitle sub="Live system metrics">Resources</SectionTitle>
          <div style={{ display: "flex", gap: 28, justifyContent: "space-around", flexWrap: "wrap" }}>
            <MiniGauge label="CPU"  val={cpu}  warn={85} />
            <MiniGauge label="RAM"  val={ram}  warn={88} />
            <MiniGauge label="Disk" val={disk} warn={90} />
            <MiniGauge label="GPU"  val={gpu}  warn={85} />
            {sys && <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: 22, fontWeight: 800, fontFamily: T.mono, color: T.ink }}>{sys.threads || 0}</div>
              <div style={{ fontSize: 10, color: T.ink4, marginTop: 4, fontWeight: 600 }}>Threads</div>
            </div>}
          </div>
        </Card>

        {/* Agent status grid */}
        <div>
          <SectionTitle sub="Click any card to navigate">All agents</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
            {AGENTS.map((a) => (
              <AgentStatusCard key={a.id} agent={a} sysAgent={agents.find((s) => s.id === a.id)} onClick={() => onNavigate(a.id)} />
            ))}
          </div>
        </div>

        {/* Data snippets row */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card pad={14}>
            <SectionTitle sub="Latest movers" right={<button onClick={() => onNavigate("wallstreet_wolf")} style={{ fontSize: 11, color: T.violet, background: T.violetBg, border: `1px solid ${T.violet}33`, borderRadius: 6, padding: "2px 9px", cursor: "pointer", fontFamily: T.sans }}>Open Wolf →</button>}>
              Wallstreet Wolf
            </SectionTitle>
            <WolfSnippet onClick={() => onNavigate("wallstreet_wolf")} />
          </Card>

          <Card pad={14}>
            <SectionTitle sub="Recent disclosures" right={<button onClick={() => onNavigate("capitol_tracker")} style={{ fontSize: 11, color: "#dc2626", background: "#fef2f2", border: "1px solid #dc262633", borderRadius: 6, padding: "2px 9px", cursor: "pointer", fontFamily: T.sans }}>Open Tracker →</button>}>
              Capitol Tracker
            </SectionTitle>
            <CapitolSnippet onClick={() => onNavigate("capitol_tracker")} />
          </Card>

          <Card pad={14}>
            <SectionTitle sub="Today's digest" right={<button onClick={() => onNavigate("morning_brief")} style={{ fontSize: 11, color: "#b45309", background: "#fffbeb", border: "1px solid #d9770633", borderRadius: 6, padding: "2px 9px", cursor: "pointer", fontFamily: T.sans }}>Open Brief →</button>}>
              Morning Brief
            </SectionTitle>
            <BriefSnippet />
          </Card>

          <Card pad={14}>
            <SectionTitle sub="Unusual options activity" right={<button onClick={() => onNavigate("options_flow")} style={{ fontSize: 11, color: T.violet, background: T.violetBg, border: `1px solid ${T.violet}33`, borderRadius: 6, padding: "2px 9px", cursor: "pointer", fontFamily: T.sans }}>Open Flow →</button>}>
              Options Flow
            </SectionTitle>
            <OptionsSnippet onClick={() => onNavigate("options_flow")} />
          </Card>
        </div>

        {/* Recent events */}
        {events.length > 0 && (
          <Card pad={14}>
            <SectionTitle sub="Recent platform events">Activity</SectionTitle>
            <div>
              {events.map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 10, padding: "6px 0", fontSize: 12.5, alignItems: "baseline", borderBottom: i < events.length - 1 ? `1px solid ${T.line2}` : "none" }}>
                  <span style={{ fontFamily: T.mono, color: T.ink4, fontSize: 10.5, flexShrink: 0 }}>{e.t}</span>
                  <Dot c={e.c} s={5} />
                  <span style={{ color: T.ink2 }}>{e.m}</span>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
