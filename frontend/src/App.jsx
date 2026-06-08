// ============================================================================
// App.jsx — shell: left nav, appearance controls, routing. Wired to the backend.
// ============================================================================
import { useState, useEffect } from "react";
import { T, applyMode, AGENT_COLOR } from "./theme/tokens";
import { Dot, Appearance } from "./theme/ui";
import { useSystemState } from "./state/api";

import Orchestrator from "./tabs/Orchestrator";
import AITimes from "./tabs/AITimes";
import Mailman from "./tabs/Mailman";
import Wolf from "./tabs/Wolf";
import Compass from "./tabs/Compass";
import Aegis from "./tabs/Aegis";
import DevDaily from "./tabs/DevDaily";
import StrategyScout from "./tabs/StrategyScout";
import Settings from "./tabs/Settings";

const NAV = [
  { id: "orchestrator", label: "Orchestrator", glyph: "◇" },
  { id: "ai_times", label: "AI-Times", glyph: "▶" },
  { id: "mailman", label: "Mailman", glyph: "✉" },
  { id: "wallstreet_wolf", label: "Wallstreet Wolf", glyph: "$" },
  { id: "compass", label: "Wallstreet Compass", glyph: "◎" },
  { id: "aegis", label: "Aegis", glyph: "❖" },
  { id: "devdaily", label: "GitHub Trending", glyph: "⌥" },
  { id: "strategy_scout", label: "Strategy Scout", glyph: "✦" },
];
const SETTINGS_ITEM = { id: "settings", label: "Settings", glyph: "⚙" };
const TABS = { ai_times: AITimes, mailman: Mailman, wallstreet_wolf: Wolf, compass: Compass, aegis: Aegis, devdaily: DevDaily, strategy_scout: StrategyScout };
const dotColor = { running: T.green, queued: T.amber, crashed: T.red, idle: "#aeb4bf" };

function NavItem({ item, active, onClick, badge }) {
  const col = AGENT_COLOR[item.id] || T.violet;
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

function Sidebar({ tab, setTab, theme, setTheme, mode, setMode, sys, online, transport }) {
  const agents = sys?.agents || [];
  const res = sys?.res;
  const statusOf = (id) => agents.find((a) => a.id === id)?.status;
  const anyAlarm = !!sys?.alarm;

  return (
    <div style={{ width: 248, flex: "0 0 auto", background: T.sidebar, borderRight: `1px solid ${T.line}`, display: "flex", flexDirection: "column", padding: "18px 14px", height: "100vh", position: "sticky", top: 0, overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11, padding: "4px 8px 18px" }}>
        <div style={{ width: 34, height: 34, borderRadius: 9, background: "linear-gradient(135deg,#7c5cf6,#9d7bff)", display: "grid", placeItems: "center", color: "#fff", fontWeight: 700, fontSize: 16, flex: "0 0 auto" }}>◇</div>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 800, letterSpacing: -0.2, lineHeight: 1.1 }}>Orchestrator</div>
          <div style={{ fontSize: 10.5, color: T.ink3, fontFamily: T.mono }}>multi-agent platform</div>
        </div>
      </div>

      <div style={{ fontSize: 10.5, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.6, padding: "0 12px 8px" }}>System</div>
      <NavItem item={NAV[0]} active={tab === "orchestrator"} onClick={() => setTab("orchestrator")}
        badge={<Dot c={anyAlarm ? T.red : online ? T.green : T.amber} s={7} />} />
      <NavItem item={SETTINGS_ITEM} active={tab === "settings"} onClick={() => setTab("settings")} />

      <div style={{ fontSize: 10.5, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.6, padding: "16px 12px 8px" }}>Agents</div>
      {NAV.slice(1).map((it) => {
        const st = statusOf(it.id);
        return <NavItem key={it.id} item={it} active={tab === it.id} onClick={() => setTab(it.id)}
          badge={st ? <Dot c={dotColor[st] || "#aeb4bf"} s={7} /> : null} />;
      })}

      <div style={{ marginTop: "auto", paddingTop: 14, borderTop: `1px solid ${T.line}` }}>
        <Appearance theme={theme} setTheme={setTheme} mode={mode} setMode={setMode} />
      </div>
      <div style={{ padding: "12px 12px 4px", borderTop: `1px solid ${T.line}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <Dot c={online ? T.green : T.amber} s={7} />
          <span style={{ fontSize: 11.5, fontWeight: 600, color: T.ink2 }}>{(sys?.llm?.model) || "Qwen3"} · local</span>
          <span style={{ marginLeft: "auto", fontSize: 10, fontFamily: T.mono, color: T.ink4 }}>{transport === "ws" ? "live · ws" : transport === "poll" ? "poll" : "…"}</span>
        </div>
        <div style={{ fontSize: 10, color: T.ink4, fontFamily: T.mono, lineHeight: 1.6 }}>
          {res ? <>CPU {Math.round(res.cpu.v)}% · RAM {Math.round(res.ram.v)}% · GPU {Math.round(res.gpu.v)}%<br /></> : <>connecting…<br /></>}
          localhost:5174
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState(() => localStorage.getItem("om_tab") || "orchestrator");
  const [theme, setTheme] = useState(() => localStorage.getItem("om_theme") || "aria");
  const [mode, setMode] = useState(() => localStorage.getItem("om_mode") || "light");
  applyMode(mode); // mutate shared tokens before children render

  const { state: sys, online, transport } = useSystemState();

  useEffect(() => { localStorage.setItem("om_tab", tab); }, [tab]);
  useEffect(() => { localStorage.setItem("om_theme", theme); }, [theme]);
  useEffect(() => {
    localStorage.setItem("om_mode", mode);
    document.body.style.background = T.bg;
    document.documentElement.style.colorScheme = mode;
  }, [mode]);

  const agent = sys?.agents?.find((a) => a.id === tab);
  let content;
  if (tab === "orchestrator") {
    content = <Orchestrator sys={sys} online={online} theme={theme} />;
  } else if (tab === "settings") {
    content = <Settings />;
  } else {
    const TabEl = TABS[tab];
    content = <TabEl key={tab} status={agent?.status} agentError={agent?.error} progress={agent?.progress} result={agent?.result} />;
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: T.bg, fontFamily: T.sans, color: T.ink }}>
      <Sidebar tab={tab} setTab={setTab} theme={theme} setTheme={setTheme} mode={mode} setMode={setMode} sys={sys} online={online} transport={transport} />
      <div style={{ flex: 1, minWidth: 0 }}>{content}</div>
    </div>
  );
}
