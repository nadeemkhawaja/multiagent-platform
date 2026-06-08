// ============================================================================
// CommandPalette.jsx — Cmd+K / Ctrl+K overlay
// Searches tabs, tickers, politicians, recent events
// ============================================================================
import { useState, useEffect, useRef, useMemo } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { useAgentData } from "../state/api";

const NAV_ITEMS = [
  { id: "home",            label: "Home",              glyph: "⌂",  type: "tab", desc: "Mission control dashboard" },
  { id: "orchestrator",   label: "Orchestrator",       glyph: "◇",  type: "tab", desc: "System resources & agent status" },
  { id: "ai_times",       label: "AI-Times",           glyph: "▶",  type: "tab", desc: "Latest AI videos & news" },
  { id: "mailman",        label: "Mailman",            glyph: "✉",  type: "tab", desc: "Gmail inbox classifier" },
  { id: "wallstreet_wolf",label: "Wallstreet Wolf",    glyph: "$",  type: "tab", desc: "Stock watchlist & market data" },
  { id: "compass",        label: "Wallstreet Compass", glyph: "◎",  type: "tab", desc: "Market signals & analysis" },
  { id: "devdaily",       label: "GitHub Trending",    glyph: "⌥",  type: "tab", desc: "Daily dev & AI repos" },
  { id: "strategy_scout", label: "Strategy Scout",     glyph: "✦",  type: "tab", desc: "Trading strategy research" },
  { id: "capitol_tracker",label: "Capitol Tracker",    glyph: "🏛", type: "tab", desc: "Congressional stock trades" },
  { id: "morning_brief",  label: "Morning Brief",      glyph: "☀",  type: "tab", desc: "Daily personalized digest" },
  { id: "options_flow",   label: "Options Flow",       glyph: "⚡", type: "tab", desc: "Unusual options activity" },
  { id: "earnings_cal",   label: "Earnings Calendar",  glyph: "📅", type: "tab", desc: "Upcoming earnings & expected moves" },
  { id: "cisco_pulse",    label: "Cisco Pulse",        glyph: "◈",  type: "tab", desc: "ACI/NDFC releases & CVEs" },
  { id: "settings",       label: "Settings",           glyph: "⚙",  type: "tab", desc: "Schedules & agent config" },
];

function score(item, q) {
  const s = q.toLowerCase();
  const l = item.label.toLowerCase();
  const d = (item.desc || "").toLowerCase();
  if (l === s) return 100;
  if (l.startsWith(s)) return 80;
  if (l.includes(s)) return 60;
  if (d.includes(s)) return 30;
  return 0;
}

export default function CommandPalette({ open, onClose, onNavigate, sys }) {
  const [query, setQuery] = useState("");
  const [idx, setIdx] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  const { data: wolfData } = useAgentData("wallstreet_wolf");
  const { data: capitolData } = useAgentData("capitol_tracker");

  useEffect(() => {
    if (open) { setQuery(""); setIdx(0); setTimeout(() => inputRef.current?.focus(), 30); }
  }, [open]);

  useEffect(() => {
    const handler = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // Build search corpus
  const corpus = useMemo(() => {
    const items = [...NAV_ITEMS];

    // Wolf tickers
    (wolfData?.wolf?.watchlist || []).forEach((w) => {
      items.push({
        id: `wolf_${w.ticker}`, label: w.ticker, glyph: "$", type: "ticker",
        desc: `${w.name || ""} · ${w.pct > 0 ? "+" : ""}${(w.pct || 0).toFixed(2)}%`,
        action: () => onNavigate("wallstreet_wolf"),
      });
    });

    // Capitol politicians
    const pols = [...new Set((capitolData?.tracker?.trades || []).map((t) => t.politician))];
    pols.forEach((pol) => {
      items.push({
        id: `pol_${pol}`, label: pol, glyph: "🏛", type: "politician",
        desc: "View in Capitol Tracker",
        action: () => onNavigate("capitol_tracker"),
      });
    });

    // Recent events
    (sys?.events || []).slice(0, 8).forEach((e, i) => {
      items.push({
        id: `ev_${i}`, label: e.m, glyph: "·", type: "event",
        desc: e.t, action: () => onNavigate("orchestrator"),
      });
    });

    return items;
  }, [wolfData, capitolData, sys, onNavigate]);

  const results = useMemo(() => {
    if (!query.trim()) return NAV_ITEMS.slice(0, 8);
    return corpus
      .map((item) => ({ ...item, _score: score(item, query) }))
      .filter((item) => item._score > 0)
      .sort((a, b) => b._score - a._score)
      .slice(0, 10);
  }, [query, corpus]);

  const safeIdx = Math.min(idx, results.length - 1);

  const handleKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, results.length - 1)); }
    if (e.key === "ArrowUp")   { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
    if (e.key === "Enter" && results[safeIdx]) { pick(results[safeIdx]); }
  };

  const pick = (item) => {
    if (item.action) item.action();
    else if (item.type === "tab") onNavigate(item.id);
    onClose();
  };

  if (!open) return null;

  const TYPE_LABEL = { tab: "Page", ticker: "Ticker", politician: "Politician", event: "Event" };
  const TYPE_COL   = { tab: T.violet, ticker: "#16a34a", politician: "#dc2626", event: T.ink3 };

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 999, background: "rgba(0,0,0,.45)", display: "grid", placeItems: "start center", paddingTop: "14vh" }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: "min(580px, 92vw)", background: T.card, border: `1px solid ${T.line}`, borderRadius: 16, boxShadow: "0 20px 60px rgba(0,0,0,.25)", overflow: "hidden" }}>
        {/* Search input */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", borderBottom: `1px solid ${T.line2}` }}>
          <span style={{ fontSize: 16, color: T.ink4 }}>⌘</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setIdx(0); }}
            onKeyDown={handleKey}
            placeholder="Jump to tab, search ticker or politician…"
            style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 15, color: T.ink, fontFamily: T.sans }}
          />
          {query && <button onClick={() => setQuery("")} style={{ fontSize: 13, color: T.ink4, background: "none", border: "none", cursor: "pointer" }}>✕</button>}
          <span style={{ fontSize: 11, color: T.ink4, background: T.cardAlt, border: `1px solid ${T.line}`, borderRadius: 5, padding: "2px 7px", fontFamily: T.mono }}>esc</span>
        </div>

        {/* Results */}
        <div ref={listRef} style={{ maxHeight: 380, overflowY: "auto" }}>
          {results.length === 0 && (
            <div style={{ padding: "28px 18px", textAlign: "center", fontSize: 13, color: T.ink4 }}>No results for "{query}"</div>
          )}
          {results.map((item, i) => {
            const col = AGENT_COLOR[item.id] || TYPE_COL[item.type] || T.violet;
            const active = i === safeIdx;
            return (
              <div key={item.id} onClick={() => pick(item)} onMouseEnter={() => setIdx(i)}
                style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 18px", cursor: "pointer", background: active ? T.violetBg : "transparent", transition: "background .1s" }}>
                <div style={{ width: 30, height: 30, borderRadius: 8, background: col + "18", color: col, display: "grid", placeItems: "center", fontSize: 14, fontWeight: 700, flex: "0 0 auto" }}>
                  {item.glyph}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, color: T.ink, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</div>
                  {item.desc && <div style={{ fontSize: 11.5, color: T.ink4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.desc}</div>}
                </div>
                <span style={{ fontSize: 10, fontWeight: 700, color: TYPE_COL[item.type] || T.ink4, background: (TYPE_COL[item.type] || T.ink4) + "18", padding: "2px 8px", borderRadius: 5, flexShrink: 0 }}>
                  {TYPE_LABEL[item.type] || item.type}
                </span>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div style={{ display: "flex", gap: 16, padding: "10px 18px", borderTop: `1px solid ${T.line2}`, fontSize: 11, color: T.ink4 }}>
          <span><span style={{ fontFamily: T.mono, background: T.cardAlt, padding: "1px 5px", borderRadius: 4 }}>↑↓</span> navigate</span>
          <span><span style={{ fontFamily: T.mono, background: T.cardAlt, padding: "1px 5px", borderRadius: 4 }}>↵</span> open</span>
          <span><span style={{ fontFamily: T.mono, background: T.cardAlt, padding: "1px 5px", borderRadius: 4 }}>esc</span> close</span>
          <span style={{ marginLeft: "auto" }}>{results.length} result{results.length !== 1 ? "s" : ""}</span>
        </div>
      </div>
    </div>
  );
}
