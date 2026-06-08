// ============================================================================
// icons.jsx — crisp 24×24 stroke icons (inherit color via currentColor).
// Used by the Orchestrator metric cards and elsewhere.
// ============================================================================

const base = (size, color, stroke) => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none",
  stroke: color, strokeWidth: stroke, strokeLinecap: "round", strokeLinejoin: "round",
  style: { display: "block" },
});

export function CpuIcon({ size = 18, color = "currentColor", stroke = 1.7 }) {
  return (
    <svg {...base(size, color, stroke)}>
      <rect x="6" y="6" width="12" height="12" rx="2.2" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
      <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
    </svg>
  );
}

export function RamIcon({ size = 18, color = "currentColor", stroke = 1.7 }) {
  return (
    <svg {...base(size, color, stroke)}>
      <rect x="2.5" y="8" width="19" height="9" rx="1.6" />
      <path d="M7 8v5M11 8v5M13 8v5M17 8v5" />
      <path d="M5 17v2.5M9 17v2.5M15 17v2.5M19 17v2.5" />
    </svg>
  );
}

export function DiskIcon({ size = 18, color = "currentColor", stroke = 1.7 }) {
  return (
    <svg {...base(size, color, stroke)}>
      <ellipse cx="12" cy="5.5" rx="8" ry="3" />
      <path d="M4 5.5v13c0 1.66 3.58 3 8 3s8-1.34 8-3v-13" />
      <path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3" />
    </svg>
  );
}

export function GpuIcon({ size = 18, color = "currentColor", stroke = 1.7 }) {
  return (
    <svg {...base(size, color, stroke)}>
      <rect x="2" y="7" width="20" height="10" rx="2.2" />
      <circle cx="8" cy="12" r="2.4" />
      <circle cx="15.5" cy="12" r="2.4" />
      <path d="M5 17v3M19 17v3" />
    </svg>
  );
}

export function NetIcon({ size = 18, color = "currentColor", stroke = 1.7 }) {
  return (
    <svg {...base(size, color, stroke)}>
      <path d="M7.5 18V6M7.5 6 4 9.5M7.5 6 11 9.5" />
      <path d="M16.5 6v12M16.5 18 13 14.5M16.5 18 20 14.5" />
    </svg>
  );
}

export function StrategyIcon({ size = 18, color = "currentColor", stroke = 1.7 }) {
  // candlestick + trend — used by Strategy Scout
  return (
    <svg {...base(size, color, stroke)}>
      <path d="M3 20h18" />
      <path d="M7 16V8M7 6v2m0 6v2" /><rect x="5.5" y="8" width="3" height="6" rx="0.8" />
      <path d="M16 14V7M16 5v2m0 7v2" /><rect x="14.5" y="7" width="3" height="7" rx="0.8" />
      <path d="M4 6l5-3 4 2 7-4" opacity="0.5" />
    </svg>
  );
}

export function ShieldIcon({ size = 18, color = "currentColor", stroke = 1.7 }) {
  return (
    <svg {...base(size, color, stroke)}>
      <path d="M12 3 5 6v5c0 4.4 3 7.6 7 9 4-1.4 7-4.6 7-9V6l-7-3Z" />
      <path d="M9.2 12.2 11 14l4-4.2" />
    </svg>
  );
}
