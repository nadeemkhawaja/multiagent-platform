// ============================================================================
// ui.jsx — shared primitives (ported from the Claude design bundle).
// All components read the mutable token object `T` at render time.
// ============================================================================
import { useState, useEffect, useRef, useCallback, useContext, createContext, useSyncExternalStore } from "react";
import { T } from "./tokens";

// ── Layout context ──────────────────────────────────────────────────────────
// Below MOBILE the sidebar leaves the flow and becomes an off-canvas drawer, so
// something on the page has to own the button that opens it. TabHeader is the
// only chrome every tab renders, so App publishes the drawer handle here and
// TabHeader picks it up — rather than threading a prop through twelve tabs that
// have no other reason to know the nav exists.
export const MOBILE_Q = "(max-width: 720px)";
// `goTab` lets one tab hand the reader to another — Technologia's cards point
// at Alpha Wolf, which is the only place a trade is taken.
export const NavContext = createContext({ mobile: false, openNav: null, goTab: null });
export const useNav = () => useContext(NavContext);

// Media query as reactive state, read fresh on every notification rather than
// cached from the event payload. It listens to the query's own `change` *and*
// to resize, because a viewport change does not always dispatch `change` — and
// when it doesn't, cached state leaves the layout stuck at the old breakpoint.
export function useMediaQuery(query) {
  const subscribe = useCallback((notify) => {
    const mq = window.matchMedia(query);
    mq.addEventListener("change", notify);
    window.addEventListener("resize", notify);
    return () => { mq.removeEventListener("change", notify); window.removeEventListener("resize", notify); };
  }, [query]);
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false);
}

export const Dot = ({ c, s = 7 }) => (
  <i style={{ width: s, height: s, borderRadius: s, background: c, display: "inline-block", flex: "0 0 auto" }} />
);

// ── Responsive grid tracks ──────────────────────────────────────────────────
// Holds exactly `n` columns while there is room, then drops to fewer as the
// container narrows, and never exceeds `n`. A plain `repeat(auto-fit, minmax(X,
// 1fr))` would happily render *more* columns than intended on a wide screen;
// clamping the track to at least an n-th of the container prevents that, and
// `min(100%, …)` stops it overflowing when the container is narrower than `min`.
//
// This exists because the layout is authored as inline styles, which cannot
// carry a media or container query — the whole responsive behaviour has to fit
// in a single track value.
export const gridCols = (n, gap = 12, min = 260) =>
  `repeat(auto-fit, minmax(min(100%, max(${min}px, (100% - ${(n - 1) * gap}px) / ${n})), 1fr))`;

// ── Dialog behaviour ────────────────────────────────────────────────────────
// Returns a ref to spread onto the dialog surface. Handles the three things a
// modal owes a keyboard user and none of this app's modals did: Escape closes,
// focus moves in on open and returns to the trigger on close, and Tab stays
// inside — otherwise you tab straight out into the page behind the overlay.
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useDialog(open, onClose) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const restoreTo = document.activeElement;
    const visible = () => Array.from(ref.current?.querySelectorAll(FOCUSABLE) || [])
      .filter((el) => el.offsetParent !== null);
    // Focus the dialog itself when it has no controls yet (e.g. still loading).
    (visible()[0] || ref.current)?.focus?.();

    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onClose(); return; }
      if (e.key !== "Tab" || !ref.current) return;
      const f = visible();
      if (!f.length) { e.preventDefault(); return; }
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      else if (!ref.current.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    };
    // Capture, so the dialog resolves Escape before the app's window-level
    // shortcut handler sees it.
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      try { restoreTo?.focus?.(); } catch { /* trigger unmounted */ }
    };
  }, [open, onClose]);
  return ref;
}

// `interactive` adds a hover-lift + accent glow (for clickable cards).
export function Card({ children, style, pad = 12, interactive, className = "", ...rest }) {
  return (
    // maxWidth/minWidth are the floor for every card in the app: several are
    // laid out with alignSelf:"flex-start" so they hug their content, and a card
    // that hugs a 14-column table will happily grow past a phone viewport and
    // take the whole page sideways with it.
    <div {...rest} className={(interactive ? "om-lift " : "") + className}
      style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 14, padding: pad,
        boxShadow: T.shadow, maxWidth: "100%", minWidth: 0, ...style }}>
      {children}
    </div>
  );
}

export function Pill({ children, c = T.ink2, bg, bd, mono, style, title }) {
  return (
    <span title={title} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, color: c, background: bg || T.line2, border: bd ? `1px solid ${bd}` : "none", padding: "5px 10px", borderRadius: 8, fontFamily: mono ? T.mono : T.sans, whiteSpace: "nowrap", ...style }}>
      {children}
    </span>
  );
}

export function Btn({ children, onClick, kind = "default", size = "md", style, disabled }) {
  const base = {
    fontFamily: T.sans, fontWeight: 600, cursor: disabled ? "not-allowed" : "pointer", border: "1px solid transparent",
    borderRadius: 9, display: "inline-flex", alignItems: "center", gap: 7, transition: "all .14s ease",
    fontSize: size === "sm" ? 12.5 : 13.5, padding: size === "sm" ? "6px 11px" : "9px 15px", opacity: disabled ? 0.55 : 1,
    whiteSpace: "nowrap", flexShrink: 0,
  };
  const kinds = {
    default: { background: T.card, borderColor: T.line, color: T.ink },
    primary: { background: T.violet, color: T.onAccent },
    ghost: { background: "transparent", color: T.ink2 },
    danger: { background: T.redBg, color: T.red, borderColor: T.red + "55" },
    soft: { background: T.violetBg, color: T.violet },
  };
  // `disabled` was previously only a fade plus a dropped handler: the button
  // stayed focusable and was announced as available, and a keyboard user could
  // tab to a dead control. Setting the real attribute also makes the browser
  // skip it in the tab order and exempts it from the contrast floor.
  return <button type="button" disabled={disabled} aria-disabled={disabled || undefined}
    onClick={disabled ? undefined : onClick} style={{ ...base, ...kinds[kind], ...style }}
    onMouseEnter={(e) => !disabled && (e.currentTarget.style.filter = "brightness(0.97)")}
    onMouseLeave={(e) => (e.currentTarget.style.filter = "none")}>{children}</button>;
}

// Section headings are real <h2>s: every tab is a section list under the tab's
// own <h1>, so this is what gives the app a document outline at all.
export function SectionTitle({ children, right, sub }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 6 }}>
      <div>
        <h2 style={{ fontSize: 13, fontWeight: 700, letterSpacing: -0.2, margin: 0 }}>{children}</h2>
        {sub && <div style={{ fontSize: 11, color: T.ink3, marginTop: 1 }}>{sub}</div>}
      </div>
      {right}
    </div>
  );
}

export function TabHeader({ icon, color, title, sub, actions }) {
  // Frosted-glass sticky header: content scrolls under it over the aurora.
  // The BAR spans full width (so the glass and its rule reach both edges) but
  // its contents sit in the same centred measure as the body below, otherwise
  // the title and actions would drift away from the columns they belong to.
  const { mobile, openNav } = useNav();
  return (
    <div style={{ borderBottom: `1px solid ${T.line}`, background: T.card + "c2", backdropFilter: "blur(14px) saturate(1.4)", WebkitBackdropFilter: "blur(14px) saturate(1.4)", position: "sticky", top: 0, zIndex: 5 }}>
    <div className="om-measure" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", rowGap: 8, padding: "10px var(--om-gutter)" }}>
      {/* minWidth:0 and a shrinkable title block: this was flexShrink:0, so a long
          subtitle (Alpha Wolf's runs to a full sentence) could not wrap and pushed
          the page sideways once the window was narrow. */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0, flex: "1 1 auto" }}>
        {/* The only way back to the nav once it is off-canvas, so it leads the
            header and is a full 38px touch target rather than an icon-sized one. */}
        {mobile && openNav && (
          <button type="button" onClick={openNav} aria-label="Open navigation"
            style={{ width: 38, height: 38, flex: "0 0 auto", borderRadius: 10, border: `1px solid ${T.line}`,
              background: T.cardAlt, color: T.ink2, fontSize: 15, cursor: "pointer", display: "grid", placeItems: "center" }}>☰</button>
        )}
        {/* The glyph repeats the title beside it, so it is decorative to AT. On a
            phone it is pure ornament competing with the menu button for the same
            edge, so it goes. */}
        {icon && !mobile && <div aria-hidden="true" style={{ width: 30, height: 30, borderRadius: 9, background: color + "1a", color, display: "grid", placeItems: "center", fontSize: 15, fontWeight: 700, boxShadow: `0 4px 14px ${color}26`, flex: "0 0 auto" }}>{icon}</div>}
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontSize: 15, fontWeight: 700, letterSpacing: -0.3, margin: 0 }}>{title}</h1>
          {/* The subtitles are scene-setting ("Yahoo Finance · live watchlist ·
              gainers / losers"), and at phone width they wrap to three lines and
              push the actual data below the fold. */}
          {sub && !mobile && <div style={{ fontSize: 11, color: T.ink3, marginTop: 1 }}>{sub}</div>}
        </div>
      </div>
      {/* Every tab hangs 3–5 controls here. Wrapped at phone width they stack
          three rows deep and push the first real number ~270px down an 844px
          screen, so on mobile they become one horizontally-scrollable toolbar
          instead — no control is dropped, the header just stops growing. */}
      <div className={mobile ? "om-noscrollbar" : undefined} style={{ display: "flex", alignItems: "center", gap: 9,
        ...(mobile
          ? { flexWrap: "nowrap", overflowX: "auto", width: "100%", justifyContent: "flex-start",
              paddingBottom: 2, overscrollBehaviorX: "contain", scrollbarWidth: "none" }
          : { flexWrap: "wrap", justifyContent: "flex-end" }) }}>{actions}</div>
    </div>
    </div>
  );
}

export const Delta = ({ v, suffix = "%", style }) => (
  <span style={{ fontFamily: T.mono, fontWeight: 600, color: v >= 0 ? T.green : T.red, ...style }}>
    {v >= 0 ? "▲" : "▼"} {Math.abs(v).toFixed(2)}{suffix}
  </span>
);

// ── DataTable ────────────────────────────────────────────────────────────────
// The app's one dense-data surface. Three deliberate choices, applied here once
// so every agent tab reads the same way instead of re-deciding per tab:
//
//  · width:auto in a flex wrapper — the table takes its CONTENT width and sits
//    left. Stretching a numeric grid across a 1000px card only pushes related
//    figures apart; scanning is what these tables are for.
//  · full gridlines — at this density the eye needs rules to hold a row across
//    many columns and to track one field down many rows.
//  · sortable headers — click to sort, click again to flip. Text columns sort
//    A-Z (by name), signed-number columns sort by magnitude, which is what
//    "sort bullish/bearish" means for a change %, bias score or sentiment.
//
// Column: { key, label, align, mono, width, title, sort, render, headStyle }
// `sort` is an accessor (row) => value; omit it to make a column unsortable.
// `fill` opts a table into filling its card instead of hugging its content. Use
// it ONLY where the card itself is width-capped (see the CardRow groups in Wolf
// and Compass): the point is to close the gap between a 480px table and the card
// beside it, not to spread six columns across a 2000px monitor.
export function DataTable({ columns, rows = [], rowKey, rowTint, defaultSort, defaultDir = "desc",
                            empty = "Nothing to show.", maxHeight, fill }) {
  const [sortKey, setSortKey] = useState(defaultSort ?? null);
  const [dir, setDir] = useState(defaultDir);
  const rule = `1px solid ${T.line}`;

  const active = columns.find((c) => c.key === sortKey && c.sort);
  const view = active
    ? [...rows].sort((a, b) => {
        const av = active.sort(a), bv = active.sort(b);
        // Blanks sink to the bottom in BOTH directions — a missing reading is
        // not "the smallest", and letting it lead an ascending sort buries the
        // rows that actually have data.
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        const r = typeof av === "string" || typeof bv === "string"
          ? String(av).localeCompare(String(bv), undefined, { numeric: true })
          : av - bv;
        return dir === "asc" ? r : -r;
      })
    : rows;

  const onSort = (c) => {
    if (!c.sort) return;
    if (c.key === sortKey) setDir(dir === "asc" ? "desc" : "asc");
    else { setSortKey(c.key); setDir(c.defaultDir || "desc"); }
  };

  // Contiguous columns sharing a `group` become one spanning caption.
  const bands = [];
  for (const c of columns) {
    const last = bands[bands.length - 1];
    if (c.group && last?.group === c.group) last.cols.push(c);
    else bands.push({ group: c.group || null, cols: [c] });
  }
  const hasGroups = bands.some((b) => b.group);

  const headBase = {
    padding: "3px 7px", fontSize: 9, fontWeight: 700, color: T.ink4,
    textTransform: "uppercase", letterSpacing: 0.3, borderBottom: rule, borderRight: rule,
    whiteSpace: "nowrap", userSelect: "none",
    position: maxHeight ? "sticky" : "static", top: 0, background: T.card, zIndex: 1,
  };
  const renderTh = (c, { rowSpan, sub } = {}) => {
    const on = c.key === sortKey && c.sort;
    return (
      <th key={c.key} rowSpan={rowSpan}
        title={c.title || (c.sort ? `Sort by ${c.label || c.key}` : undefined)}
        onClick={() => onSort(c)}
        aria-sort={on ? (dir === "asc" ? "ascending" : "descending") : undefined}
        style={{ ...headBase, color: on ? T.ink2 : T.ink4,
          textAlign: sub ? "center" : (c.align || "left"),
          fontSize: sub ? 8 : 9, padding: sub ? "0 3px 3px" : "3px 7px",
          cursor: c.sort ? "pointer" : "default", ...c.headStyle }}>
        {c.label}
        {on && <span style={{ marginLeft: 3, fontSize: 8 }}>{dir === "asc" ? "▲" : "▼"}</span>}
      </th>
    );
  };

  if (!rows?.length) return <div style={{ fontSize: 12, color: T.ink4, padding: "6px 0" }}>{empty}</div>;

  return (
    // A dense grid must keep its columns aligned to stay readable, so it scrolls
    // inside its own card rather than reflowing or pushing the page sideways —
    // overscroll-behavior stops that scroll chaining into the page on a phone,
    // where a horizontal flick at the end of a table used to trigger back-swipe.
    <div style={{ overflowX: "auto", overflowY: maxHeight ? "auto" : "visible",
      maxHeight, maxWidth: "100%", marginTop: 6, display: "flex", alignItems: "flex-start",
      overscrollBehaviorX: "contain", WebkitOverflowScrolling: "touch",
      ...(fill ? { flex: 1, minWidth: 0 } : null) }}>
      <table style={{ width: fill ? "100%" : "auto", borderCollapse: "collapse", fontSize: 11.5, border: rule }}>
        <thead>
          <tr>
            {bands.map((b, bi) => (b.group
              // A band of related columns (e.g. Technologia's five confluence
              // signals) gets a spanning caption; everything else spans both
              // header rows so the two tiers stay flush.
              ? <th key={`g${bi}`} colSpan={b.cols.length} style={{ ...headBase, textAlign: "center",
                  borderBottom: hasGroups ? "none" : rule, cursor: "default" }}>{b.group}</th>
              : renderTh(b.cols[0], { rowSpan: hasGroups ? 2 : undefined })))}
          </tr>
          {hasGroups && (
            <tr>
              {bands.filter((b) => b.group).flatMap((b) =>
                b.cols.map((c) => renderTh(c, { sub: true })))}
            </tr>
          )}
        </thead>
        <tbody>
          {view.map((r, i) => {
            const tint = rowTint?.(r);
            return (
              <tr key={rowKey ? rowKey(r) : i}
                style={{ borderBottom: rule, background: tint ? tint + "0c" : "transparent",
                  boxShadow: tint ? `inset 2px 0 0 ${tint}` : "none" }}>
                {columns.map((c) => (
                  <td key={c.key} style={{ padding: "3px 7px", borderRight: rule,
                    textAlign: c.align || "left", whiteSpace: "nowrap",
                    fontFamily: c.mono ? T.mono : T.sans, width: c.width,
                    ...(c.cellStyle ? c.cellStyle(r) : null) }}>
                    {c.render ? c.render(r, i) : r[c.key]}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── CardRow ──────────────────────────────────────────────────────────────────
// Sections whose natural width is a table, not the page. Stacked one per line
// they left ~1500px of a 2560px monitor empty beside a 480px table; side by side
// they fill the row and wrap to the next line as the window narrows.
//
// Each child carries `flex: 1 1 <basis>` plus a max — the max is what keeps this
// from becoming the thing it replaced, a handful of columns smeared across a
// wide screen. Below the sum of the maxes nothing changes at all, which is why
// the windowed layout is untouched.
export function CardRow({ children, gap = 10, style }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap, alignItems: "flex-start", ...style }}>
      {children}
    </div>
  );
}
// Spread onto a Card inside a CardRow. `max` is the point past which extra width
// stops helping the table read and starts hurting it.
export const grow = (basis, max) => ({ flex: `1 1 ${basis}px`, maxWidth: max, minWidth: 0 });

export function Segmented({ options, value, onChange, full }) {
  return (
    <div style={{ display: "flex", gap: 3, padding: 3, background: T.mode === "dark" ? "#0b0d11" : "#e9eaee", borderRadius: 9, width: full ? "100%" : "auto" }}>
      {options.map((o) => {
        const on = o.v === value;
        return (
          <button key={o.v} onClick={() => onChange(o.v)} style={{
            flex: full ? 1 : "0 0 auto", cursor: "pointer", border: "none", borderRadius: 7, padding: "5px 9px",
            background: on ? T.card : "transparent", color: on ? T.ink : T.ink3, fontWeight: on ? 700 : 600,
            fontSize: 11.5, fontFamily: T.sans, boxShadow: on ? T.shadow : "none", transition: "all .14s",
            display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 5,
          }}>{o.icon}{o.label}</button>
        );
      })}
    </div>
  );
}

export function Appearance({ mode, setMode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 7, paddingLeft: 2 }}>Appearance</div>
      <Segmented full value={mode} onChange={setMode} options={[{ v: "light", label: "Light", icon: "☀" }, { v: "dark", label: "Dark", icon: "☾" }]} />
    </div>
  );
}
