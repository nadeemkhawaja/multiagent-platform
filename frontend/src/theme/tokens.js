// ============================================================================
// tokens.js — design tokens. Theme- and mode-aware.
// T is a single mutable object; applyTheme() rewrites its surface tokens in
// place, so every component that reads T at render time re-skins on toggle.
// Themes ported from design-mockups/: Polished (1), Terminal (2), SaaS (3).
// `side*` tokens style the sidebar independently of the app surface (the SaaS
// theme pairs a dark sidebar with a light app); most themes mirror them.
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
  ink: "#16181d", ink2: "#4b5360", ink3: "#8a909c", ink4: "#aeb4bf",
  violet: "#7c5cf6", green: "#16a34a", red: "#e5484d", amber: "#f59e0b", blue: "#2f6feb", teal: "#0d9488",
  violetBg: "#f1edfe", greenBg: "#eafaf0", redBg: "#fdeced", amberBg: "#fef5e7",
  shadow: "0 1px 3px rgba(20,24,40,.06)",
  trackGrad: "linear-gradient(90deg, rgba(229,72,77,.16), rgba(148,163,184,.12), rgba(22,163,74,.16))",
  sans: SANS,
};
const DARK = {
  bg: "#0d0f13", card: "#15181e", cardAlt: "#1b1f27", sidebar: "#101217",
  line: "#272b34", line2: "#23272f",
  ink: "#eef1f5", ink2: "#a7afbd", ink3: "#7a8492", ink4: "#586069",
  violet: "#a78bfa", green: "#34d399", red: "#f87171", amber: "#fbbf24", blue: "#60a5fa", teal: "#2dd4bf",
  violetBg: "rgba(124,92,246,.20)", greenBg: "rgba(52,211,153,.15)", redBg: "rgba(248,113,113,.15)", amberBg: "rgba(251,191,36,.15)",
  shadow: "0 1px 3px rgba(0,0,0,.5)",
  trackGrad: "linear-gradient(90deg, rgba(248,113,113,.22), rgba(148,163,184,.14), rgba(52,211,153,.22))",
  sans: SANS,
};
Object.assign(LIGHT, sideOf(LIGHT));
Object.assign(DARK, sideOf(DARK));

// design-mockups/1-polished.html — current light family, white sidebar, softer shadow
const POLISHED_LIGHT = { ...LIGHT, sidebar: "#ffffff", shadow: "0 1px 3px rgba(20,24,40,.04)" };
Object.assign(POLISHED_LIGHT, sideOf(POLISHED_LIGHT),
  { sideLine: "#ececf0", sideActive: "#f6f7f9", sideBtn: "#fafbfc" });

// design-mockups/2-terminal.html — always-dark, monospace, hacker green
const TERMINAL = {
  bg: "#0a0c10", card: "#11141b", cardAlt: "#161a23", sidebar: "#0a0c10",
  line: "#232936", line2: "#1b212c",
  ink: "#e6e9f0", ink2: "#9aa3b5", ink3: "#6b7384", ink4: "#454c5c",
  violet: "#a78bfa", green: "#22c55e", red: "#ef4444", amber: "#fbbf24", blue: "#60a5fa", teal: "#2dd4bf",
  violetBg: "rgba(167,139,250,.16)", greenBg: "rgba(34,197,94,.14)", redBg: "rgba(239,68,68,.14)", amberBg: "rgba(251,191,36,.14)",
  shadow: "none",
  trackGrad: "linear-gradient(90deg, rgba(239,68,68,.22), rgba(107,115,132,.14), rgba(34,197,94,.22))",
  sans: MONO,
};
Object.assign(TERMINAL, sideOf(TERMINAL));

// design-mockups/3-saas.html — light app, dark sidebar, cool grays
const SAAS_SIDE = {
  sideInk: "#f5f6f8", sideInk2: "#c6cad3", sideMuted: "#8b919d",
  sideLine: "rgba(255,255,255,.13)", sideActive: "rgba(255,255,255,.10)", sideBtn: "rgba(255,255,255,.07)",
};
const SAAS_LIGHT = {
  ...LIGHT, bg: "#f5f6fb", sidebar: "#16181d", line: "#eceef3",
  ink2: "#5b6472", ink3: "#9aa1ad", ink4: "#c6cad3",
  ...SAAS_SIDE,
};
const SAAS_DARK = { ...DARK, sidebar: "#0a0c10", ...SAAS_SIDE };

export const THEMES = {
  aria:     { label: "Aria",     light: LIGHT,          dark: DARK },
  atlas:    { label: "Atlas",    light: LIGHT,          dark: DARK },
  polished: { label: "Polished", light: POLISHED_LIGHT, dark: DARK },
  terminal: { label: "Terminal", light: TERMINAL,       dark: TERMINAL, alwaysDark: true },
  saas:     { label: "SaaS",     light: SAAS_LIGHT,     dark: SAAS_DARK },
};

export const T = {
  ...LIGHT, mode: "light", theme: "aria",
  sans: SANS,
  mono: MONO,
};

export function applyTheme(theme, mode) {
  const name = THEMES[theme] ? theme : "aria";
  const t = THEMES[name];
  const effMode = t.alwaysDark || mode === "dark" ? "dark" : "light";
  Object.assign(T, t[effMode], { mode: effMode, theme: name });
}

export function applyMode(m) {
  applyTheme(T.theme || "aria", m);
}

// agent accent palette (keyed by backend agent ids)
export const AGENT_COLOR = {
  orchestrator:    "#7c5cf6",
  ai_times:        "#e5484d",
  mailman:         "#2f6feb",
  wallstreet_wolf: "#16a34a",
  compass:         "#f59e0b",
  devdaily:        "#6366f1",
  strategy_scout:  "#0ea5e9",
  capitol_tracker: "#dc2626",
  morning_brief:   "#f59e0b",
  options_flow:    "#7c5cf6",
  earnings_cal:    "#16a34a",
  cisco_pulse:     "#0d9488",
  alpha_wolf:      "#7c3aed",
};

export const STAT = {
  running: { c: "#1aa64b", t: "Running" },
  idle: { c: "#9aa1ad", t: "Idle" },
  queued: { c: "#f59e0b", t: "Queued" },
  crashed: { c: "#ef5350", t: "Crashed" },
};
