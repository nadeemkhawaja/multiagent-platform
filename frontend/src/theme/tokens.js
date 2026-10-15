// ============================================================================
// tokens.js — design tokens. Mode-aware (light/dark).
//
// T, AGENT_COLOR and STAT are single mutable objects; applyMode() rewrites them
// in place, so every component that reads them at render time re-skins on
// toggle. Never copy a value out of them at module scope — the copy freezes in
// whichever mode happened to be active at import time.
// `side*` tokens style the sidebar independently of the app surface.
//
// Colour system — three disjoint roles, so a colour never means two things:
//
//   VALENCE   green / red / amber. Market direction, P&L, agent health. These
//             are data, not decoration. Nothing else may wear them.
//   IDENTITY  AGENT_COLOR, drawn from hues 196–347 only. Deliberately excludes
//             the valence band, so an agent badge can never read as "up",
//             "down" or "warning". Alpha Wolf heads the family at the highest
//             chroma in the app; its trading sub-agents fan out beneath it,
//             which renders the product hierarchy as colour.
//   NEUTRAL   ink → ink4. All four tiers are body-text legible; ink4 alone
//             carries ~150 text nodes, so it is a readable tier, not a wash.
//
// `onAccent` is the foreground for text sitting ON a solid accent fill. It is
// white in light mode and near-black in dark, because the accents themselves
// invert: white on dark-mode green is 1.9:1. Never hard-code "#fff" on a chip
// whose background is a token.
//
// Every value was solved in OKLCH against a contrast target, then verified
// ≥4.5:1 in three pairings, because all three occur in this codebase:
//   1. against all four surfaces of its own mode (card, cardAlt, bg, sidebar);
//   2. against its own `*Bg` tint, for coloured text in a pill;
//   3. against a tint of ITSELF — the `col + "18"` chip pattern used for agent
//      badges and ticker chips. This is the binding constraint in light mode
//      and the reason the light accents sit darker than they first appear.
// Lightness alternates between neighbouring agents so the blue-cyan stretch of
// the identity fan stays separable; hue alone collapses at these lightnesses.
// Green is always lighter than red in both modes, so the pair stays separable
// by lightness when hue collapses under deuteranopia — the ▲/▼ in ui.jsx
// carries the shape cue. Values ship as 6-digit hex because call sites
// concatenate alpha suffixes (`T.violet + "18"`); oklch() strings would break
// every one of them.
// ============================================================================
const SANS = "'Hanken Grotesk', sans-serif";
const MONO = "'JetBrains Mono', monospace";

// sidebar tokens that simply mirror the app surface
const sideOf = (p) => ({
  sideInk: p.ink, sideInk2: p.ink2, sideMuted: p.ink4,
  sideLine: p.line, sideActive: p.card, sideBtn: p.cardAlt,
});

const LIGHT = {
  bg: "#f6f7f9", card: "#ffffff", cardAlt: "#fafbfc", sidebar: "#f1f1f3",
  line: "#ececf0", line2: "#f1f2f5",
  ink: "#191d22", ink2: "#454a50", ink3: "#595e64", ink4: "#676c72",
  violet: "#6a4bbc", green: "#007232", red: "#9e1618", amber: "#885700", blue: "#005b9f", teal: "#006d6e",
  violetBg: "#f3f1fa", greenBg: "#ebf4ef", redBg: "#f7eced", amberBg: "#f5f2eb",
  blueBg: "#ebf2f7", tealBg: "#ebf3f3",
  onAccent: "#ffffff",
  shadow: "0 1px 3px rgba(20,24,40,.06)",
  trackGrad: "linear-gradient(90deg, rgba(167,34,32,.16), rgba(148,163,184,.12), rgba(0,127,56,.16))",
  sans: SANS,
};
const DARK = {
  bg: "#0d0f13", card: "#15181e", cardAlt: "#1b1f27", sidebar: "#101217",
  line: "#272b34", line2: "#23272f",
  ink: "#e7ecf4", ink2: "#afb5bc", ink3: "#959aa1", ink4: "#83888f",
  violet: "#b19dff", green: "#6acf83", red: "#f46b60", amber: "#feb244", blue: "#61b0ff", teal: "#49c8c8",
  violetBg: "#323148", greenBg: "#253a31", redBg: "#3e272a", amberBg: "#403425",
  blueBg: "#233448", tealBg: "#1f393d",
  onAccent: "#0f1216",
  shadow: "0 1px 3px rgba(0,0,0,.5)",
  trackGrad: "linear-gradient(90deg, rgba(244,107,96,.22), rgba(148,163,184,.14), rgba(106,207,131,.22))",
  sans: SANS,
};
Object.assign(LIGHT, sideOf(LIGHT));
Object.assign(DARK, sideOf(DARK));

// ── Agent identity (keyed by backend agent ids) ──────────────────────────────
// Listed as the visual family rather than the sidebar order: Alpha Wolf as the
// head, then its pack fanning violet → blue → cyan, then the orchestrator —
// near-neutral, because it is infrastructure and should recede rather than
// compete with the agents it supervises. It has no tab of its own; the colour
// still keys its rows in the event log and its status dot.
const AGENT_LIGHT = {
  alpha_wolf:      "#8730cc",
  wallstreet_wolf: "#5357b7",
  technologia:     "#006c7b",
  orchestrator:    "#4e5868",
};
const AGENT_DARK = {
  alpha_wolf:      "#c793ff",
  wallstreet_wolf: "#98a1ff",
  technologia:     "#22b8d1",
  orchestrator:    "#a0aabd",
};

// Agent status is valence, not identity, so it reads off the semantic ramp
// instead of carrying colours of its own.
const statOf = (p) => ({
  running: { c: p.green, t: "Running" },
  idle:    { c: p.ink3,  t: "Idle" },
  queued:  { c: p.amber, t: "Queued" },
  crashed: { c: p.red,   t: "Crashed" },
});

export const T = {
  ...LIGHT, mode: "light",
  sans: SANS,
  mono: MONO,
};

// Mutable like T — mutated in place by applyMode(), never reassigned, so the
// modules that imported these bindings keep seeing the current mode.
export const AGENT_COLOR = { ...AGENT_LIGHT };

export const STAT = { ...statOf(LIGHT) };

export function applyMode(m) {
  const mode = m === "dark" ? "dark" : "light";
  const p = mode === "dark" ? DARK : LIGHT;
  Object.assign(T, p, { mode });
  Object.assign(AGENT_COLOR, mode === "dark" ? AGENT_DARK : AGENT_LIGHT);
  Object.assign(STAT, statOf(p));
}
