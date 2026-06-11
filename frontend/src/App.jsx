// ============================================================================
// App.jsx — shell: collapsible nav, command palette, toasts, keyboard shortcuts
// ============================================================================
import { useState, useEffect, useRef, useCallback, Component } from "react";
import { T, applyMode, AGENT_COLOR } from "./theme/tokens";
import { Dot } from "./theme/ui";
import { useSystemState, useAgentData } from "./state/api";
import { ToastContainer, useToasts, useAgentToasts } from "./components/Toast";
import CommandPalette from "./components/CommandPalette";
import AskAI from "./components/AskAI";

import Orchestrator   from "./tabs/Orchestrator";
import AITimes        from "./tabs/AITimes";
import Mailman        from "./tabs/Mailman";
import Wolf           from "./tabs/Wolf";
import Compass        from "./tabs/Compass";
import DevDaily       from "./tabs/DevDaily";
import StrategyScout  from "./tabs/StrategyScout";
import CapitolTracker from "./tabs/CapitolTracker";
import MorningBrief   from "./tabs/MorningBrief";
import OptionsFlow    from "./tabs/OptionsFlow";
import EarningsCalendar from "./tabs/EarningsCalendar";
import CiscoPulse     from "./tabs/CiscoPulse";
import AlphaWolf      from "./tabs/AlphaWolf";
import Settings       from "./tabs/Settings";

// Main panel — always-pinned agents (the graded four + Cisco Pulse).
const MAIN_AGENTS = [
  { id: "ai_times",         label: "AI-Times",          glyph: "▶"  },
  { id: "mailman",          label: "Mailman",            glyph: "✉"  },
  { id: "wallstreet_wolf",  label: "Wallstreet Wolf",   glyph: "$"  },
  { id: "cisco_pulse",      label: "Cisco Pulse",       glyph: "◈"  },
  { id: "devdaily",         label: "GitHub Trending",   glyph: "⌥"  },
];
// Alpha Wolf — master agent (the group header itself) + its pack of sub-agents.
const ALPHA_MASTER = { id: "alpha_wolf", label: "Alpha Wolf", glyph: "🐺" };
const ALPHA_GROUP = [
  { id: "wallstreet_wolf",  label: "Wallstreet Wolf",   glyph: "$"  },
  { id: "compass",          label: "Wallstreet Compass", glyph: "◎"  },
  { id: "strategy_scout",   label: "Strategy Scout",    glyph: "✦"  },
  { id: "capitol_tracker",  label: "Capitol Tracker",   glyph: "🏛" },
  { id: "options_flow",     label: "Options Flow",      glyph: "⚡" },
  { id: "earnings_cal",     label: "Earnings Calendar", glyph: "📅" },
];
const SETTINGS_ITEM   = { id: "settings",     label: "Settings",     glyph: "⚙" };
const ORCHESTRATOR_IT = { id: "orchestrator", label: "Orchestrator", glyph: "◇" };

// The four graded agents. Demo mode collapses the sidebar to just these so a
// 10-minute video only shows the rubric-scored components.
const CORE_AGENTS = ["ai_times", "mailman", "wallstreet_wolf", "devdaily"];

const TABS = {
  ai_times:         AITimes,
  mailman:          Mailman,
  wallstreet_wolf:  Wolf,
  compass:          Compass,
  devdaily:         DevDaily,
  strategy_scout:   StrategyScout,
  capitol_tracker:  CapitolTracker,
  morning_brief:    MorningBrief,
  options_flow:     OptionsFlow,
  earnings_cal:     EarningsCalendar,
  cisco_pulse:      CiscoPulse,
  alpha_wolf:       AlphaWolf,
};

// All tabs for keyboard shortcut ordering (no home)
const ORDERED_TABS = ["orchestrator","ai_times","mailman","wallstreet_wolf","cisco_pulse","devdaily","alpha_wolf","compass","strategy_scout","capitol_tracker","options_flow","earnings_cal","morning_brief"];

const dotColor = { running: T.green, queued: T.amber, crashed: T.red, idle: "#aeb4bf" };

// ── Tab error boundary ───────────────────────────────────────────────────────
// A crash inside one tab must never blank the whole app: catch it, show the
// error inline, and keep the sidebar alive so the user can navigate away.
// Keyed by tab in App so switching tabs resets the boundary automatically.
class TabErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    console.error("[TabErrorBoundary] tab crashed:", error, info?.componentStack);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ padding: 40 }}>
        <div style={{ background: T.card, border: `1px solid ${T.red}44`, borderRadius: 14, padding: "22px 26px", maxWidth: 640 }}>
          <div style={{ fontSize: 15, fontWeight: 800, color: T.red, marginBottom: 8 }}>⚠ This tab crashed while rendering</div>
          <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.55, marginBottom: 12 }}>
            The rest of the app is still running — switch to another tab, or reload this one.
            This usually means the agent saved data in an unexpected shape; re-running the agent typically fixes it.
          </div>
          <div style={{ fontFamily: T.mono, fontSize: 11.5, color: T.ink3, background: T.cardAlt, border: `1px solid ${T.line}`, borderRadius: 8, padding: "10px 12px", marginBottom: 14, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {String(this.state.error?.message || this.state.error)}
          </div>
          <button onClick={() => this.setState({ error: null })} style={{ padding: "7px 16px", background: T.cardAlt, border: `1px solid ${T.line}`, borderRadius: 8, color: T.ink2, cursor: "pointer", fontSize: 12.5, fontFamily: T.sans, fontWeight: 600 }}>
            Reload tab
          </button>
        </div>
      </div>
    );
  }
}

// ── Keyboard shortcut help overlay ──────────────────────────────────────────
function ShortcutHelp({ onClose }) {
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 998, background: "rgba(0,0,0,.45)", display: "grid", placeItems: "center" }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 16, padding: "24px 28px", width: 380, boxShadow: "0 20px 60px rgba(0,0,0,.2)" }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>Keyboard shortcuts</div>
        {[
          ["⌘ K", "Command palette"],
          ["1 – 9", "Jump to tab by number"],
          ["R", "Refresh active agent"],
          ["S", "Go to Settings"],
          ["O", "Go to Orchestrator"],
          ["?", "Show this help"],
          ["Esc", "Close overlay"],
        ].map(([k, d]) => (
          <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 0", borderBottom: `1px solid ${T.line2}`, fontSize: 13 }}>
            <span style={{ color: T.ink2 }}>{d}</span>
            <span style={{ fontFamily: T.mono, fontSize: 12, background: T.cardAlt, border: `1px solid ${T.line}`, borderRadius: 5, padding: "2px 8px", color: T.ink3 }}>{k}</span>
          </div>
        ))}
        <button onClick={onClose} style={{ marginTop: 16, width: "100%", padding: "8px", background: T.cardAlt, border: `1px solid ${T.line}`, borderRadius: 8, color: T.ink2, cursor: "pointer", fontSize: 13, fontFamily: T.sans }}>Close</button>
      </div>
    </div>
  );
}

// ── NavItem ──────────────────────────────────────────────────────────────────
function NavItem({ item, active, onClick, badge, collapsed }) {
  const col = AGENT_COLOR[item.id] || T.violet;
  if (collapsed) {
    return (
      <button onClick={onClick} title={item.label} style={{
        width: 38, height: 38, borderRadius: 10, margin: "1px auto", display: "flex", alignItems: "center", justifyContent: "center",
        background: active ? col + "1f" : "transparent", border: `1px solid ${active ? col + "44" : "transparent"}`,
        color: active ? col : T.sideInk2, fontSize: 15, fontWeight: 700, cursor: "pointer",
        transition: "all .14s", position: "relative",
      }}>
        {item.glyph}
        {badge && <div style={{ position: "absolute", top: 4, right: 4 }}>{badge}</div>}
      </button>
    );
  }
  return (
    <button onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left",
      cursor: "pointer", padding: "8px 10px", borderRadius: 10,
      border: `1px solid ${active ? T.sideLine : "transparent"}`,
      background: active ? T.sideActive : "transparent",
      boxShadow: active ? T.shadow : "none",
      font: "inherit", transition: "all .14s", marginBottom: 1,
    }}
      onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = T.sideBtn; }}
      onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}>
      <span style={{ width: 26, height: 26, borderRadius: 7, background: col + (active ? "1f" : "12"), color: col, display: "grid", placeItems: "center", fontSize: 13, fontWeight: 700, flex: "0 0 auto" }}>{item.glyph}</span>
      <span style={{ fontSize: 13, fontWeight: active ? 700 : 500, color: active ? T.sideInk : T.sideInk2, flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</span>
      {badge}
    </button>
  );
}

// ── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({ tab, setTab, sys, online, capitolCount, collapsed, setCollapsed, onCmdK }) {
  const agents = sys?.agents || [];
  const res = sys?.res;
  const statusOf = (id) => agents.find((a) => a.id === id)?.status;
  const anyAlarm = !!sys?.alarm;
  const demo = !!sys?.demo;
  const mainList = demo ? MAIN_AGENTS.filter((a) => CORE_AGENTS.includes(a.id)) : MAIN_AGENTS;
  const [alphaOpen, setAlphaOpen] = useState(true);
  const W = collapsed ? 58 : 232;

  const sectionLabel = (text) => collapsed ? null : (
    <div style={{ fontSize: 10, fontWeight: 700, color: T.sideMuted, textTransform: "uppercase", letterSpacing: 0.6, padding: "0 10px 6px", marginTop: 12 }}>{text}</div>
  );

  const renderNav = (it, keyPrefix = "") => {
    const st = statusOf(it.id);
    const isCapitol = it.id === "capitol_tracker";
    // Capitol's trade-count pill must not hide the live status dot — show both.
    const badge = !collapsed && (st || (isCapitol && capitolCount > 0)) ? (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        {isCapitol && capitolCount > 0 &&
          <span style={{ fontSize: 9.5, fontWeight: 700, background: "#dc262620", color: "#dc2626", padding: "1px 6px", borderRadius: 4, fontFamily: T.mono }}>{capitolCount}</span>}
        {st && <Dot c={dotColor[st] || "#aeb4bf"} s={6} />}
      </span>
    ) : null;
    return <NavItem key={keyPrefix + it.id} item={it} active={tab === it.id} onClick={() => setTab(it.id)} badge={badge} collapsed={collapsed} />;
  };

  return (
    <div style={{ width: W, flex: `0 0 ${W}px`, background: T.sidebar, borderRight: `1px solid ${T.sideLine}`, display: "flex", flexDirection: "column", padding: collapsed ? "14px 8px" : "14px 10px", height: "100vh", position: "sticky", top: 0, overflowY: "auto", overflowX: "hidden", transition: "width .22s ease, flex .22s ease" }}>

      {/* Logo — clicking navigates to Orchestrator */}
      <div style={{ display: "flex", alignItems: "center", gap: collapsed ? 0 : 10, padding: collapsed ? "2px 0 12px" : "2px 4px 14px", justifyContent: collapsed ? "center" : "space-between" }}>
        {!collapsed && (
          <button onClick={() => setTab("orchestrator")} title="Orchestrator" style={{ display: "flex", alignItems: "center", gap: 9, background: tab === "orchestrator" ? T.violet + "18" : "transparent", border: tab === "orchestrator" ? `1px solid ${T.violet}33` : "1px solid transparent", borderRadius: 8, padding: "4px 8px 4px 4px", cursor: "pointer", flex: 1, minWidth: 0 }}>
            <div style={{ width: 30, height: 30, borderRadius: 8, background: "linear-gradient(135deg,#7c5cf6,#9d7bff)", display: "grid", placeItems: "center", color: "#fff", fontWeight: 700, fontSize: 14, flex: "0 0 auto" }}>◇</div>
            <div style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
              <div style={{ fontSize: 12.5, fontWeight: 800, letterSpacing: -0.2, lineHeight: 1.1, color: T.sideInk }}>Orchestrator</div>
              <div style={{ fontSize: 9.5, color: T.sideMuted, fontFamily: T.mono }}>multi-agent</div>
            </div>
            <Dot c={anyAlarm ? T.red : online ? T.green : T.amber} s={6} />
          </button>
        )}
        {collapsed && (
          <button onClick={() => setTab("orchestrator")} title="Orchestrator" style={{ width: 30, height: 30, borderRadius: 8, background: tab === "orchestrator" ? "linear-gradient(135deg,#7c5cf6,#9d7bff)" : "linear-gradient(135deg,#7c5cf6,#9d7bff)", display: "grid", placeItems: "center", color: "#fff", fontWeight: 700, fontSize: 14, border: "none", cursor: "pointer" }}>◇</button>
        )}
        <button onClick={() => setCollapsed(!collapsed)} title={collapsed ? "Expand sidebar" : "Collapse sidebar"} style={{ width: 22, height: 22, borderRadius: 6, background: T.sideBtn, border: `1px solid ${T.sideLine}`, cursor: "pointer", display: "grid", placeItems: "center", fontSize: 11, color: T.sideInk2, flexShrink: 0 }}>
          {collapsed ? "▶" : "◀"}
        </button>
      </div>

      {/* Cmd+K search */}
      {!collapsed && (
        <button onClick={onCmdK} style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", background: T.sideBtn, border: `1px solid ${T.sideLine}`, borderRadius: 8, padding: "6px 10px", marginBottom: 10, cursor: "pointer", fontFamily: T.sans }}>
          <span style={{ fontSize: 13, color: T.sideMuted }}>⌘</span>
          <span style={{ fontSize: 12, color: T.sideMuted, flex: 1, textAlign: "left" }}>Search…</span>
          <span style={{ fontSize: 10, fontFamily: T.mono, color: T.sideMuted, background: T.sideActive, border: `1px solid ${T.sideLine}`, borderRadius: 4, padding: "1px 5px" }}>K</span>
        </button>
      )}

      {/* Main agents */}
      {sectionLabel(demo ? "Agents · demo mode" : "Agents")}
      {mainList.map((it) => renderNav(it))}

      {/* Alpha Wolf — master agent (header navigates) + expandable pack (hidden in demo) */}
      {!demo && !collapsed && (
        <>
          <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 4 }}>
            <div style={{ flex: 1, minWidth: 0 }}>{renderNav(ALPHA_MASTER)}</div>
            <button onClick={() => setAlphaOpen((o) => !o)} title={alphaOpen ? "Collapse pack" : "Expand pack"} style={{
              width: 24, height: 24, borderRadius: 6, border: `1px solid ${T.sideLine}`, background: T.sideBtn,
              color: T.sideInk2, cursor: "pointer", fontSize: 10, flex: "0 0 auto", display: "grid", placeItems: "center",
            }}>{alphaOpen ? "▾" : "▸"}</button>
          </div>
          {alphaOpen && (
            <div style={{ marginLeft: 14, paddingLeft: 6, borderLeft: `1px solid ${T.sideLine}` }}>
              {ALPHA_GROUP.map((it) => renderNav(it, "grp-"))}
            </div>
          )}
        </>
      )}
      {!demo && collapsed && (
        <>
          <div style={{ height: 1, background: T.sideLine, margin: "10px 8px" }} />
          {renderNav(ALPHA_MASTER)}
          {ALPHA_GROUP.map((it) => renderNav(it, "grp-"))}
        </>
      )}

      {/* Bottom — Settings pinned */}
      <div style={{ marginTop: "auto", paddingTop: 10, borderTop: `1px solid ${T.sideLine}` }}>
        <NavItem item={SETTINGS_ITEM} active={tab === "settings"} onClick={() => setTab("settings")} collapsed={collapsed} />
        <div style={{ padding: collapsed ? "8px 0" : "8px 4px 2px", fontSize: 10, color: T.sideMuted, fontFamily: T.mono, lineHeight: 1.6, textAlign: collapsed ? "center" : "left" }}>
          {!collapsed && (res
            ? <>CPU {Math.round(res.cpu?.v || 0)}% · RAM {Math.round(res.ram?.v || 0)}%<br /></>
            : <>connecting…<br /></>)}
          <Dot c={online ? T.green : T.amber} s={6} />
          {!collapsed && " 5174"}
        </div>
      </div>
    </div>
  );
}

// ── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [tab, setTab]       = useState(() => { const t = localStorage.getItem("om_tab"); return t === "home" ? "orchestrator" : (t || "orchestrator"); });
  const [mode, setMode]     = useState(() => localStorage.getItem("om_mode") || "light");
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("om_collapsed") === "1");
  const [cmdOpen, setCmdOpen]     = useState(false);
  const [helpOpen, setHelpOpen]   = useState(false);
  applyMode(mode);

  const { state: sys, online, transport } = useSystemState();
  const { data: capitolData } = useAgentData("capitol_tracker");
  const capitolCount = capitolData?.tracker?.stats?.total || 0;

  const { toasts, addToast, dismissToast } = useToasts();
  useAgentToasts(sys, addToast);

  // Persist prefs
  useEffect(() => { localStorage.setItem("om_tab", tab); }, [tab]);
  useEffect(() => { localStorage.setItem("om_collapsed", collapsed ? "1" : "0"); }, [collapsed]);
  useEffect(() => { localStorage.setItem("om_mode", mode); document.body.style.background = T.bg; document.documentElement.style.colorScheme = T.mode; }, [mode]);

  const navigate = useCallback((id) => setTab(id), []);

  // In demo mode, don't sit on a now-hidden agent tab.
  useEffect(() => {
    if (sys?.demo && tab !== "orchestrator" && tab !== "settings" && !CORE_AGENTS.includes(tab)) {
      setTab("orchestrator");
    }
  }, [sys?.demo, tab]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); setCmdOpen(true); return; }
      if (e.key === "Escape") { setCmdOpen(false); setHelpOpen(false); return; }
      if (e.key === "?") { setHelpOpen(true); return; }
      if (e.key === "o" || e.key === "O") { setTab("orchestrator"); return; }
      if (e.key === "s" || e.key === "S") { setTab("settings"); return; }
      const num = parseInt(e.key);
      if (num >= 1 && num <= 9 && ORDERED_TABS[num - 1]) setTab(ORDERED_TABS[num - 1]);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const agent = sys?.agents?.find((a) => a.id === tab);
  let content;
  if (tab === "orchestrator") {
    content = <Orchestrator sys={sys} online={online} onNavigate={navigate} />;
  } else if (tab === "settings") {
    content = <Settings mode={mode} setMode={setMode} />;
  } else {
    const TabEl = TABS[tab];
    if (!TabEl) { content = <div style={{ padding: 40, color: T.ink3 }}>Tab not found: {tab}</div>; }
    else content = <TabEl key={tab} status={agent?.status} agentError={agent?.error} progress={agent?.progress} result={agent?.result} />;
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: T.bg, fontFamily: T.sans, color: T.ink }}>
      <Sidebar
        tab={tab} setTab={setTab}
        sys={sys} online={online}
        capitolCount={capitolCount}
        collapsed={collapsed} setCollapsed={setCollapsed}
        onCmdK={() => setCmdOpen(true)}
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <TabErrorBoundary key={tab}>{content}</TabErrorBoundary>
      </div>

      {/* Per-agent AI assistant — every agent tab gets an Ask-AI panel */}
      {TABS[tab] && <AskAI key={"ai-" + tab} agentId={tab} agentName={agent?.n || tab} color={AGENT_COLOR[tab]} />}

      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} onNavigate={(id) => { setTab(id); setCmdOpen(false); }} sys={sys} />
      {helpOpen && <ShortcutHelp onClose={() => setHelpOpen(false)} />}
      <ToastContainer toasts={toasts} dismiss={dismissToast} />
    </div>
  );
}
