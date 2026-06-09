// ============================================================================
// Orchestrator.jsx — Mission Control: agent overview + system gauges + ops
// Merged from Home + Orchestrator. Single entry point for the whole platform.
// ============================================================================
import { useState, useEffect, useRef, useMemo } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, Dot, StatusPill, Ring, SectionTitle, TabHeader, Btn } from "../theme/ui";
import { CpuIcon, RamIcon, DiskIcon, GpuIcon, NetIcon } from "../theme/icons";
import { API_BASE, useAgentData, setDemoMode, spikeResource, crashAgent } from "../state/api";

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
    <div onClick={() => onNavigate(agent.id)}
      style={{ background: T.card, border: `1px solid ${status === "crashed" ? T.red + "55" : T.line}`, borderRadius: 12, padding: "12px 14px", cursor: "pointer", transition: "all .15s", display: "flex", gap: 10, alignItems: "center" }}
      onMouseEnter={(e) => e.currentTarget.style.borderColor = col + "66"}
      onMouseLeave={(e) => e.currentTarget.style.borderColor = status === "crashed" ? T.red + "55" : T.line}>
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

// Data snippet components ─────────────────────────────────────────────────────
function WolfSnippet({ onNavigate }) {
  const { data } = useAgentData("wallstreet_wolf");
  const md = data?.market_data || data?.wolf || {};
  const gainers = (md.top_gainers || md.gainers || []).slice(0, 3);
  const losers  = (md.top_losers  || md.losers  || []).slice(0, 3);
  if (!gainers.length) return <div style={{ fontSize: 12, color: T.ink4, padding: "8px 0" }}>No data — run Wolf first</div>;
  const ticker = (s) => s.symbol || s.ticker || "?";
  const pct    = (s) => (s.change_pct ?? s.pct ?? 0);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
      {[["Top gainers", gainers, T.green, true], ["Top losers", losers, T.red, false]].map(([label, list, col, pos]) => (
        <div key={label}>
          <div style={{ fontSize: 10, fontWeight: 700, color: col, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 5 }}>{label}</div>
          {list.map((s) => (
            <div key={ticker(s)} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: 12, borderBottom: `1px solid ${T.line2}` }}>
              <span style={{ fontWeight: 700, fontFamily: T.mono }}>{ticker(s)}</span>
              <span style={{ color: col, fontFamily: T.mono }}>{pos && pct(s) > 0 ? "+" : ""}{pct(s).toFixed(2)}%</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function CapitolSnippet({ onNavigate }) {
  const { data } = useAgentData("capitol_tracker");
  const trades = (data?.tracker?.trades || []).slice(0, 5);
  if (!trades.length) return <div style={{ fontSize: 12, color: T.ink4, padding: "8px 0" }}>No data — run Capitol Tracker</div>;
  return (
    <div>
      {trades.map((t, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0", fontSize: 12, borderBottom: `1px solid ${T.line2}` }}>
          <span style={{ fontWeight: 700, fontFamily: T.mono, minWidth: 44 }}>{t.ticker || "—"}</span>
          <span style={{ flex: 1, color: T.ink3, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.politician}</span>
          <span style={{ fontSize: 10, fontWeight: 700, color: /purchase|buy|exercise/i.test(t.type) ? T.green : T.red, background: /purchase|buy|exercise/i.test(t.type) ? "#f0fdf4" : "#fef2f2", padding: "2px 6px", borderRadius: 4 }}>{t.type?.slice(0, 8)}</span>
        </div>
      ))}
    </div>
  );
}

function BriefSnippet() {
  const { data } = useAgentData("morning_brief");
  const brief = data?.brief;
  if (!brief) return <div style={{ fontSize: 12, color: T.ink4, padding: "8px 0" }}>No brief — runs at 06:00 daily</div>;
  return (
    <div>
      {brief.weather && <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, fontSize: 12 }}><span style={{ fontSize: 16 }}>🌤</span><span style={{ color: T.ink2 }}>{brief.weather}</span></div>}
      {brief.narrative && <div style={{ fontSize: 12, color: T.ink2, lineHeight: 1.5 }}>{brief.narrative.slice(0, 200)}…</div>}
    </div>
  );
}

function OptionsSnippet() {
  const { data } = useAgentData("options_flow");
  const signals = (data?.flow?.signals || []).slice(0, 4);
  if (!signals.length) return <div style={{ fontSize: 12, color: T.ink4, padding: "8px 0" }}>No data — run Options Flow</div>;
  return (
    <div>
      {signals.map((s, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0", fontSize: 12, borderBottom: `1px solid ${T.line2}` }}>
          <span style={{ fontWeight: 700, fontFamily: T.mono, minWidth: 44, color: AGENT_COLOR.options_flow }}>{s.ticker}</span>
          <span style={{ fontSize: 10, background: "#f1edfe", color: T.violet, padding: "2px 6px", borderRadius: 4, fontWeight: 700 }}>{s.type || "call"}</span>
          <span style={{ flex: 1, color: T.ink3, fontSize: 11 }}>IV ~{s.iv_pct?.toFixed(0)}%ile</span>
        </div>
      ))}
    </div>
  );
}

// Mini gauge ring (compact) ───────────────────────────────────────────────────
function MiniGauge({ label, val, warn = 85 }) {
  const hot = val >= warn;
  const col = hot ? T.red : T.green;
  return (
    <div style={{ textAlign: "center" }}>
      <Ring val={Math.min(100, val)} size={44} stroke={5} color={col} track={T.line2}>
        <span style={{ fontSize: 10, fontWeight: 700, fontFamily: T.mono, color: hot ? T.red : T.ink }}>{Math.round(val)}</span>
      </Ring>
      <div style={{ fontSize: 10, color: T.ink4, marginTop: 3, fontWeight: 600 }}>{label}</div>
    </div>
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
        <span style={{ fontSize: 25, fontWeight: 800, letterSpacing: -1, fontFamily: T.mono, color: hot ? T.red : T.ink }}>{fmtVal(v, m.unit)}</span>
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

function AgentCard({ a }) {
  const col = accent(a.id);
  const crashed = a.status === "crashed";
  return (
    <div style={{ border: `1px solid ${crashed ? T.red + "55" : T.line}`, borderRadius: 12, padding: 14, display: "flex", gap: 12, alignItems: "center", background: crashed ? T.redBg : T.card, transition: "all .2s" }}>
      <div style={{ width: 38, height: 38, borderRadius: 10, background: col + "1a", color: col, display: "grid", placeItems: "center", fontSize: 16, fontWeight: 700, flex: "0 0 auto" }}>{a.glyph}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>{a.n}</div>
        <div style={{ fontSize: 11.5, color: T.ink4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{a.desc}</div>
      </div>
      <div style={{ textAlign: "right", flex: "0 0 auto" }}>
        <StatusPill status={a.status} />
        <div style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono, marginTop: 3 }}>
          {crashed ? "restarting…" : a.schedule}
        </div>
      </div>
    </div>
  );
}

function Semaphore({ s }) {
  const llm = s.llm || { queue: [], heldS: 0, tokens: 0, rate: 0, holder: null };
  const holder = s.agents.find((a) => a.id === llm.holder);
  const pct = Math.min(100, (llm.heldS / 6) * 100);
  return (
    <Card pad={20} style={{ display: "flex", flexDirection: "column", height: "100%" }}>
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

function EventLog({ s }) {
  const [expanded, setExpanded] = useState(false);
  const events = s.events || [];
  const shown = expanded ? events : events.slice(0, 12);
  return (
    <Card pad={20} style={{ height: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <SectionTitle sub="orchestrator activity" right={
          events.length > 12 && (
            <button onClick={() => setExpanded(!expanded)} style={{ fontSize: 11, color: T.violet, background: T.violetBg, border: `1px solid ${T.violet}33`, borderRadius: 6, padding: "2px 10px", cursor: "pointer", fontFamily: T.sans, fontWeight: 600 }}>
              {expanded ? "▲ Collapse" : `▼ Show all ${events.length}`}
            </button>
          )
        }>Event log</SectionTitle>
      </div>
      <div style={{ display: "flex", flexDirection: "column", maxHeight: expanded ? "none" : 360, overflow: "hidden" }}>
        {shown.map((e, i) => (
          <div key={i} style={{ display: "flex", gap: 11, padding: "7px 0", fontSize: 12.5, alignItems: "baseline", borderBottom: i < shown.length - 1 ? `1px solid ${T.line2}` : "none" }}>
            <span style={{ fontFamily: T.mono, color: "#b6bcc6", fontSize: 10.5, flex: "0 0 auto", whiteSpace: "nowrap" }}>{e.t}</span>
            <Dot c={e.c} s={6} />
            <span style={{ color: T.ink2 }}>{e.m}</span>
          </div>
        ))}
        {events.length === 0 && <div style={{ fontSize: 12, color: T.ink4 }}>No events yet.</div>}
        {!expanded && events.length > 12 && (
          <div style={{ padding: "8px 0", textAlign: "center", fontSize: 11.5, color: T.ink4, borderTop: `1px solid ${T.line2}`, marginTop: 4 }}>
            {events.length - 12} older events hidden
          </div>
        )}
      </div>
    </Card>
  );
}

// Cross-agent Signals: Wolf watchlist tickers that appear in Capitol Tracker trades
function SignalsPanel({ sys }) {
  const { data: wolfData } = useAgentData("wallstreet_wolf");
  const { data: capitolData } = useAgentData("capitol_tracker");

  const signals = useMemo(() => {
    const wolfStocks = wolfData?.wolf?.watchlist || [];
    const capitolTrades = capitolData?.tracker?.trades || [];
    if (!wolfStocks.length || !capitolTrades.length) return [];

    const watchTickers = new Set(wolfStocks.map((w) => (w.ticker || w.symbol || "").toUpperCase()));
    const matched = {};
    capitolTrades.forEach((t) => {
      const tk = (t.ticker || "").toUpperCase();
      if (tk && watchTickers.has(tk)) {
        if (!matched[tk]) matched[tk] = [];
        matched[tk].push(t);
      }
    });
    return Object.entries(matched).sort((a, b) => b[1].length - a[1].length);
  }, [wolfData, capitolData]);

  if (!signals.length) return null;
  const RED = "#dc2626"; const GREEN = "#16a34a";

  return (
    <Card pad={20} style={{ borderColor: "#f59e0b55", background: "#fffbeb" }}>
      <SectionTitle sub="Wolf watchlist tickers with recent congressional trades" right={
        <Pill c="#d97706" bg="#fde68a80">⚡ {signals.length} overlap{signals.length !== 1 ? "s" : ""}</Pill>
      }>Cross-Agent Signals</SectionTitle>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 6 }}>
        {signals.map(([ticker, trades]) => {
          const buys = trades.filter((t) => /purchase|buy|exercise|call/i.test(t.type)).length;
          const sells = trades.filter((t) => /sale|sell/i.test(t.type)).length;
          const net = buys - sells;
          const col = net > 0 ? GREEN : net < 0 ? RED : "#6b7280";
          return (
            <div key={ticker} style={{ background: T.card, border: `1px solid ${col}44`, borderRadius: 10, padding: "10px 14px", minWidth: 120 }}>
              <div style={{ fontSize: 16, fontWeight: 800, fontFamily: "monospace", color: col }}>{ticker}</div>
              <div style={{ fontSize: 10.5, color: "#92400e", marginTop: 3 }}>
                {trades.length} trade{trades.length !== 1 ? "s" : ""} · {[...new Set(trades.map((t) => t.politician.split(" ").pop()))].slice(0, 2).join(", ")}
              </div>
              <div style={{ display: "flex", gap: 5, marginTop: 5 }}>
                {buys > 0 && <span style={{ fontSize: 10, fontWeight: 700, color: GREEN, background: "#f0fdf4", padding: "2px 6px", borderRadius: 4 }}>▲ {buys} buy</span>}
                {sells > 0 && <span style={{ fontSize: 10, fontWeight: 700, color: RED, background: "#fef2f2", padding: "2px 6px", borderRadius: 4 }}>▼ {sells} sell</span>}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 11, color: "#92400e", marginTop: 12 }}>
        These tickers appear on your Wolf watchlist <em>and</em> in recent STOCK Act congressional disclosures. Educational use only — not investment advice.
      </div>
    </Card>
  );
}

// ---------- Atlas layout ----------
function MetricStrip({ s }) {
  return (
    <Card pad={0} style={{ display: "flex", alignItems: "stretch", overflow: "hidden", flexWrap: "wrap" }}>
      {METRICS.map((m, i) => {
        const r = s.res[m.k] || { v: 0, hist: [] };
        const hot = r.v >= m.warn; const col = hot ? T.red : T.green;
        const Icon = m.icon;
        return (
          <div key={m.k} style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px", flex: "1 1 170px", borderRight: i < METRICS.length - 1 ? `1px solid ${T.line2}` : "none" }}>
            <div style={{ width: 30, height: 30, borderRadius: 8, background: col + "16", color: col, display: "grid", placeItems: "center", flex: "0 0 auto" }}><Icon size={16} /></div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 10, color: T.ink3, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4 }}>{m.label}</div>
              <div style={{ fontSize: 21, fontWeight: 800, fontFamily: T.mono, letterSpacing: -0.5, color: hot ? T.red : T.ink }}>{fmtVal(r.v, m.unit)}<span style={{ fontSize: 11, color: T.ink4 }}>{m.unit === "%" ? "%" : " " + m.unit}</span></div>
            </div>
            <div style={{ marginLeft: "auto" }}><ThresholdChart data={r.hist} threshold={m.warn} cap={m.cap} w={72} h={34} /></div>
          </div>
        );
      })}
    </Card>
  );
}

function AgentTable({ s }) {
  const cols = "1.8fr 0.9fr 0.6fr 0.7fr 0.7fr 1fr";
  return (
    <Card pad={0} style={{ overflow: "hidden" }}>
      <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.line2}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>Managed agents</div>
        <Pill mono c={T.ink3}>auto-restart on</Pill>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: cols, padding: "10px 20px", fontSize: 10.5, color: T.ink4, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, borderBottom: `1px solid ${T.line2}` }}>
        <span>Agent</span><span>Status</span><span style={{ textAlign: "right" }}>CPU</span><span style={{ textAlign: "right" }}>Mem</span><span style={{ textAlign: "right" }}>Restarts</span><span style={{ textAlign: "right" }}>Schedule</span>
      </div>
      {s.agents.map((a) => {
        const col = accent(a.id); const crashed = a.status === "crashed";
        return (
          <div key={a.id} style={{ display: "grid", gridTemplateColumns: cols, padding: "14px 20px", alignItems: "center", borderBottom: `1px solid ${T.line2}`, fontSize: 13, background: crashed ? T.redBg : "transparent" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
              <div style={{ width: 30, height: 30, borderRadius: 8, background: col + "1a", color: col, display: "grid", placeItems: "center", fontWeight: 700, fontSize: 13 }}>{a.glyph}</div>
              <div style={{ minWidth: 0 }}><div style={{ fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{a.n}</div><div style={{ fontSize: 11, color: T.ink4 }}>{a.desc}</div></div>
            </div>
            <StatusPill status={a.status} />
            <span style={{ fontFamily: T.mono, color: T.ink2, textAlign: "right" }}>{a.cpu}%</span>
            <span style={{ fontFamily: T.mono, color: T.ink2, textAlign: "right" }}>{a.mem}m</span>
            <span style={{ fontFamily: T.mono, color: T.ink3, textAlign: "right" }}>{a.restarts}</span>
            <span style={{ fontFamily: T.mono, fontSize: 11.5, color: T.ink3, textAlign: "right" }}>{crashed ? "restarting…" : a.schedule}</span>
          </div>
        );
      })}
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

export default function Orchestrator({ sys, online, theme = "aria", onNavigate }) {
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

      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>

        {/* ── Resource metric cards (live system metrics · updates every 5s) ── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
          {METRICS.map((m) => <ResCard key={m.k} m={m} r={s.res[m.k] || { v: 0, hist: [] }} />)}
        </div>

        {/* ── Agent overview grid (clickable) ──────────────────────────────── */}
        <div>
          <SectionTitle sub="click any card to open that agent's tab">{shownAgents.length} {demo ? "graded agents · demo mode" : "managed agents · auto-restart enabled"}</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 10, marginTop: 8 }}>
            {shownAgents.map((a) => (
              <AgentOverviewCard key={a.id} agent={a} sysAgent={s.agents.find((x) => x.id === a.id)} onNavigate={nav} />
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
      </div>
    </div>
  );
}
