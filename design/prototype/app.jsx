// ============================================================================
// app.jsx — shell: left nav, routing, global tick. Mount last.
// ============================================================================
const NAV = [
  { id: "orchestrator", label: "Orchestrator", glyph: "◇", el: "OrchestratorTab" },
  { id: "ai-times", label: "AI-Times", glyph: "▶", el: "AITimesTab" },
  { id: "mailman", label: "Mailman", glyph: "✉", el: "MailmanTab" },
  { id: "wolf", label: "Wallstreet Wolf", glyph: "$", el: "WolfTab" },
  { id: "compass", label: "Compass", glyph: "◎", el: "CompassTab" },
  { id: "aegis", label: "Aegis", glyph: "❖", el: "AegisTab" },
];

function NavItem({ item, active, onClick, badge }) {
  const col = AGENT_COLOR[item.id];
  return (
    <button onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 12, width: "100%", textAlign: "left", cursor: "pointer",
      padding: "9px 12px", borderRadius: 10, border: "1px solid transparent", marginBottom: 2,
      background: active ? T.card : "transparent", boxShadow: active ? T.shadow : "none",
      borderColor: active ? T.line : "transparent", font: "inherit", transition: "all .14s",
    }}
      onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = T.mode === "dark" ? "#ffffff10" : "#ffffff80"; }}
      onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}>
      <span style={{ width: 28, height: 28, borderRadius: 8, background: col + (active ? "1f" : "14"), color: col, display: "grid", placeItems: "center", fontSize: 14, fontWeight: 700, flex: "0 0 auto" }}>{item.glyph}</span>
      <span style={{ fontSize: 13.5, fontWeight: active ? 700 : 600, color: active ? T.ink : T.ink2, flex: 1 }}>{item.label}</span>
      {badge}
    </button>
  );
}

function Sidebar({ tab, setTab, theme, setTheme, mode, setMode }) {
  const s = useSim();
  const statusFor = (id) => {
    const a = s.agents.find((x) => x.id === id);
    if (!a) return null;
    if (a.status === "crashed") return <Dot c={T.red} s={7} />;
    if (a.status === "running") return <Dot c={T.green} s={7} />;
    if (a.status === "queued") return <Dot c={T.amber} s={7} />;
    return <Dot c={T.ink4} s={7} />;
  };
  return (
    <div style={{ width: 248, flex: "0 0 auto", background: T.sidebar, borderRight: `1px solid ${T.line}`, display: "flex", flexDirection: "column", padding: "18px 14px", height: "100vh", position: "sticky", top: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11, padding: "4px 8px 18px" }}>
        <div style={{ width: 34, height: 34, borderRadius: 9, background: "linear-gradient(135deg,#7c5cf6,#9d7bff)", display: "grid", placeItems: "center", color: "#fff", fontWeight: 700, fontSize: 16, flex: "0 0 auto" }}>◇</div>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 800, letterSpacing: -0.2, lineHeight: 1.1 }}>Orchestrator</div>
          <div style={{ fontSize: 10.5, color: T.ink3, fontFamily: T.mono }}>multi-agent platform</div>
        </div>
      </div>

      <div style={{ fontSize: 10.5, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.6, padding: "0 12px 8px" }}>System</div>
      <NavItem item={NAV[0]} active={tab === "orchestrator"} onClick={() => setTab("orchestrator")}
        badge={s.alarm ? <Dot c={T.red} s={7} /> : <Dot c={T.green} s={7} />} />

      <div style={{ fontSize: 10.5, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.6, padding: "16px 12px 8px" }}>Agents</div>
      {NAV.slice(1).map((it) => (
        <NavItem key={it.id} item={it} active={tab === it.id} onClick={() => setTab(it.id)} badge={statusFor(it.id)} />
      ))}

      <div style={{ marginTop: "auto", paddingTop: 14, borderTop: `1px solid ${T.line}` }}>
        <Appearance theme={theme} setTheme={setTheme} mode={mode} setMode={setMode} />
      </div>
      <div style={{ padding: "12px 12px 4px", borderTop: `1px solid ${T.line}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <Dot c={T.green} s={7} />
          <span style={{ fontSize: 11.5, fontWeight: 600, color: T.ink2 }}>Qwen3 · local</span>
          <span style={{ marginLeft: "auto", fontSize: 10, fontFamily: T.mono, color: T.ink4 }}>Ollama</span>
        </div>
        <div style={{ fontSize: 10, color: T.ink4, fontFamily: T.mono, lineHeight: 1.6 }}>
          CPU {s.res.cpu.v}% · RAM {s.res.ram.v}% · GPU {s.res.gpu.v}%<br />localhost:8787
        </div>
      </div>
    </div>
  );
}

function App() {
  const [tab, setTab] = React.useState(() => localStorage.getItem("om_tab") || "orchestrator");
  const [theme, setTheme] = React.useState(() => localStorage.getItem("om_theme") || "aria");
  const [mode, setMode] = React.useState(() => localStorage.getItem("om_mode") || "light");
  applyMode(mode); // mutate shared tokens before children render
  React.useEffect(() => { Sim.start(); }, []);
  React.useEffect(() => { localStorage.setItem("om_tab", tab); }, [tab]);
  React.useEffect(() => { localStorage.setItem("om_theme", theme); }, [theme]);
  React.useEffect(() => {
    localStorage.setItem("om_mode", mode);
    document.body.style.background = T.bg;
    document.documentElement.style.colorScheme = mode;
  }, [mode]);
  const active = NAV.find((n) => n.id === tab);
  const TabEl = window[active.el];
  const extra = active.id === "orchestrator" ? { theme } : {};
  return (
    <div style={{ display: "flex", minHeight: "100vh", background: T.bg, fontFamily: T.sans, color: T.ink }}>
      <Sidebar tab={tab} setTab={setTab} theme={theme} setTheme={setTheme} mode={mode} setMode={setMode} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <TabEl key={tab} {...extra} />
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
