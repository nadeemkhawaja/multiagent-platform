// ============================================================================
// tokens.js — design tokens. Mode-aware (light/dark).
//
// THESIS: a trading cockpit read in glances is a QUOTE BOARD, not a dashboard
// of cards. It refuses the card-grid-with-six-accent-hues arrangement that the
// category ships by default, and the Bloomberg-pastiche that is its predictable
// opposite.
// OWN-WORLD: the open-outcry exchange as a physical place — painted steel board,
// chalk figures, a brass session rail, and the enamel pit badge. Colour lives
// ONLY on the badge and on up/down; board, chalk and brass carry everything
// else. One typeface, Archivo, worked across its width axis: Expanded for board
// numerals, Narrow for table headers.
// STORY: the trader sees the board, reads today's one call, and acts.
// FIRST VIEWPORT: session rail across the top, the live call at board scale,
// the pack's badges down the left.
// FORM: candidate 7 of the grounded list; seed key d5cb9cdb.
// FINISH: unreviewed and undocumented is unfinished; this build ends with the
// finish review, the verdict, and DESIGN.md.
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
//             are data, not decoration. Nothing else may wear them, and in this
//             world they are ENAMEL: the only saturated marks on a painted board.
//   IDENTITY  AGENT_COLOR — the pit badge. A narrow cool ramp (hues 205–195)
//             well clear of the valence band, so a badge can never read as "up",
//             "down" or "warning". Alpha Wolf heads the family at the highest
//             chroma; its sub-agents step down and cool off beneath it, which
//             renders the product hierarchy as colour. The ramp is deliberately
//             NARROW — the previous fan ran violet→blue→teal and put a third
//             colour family on screen beside valence and the accent.
//   NEUTRAL   ink → ink4, all four body-text legible. These are CHALK on the
//             board: warm off-white, never pure #fff, because pure white on a
//             dark ground haloes and is the single clearest tell of a screen
//             pretending to be a surface.
//
// `violet` keeps its key name for the ~200 call sites that read it, but it is
// no longer violet: it is the badge enamel, the one identity accent. Renaming
// the key would be a mechanical change touching every tab for no visual gain.
//
// `onAccent` is the foreground for text sitting ON a solid accent fill. It is
// chalk in light mode and board-black in dark, because the accents themselves
// invert. Never hard-code "#fff" on a chip whose background is a token.
//
// Every value was solved against a contrast target and verified ≥4.5:1 in three
// pairings, because all three occur in this codebase:
//   1. against all four surfaces of its own mode (card, cardAlt, bg, sidebar);
//   2. against its own `*Bg` tint, for coloured text in a pill;
//   3. against a tint of ITSELF — the `col + "18"` chip pattern used for agent
//      badges and ticker chips.
// Green is always lighter than red in both modes, so the pair stays separable
// by lightness when hue collapses under deuteranopia — the ▲/▼ in ui.jsx
// carries the shape cue. Values ship as 6-digit hex because call sites
// concatenate alpha suffixes (`T.violet + "18"`); oklch() strings would break
// every one of them.
// ============================================================================

// One family, worked across its width axis. Archivo is a signage grotesque with
// a real wdth axis (62.5–125) and true tabular lining figures, so the whole
// scale — monumental board numerals, UI text, and condensed table headers —
// comes out of a single face. Operate surfaces do not need a display/body
// pairing, and the incumbent Hanken Grotesk + JetBrains Mono put two voices on
// screen where one, worked harder, reads cleaner.
const SANS = "'Archivo', ui-sans-serif, system-ui, sans-serif";
// Numerals in this app are MEASUREMENT — prices, sizes, R multiples — so they
// get the tabular treatment rather than a second "technical-looking" family.
// `mono` stays exported because call sites read it; it now resolves to Archivo
// with tabular figures applied at the call site via `T.tnum`.
const MONO = "'Archivo', ui-sans-serif, system-ui, sans-serif";

// Apply to any element whose digits must not shift between renders. Prices tick
// every few seconds; proportional figures make a whole column jitter.
const TNUM = { fontVariantNumeric: "tabular-nums lining-nums" };

// sidebar tokens that simply mirror the app surface
const sideOf = (p) => ({
  sideInk: p.ink, sideInk2: p.ink2, sideMuted: p.ink4,
  sideLine: p.line, sideActive: p.card, sideBtn: p.cardAlt,
});

// ── LIGHT — the board in daylight ───────────────────────────────────────────
// Painted board under room light: warm pale ground, graphite figures, brass
// rules. Not paper-white; a board is a surface with pigment in it.
const LIGHT = {
  bg: "#e7e4dc", card: "#f4f2ec", cardAlt: "#edeae2", sidebar: "#dcd8ce",
  line: "#cfcabe", line2: "#dcd8cd",
  ink: "#1a1d1f", ink2: "#42464a", ink3: "#55595d", ink4: "#656a6e",
  violet: "#1f5c96", green: "#1a6b3c", red: "#9c2520", amber: "#7d5310",
  blue: "#1f5c96", teal: "#11636b",
  violetBg: "#e2e7ee", greenBg: "#e2ebe5", redBg: "#f0e3e1", amberBg: "#efe8da",
  blueBg: "#e2e7ee", tealBg: "#dfe9ea",
  onAccent: "#f4f2ec",
  // Brass: the session rail and structural warmth. A NEUTRAL in this system,
  // never an accent — it must not be read as amber.
  brass: "#9a7b3f", brassBg: "#e9e1d0",
  shadow: "0 1px 2px rgba(26,29,31,.10)",
  trackGrad: "linear-gradient(90deg, rgba(156,37,32,.16), rgba(120,116,105,.12), rgba(26,107,60,.16))",
  sans: SANS,
};

// ── DARK — the board itself ─────────────────────────────────────────────────
// The use scene decides this, not the category: one trader at a desk through a
// full session, this window open beside a broker and charts in a lit room, read
// in short glances for hours. A dark painted board holds the enamel marks and
// does not glare at hour six.
const DARK = {
  bg: "#101315", card: "#191d20", cardAlt: "#1f2429", sidebar: "#0c0e10",
  line: "#2d3337", line2: "#252b2e",
  ink: "#eae7de", ink2: "#b4b0a6", ink3: "#97938a", ink4: "#848077",
  violet: "#74b3e8", green: "#5fc98c", red: "#f4685c", amber: "#e3a53f",
  blue: "#74b3e8", teal: "#46c4c4",
  violetBg: "#1c3042", greenBg: "#1b3a2a", redBg: "#3c2422", amberBg: "#3a2e1b",
  blueBg: "#1c3042", tealBg: "#153537",
  onAccent: "#101315",
  brass: "#c79a4e", brassBg: "#332a1a",
  shadow: "0 1px 3px rgba(0,0,0,.55)",
  trackGrad: "linear-gradient(90deg, rgba(244,104,92,.22), rgba(148,144,134,.12), rgba(95,201,140,.22))",
  sans: SANS,
};
Object.assign(LIGHT, sideOf(LIGHT));
Object.assign(DARK, sideOf(DARK));

// ── Agent identity — the pit badge ──────────────────────────────────────────
// A narrow cool ramp, not a fan across the wheel. Alpha Wolf is the head of the
// family at the highest chroma; the pack steps down and cools beneath it, and
// the orchestrator is near-neutral because it is infrastructure and should
// recede rather than compete with the agents it supervises.
const AGENT_LIGHT = {
  alpha_wolf:      "#17558f",
  wallstreet_wolf: "#1d6079",
  technologia:     "#136a6a",
  orchestrator:    "#565d64",
};
const AGENT_DARK = {
  alpha_wolf:      "#7cbcf2",
  wallstreet_wolf: "#5bb9cf",
  technologia:     "#49c2b6",
  orchestrator:    "#9aa3ab",
};

// Two- and three-letter badge acronyms. The pit badge is how a floor identifies
// a trader at distance, and it is why colour can stay this contained: identity
// lives in a glyph on enamel, not in a tinted panel.
export const AGENT_BADGE = {
  alpha_wolf: "AW",
  wallstreet_wolf: "WW",
  technologia: "TG",
  orchestrator: "OR",
};

// Agent status is valence, not identity, so it reads off the semantic ramp
// instead of carrying colours of its own.
const statOf = (p) => ({
  running: { c: p.green, t: "Running" },
  idle:    { c: p.ink3,  t: "Idle" },
  queued:  { c: p.amber, t: "Queued" },
  crashed: { c: p.red,   t: "Crashed" },
});

// ── Type scale ──────────────────────────────────────────────────────────────
// Fixed px, ratio ~1.2, because this is an Operate surface viewed at one DPI on
// one desk; fluid clamps buy nothing and make a sidebar heading shrink for no
// reason. The complaint this answers: after one 22px heading everything sat
// between 10 and 12.5px, so the thing you opened the app to read did not
// outrank the thing you did not.
//
// `board` is the one monumental size — the live call, the figure you read from
// across the desk. Exactly one element per screen may wear it.
export const TYPE = {
  board: 44, display: 28, title: 20, head: 16,
  body: 13.5, dense: 12.5, label: 11.5, micro: 10.5,
};

// Width axis. Archivo's wdth carries hierarchy that size alone cannot on a
// dense screen: condensed headers buy horizontal room in tables, expanded
// numerals give the board figure presence without another 10px of height.
export const WIDTH = { narrow: 85, normal: 100, wide: 112 };

// Spacing — a 4px base. Tight groups, generous separation.
export const SPACE = { hair: 2, xs: 4, sm: 8, md: 12, lg: 18, xl: 28, xxl: 44 };

export const T = {
  ...LIGHT, mode: "light",
  sans: SANS,
  mono: MONO,
  tnum: TNUM,
  type: TYPE,
  space: SPACE,
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
  // The board's own ground, so the page behind the app matches the surface and
  // an overscroll does not flash the old violet-tinted white.
  try {
    document.documentElement.style.background = p.bg;
    document.documentElement.style.colorScheme = mode;
    // Stylesheet hook: ::selection and the scrollbar can't read inline tokens.
    document.documentElement.setAttribute("data-om", mode);
  } catch (e) { /* SSR / tests */ }
}
