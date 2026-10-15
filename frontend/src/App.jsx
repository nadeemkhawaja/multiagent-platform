// ============================================================================
// App.jsx — shell: collapsible nav, command palette, toasts, keyboard shortcuts
// ============================================================================
import { useState, useEffect, useCallback, useMemo, Component } from "react";
import { T, applyMode, AGENT_COLOR, STAT, AGENT_BADGE } from "./theme/tokens";
import { Badge } from "./theme/icons";
import { Dot, useDialog, useMediaQuery, NavContext, MOBILE_Q } from "./theme/ui";
import { useSystemState } from "./state/api";
import CommandPalette from "./components/CommandPalette";
import AskLufi from "./components/AskLufi";
import Aurora from "./components/Aurora";

import Wolf           from "./tabs/Wolf";
import Technologia    from "./tabs/Technologia";
import AlphaWolf      from "./tabs/AlphaWolf";
import Settings       from "./tabs/Settings";

// Alpha Wolf — master agent (the group header itself) + its pack of sub-agents.
const ALPHA_MASTER = { id: "alpha_wolf", label: "Alpha Wolf", glyph: "🐺" };
const ALPHA_GROUP = [
  { id: "wallstreet_wolf",  label: "Wallstreet Wolf",   glyph: "$"  },
  { id: "technologia",      label: "Technologia",       glyph: "◭" },
];
const SETTINGS_ITEM   = { id: "settings",     label: "Settings",     glyph: "⚙" };

const TABS = {
  wallstreet_wolf:  Wolf,
  technologia:      Technologia,
  alpha_wolf:       AlphaWolf,
};

// All tabs for keyboard shortcut ordering
const ORDERED_TABS = ["alpha_wolf","wallstreet_wolf","technologia"];

// Agent status colour comes from STAT in tokens.js — the same table the rest of
// the app reads. This was a second, hand-written copy that had already drifted:
// it painted `idle` with ink4 while STAT.idle is ink3, so the same agent in the
// same state wore two different greys depending on which component drew it.
// Read at call time, never captured: STAT is mutated in place by applyMode().
const dotColor = (s) => (STAT[s] || STAT.idle).c;

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
  const dialogRef = useDialog(true, onClose);
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 998, background: "rgba(0,0,0,.45)", display: "grid", placeItems: "center" }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="om-shortcuts-title" tabIndex={-1}
        onClick={(e) => e.stopPropagation()} style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 16, padding: "24px 28px", width: 380, boxShadow: "0 20px 60px rgba(0,0,0,.2)" }}>
        <h2 id="om-shortcuts-title" style={{ fontSize: 16, fontWeight: 700, marginBottom: 16, marginTop: 0 }}>Keyboard shortcuts</h2>
        {/* Generated from ORDERED_TABS rather than hand-listed: the range drifted
            to "1 – 9" while three tabs exist, and an "R — Refresh active agent"
            row survived here long after the binding it documented was gone. */}
        {[
          ["⌘ K", "Command palette"],
          [`1 – ${ORDERED_TABS.length}`, "Jump to tab by number"],
          ["W", "Go to Alpha Wolf"],
          ["S", "Go to Settings"],
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
        background: active ? T.sideActive : "transparent",
        border: `1px solid ${active ? T.sideLine : "transparent"}`,
        color: active ? col : T.sideInk2, fontSize: 15, fontWeight: 700, cursor: "pointer",
        transition: "all .14s", position: "relative", borderRadius: 3,
      }}>
        {AGENT_BADGE[item.id]
          ? <Badge code={AGENT_BADGE[item.id]} color={active ? col : col + "cc"} size={22} />
          : item.glyph}
        {badge && <div style={{ position: "absolute", top: 4, right: 4 }}>{badge}</div>}
      </button>
    );
  }
  return (
    <button onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left",
      cursor: "pointer", padding: "7px 9px", borderRadius: 3,
      border: `1px solid ${active ? T.sideLine : "transparent"}`,
      background: active ? T.sideActive : "transparent",
      boxShadow: "none",
      font: "inherit", transition: "all .14s", marginBottom: 1,
    }}
      onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = T.sideBtn; }}
      onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}>
      {AGENT_BADGE[item.id]
        ? <Badge code={AGENT_BADGE[item.id]} color={active ? col : col + "cc"} size={22} title={item.label} />
        : <span style={{ width: 22, height: 22, borderRadius: 2, background: col + (active ? "1f" : "12"), color: col, display: "grid", placeItems: "center", fontSize: 12, fontWeight: 700, flex: "0 0 auto" }}>{item.glyph}</span>}
      <span style={{ fontSize: 13, fontWeight: active ? 700 : 500, color: active ? T.sideInk : T.sideInk2, flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</span>
      {badge}
    </button>
  );
}

// ── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({ tab, setTab, sys, online, collapsed: collapsedProp, setCollapsed, mobile, open, onClose }) {
  // The width breakpoints that force the rail on a narrow desktop window also
  // fire on a phone, where the drawer wants full labels — so the drawer wins.
  const collapsed = mobile ? false : collapsedProp;
  const agents = sys?.agents || [];
  const statusOf = (id) => agents.find((a) => a.id === id)?.status;
  const [alphaOpen, setAlphaOpen] = useState(true);
  // A drawer costs a deliberate tap to open, so it always shows labels — the
  // icon rail exists to buy back horizontal space, and a drawer isn't competing
  // for any. `collapsed` is ignored here rather than fought with.
  const W = mobile ? 272 : collapsed ? 58 : 232;

  // Off-canvas: out of the flex flow entirely, so `main` gets the full width
  // instead of the 58px rail it would otherwise keep reserving on a 390px phone.
  const shell = mobile
    ? { position: "fixed", top: 0, left: 0, zIndex: 60, width: W, flex: "none",
        transform: open ? "none" : "translateX(-101%)",
        // visibility is in the transition on purpose: it keeps the drawer in the
        // tab order only while it is on screen, but still holds it visible for
        // the full 240ms of the slide-out instead of blinking away at frame one.
        transition: "transform .24s cubic-bezier(.22,.7,.2,1), visibility .24s",
        boxShadow: open ? "0 0 60px rgba(0,0,0,.35)" : "none",
        visibility: open ? "visible" : "hidden",
        // Whole shorthand, not just paddingBottom: React warns (and can drop the
        // longhand on a rerender) when a style object mixes `padding` with
        // `paddingBottom`, and the base style below sets the shorthand.
        padding: "14px 10px calc(14px + env(safe-area-inset-bottom))" }
    : { position: "sticky", top: 0, width: W, flex: `0 0 ${W}px`,
        transition: "width .22s ease, flex .22s ease" };

  const sectionLabel = (text) => collapsed ? null : (
    <div style={{ fontSize: 10, fontWeight: 700, color: T.sideMuted, textTransform: "uppercase", letterSpacing: 0.9, fontStretch: "88%", padding: "0 10px 6px", marginTop: 14 }}>{text}</div>
  );

  const renderNav = (it, keyPrefix = "") => {
    const st = statusOf(it.id);
    const badge = !collapsed && st ? (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        {st && <Dot c={dotColor(st)} s={6} />}
      </span>
    ) : null;
    return <NavItem key={keyPrefix + it.id} item={it} active={tab === it.id} onClick={() => setTab(it.id)} badge={badge} collapsed={collapsed} />;
  };

  // Intentional layout animation, and the one place we keep it. Collapsing the
  // sidebar reflows the main column and swaps labels for glyphs, so there is no
  // transform equivalent. It is user-initiated and runs once for 220ms, unlike
  // the progress bars, which re-animated on every poll and now use scaleX.
  return (
    <nav aria-label="Agents" aria-hidden={mobile && !open ? "true" : undefined}
      style={{ background: T.sidebar, borderRight: `1px solid ${T.sideLine}`, display: "flex", flexDirection: "column",
        padding: collapsed ? "14px 8px" : "14px 10px",
        // dvh, not vh: on iOS Safari 100vh is the height with the URL bar
        // *hidden*, so a 100vh drawer runs its Settings row under the toolbar.
        minHeight: "100vh", height: "100dvh",
        overflowY: "auto", overflowX: "hidden", ...shell }}>

      {/* No brand block and no search button: the sidebar is the agent list and
          nothing else. Backend health moved to the footer dot (it was duplicated
          here), and the palette is still ⌘K — it never needed a button. Only the
          rail/drawer toggle survives, since collapsing has no other control. */}
      <div style={{ display: "flex", alignItems: "center", padding: collapsed ? "2px 0 8px" : "2px 4px 6px", justifyContent: collapsed ? "center" : "flex-end" }}>
        {/* Same slot, two jobs: rail toggle on a desktop, dismiss on a phone —
            where there is no rail to toggle to and the drawer needs a way out
            that isn't the backdrop. Sized up to a real touch target there. */}
        <button onClick={mobile ? onClose : () => setCollapsed(!collapsed)}
          aria-label={mobile ? "Close navigation" : collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={mobile ? "Close" : collapsed ? "Expand sidebar" : "Collapse sidebar"}
          style={{ width: mobile ? 34 : 22, height: mobile ? 34 : 22, borderRadius: mobile ? 9 : 6, background: T.sideBtn, border: `1px solid ${T.sideLine}`, cursor: "pointer", display: "grid", placeItems: "center", fontSize: mobile ? 14 : 11, color: T.sideInk2, flexShrink: 0 }}>
          {mobile ? "✕" : collapsed ? "▶" : "◀"}
        </button>
      </div>

      {/* Alpha Wolf — master agent (the header itself navigates) + its pack. */}
      {sectionLabel("Agents")}
      {!collapsed ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
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
      ) : (
        // The rail has no room for the indent rule or the disclosure toggle, so
        // the pack simply follows its master as a flat run of glyphs.
        <>
          {renderNav(ALPHA_MASTER)}
          {ALPHA_GROUP.map((it) => renderNav(it, "grp-"))}
        </>
      )}

      {/* Bottom — Settings pinned */}
      <div style={{ marginTop: "auto", paddingTop: 10, borderTop: `1px solid ${T.sideLine}` }}>
        <NavItem item={SETTINGS_ITEM} active={tab === "settings"} onClick={() => setTab("settings")} collapsed={collapsed} />
        <div style={{ padding: collapsed ? "8px 0" : "8px 4px 2px", fontSize: 10, color: T.sideMuted, fontFamily: T.mono, lineHeight: 1.6, textAlign: collapsed ? "center" : "left" }}>
          <Dot c={online ? T.green : T.amber} s={6} />
          {/* The API is same-origin now, so the port to show is this page's. */}
          {!collapsed && ` ${online ? "live" : "connecting…"} · ${window.location.port || "80"}`}
        </div>
      </div>
    </nav>
  );
}

// ── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  // Validate the persisted tab against the tabs that actually exist, so anyone
  // whose last session ended on a since-removed agent (options_flow,
  // earnings_cal, devdaily, cisco_pulse, orchestrator) doesn't reopen the app
  // onto a dead screen. Any unknown id falls back to Alpha Wolf, the landing tab.
  const [tab, setTab] = useState(() => {
    const t = localStorage.getItem("om_tab");
    return t && (t === "settings" || TABS[t]) ? t : "alpha_wolf";
  });
  const [mode, setMode]     = useState(() => localStorage.getItem("om_mode") || "light");
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("om_collapsed") === "1");
  const [cmdOpen, setCmdOpen]     = useState(false);
  const [helpOpen, setHelpOpen]   = useState(false);
  applyMode(mode);

  // Tiled beside a broker window, 232px of sidebar is a third of the workspace
  // and the labels cost more than they earn. Drop to the icon rail below this
  // width without touching the stored preference, so the labels come back when
  // the window widens. Expanding by hand while narrow overrides it.
  // Two thresholds. Below NARROW the rail is the default but you can override it
  // by expanding; below TIGHT the labels simply do not fit beside content, so the
  // rail is forced and the override is ignored until the window widens again.
  const narrow = useMediaQuery("(max-width: 1080px)");
  const tight  = useMediaQuery("(max-width: 780px)");
  // Third and last breakpoint. Below this a rail is no longer a saving — 58px
  // of a 390px screen is 15% of the viewport spent on navigation you are not
  // using — so the nav leaves the flow entirely and becomes a drawer.
  const mobile = useMediaQuery(MOBILE_Q);
  const [navOpen, setNavOpen] = useState(false);
  const [expandedByHand, setExpandedByHand] = useState(false);
  // A deliberate expand lasts until the next breakpoint change, then defers to
  // the layout again.
  useEffect(() => { setExpandedByHand(false); }, [narrow, tight]);
  const railed = collapsed || tight || (narrow && !expandedByHand);
  const setRailed = useCallback((v) => {
    setCollapsed(v);
    if (!v) setExpandedByHand(true);
  }, []);

  const { state: sys, online } = useSystemState();

  // Persist prefs
  useEffect(() => { localStorage.setItem("om_tab", tab); }, [tab]);
  useEffect(() => { localStorage.setItem("om_collapsed", collapsed ? "1" : "0"); }, [collapsed]);
  useEffect(() => {
    localStorage.setItem("om_mode", mode);
    document.body.style.background = T.bg;
    document.documentElement.style.colorScheme = T.mode;
    // Republish the few tokens CSS needs. The focus ring and skip link live in
    // index.css because :focus-visible cannot be expressed as an inline style,
    // so they read these vars rather than duplicating the palette.
    const root = document.documentElement.style;
    root.setProperty("--focus-ring", T.violet);
    root.setProperty("--focus-surface", T.card);
    root.setProperty("--focus-ink", T.ink);
  }, [mode]);

  const closeNav = useCallback(() => setNavOpen(false), []);
  const openNav = useCallback(() => setNavOpen(true), []);
  // Stable object: this sits above every tab, so a fresh identity each render
  // would invalidate the context for all of them on every poll of system state.
  const navCtx = useMemo(() => ({ mobile, openNav, goTab: setTab }), [mobile, openNav]);

  // Picking an agent is the drawer's whole purpose, so it dismisses itself on
  // arrival; and if the window grows back to desktop while it is open, the nav
  // returns to the flow and a stuck-open flag would re-show it on the next
  // shrink with no way to tell it had been left open.
  useEffect(() => { setNavOpen(false); }, [tab, mobile]);

  // Freeze the page behind the drawer — without this a swipe over the backdrop
  // scrolls the tab underneath while the nav sits still on top of it.
  useEffect(() => {
    document.body.classList.toggle("om-navlock", navOpen);
    return () => document.body.classList.remove("om-navlock");
  }, [navOpen]);

  // Stable identities: useDialog keys its focus effect on onClose, so an inline
  // arrow would re-run the effect on every render and keep stealing focus.
  const closeHelp = useCallback(() => setHelpOpen(false), []);
  const closeCmd = useCallback(() => setCmdOpen(false), []);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      // Never hijack typing — including rich-text/contenteditable surfaces.
      const el = document.activeElement;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el?.isContentEditable) return;

      // ⌘K is the only shortcut allowed to carry a modifier. Without the guard
      // below, ⌘S opened Settings *and* the browser's save dialog, and ⌘O
      // opened a file picker over the app.
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmdOpen(true); return; }
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      if (e.key === "Escape") { setCmdOpen(false); setHelpOpen(false); setNavOpen(false); return; }

      // A dialog owns the screen while it is open; single-key shortcuts must
      // not navigate the app behind it.
      if (document.querySelector('[role="dialog"]')) return;

      if (e.key === "?") { setHelpOpen(true); return; }
      if (e.key === "w" || e.key === "W") { setTab("alpha_wolf"); return; }
      if (e.key === "s" || e.key === "S") { setTab("settings"); return; }
      const num = parseInt(e.key);
      if (num >= 1 && num <= 9 && ORDERED_TABS[num - 1]) setTab(ORDERED_TABS[num - 1]);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const agent = sys?.agents?.find((a) => a.id === tab);
  let content;
  if (tab === "settings") {
    content = <Settings mode={mode} setMode={setMode} />;
  } else {
    const TabEl = TABS[tab];
    if (!TabEl) {
      // Reachable if an agent is removed while its tab is open. Recover rather
      // than leaving a dead end.
      content = (
        <div style={{ padding: 40 }}>
          <div style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 14, padding: "22px 26px", maxWidth: 560 }}>
            <div style={{ fontSize: 15, fontWeight: 800, marginBottom: 8 }}>That agent isn't available</div>
            <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.55, marginBottom: 14 }}>
              <span style={{ fontFamily: T.mono }}>{tab}</span> isn't one of the agents this platform runs any more.
            </div>
            <button type="button" onClick={() => setTab("alpha_wolf")}
              style={{ padding: "7px 16px", background: T.cardAlt, border: `1px solid ${T.line}`, borderRadius: 8, color: T.ink2, cursor: "pointer", fontSize: 12.5, fontFamily: T.sans, fontWeight: 600 }}>
              Go to Alpha Wolf
            </button>
          </div>
        </div>
      );
    }
    else content = <TabEl key={tab} status={agent?.status} agentError={agent?.error} progress={agent?.progress} result={agent?.result} />;
  }

  return (
    <NavContext.Provider value={navCtx}>
      <a className="om-skip" href="#om-main">Skip to content</a>
      <Aurora />
      <div style={{ display: "flex", minHeight: "100vh", background: "transparent", fontFamily: T.sans, color: T.ink, position: "relative", zIndex: 1 }}>
      <Sidebar
        tab={tab} setTab={setTab}
        sys={sys} online={online}
        collapsed={railed} setCollapsed={setRailed}
        mobile={mobile} open={navOpen} onClose={closeNav}
      />
      {/* Backdrop. Kept mounted and faded so the drawer's 240ms slide-out isn't
          left hanging over a page that already looks dismissed. */}
      {mobile && (
        <div onClick={closeNav} aria-hidden="true" style={{
          position: "fixed", inset: 0, zIndex: 55, background: "rgba(8,10,14,.5)",
          opacity: navOpen ? 1 : 0, visibility: navOpen ? "visible" : "hidden",
          transition: "opacity .24s ease, visibility .24s",
        }} />
      )}
      {/* tabIndex -1 so the skip link can move focus here; the sidebar is ~14
          tab stops deep before the content begins. */}
      <main id="om-main" tabIndex={-1} style={{ flex: 1, minWidth: 0, outline: "none" }}>
        <TabErrorBoundary key={tab}><div className="om-fade">{content}</div></TabErrorBoundary>
      </main>

      {/* Per-agent AI assistant — every agent tab gets an Ask-Lufi panel */}
      {TABS[tab] && <AskLufi key={"ai-" + tab} agentId={tab} agentName={agent?.n || tab} color={AGENT_COLOR[tab]} mobile={mobile} />}

      <CommandPalette open={cmdOpen} onClose={closeCmd} onNavigate={(id) => { setTab(id); setCmdOpen(false); }} sys={sys} />
      {helpOpen && <ShortcutHelp onClose={closeHelp} />}
      </div>
    </NavContext.Provider>
  );
}
