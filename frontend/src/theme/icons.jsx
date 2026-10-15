// ============================================================================
// icons.jsx — the app's one icon system.
//
// Drawn, not typed. The incumbent used emoji (🐺 🃏 📊 🛑 ⚡ ⚠ 🎯 ⏰ ◭) as
// iconography, which puts a different illustrator's artwork — in a different
// style, weight and colour, rendered differently per OS — beside hand-tuned
// type and a measured palette. On the board, marks are stencilled: one stroke
// weight, one terminal, one optical size, and they inherit `currentColor` so a
// mark in an enamel-red alert is enamel red without a second definition.
//
// Geometry: 24-unit grid, 1.6 stroke, round caps and joins. Anything added here
// stays on that grid; a 2px icon beside a 1.6px icon is the tell that an icon
// set grew by accident rather than by design.
// ============================================================================
import { T } from "./tokens";

const PATHS = {
  // The pack. A wolf head reduced to the two ears and muzzle that survive at
  // 14px — the literal animal does not.
  wolf: <path d="M4 5l3.2 2.2M20 5l-3.2 2.2M4 5l1 7.2a7 7 0 0 0 14 0L20 5M9.5 11.5h.01M14.5 11.5h.01M12 15l-1.4 1.4M12 15l1.4 1.4" />,
  // Technologia: the auction distribution — a profile built of stacked rows.
  profile: <><path d="M4 6h8M4 10h13M4 14h10M4 18h6" /></>,
  // A trade card.
  card: <><rect x="4" y="4" width="16" height="16" rx="1.5" /><path d="M8.5 9.5h3M8.5 13h7" /></>,
  // Performance: a closed-trade journal as plotted bars.
  bars: <><path d="M4 20V11M9.3 20V5M14.7 20v-6M20 20V8" /></>,
  // Execution.
  bolt: <path d="M13.5 3L5.5 13.5h5L10 21l8.5-10.5h-5L13.5 3z" />,
  // A stop: the octagon, the one shape that means this and nothing else.
  stop: <path d="M8.6 3.5h6.8l4.1 4.1v6.8l-4.1 4.1H8.6l-4.1-4.1V7.6z" />,
  // A target taken.
  target: <><circle cx="12" cy="12" r="7.5" /><circle cx="12" cy="12" r="3" /></>,
  // Rotation out of a position.
  rotate: <><path d="M20 12a8 8 0 1 1-2.6-5.9" /><path d="M20 4v4.5h-4.5" /></>,
  // Warning. Not the emoji triangle: same silhouette, this set's stroke.
  warn: <><path d="M12 4.2L21 19.5H3z" /><path d="M12 10v4M12 17h.01" /></>,
  clock: <><circle cx="12" cy="12" r="8.2" /><path d="M12 7.2V12l3.2 2" /></>,
  check: <path d="M4.5 12.5l4.8 4.8L19.5 7" />,
  // Confluence: independent reads converging on one level.
  converge: <><path d="M3.5 5.5L12 12M3.5 18.5L12 12M12 12h8.5" /></>,
  settings: <><circle cx="12" cy="12" r="3.1" /><path d="M12 2.8v2.6M12 18.6v2.6M21.2 12h-2.6M5.4 12H2.8M18.5 5.5l-1.8 1.8M7.3 16.7l-1.8 1.8M18.5 18.5l-1.8-1.8M7.3 7.3L5.5 5.5" /></>,
};

/**
 * One stencil. `size` is the box; the stroke stays 1.6 at every size on
 * purpose, because scaling the stroke with the box is what makes an icon set
 * look like three icon sets.
 */
export function Ico({ name, size = 15, color, style, title }) {
  const d = PATHS[name];
  if (!d) return null;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color || "currentColor"} strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden={title ? undefined : "true"}
      role={title ? "img" : undefined}
      style={{ flex: "0 0 auto", display: "block", ...style }}>
      {title && <title>{title}</title>}
      {d}
    </svg>
  );
}

/**
 * The pit badge: a two-letter acronym on enamel. This is how a floor identifies
 * a trader at distance, and it is why colour can stay as contained as it is in
 * this palette — identity lives in a glyph on a 20px chip rather than in a
 * tinted panel, a coloured border and a matching heading.
 */
export function Badge({ code, color, size = 20, title }) {
  return (
    <span title={title} style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: size, height: size, flex: "0 0 auto",
      background: color, color: T.onAccent, borderRadius: 2,
      fontFamily: T.sans, fontSize: size * 0.46, fontWeight: 800,
      fontStretch: "88%", letterSpacing: 0.3, lineHeight: 1,
    }}>{code}</span>
  );
}
