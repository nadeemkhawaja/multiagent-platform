// ============================================================================
// tokens.js — design tokens. Mode-aware (light / dark).
// T is a single mutable object; applyMode() rewrites its surface tokens in
// place, so every component that reads T at render time re-skins on toggle.
// (Ported from the Claude design bundle's ui.jsx.)
// ============================================================================
const LIGHT = {
  bg: "#f6f7f9", card: "#ffffff", cardAlt: "#fafbfc", sidebar: "#f1f1f3",
  line: "#ececf0", line2: "#f1f2f5",
  ink: "#16181d", ink2: "#4b5360", ink3: "#8a909c", ink4: "#aeb4bf",
  violet: "#7c5cf6", green: "#16a34a", red: "#e5484d", amber: "#f59e0b", blue: "#2f6feb", teal: "#0d9488",
  violetBg: "#f1edfe", greenBg: "#eafaf0", redBg: "#fdeced", amberBg: "#fef5e7",
  shadow: "0 1px 3px rgba(20,24,40,.06)",
  trackGrad: "linear-gradient(90deg, rgba(229,72,77,.16), rgba(148,163,184,.12), rgba(22,163,74,.16))",
};
const DARK = {
  bg: "#0d0f13", card: "#15181e", cardAlt: "#1b1f27", sidebar: "#101217",
  line: "#272b34", line2: "#23272f",
  ink: "#eef1f5", ink2: "#a7afbd", ink3: "#7a8492", ink4: "#586069",
  violet: "#a78bfa", green: "#34d399", red: "#f87171", amber: "#fbbf24", blue: "#60a5fa", teal: "#2dd4bf",
  violetBg: "rgba(124,92,246,.20)", greenBg: "rgba(52,211,153,.15)", redBg: "rgba(248,113,113,.15)", amberBg: "rgba(251,191,36,.15)",
  shadow: "0 1px 3px rgba(0,0,0,.5)",
  trackGrad: "linear-gradient(90deg, rgba(248,113,113,.22), rgba(148,163,184,.14), rgba(52,211,153,.22))",
};

export const T = {
  ...LIGHT, mode: "light",
  sans: "'Hanken Grotesk', sans-serif",
  mono: "'JetBrains Mono', monospace",
};

export function applyMode(m) {
  Object.assign(T, m === "dark" ? DARK : LIGHT, { mode: m });
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
