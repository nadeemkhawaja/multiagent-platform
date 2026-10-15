// ============================================================================
// CommandPalette.jsx — Cmd+K / Ctrl+K overlay
// Searches tabs, watchlist tickers and recent orchestrator events.
// ============================================================================
import { useState, useEffect, useRef, useMemo } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { useAgentData } from "../state/api";
import { useDialog } from "../theme/ui";

// Every id here must exist in App's TABS map. "home" used to sit at the top and
// routed to a tab that no longer exists, so picking the first entry in the
// palette landed on "Tab not found"; Alpha Wolf — the master agent — was missing
// from the list entirely and so was unreachable by ⌘K.
const NAV_ITEMS = [
  { id: "alpha_wolf",     label: "Alpha Wolf",         glyph: "🐺", type: "tab", desc: "Master strategist · live decisions & paper trades" },
  { id: "wallstreet_wolf",label: "Wallstreet Wolf",    glyph: "$",  type: "tab", desc: "Tape, regime bias & key levels" },
  { id: "technologia",    label: "Technologia",        glyph: "◭",  type: "tab", desc: "VP/VWAP/MFI divergence signals" },
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

  useEffect(() => {
    if (open) { setQuery(""); setIdx(0); setTimeout(() => inputRef.current?.focus(), 30); }
  }, [open]);

  // The palette used to hand-roll a window-level Escape listener and nothing
  // else — no focus trap, and no focus returned to whatever opened it. Every
  // other overlay in the app (shortcut help, email preview) already goes
  // through useDialog; this is the same behaviour from the same place.
  const dialogRef = useDialog(open, onClose);

  // Build search corpus
  const corpus = useMemo(() => {
    const items = [...NAV_ITEMS];

    // Watchlist tickers. This read `wolfData.wolf.watchlist` with `.ticker` and
    // `.pct` — a shape the agent has never returned — so ticker search silently
    // matched nothing no matter what you typed. The real payload is
    // `market_data.watchlist` with `symbol` / `change_pct`.
    (wolfData?.market_data?.watchlist || []).forEach((w) => {
      const pct = Number(w.change_pct) || 0;
      items.push({
        id: `wolf_${w.symbol}`, label: w.symbol, glyph: "$", type: "ticker",
        desc: `${w.name || ""} · ${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`,
        action: () => onNavigate("wallstreet_wolf"),
      });
    });

    // Recent events
    (sys?.events || []).slice(0, 8).forEach((e, i) => {
      items.push({
        id: `ev_${i}`, label: e.m, glyph: "·", type: "event",
        desc: e.t, action: () => onNavigate("alpha_wolf"),
      });
    });

    return items;
  }, [wolfData, sys, onNavigate]);

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

  // Capitol Tracker is retired, so "politician" is no longer a result type here.
  const TYPE_LABEL = { tab: "Page", ticker: "Ticker", event: "Event" };
  const TYPE_COL   = { tab: T.violet, ticker: T.green, event: T.ink3 };

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 999, background: "rgba(0,0,0,.45)", display: "grid", placeItems: "start center", paddingTop: "14vh" }}>
      {/* Combobox + listbox: the input keeps DOM focus while the arrow keys move
          a virtual cursor, which aria-activedescendant is what announces. */}
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Command palette" tabIndex={-1}
        onClick={(e) => e.stopPropagation()} style={{ width: "min(580px, 92vw)", background: T.card, border: `1px solid ${T.line}`, borderRadius: 16, boxShadow: "0 20px 60px rgba(0,0,0,.25)", overflow: "hidden" }}>
        {/* Search input */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", borderBottom: `1px solid ${T.line2}` }}>
          <span aria-hidden="true" style={{ fontSize: 16, color: T.ink4 }}>⌘</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setIdx(0); }}
            onKeyDown={handleKey}
            placeholder="Jump to a tab, search a ticker or a recent event…"
            aria-label="Search pages, tickers and recent events"
            role="combobox"
            aria-expanded={results.length > 0}
            aria-controls="om-palette-list"
            aria-autocomplete="list"
            aria-activedescendant={results[safeIdx] ? `om-palette-opt-${results[safeIdx].id}` : undefined}
            style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 15, color: T.ink, fontFamily: T.sans }}
          />
          {query && <button type="button" aria-label="Clear search" onClick={() => setQuery("")} style={{ fontSize: 13, color: T.ink4, background: "none", border: "none", cursor: "pointer" }}>✕</button>}
          <span aria-hidden="true" style={{ fontSize: 11, color: T.ink4, background: T.cardAlt, border: `1px solid ${T.line}`, borderRadius: 5, padding: "2px 7px", fontFamily: T.mono }}>esc</span>
        </div>

        {/* Results */}
        <div ref={listRef} id="om-palette-list" role="listbox" aria-label="Results" style={{ maxHeight: 380, overflowY: "auto" }}>
          {results.length === 0 && (
            <div style={{ padding: "28px 18px", textAlign: "center", fontSize: 13, color: T.ink4 }}>No results for "{query}"</div>
          )}
          {results.map((item, i) => {
            const col = AGENT_COLOR[item.id] || TYPE_COL[item.type] || T.violet;
            const active = i === safeIdx;
            return (
              <div key={item.id} id={`om-palette-opt-${item.id}`} role="option" aria-selected={active}
                onClick={() => pick(item)} onMouseEnter={() => setIdx(i)}
                style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 18px", cursor: "pointer", background: active ? T.violetBg : "transparent", transition: "background .1s" }}>
                <div aria-hidden="true" style={{ width: 30, height: 30, borderRadius: 8, background: col + "18", color: col, display: "grid", placeItems: "center", fontSize: 14, fontWeight: 700, flex: "0 0 auto" }}>
                  {item.glyph}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, color: T.ink, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</div>
                  {/* ink2, not ink4: the active row sits on the violet tint, where
                      ink4 falls to 3.5:1 and even ink3 only reaches 4.44. Size and
                      weight already separate this from the label above it. */}
                  {item.desc && <div style={{ fontSize: 11.5, color: T.ink2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.desc}</div>}
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
