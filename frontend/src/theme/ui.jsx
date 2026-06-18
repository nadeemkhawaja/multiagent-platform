// ============================================================================
// ui.jsx — shared primitives (ported from the Claude design bundle).
// All components read the mutable token object `T` at render time.
// ============================================================================
import { useState, useEffect, useRef } from "react";
import { T, STAT } from "./tokens";

export const Dot = ({ c, s = 7 }) => (
  <i style={{ width: s, height: s, borderRadius: s, background: c, display: "inline-block", flex: "0 0 auto" }} />
);

// Soft "breathing" status dot — used for live/running indicators.
export const LiveDot = ({ c, s = 7 }) => (
  <i style={{ width: s, height: s, borderRadius: s, background: c, color: c, display: "inline-block",
    flex: "0 0 auto", boxShadow: `0 0 0 0 ${c}`, animation: "omLive 1.6s ease-in-out infinite" }} />
);

// `interactive` adds a hover-lift + accent glow (for clickable cards).
export function Card({ children, style, pad = 12, interactive, className = "", ...rest }) {
  return (
    <div {...rest} className={(interactive ? "om-lift " : "") + className}
      style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 14, padding: pad,
        boxShadow: T.shadow, ...style }}>
      {children}
    </div>
  );
}

// ── Motion helpers ───────────────────────────────────────────────────────────
// Smoothly tween a displayed number toward its latest target so live values
// feel alive instead of snapping. Honors prefers-reduced-motion (snaps).
export function useCountUp(target, { duration = 600, decimals = 0 } = {}) {
  const [val, setVal] = useState(target || 0);
  const fromRef = useRef(target || 0);
  const rafRef = useRef(0);
  useEffect(() => {
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const from = fromRef.current;
    const to = Number(target) || 0;
    if (reduce || from === to) { fromRef.current = to; setVal(to); return; }
    const t0 = performance.now();
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 3);              // easeOutCubic
      const cur = from + (to - from) * eased;
      setVal(cur);
      if (p < 1) rafRef.current = requestAnimationFrame(tick);
      else fromRef.current = to;
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, duration]);
  const f = Number(val).toFixed(decimals);
  return decimals ? f : Math.round(val).toString();
}

export function CountUp({ value, decimals = 0, duration = 600, ...rest }) {
  const shown = useCountUp(value, { duration, decimals });
  return <span {...rest}>{shown}</span>;
}

// Staggered entrance wrapper. `delay` in ms; `kind` picks the keyframe.
export function Reveal({ children, delay = 0, kind = "rise", style }) {
  const cls = kind === "pop" ? "om-pop" : kind === "fade" ? "om-fade" : "om-rise";
  return <div className={cls} style={{ animationDelay: `${delay}ms`, ...style }}>{children}</div>;
}

export function Pill({ children, c = T.ink2, bg, bd, mono, style }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, color: c, background: bg || T.line2, border: bd ? `1px solid ${bd}` : "none", padding: "5px 10px", borderRadius: 8, fontFamily: mono ? T.mono : T.sans, whiteSpace: "nowrap", ...style }}>
      {children}
    </span>
  );
}

export function StatusPill({ status }) {
  const s = STAT[status] || STAT.idle;
  return <Pill c={s.c} bg="transparent" style={{ padding: "2px 0" }}><Dot c={s.c} />{s.t}</Pill>;
}

export function Btn({ children, onClick, kind = "default", size = "md", style, disabled }) {
  const base = {
    fontFamily: T.sans, fontWeight: 600, cursor: disabled ? "not-allowed" : "pointer", border: "1px solid transparent",
    borderRadius: 9, display: "inline-flex", alignItems: "center", gap: 7, transition: "all .14s ease",
    fontSize: size === "sm" ? 12.5 : 13.5, padding: size === "sm" ? "6px 11px" : "9px 15px", opacity: disabled ? 0.55 : 1,
  };
  const kinds = {
    default: { background: T.card, borderColor: T.line, color: T.ink },
    primary: { background: T.violet, color: T.mode === "dark" ? "#1a1410" : "#fff" },
    ghost: { background: "transparent", color: T.ink2 },
    danger: { background: T.redBg, color: T.red, borderColor: T.red + "55" },
    soft: { background: T.violetBg, color: T.violet },
  };
  return <button onClick={disabled ? undefined : onClick} style={{ ...base, ...kinds[kind], ...style }}
    onMouseEnter={(e) => !disabled && (e.currentTarget.style.filter = "brightness(0.97)")}
    onMouseLeave={(e) => (e.currentTarget.style.filter = "none")}>{children}</button>;
}

export function Ring({ val, size = 64, stroke = 7, color = T.violet, track, children }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r;
  // Draw-in on mount: start empty, then animate to the real value via the
  // stroke-dashoffset transition below (one frame after mount).
  const [shown, setShown] = useState(0);
  useEffect(() => { const id = requestAnimationFrame(() => setShown(val)); return () => cancelAnimationFrame(id); }, [val]);
  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={track || T.line2} strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke}
          strokeDasharray={c} strokeDashoffset={c * (1 - shown / 100)} strokeLinecap="round"
          style={{ transition: "stroke-dashoffset .7s cubic-bezier(.22,.7,.2,1), stroke .3s ease" }} />
      </svg>
      {children && <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>{children}</div>}
    </div>
  );
}

export function Spark({ data, w = 96, h = 30, color = T.violet, fill = true, strokeW = 1.6 }) {
  if (!data || !data.length) return null;
  const max = Math.max(...data), min = Math.min(...data), rng = max - min || 1;
  const pts = data.map((v, i) => [(i / (data.length - 1 || 1)) * w, h - ((v - min) / rng) * (h - 4) - 2]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      {fill && <path d={d + ` L${w} ${h} L0 ${h} Z`} fill={color} opacity="0.10" />}
      <path d={d} fill="none" stroke={color} strokeWidth={strokeW} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SectionTitle({ children, right, sub }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 6 }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: -0.2 }}>{children}</div>
        {sub && <div style={{ fontSize: 11, color: T.ink3, marginTop: 1 }}>{sub}</div>}
      </div>
      {right}
    </div>
  );
}

export function TabHeader({ icon, color, title, sub, actions }) {
  // Frosted-glass sticky header: content scrolls under it over the aurora.
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 22px", borderBottom: `1px solid ${T.line}`, background: T.card + "c2", backdropFilter: "blur(14px) saturate(1.4)", WebkitBackdropFilter: "blur(14px) saturate(1.4)", position: "sticky", top: 0, zIndex: 5 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {icon && <div style={{ width: 30, height: 30, borderRadius: 9, background: color + "1a", color, display: "grid", placeItems: "center", fontSize: 15, fontWeight: 700, boxShadow: `0 4px 14px ${color}26` }}>{icon}</div>}
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: -0.3 }}>{title}</div>
          {sub && <div style={{ fontSize: 11, color: T.ink3, marginTop: 1 }}>{sub}</div>}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>{actions}</div>
    </div>
  );
}

export const Delta = ({ v, suffix = "%", style }) => (
  <span style={{ fontFamily: T.mono, fontWeight: 600, color: v >= 0 ? T.green : T.red, ...style }}>
    {v >= 0 ? "▲" : "▼"} {Math.abs(v).toFixed(2)}{suffix}
  </span>
);

export function StripedSlot({ h = 96, label, color = T.violet, glyph }) {
  return (
    <div style={{
      height: h, borderRadius: 10, position: "relative", overflow: "hidden", display: "grid", placeItems: "center",
      background: `repeating-linear-gradient(135deg, ${color}14 0 10px, ${color}08 10px 20px)`, border: `1px solid ${color}22`,
    }}>
      {glyph && <div style={{ fontSize: 22, color: color, opacity: 0.85 }}>{glyph}</div>}
      {label && <div style={{ position: "absolute", bottom: 6, left: 8, fontFamily: T.mono, fontSize: 9.5, color: color, opacity: 0.7 }}>{label}</div>}
    </div>
  );
}

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
