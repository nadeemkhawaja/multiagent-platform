// ============================================================================
// Orchestrator.jsx — Mission Control: agent overview + system gauges + ops
// Merged from Home + Orchestrator. Single entry point for the whole platform.
// ============================================================================
import { useState, useEffect, useRef } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, Dot, Ring, SectionTitle, TabHeader, Btn, CountUp, Reveal, LiveDot } from "../theme/ui";
import { CpuIcon, RamIcon, DiskIcon, GpuIcon, NetIcon } from "../theme/icons";
import { API_BASE, setDemoMode, spikeResource, crashAgent, getMetrics } from "../state/api";

// ── Live clock + US market session (computed client-side, always live) ───────
function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(id); }, []);
  return now;
}
function marketStatus(now) {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(now);
  const get = (t) => parts.find((p) => p.type === t)?.value;
  const wd = get("weekday");
  const mins = parseInt(get("hour")) * 60 + parseInt(get("minute"));
  const weekday = !["Sat", "Sun"].includes(wd);
  let session = "Closed", open = false;
  if (weekday) {
    if (mins >= 240 && mins < 570) session = "Pre-market";
    else if (mins >= 570 && mins < 960) { session = "Open"; open = true; }
    else if (mins >= 960 && mins < 1200) session = "After-hours";
  }
  return { open, session, et: `${get("hour")}:${get("minute")} ET` };
}
function greeting(now) {
  const h = now.getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function HeroKpi({ label, value, decimals = 0, suffix = "", color, accent, live }) {
  return (
    <div style={{ flex: "1 1 130px", minWidth: 120, padding: "9px 14px", borderRadius: 14, background: T.card + "99", border: `1px solid ${T.line}`, backdropFilter: "blur(6px)", WebkitBackdropFilter: "blur(6px)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10.5, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.6 }}>
        {live && <LiveDot c={color || T.green} s={6} />}{label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: -1, fontFamily: T.mono, color: color || T.ink, marginTop: 2, lineHeight: 1 }}>
        {typeof value === "number" ? <CountUp value={value} decimals={decimals} /> : value}{suffix}
      </div>
      {accent && <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 3 }}>{accent}</div>}
    </div>
  );
}

function CommandCenterHero({ s, online }) {
  const now = useClock();
  const mkt = marketStatus(now);
  const running = s.agents.filter((a) => a.status === "running").length;
  const total = s.agents.length || 0;
  const healthy = online && !s.alarm;
  const timeStr = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const dateStr = now.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  return (
    <Reveal kind="pop">
      <div style={{ position: "relative", overflow: "hidden", borderRadius: 16, padding: "15px 22px",
        background: `linear-gradient(135deg, ${T.violet}1f, ${T.blue}14 55%, ${T.teal}12)`,
        border: `1px solid ${T.violet}33`, boxShadow: T.shadow }}>
        <div style={{ position: "absolute", top: -40, right: -20, width: 220, height: 220, borderRadius: "50%", background: `radial-gradient(circle, ${T.violet}33, transparent 70%)`, filter: "blur(20px)", pointerEvents: "none" }} />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 18, flexWrap: "wrap", position: "relative" }}>
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: T.violet, letterSpacing: 0.3 }}>{greeting(now)} · Mission Control</div>
            <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: -0.5, marginTop: 3 }}>Multi-Agent Platform</div>
            <div style={{ fontSize: 12.5, color: T.ink3, marginTop: 4, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                {healthy ? <LiveDot c={T.green} s={7} /> : <Dot c={s.alarm ? T.red : T.amber} s={7} />}
                {healthy ? "All systems nominal" : s.alarm ? "Alarm active" : "Backend offline"}
              </span>
              <span style={{ color: T.ink4 }}>·</span>
              <span>{(s.llm && s.llm.model) || "Qwen3"} · local inference</span>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 30, fontWeight: 800, fontFamily: T.mono, letterSpacing: -1, lineHeight: 1 }}>{timeStr}</div>
            <div style={{ fontSize: 12, color: T.ink3, marginTop: 4 }}>{dateStr}</div>
            <div style={{ marginTop: 8, display: "inline-flex", alignItems: "center", gap: 7, padding: "4px 11px", borderRadius: 999,
              background: mkt.open ? T.green + "1c" : T.line2, border: `1px solid ${mkt.open ? T.green + "55" : T.line}` }}>
              {mkt.open ? <LiveDot c={T.green} s={6} /> : <Dot c={T.ink4} s={6} />}
              <span style={{ fontSize: 11.5, fontWeight: 700, color: mkt.open ? T.green : T.ink3 }}>US market · {mkt.session}</span>
              <span style={{ fontSize: 10.5, fontFamily: T.mono, color: T.ink4 }}>{mkt.et}</span>
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap", position: "relative" }}>
          <HeroKpi label="Agents running" value={running} color={running > 0 ? T.green : T.ink3} accent={`${total} managed`} live={running > 0} />
          <HeroKpi label="CPU load" value={Math.round(s.res?.cpu?.v || 0)} suffix="%" color={(s.res?.cpu?.v || 0) >= 85 ? T.red : T.blue} live />
          <HeroKpi label="Memory" value={Math.round(s.res?.ram?.v || 0)} suffix="%" color={(s.res?.ram?.v || 0) >= 88 ? T.red : T.violet} live />
          <HeroKpi label="Threads" value={s.threads || 0} color={T.teal} accent="active" />
          <HeroKpi label="Uptime" value={fmtUptime(s.uptimeS || 0)} color={T.ink} accent="since boot" />
        </div>
      </div>
    </Reveal>
  );
}

// ── All agents the Home overview knows about ─────────────────────────────────
const ALL_AGENTS = [
  { id: "ai_times",        label: "AI-Times",         glyph: "▶", desc: "Latest AI videos" },
  { id: "mailman",         label: "Mailman",           glyph: "✉", desc: "Inbox classifier" },
  { id: "wallstreet_wolf", label: "Wolf",              glyph: "$", desc: "Stock watchlist" },
  { id: "compass",         label: "Compass",           glyph: "◎", desc: "Market signals" },
  { id: "devdaily",        label: "GitHub Trending",   glyph: "⌥", desc: "Dev repos" },
  { id: "strategy_scout",  label: "Strategy Scout",    glyph: "✦", desc: "Trading research" },
  { id: "capitol_tracker", label: "Capitol Tracker",   glyph: "🏛", desc: "Congress trades" },
  { id: "morning_brief",   label: "Morning Brief",     glyph: "☀", desc: "Daily digest" },
  { id: "options_flow",    label: "Options Flow",      glyph: "⚡", desc: "Unusual activity" },
  { id: "earnings_cal",    label: "Earnings Calendar", glyph: "📅", desc: "Upcoming earnings" },
  { id: "cisco_pulse",     label: "Cisco Pulse",       glyph: "◈", desc: "NetOps intel" },
  { id: "alpha_wolf",      label: "Alpha Wolf",        glyph: "🐺", desc: "Master strategist" },
];
// The four graded agents — demo mode narrows the overview grid to just these.
const CORE_AGENTS = ["ai_times", "mailman", "wallstreet_wolf", "devdaily"];
const STATUS_BG = { running: "#eafaf0", idle: "transparent", crashed: "#fdeced", queued: "#fef5e7" };

// Compact clickable card used in the agent grid
function AgentOverviewCard({ agent, sysAgent, onNavigate }) {
  const col = AGENT_COLOR[agent.id] || T.violet;
  const status = sysAgent?.status || "idle";
  const sc = status === "running" ? T.green : status === "crashed" ? T.red : status === "queued" ? T.amber : T.ink4;
  return (
    <div onClick={() => onNavigate(agent.id)} className="om-lift"
      style={{ background: T.card, border: `1px solid ${status === "crashed" ? T.red + "55" : T.line}`, borderRadius: 12, padding: "12px 14px", cursor: "pointer", display: "flex", gap: 10, alignItems: "center", boxShadow: T.shadow }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = col + "66"; e.currentTarget.style.boxShadow = `0 8px 22px ${col}26`; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = status === "crashed" ? T.red + "55" : T.line; e.currentTarget.style.boxShadow = T.shadow; }}>
      <div style={{ width: 34, height: 34, borderRadius: 9, background: col + "18", color: col, display: "grid", placeItems: "center", fontSize: 15, flex: "0 0 auto" }}>{agent.glyph}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{agent.label}</div>
        <div style={{ fontSize: 10.5, color: T.ink4 }}>{sysAgent?.schedule || agent.desc}</div>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 9.5, fontWeight: 700, color: sc, background: STATUS_BG[status] || T.cardAlt, padding: "2px 7px", borderRadius: 5, border: `1px solid ${sc}22` }}>{status}</div>
      </div>
    </div>
  );
}

// ── Agent orchestration map (two master layers) ──────────────────────────────
// A static hierarchy diagram: the Orchestrator (top master) drives the general
// agents + Alpha Wolf, and Alpha Wolf (second-tier master) drives the finance
// pack. A link only animates while THAT agent is actually running — nothing
// pulses at idle, so motion always means real work.
const MESH_GENERAL = ["ai_times", "mailman", "devdaily", "cisco_pulse", "morning_brief"];
const MESH_FINANCE = ["wallstreet_wolf", "compass", "strategy_scout", "capitol_tracker", "options_flow", "earnings_cal"];
// Short labels so each node fits its slot without wrapping.
const MESH_LABEL = {
  ai_times: "AI-Times", mailman: "Mailman", devdaily: "GitHub", cisco_pulse: "Cisco", morning_brief: "Brief",
  wallstreet_wolf: "Wolf", compass: "Compass", strategy_scout: "Scout", capitol_tracker: "Capitol",
  options_flow: "Options", earnings_cal: "Earnings", alpha_wolf: "Alpha Wolf",
};

function AgentMesh({ agents = [] }) {
  const reduce = typeof window !== "undefined" && window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const meta = Object.fromEntries(ALL_AGENTS.map((a) => [a.id, a]));
  const statusOf = (id) => (agents.find((a) => a.id === id)?.status) || "idle";
  const node = (id, x, y) => ({
    id, x, y, label: MESH_LABEL[id] || meta[id]?.label || id,
    glyph: meta[id]?.glyph || "•", col: AGENT_COLOR[id] || T.violet,
    running: statusOf(id) === "running",
  });

  const orch = { x: 390, y: 56 };
  const alpha = node("alpha_wolf", 588, 158);
  const generals = MESH_GENERAL.map((id, i) => node(id, 62 + i * 78, 158));
  const finance = MESH_FINANCE.map((id, i) => node(id, 438 + i * 60, 270));
  const runningCount = [...generals, ...finance, alpha].filter((n) => n.running).length;

  // One link: a faint static line, upgraded to a bright line + a travelling
  // pulse only while the child agent is running.
  const Link = ({ from, to, col, live }) => (
    <g>
      <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke={col}
        strokeWidth={live ? 2.2 : 1.1} strokeOpacity={live ? 0.8 : 0.2} strokeLinecap="round" />
      {live && !reduce && (
        <circle r="3.6" fill={col}>
          <animateMotion dur="1.5s" repeatCount="indefinite" path={`M${from.x},${from.y} L${to.x},${to.y}`} />
          <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.15;0.8;1" dur="1.5s" repeatCount="indefinite" />
        </circle>
      )}
    </g>
  );

  // One node: static ring; a soft expanding ripple appears only while running.
  const Node = ({ n, r = 18, master }) => (
    <g>
      {n.running && !reduce && (
        <circle cx={n.x} cy={n.y} r={r} fill="none" stroke={n.col} strokeWidth="2">
          <animate attributeName="r" values={`${r};${r + 9}`} dur="1.6s" repeatCount="indefinite" />
          <animate attributeName="stroke-opacity" values="0.55;0" dur="1.6s" repeatCount="indefinite" />
        </circle>
      )}
      <circle cx={n.x} cy={n.y} r={r} fill={n.running ? n.col + "1f" : T.card}
        stroke={n.col} strokeWidth={n.running ? 2.4 : 1.4} strokeOpacity={n.running ? 1 : 0.55} />
      <text x={n.x} y={n.y + (master ? 5 : 4)} textAnchor="middle" fontSize={master ? 16 : 14} fill={n.col}>{n.glyph}</text>
      <text x={n.x} y={n.y + r + 13} textAnchor="middle" fontSize="9.5" fontWeight={master ? 800 : 600}
        fill={n.running ? n.col : T.ink3} fontFamily={T.sans}>{n.label}</text>
    </g>
  );

  return (
    <Card pad={16} style={{ overflow: "hidden" }}>
      <SectionTitle sub="Orchestrator drives the agents · Alpha Wolf masters the finance pack · a link animates only while that agent runs"
        right={<Pill mono c={runningCount ? T.green : T.ink3} bg={runningCount ? T.greenBg : T.line2}>{runningCount} running</Pill>}>
        Agent orchestration
      </SectionTitle>
      <svg viewBox="0 0 780 312" width="100%" style={{ display: "block", maxHeight: 312 }} role="img"
        aria-label="Orchestrator and Alpha Wolf agent hierarchy">
        <defs>
          <radialGradient id="om-master" cx="50%" cy="40%" r="62%">
            <stop offset="0%" stopColor="#b39bff" />
            <stop offset="100%" stopColor={T.violet} />
          </radialGradient>
          <radialGradient id="om-alpha" cx="50%" cy="40%" r="62%">
            <stop offset="0%" stopColor="#a87bff" />
            <stop offset="100%" stopColor={AGENT_COLOR.alpha_wolf} />
          </radialGradient>
        </defs>

        {/* Tier-1 links: Orchestrator → general agents + Alpha Wolf */}
        {generals.map((n) => <Link key={"lg" + n.id} from={orch} to={n} col={n.col} live={n.running} />)}
        <Link from={orch} to={alpha} col={AGENT_COLOR.alpha_wolf} live={alpha.running} />

        {/* Tier-2 links: Alpha Wolf → finance pack */}
        {finance.map((n) => <Link key={"lf" + n.id} from={alpha} to={n} col={n.col} live={n.running} />)}

        {/* nodes */}
        {generals.map((n) => <Node key={"ng" + n.id} n={n} />)}
        {finance.map((n) => <Node key={"nf" + n.id} n={n} r={17} />)}

        {/* Alpha Wolf — second-tier master */}
        {alpha.running && !reduce && (
          <circle cx={alpha.x} cy={alpha.y} r="24" fill="none" stroke={AGENT_COLOR.alpha_wolf} strokeWidth="2">
            <animate attributeName="r" values="24;34" dur="1.6s" repeatCount="indefinite" />
            <animate attributeName="stroke-opacity" values="0.5;0" dur="1.6s" repeatCount="indefinite" />
          </circle>
        )}
        <circle cx={alpha.x} cy={alpha.y} r="24" fill="url(#om-alpha)" />
        <text x={alpha.x} y={alpha.y + 6} textAnchor="middle" fontSize="18" fill="#fff">🐺</text>
        <text x={alpha.x} y={alpha.y + 40} textAnchor="middle" fontSize="10" fontWeight="800"
          fill={AGENT_COLOR.alpha_wolf} fontFamily={T.sans}>Alpha Wolf</text>

        {/* Orchestrator — top master */}
        <circle cx={orch.x} cy={orch.y} r="28" fill="url(#om-master)" />
        <text x={orch.x} y={orch.y + 7} textAnchor="middle" fontSize="20" fontWeight="700" fill="#fff">◇</text>
        <text x={orch.x} y={orch.y - 36} textAnchor="middle" fontSize="11" fontWeight="800"
          fill={T.ink2} fontFamily={T.sans}>Orchestrator</text>
      </svg>
    </Card>
  );
}

function fmtUptime(s) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}
const accent = (id) => AGENT_COLOR[id] || T.violet;

// System metrics shown on the Orchestrator. `warn` is the green→red threshold.
const METRICS = [
  { k: "cpu",  label: "CPU",       sub: "processor load",  icon: CpuIcon,  unit: "%",    cap: 100, warn: 85 },
  { k: "ram",  label: "Memory",    sub: "system RAM",      icon: RamIcon,  unit: "%",    cap: 100, warn: 88 },
  { k: "disk", label: "Disk",      sub: "root volume",     icon: DiskIcon, unit: "%",    cap: 100, warn: 90 },
  { k: "gpu",  label: "GPU · LLM", sub: "Qwen3 inference", icon: GpuIcon,  unit: "%",    cap: 100, warn: 85 },
  { k: "net",  label: "Network",   sub: "throughput",      icon: NetIcon,  unit: "Mb/s", cap: 100, warn: 60 },
];
const fmtVal = (v, unit) => (unit === "%" ? Math.round(v) : (v || 0).toFixed(1));

// Measure a container's pixel width so charts fill it crisply (no SVG stretch).
function useElWidth(fallback = 240) {
  const ref = useRef(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    if (!ref.current || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((e) => { const cw = e[0].contentRect.width; if (cw) setW(Math.round(cw)); });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

let _gid = 0;
// Area chart whose line turns red on any segment that crosses the threshold.
function ThresholdChart({ data, threshold, cap = 100, color = T.green, w = 240, h = 44 }) {
  if (!data || !data.length) return <div style={{ height: h }} />;
  const n = data.length;
  const hi = (Math.max(cap, threshold * 1.1, ...data) || 1) * 1.06;
  const X = (i) => (n === 1 ? w : (i / (n - 1)) * w);
  const Y = (v) => h - (Math.min(Math.max(v, 0), hi) / hi) * (h - 6) - 3;
  const pts = data.map((v, i) => [X(i), Y(v)]);
  const lineD = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const ty = Y(threshold);
  const last = data[n - 1], hot = last >= threshold, endCol = hot ? T.red : color;
  const gid = `tc${(_gid = (_gid + 1) % 1e6)}`;
  return (
    <svg width={w} height={h} style={{ display: "block", overflow: "visible" }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={endCol} stopOpacity="0.22" />
          <stop offset="100%" stopColor={endCol} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${lineD} L${w} ${h} L0 ${h} Z`} fill={`url(#${gid})`} />
      <line x1="0" y1={ty} x2={w} y2={ty} stroke={T.red} strokeWidth="1" strokeDasharray="3 3" opacity="0.4" />
      {pts.slice(1).map((p, i) => {
        const a = pts[i], over = data[i] >= threshold || data[i + 1] >= threshold;
        return <line key={i} x1={a[0]} y1={a[1]} x2={p[0]} y2={p[1]} stroke={over ? T.red : color} strokeWidth="1.9" strokeLinecap="round" />;
      })}
      <circle cx={pts[n - 1][0]} cy={pts[n - 1][1]} r="4.5" fill={endCol} opacity="0.18" />
      <circle cx={pts[n - 1][0]} cy={pts[n - 1][1]} r="2.4" fill={endCol} />
    </svg>
  );
}

function ResCard({ m, r }) {
  const [ref, w] = useElWidth();
  const v = r.v;
  const hot = v >= m.warn;
  const col = hot ? T.red : T.green;
  const ringPct = Math.min(100, (v / m.cap) * 100);
  const Icon = m.icon;
  return (
    <Card pad={13} style={{ position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 3, background: col, opacity: hot ? 0.9 : 0.5 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <div style={{ width: 34, height: 34, borderRadius: 9, background: col + "16", color: col, display: "grid", placeItems: "center", flex: "0 0 auto" }}>
          <Icon size={18} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 11, color: T.ink3, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>{m.label}</div>
          <div style={{ fontSize: 10.5, color: T.ink4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.sub}</div>
        </div>
        <Ring val={ringPct} size={34} stroke={4} color={col} track={T.line2} />
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 12 }}>
        <CountUp value={v} decimals={m.unit === "%" ? 0 : 1} duration={500} style={{ fontSize: 25, fontWeight: 800, letterSpacing: -1, fontFamily: T.mono, color: hot ? T.red : T.ink }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: T.ink4 }}>{m.unit}</span>
        <span style={{ marginLeft: "auto", fontSize: 9.5, fontWeight: 700, color: col, background: col + "16", padding: "3px 8px", borderRadius: 6 }}>{hot ? "CRITICAL" : "NOMINAL"}</span>
      </div>
      <div ref={ref} style={{ width: "100%", marginTop: 10 }}>
        <ThresholdChart data={r.hist} threshold={m.warn} cap={m.cap} w={w} h={36} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
        <span style={{ fontSize: 9.5, fontFamily: T.mono, color: T.ink4 }}>last {r.hist.length} samples</span>
        <span style={{ fontSize: 9.5, fontFamily: T.mono, color: T.ink4 }}>threshold {m.warn}{m.unit === "%" ? "%" : " Mb/s"}</span>
      </div>
    </Card>
  );
}

function AlarmBanner({ alarm, onAck }) {
  if (!alarm) return null;
  return (
    <div style={{ background: T.redBg, border: `1px solid ${T.red}55`, borderRadius: 14, padding: "16px 20px", display: "flex", alignItems: "center", gap: 16, animation: "omPulse 1.4s ease-in-out infinite" }}>
      <div style={{ width: 40, height: 40, borderRadius: 11, background: T.card, display: "grid", placeItems: "center", fontSize: 20, color: T.red, flex: "0 0 auto" }}>⚠</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 14.5, fontWeight: 700, color: T.red }}>{alarm.label} critical — {alarm.value}%</div>
        <div style={{ fontSize: 12.5, color: T.red, opacity: 0.85, marginTop: 2 }}><b>Suggested action:</b> {alarm.action}</div>
      </div>
      <Btn kind="danger" size="sm" onClick={onAck}>Acknowledge &amp; resolve</Btn>
    </div>
  );
}

function Semaphore({ s }) {
  const llm = s.llm || { queue: [], heldS: 0, tokens: 0, rate: 0, holder: null };
  const holder = s.agents.find((a) => a.id === llm.holder);
  const pct = Math.min(100, (llm.heldS / 6) * 100);
  return (
    <Card pad={15} style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <SectionTitle sub="1 permit · serialized inference, no deadlocks">LLM Semaphore</SectionTitle>
      {holder ? (
        <div style={{ background: T.violetBg, border: `1px solid ${T.line}`, borderRadius: 11, padding: 14, display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, background: accent(holder.id) + "1a", color: accent(holder.id), display: "grid", placeItems: "center", fontWeight: 700 }}>{holder.glyph}</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{holder.n}</div>
            <div style={{ fontSize: 11, color: T.ink3, fontFamily: T.mono }}>holding · {llm.heldS.toFixed(1)}s · {llm.tokens} tok · {llm.rate} tok/s</div>
          </div>
          <span style={{ fontSize: 10.5, fontWeight: 700, color: T.violet, background: T.violetBg, padding: "4px 8px", borderRadius: 6 }}>ACTIVE</span>
        </div>
      ) : (
        <div style={{ background: T.cardAlt, border: `1px solid ${T.line}`, borderRadius: 11, padding: 14, fontSize: 12.5, color: T.ink3 }}>
          Permit free · model idle
        </div>
      )}
      <div style={{ height: 5, background: T.violetBg, borderRadius: 6, overflow: "hidden", margin: "10px 0 2px" }}>
        <div style={{ width: pct + "%", height: "100%", background: T.violet, transition: "width .6s linear" }} />
      </div>
      <div style={{ fontSize: 11.5, color: T.ink3, fontWeight: 600, margin: "14px 0 8px" }}>Queue · {llm.queue.length} waiting</div>
      {llm.queue.length === 0 && <div style={{ fontSize: 12, color: T.ink4 }}>Queue empty</div>}
      {llm.queue.map((qid, i) => {
        const a = s.agents.find((x) => x.id === qid) || { glyph: "•", n: qid };
        return (
          <div key={qid + i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 4px", borderBottom: i < llm.queue.length - 1 ? `1px solid ${T.line2}` : "none" }}>
            <span style={{ fontSize: 11, color: "#b6bcc6", fontFamily: T.mono, width: 14 }}>{i + 1}</span>
            <div style={{ width: 22, height: 22, borderRadius: 6, background: accent(qid) + "1a", color: accent(qid), display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700 }}>{a.glyph}</div>
            <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1 }}>{a.n}</span>
            <span style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono }}>waiting</span>
          </div>
        );
      })}
      <div style={{ marginTop: "auto", paddingTop: 14, fontSize: 11, color: T.ink4, fontFamily: T.mono }}>{(s.llm && s.llm.model) || "Qwen3"} · mutex healthy</div>
    </Card>
  );
}

function StressTestButton({ agents = [] }) {
  const [phase, setPhase] = useState("idle"); // idle | running | done
  const [result, setResult] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef(null);

  const run = async () => {
    setPhase("running"); setResult(null); setElapsed(0);
    timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    try {
      const r = await fetch(`${API_BASE}/api/stress-test`, { method: "POST" });
      const data = await r.json();
      setResult(data); setPhase("done");
      clearInterval(timerRef.current);
      setTimeout(() => setPhase("idle"), 10000);
    } catch (e) {
      setResult({ error: String(e) }); setPhase("done");
      clearInterval(timerRef.current);
      setTimeout(() => setPhase("idle"), 6000);
    }
  };
  useEffect(() => () => clearInterval(timerRef.current), []);

  const triggered = result?.triggered || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <button onClick={run} disabled={phase === "running"} style={{
          display: "flex", alignItems: "center", gap: 8, padding: "10px 22px",
          borderRadius: 10, border: `1.5px solid ${T.red}`,
          background: phase === "running" ? T.redBg : T.red,
          color: phase === "running" ? T.red : "#fff",
          fontWeight: 700, fontSize: 13.5, cursor: phase === "running" ? "not-allowed" : "pointer",
          transition: "all .18s", fontFamily: T.sans,
        }}>
          <span style={{ fontSize: 16, display: "inline-block", animation: phase === "running" ? "omSpin .8s linear infinite" : "none" }}>
            {phase === "running" ? "↻" : "🔥"}
          </span>
          {phase === "running" ? `Running all agents… ${elapsed}s` : "Stress Test — Run All Agents"}
        </button>
        {phase === "done" && result && !result.error && (
          <span style={{ fontSize: 12.5, color: T.green, fontWeight: 600 }}>✓ {triggered.length} agents triggered</span>
        )}
        {phase === "done" && result?.error && (
          <span style={{ fontSize: 12.5, color: T.red, fontWeight: 600 }}>Error: {result.error}</span>
        )}
      </div>

      {/* Live per-agent status grid (shown while running or just done) */}
      {phase !== "idle" && agents.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {agents.map((a) => {
            const isTriggered = triggered.includes(a.id);
            const isRunning = a.status === "running";
            const col = isRunning ? T.green : isTriggered ? T.amber : T.ink3;
            const bg = isRunning ? T.greenBg : isTriggered ? T.amberBg : T.cardAlt;
            return (
              <div key={a.id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 10px", borderRadius: 8, background: bg, border: `1px solid ${col}44` }}>
                <span style={{ fontSize: 13 }}>{a.glyph}</span>
                <span style={{ fontSize: 11.5, fontWeight: 600, color: col, fontFamily: T.sans }}>{a.n}</span>
                <span style={{ fontSize: 10, color: col, fontFamily: T.mono }}>{isRunning ? "running" : isTriggered ? "triggered" : a.status}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Demo Controls: demo-mode toggle + simulate-load + crash-agent ────────────
function DemoControls({ s }) {
  const demo = !!s.demo;
  const [busy, setBusy] = useState(false);
  const toggle = async () => { setBusy(true); try { await setDemoMode(!demo); } finally { setTimeout(() => setBusy(false), 400); } };
  // In demo mode, crash a *visible* core agent so the auto-restart is on screen.
  const crashOne = () => {
    if (!demo) return crashAgent();
    const live = (s.agents || []).filter((a) => CORE_AGENTS.includes(a.id) && a.status !== "crashed");
    crashAgent(live.length ? live[Math.floor(Math.random() * live.length)].id : undefined);
  };
  const ActBtn = ({ label, onClick, color }) => (
    <button onClick={onClick} style={{
      padding: "8px 14px", borderRadius: 9, border: `1px solid ${color}55`, background: color + "12",
      color, fontWeight: 700, fontSize: 12.5, cursor: "pointer", fontFamily: T.sans,
    }}>{label}</button>
  );
  return (
    <div style={{ background: T.card, border: `1px solid ${T.violet}44`, borderRadius: 14, padding: "18px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: T.violet }}>◐</span> Demo Controls
            <span style={{ fontSize: 11, fontWeight: 600, color: T.ink4 }}>— for a clean 10-minute recording</span>
          </div>
          <div style={{ fontSize: 11.5, color: T.ink4, marginTop: 4 }}>
            {demo ? "Showing the 4 graded agents · extras hidden and paused" : "Full fleet visible · every agent scheduled"}
          </div>
        </div>
        <button onClick={toggle} disabled={busy} title="Toggle demo mode" style={{
          display: "flex", alignItems: "center", gap: 9, padding: "7px 13px", borderRadius: 999,
          border: `1px solid ${demo ? T.violet : T.line}`, background: demo ? T.violet + "16" : T.cardAlt,
          color: demo ? T.violet : T.ink3, fontWeight: 700, fontSize: 12.5, cursor: busy ? "wait" : "pointer", fontFamily: T.sans,
        }}>
          <span style={{ width: 30, height: 16, borderRadius: 999, background: demo ? T.violet : "#c4c9d4", position: "relative", transition: "all .2s", flex: "0 0 auto" }}>
            <span style={{ position: "absolute", top: 2, left: demo ? 16 : 2, width: 12, height: 12, borderRadius: 999, background: "#fff", transition: "all .2s" }} />
          </span>
          Demo mode {demo ? "ON" : "OFF"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
        <ActBtn label="⚠ Simulate CPU > 90%" onClick={() => spikeResource("cpu")} color={T.red} />
        <ActBtn label="⚠ Simulate RAM > 90%" onClick={() => spikeResource("ram")} color="#ea580c" />
        <ActBtn label="⚠ Simulate GPU > 90%" onClick={() => spikeResource("gpu")} color="#7c5cf6" />
        <ActBtn label="✕ Crash a random agent" onClick={crashOne} color={T.red} />
      </div>
      <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 10, fontFamily: T.mono }}>
        Spike → alarm banner with a suggested corrective action (auto-clears ~12 s). Crash → watchdog auto-restarts the agent ~4 s later.
      </div>
    </div>
  );
}

const SKELETON = {
  uptimeS: 0, threads: 0,
  res: { cpu: { v: 0, hist: [] }, ram: { v: 0, hist: [] }, disk: { v: 0, hist: [] }, gpu: { v: 0, hist: [] }, net: { v: 0, hist: [] } },
  agents: [], llm: { holder: null, queue: [], heldS: 0, tokens: 0, rate: 0 }, events: [], alarm: null,
};

function fmtTokens(n) {
  if (!n) return "—";
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n);
}

function RunMetrics() {
  const [metrics, setMetrics] = useState(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try { const m = await getMetrics(); if (alive) setMetrics(m); } catch { /* backend offline */ }
    };
    tick();
    const id = setInterval(tick, 30000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const rows = Object.entries(metrics?.agents || {});
  const th = { padding: "6px 10px", textAlign: "left", fontSize: 10.5, color: T.ink4, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 };
  const td = { padding: "7px 10px", fontSize: 12.5, fontFamily: T.mono, borderTop: `1px solid ${T.line2}` };

  return (
    <Card pad={15}>
      <SectionTitle sub={`per-agent telemetry over each agent's last ${metrics?.window ?? 50} runs`}>Run metrics</SectionTitle>
      {rows.length === 0 ? (
        <div style={{ fontSize: 12.5, color: T.ink3 }}>No completed runs yet — metrics appear after agents run.</div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={th}>Agent</th><th style={th}>Runs</th><th style={th}>Success</th>
            <th style={th}>Avg time</th><th style={th}>LLM calls</th><th style={th}>Tokens in</th><th style={th}>Tokens out</th>
          </tr></thead>
          <tbody>
            {rows.map(([aid, m]) => {
              const col = AGENT_COLOR[aid] || T.violet;
              const ok = m.success_rate >= 0.9;
              return (
                <tr key={aid}>
                  <td style={{ ...td, fontFamily: T.sans, fontWeight: 700 }}>
                    <span style={{ color: col, marginRight: 7 }}>●</span>{m.name}
                  </td>
                  <td style={td}>{m.runs}</td>
                  <td style={{ ...td, color: ok ? T.green : T.amber, fontWeight: 700 }}>{Math.round(m.success_rate * 100)}%</td>
                  <td style={td}>{m.avg_duration_s != null ? `${m.avg_duration_s}s` : "—"}</td>
                  <td style={td}>{m.llm_calls || "—"}</td>
                  <td style={td}>{fmtTokens(m.tokens_in)}</td>
                  <td style={td}>{fmtTokens(m.tokens_out)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function Orchestrator({ sys, online, onNavigate }) {
  const [ackd, setAckd] = useState(false);
  const s = sys || SKELETON;
  const running = s.agents.filter((a) => a.status === "running").length;
  const alarm = ackd ? null : s.alarm;
  const nav = onNavigate || (() => {});
  const demo = !!s.demo;
  const shownAgents = demo ? ALL_AGENTS.filter((a) => CORE_AGENTS.includes(a.id)) : ALL_AGENTS;

  return (
    <div>
      <TabHeader icon="◇" color={T.violet} title="Orchestrator"
        sub={`localhost:5174 · uptime ${fmtUptime(s.uptimeS)} · ${s.threads} threads`}
        actions={<>
          {!online
            ? <Pill c={T.amber} bg={T.amberBg} bd={T.amber + "55"}><Dot c={T.amber} />Backend offline</Pill>
            : alarm
              ? <Pill c={T.red} bg={T.redBg} bd={T.red + "55"}><Dot c={T.red} />Alarm active</Pill>
              : <Pill c={T.green} bg={T.greenBg} bd={T.green + "55"}><Dot c={T.green} />All systems nominal</Pill>}
          <Pill mono c={T.ink2}>{(s.llm && s.llm.model) || "Qwen3"} · local</Pill>
          <Pill mono c={T.ink3}>{running} running</Pill>
        </>} />

      <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 9 }}>

        {/* ── Command-center hero: live clock, market status, KPIs ─────────── */}
        <CommandCenterHero s={s} online={online} />

        {/* ── Animated master-agent orchestration mesh ─────────────────────── */}
        <AgentMesh agents={s.agents} />

        {/* ── Resource metric cards (live system metrics · updates every 5s) ── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
          {METRICS.map((m, i) => <Reveal key={m.k} delay={60 + i * 50}><ResCard m={m} r={s.res[m.k] || { v: 0, hist: [] }} /></Reveal>)}
        </div>

        {/* ── Agent overview grid (clickable) ──────────────────────────────── */}
        <div>
          <SectionTitle sub="click any card to open that agent's tab">{shownAgents.length} {demo ? "graded agents · demo mode" : "managed agents · auto-restart enabled"}</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 10, marginTop: 8 }}>
            {shownAgents.map((a, i) => (
              <Reveal key={a.id} delay={120 + i * 35}>
                <AgentOverviewCard agent={a} sysAgent={s.agents.find((x) => x.id === a.id)} onNavigate={nav} />
              </Reveal>
            ))}
          </div>
        </div>

        {/* ── Demo controls ───────────────────────────────────────────────── */}
        <DemoControls s={s} />

        {/* ── Alarm ───────────────────────────────────────────────────────── */}
        <AlarmBanner alarm={alarm} onAck={() => { setAckd(true); setTimeout(() => setAckd(false), 12000); }} />

        {/* ── Stress test ─────────────────────────────────────────────────── */}
        <div style={{ background: T.card, border: `1px solid ${T.red}44`, borderRadius: 14, padding: "18px 22px" }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: T.red }}>🔥</span> Stress Test
            <span style={{ fontSize: 11, fontWeight: 600, color: T.ink4, marginLeft: 4 }}>— fire all agents simultaneously to verify load handling</span>
          </div>
          <StressTestButton agents={s.agents} />
        </div>

        {/* ── LLM semaphore — assignment requirement: 1 permit, no deadlocks ── */}
        <Semaphore s={s} />

        {/* ── Per-run telemetry (tokens, latency, success rate) ────────────── */}
        <RunMetrics />
      </div>
    </div>
  );
}
