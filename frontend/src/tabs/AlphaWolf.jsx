// ============================================================================
// AlphaWolf.jsx — Master agent. Synthesizes the trading pack (Wolf, Compass,
// Strategy Scout, Capitol Tracker, Options Flow, Earnings) into a Daily +
// Weekly trade game-plan, then executes the daily ideas on a simulated
// paper-trading portfolio (virtual capital, live prices — no real money).
// ============================================================================
import { useState, useEffect, useCallback } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent, getWolfPortfolio, setWolfExecution, resetWolfPortfolio, getWolfNow } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar } from "../components/Common";
import DashboardGrid from "../components/DashboardGrid";

const PURPLE = "#7c3aed"; const PURPLE_BG = "#f5f3ff";

const SOURCE_LABELS = {
  wallstreet_wolf: "Wallstreet Wolf",
  compass: "Wallstreet Compass",
  strategy_scout: "Strategy Scout",
  capitol_tracker: "Capitol Tracker",
  options_flow: "Options Flow",
  earnings_cal: "Earnings Calendar",
};
const ALL_SOURCES = Object.keys(SOURCE_LABELS);

// The plan comes from a local LLM and is not guaranteed to match the schema —
// a field that should be a string sometimes arrives as an object or array.
// React throws on object children, so coerce everything to text before render.
function txt(v) {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map(txt).filter(Boolean).join(", ");
  if (typeof v === "object") return Object.values(v).map(txt).filter(Boolean).join(" — ");
  return String(v);
}

function dirColor(d) {
  const v = txt(d).toLowerCase();
  return v === "long" ? T.green : v === "short" ? T.red : T.ink3;
}
function biasColor(b) {
  const v = String(b || "NEUTRAL").toUpperCase();
  return v === "BULLISH" ? T.green : v === "BEARISH" ? T.red : T.ink3;
}

function BiasPill({ bias }) {
  const c = biasColor(bias);
  const v = String(bias || "NEUTRAL").toUpperCase();
  return <span style={{ fontSize: 10.5, fontWeight: 800, color: c, background: c + "16", padding: "3px 10px", borderRadius: 6 }}>{v}</span>;
}

function StancePill({ stance }) {
  const v = String(stance || "NEUTRAL").toUpperCase();
  const c = v === "RISK-ON" ? T.green : v === "RISK-OFF" ? T.red : T.ink3;
  return <span style={{ fontSize: 11, fontWeight: 800, color: "#fff", background: c, padding: "4px 12px", borderRadius: 999, whiteSpace: "nowrap" }}>{v}</span>;
}

function IdeaCard({ idea, weekly }) {
  const dc = dirColor(idea.direction);
  const thirdLabel = weekly ? "Catalyst" : "Trigger";
  const thirdVal = txt(weekly ? idea.catalyst : idea.trigger);
  const thesis = txt(idea.thesis);
  const risk = txt(idea.risk);
  const when = txt(idea.when);
  const levels = weekly ? [] : [
    ["Entry", txt(idea.entry)], ["Stop", txt(idea.stop)], ["Target", txt(idea.target)],
    ["Size", idea.size_usd != null ? `~${fmt$(idea.size_usd)} · ${idea.size_shares} sh` : ""],
  ].filter(([, v]) => v);
  return (
    <div style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: "12px 14px", background: T.card }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontFamily: T.mono, fontWeight: 800, fontSize: 15, color: T.ink }}>{txt(idea.ticker) || "—"}</span>
        <span style={{ fontSize: 9.5, fontWeight: 800, color: dc, background: dc + "16", padding: "2px 8px", borderRadius: 4, textTransform: "uppercase" }}>{txt(idea.direction) || "n/a"}</span>
        {!weekly && when && (
          <span style={{ fontSize: 10, fontWeight: 700, color: PURPLE, background: PURPLE + "14", padding: "2px 8px", borderRadius: 4, fontFamily: T.mono }}>⏰ {when}</span>
        )}
      </div>
      {thesis && <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.45, marginTop: 6 }}>{thesis}</div>}
      {levels.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 8, padding: "7px 10px", background: T.cardAlt, borderRadius: 8 }}>
          {levels.map(([label, val]) => (
            <div key={label} style={{ fontSize: 11, fontFamily: T.mono }}>
              <span style={{ color: T.ink4, fontWeight: 700, textTransform: "uppercase", fontSize: 9.5 }}>{label}</span>{" "}
              <span style={{ color: T.ink, fontWeight: 800 }}>{val}</span>
            </div>
          ))}
        </div>
      )}
      <div style={{ fontSize: 11.5, color: T.ink3, marginTop: 6, lineHeight: 1.5 }}>
        {thirdVal && <div><b style={{ color: T.ink2 }}>{thirdLabel}:</b> {thirdVal}</div>}
        {risk && <div><b style={{ color: T.ink2 }}>Risk:</b> {risk}</div>}
      </div>
    </div>
  );
}

function SessionTimeline({ timeline, currentIdx }) {
  if (!timeline?.length) return null;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 11, fontWeight: 800, color: PURPLE, textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 6 }}>⏰ Today's schedule (ET)</div>
      <div style={{ border: `1px solid ${PURPLE}22`, borderRadius: 10, overflow: "hidden" }}>
        {timeline.map((slot, i) => {
          const now = i === currentIdx;
          return (
            <div key={i} style={{ display: "flex", gap: 12, padding: "9px 14px", alignItems: "baseline",
              background: now ? PURPLE + "1e" : i % 2 === 0 ? PURPLE_BG : T.card,
              boxShadow: now ? `inset 3px 0 0 ${PURPLE}` : "none",
              borderBottom: i < timeline.length - 1 ? `1px solid ${PURPLE}14` : "none" }}>
              <div style={{ minWidth: 132, fontFamily: T.mono, fontSize: 11, fontWeight: 800, color: "#4c1d95", whiteSpace: "nowrap" }}>
                {now && <span style={{ color: "#fff", background: PURPLE, padding: "1px 6px", borderRadius: 4, marginRight: 6, fontSize: 9.5 }}>NOW</span>}
                {txt(slot.time)}
              </div>
              <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.5, flex: 1 }}>
                {txt(slot.action)}
                {(slot.tickers || []).map((t, j) => (
                  <span key={j} style={{ fontFamily: T.mono, fontWeight: 800, fontSize: 10.5, color: PURPLE, background: PURPLE + "14", padding: "1px 7px", borderRadius: 4, marginLeft: 6 }}>{txt(t)}</span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── "Right now" — Alpha Wolf as the live decision maker ──────────────────────
const STATE_STYLE = {
  ACT:           { c: "#16a34a", label: "ACT NOW" },
  TARGET_HIT:    { c: "#16a34a", label: "TARGET HIT" },
  STOPPED:       { c: "#dc2626", label: "STOPPED OUT" },
  IN_WINDOW:     { c: "#7c3aed", label: "IN WINDOW" },
  WAIT:          { c: "#64748b", label: "WAIT" },
  WINDOW_PASSED: { c: "#94a3b8", label: "WINDOW PASSED" },
  NEXT_SESSION:  { c: "#64748b", label: "NEXT SESSION" },
  MONITOR:       { c: "#f59e0b", label: "MONITOR" },
};

function fmtCountdown(min) {
  if (min == null) return "";
  return min >= 60 ? `${Math.floor(min / 60)}h ${min % 60}m` : `${min}m`;
}

function RightNowCard({ now }) {
  if (!now) return null;
  const clock = now.clock || {};
  const open = clock.is_open;
  const ideas = now.ideas || [];
  const next = clock.next_event || {};
  return (
    <div style={{ padding: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: "#fff", background: open ? T.green : T.ink3, padding: "4px 12px", borderRadius: 999 }}>
          {open ? "● MARKET OPEN" : "○ MARKET CLOSED"}
        </span>
        <span style={{ fontSize: 12.5, fontWeight: 800, color: PURPLE, fontFamily: T.mono }}>{clock.session_label}</span>
        <span style={{ fontSize: 12, color: T.ink3, fontFamily: T.mono }}>{clock.et} ET · {clock.weekday}</span>
        <div style={{ flex: 1 }} />
        {next.label && (
          <span style={{ fontSize: 11, color: T.ink3 }}>
            next: <b style={{ color: T.ink2 }}>{next.label}</b> in <b style={{ color: PURPLE, fontFamily: T.mono }}>{fmtCountdown(next.in_min)}</b>
          </span>
        )}
      </div>
      <div style={{ fontSize: 14.5, fontWeight: 800, color: "#4c1d95", lineHeight: 1.45, marginBottom: ideas.length ? 12 : 0 }}>
        🐺 {txt(now.directive)}
      </div>
      {ideas.length > 0 && (
        <div style={{ overflowX: "auto", marginTop: 12 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {["Ticker", "Dir", "Live", "Size", "Note", "State"].map((h) => (
                  <th key={h} style={{ textAlign: "left", padding: "6px 10px", fontSize: 9.5, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4, borderBottom: `1px solid ${T.line}` }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ideas.map((i, k) => {
                const st = STATE_STYLE[i.state] || STATE_STYLE.MONITOR;
                return (
                  <tr key={k} style={{ borderBottom: `1px solid ${T.line2}`, background: st.c + "08" }}>
                    <td style={{ padding: "8px 10px", fontFamily: T.mono, fontWeight: 800, color: T.ink }}>{i.ticker}</td>
                    <td style={{ padding: "8px 10px" }}>
                      <span style={{ fontSize: 9, fontWeight: 800, color: dirColor(i.direction), textTransform: "uppercase" }}>{i.direction}</span>
                    </td>
                    <td style={{ padding: "8px 10px", fontFamily: T.mono, fontSize: 11.5, fontWeight: 700, color: T.ink2 }}>
                      {i.live != null ? fmt$(i.live) : "—"}
                    </td>
                    <td style={{ padding: "8px 10px", fontSize: 10.5, color: T.ink4, fontFamily: T.mono }}>
                      {i.size_usd != null ? `~${fmt$(i.size_usd)} · ${i.size_shares} sh` : "—"}
                    </td>
                    <td style={{ padding: "8px 10px", fontSize: 11.5, color: T.ink3, lineHeight: 1.45, maxWidth: 300 }}>
                      {txt(i.note)}
                    </td>
                    <td style={{ padding: "8px 10px" }}>
                      <span style={{ fontSize: 9.5, fontWeight: 800, color: "#fff", background: st.c, padding: "3px 8px", borderRadius: 4, whiteSpace: "nowrap" }}>{st.label}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {now.pulse?.checked_at && (
        <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 10 }}>
          Pulse: checked {now.pulse.checked_at} ET{now.pulse.alerts?.length ? ` · ${now.pulse.alerts.length} alert${now.pulse.alerts.length !== 1 ? "s" : ""} sent` : " · no alerts"} · auto-checks every 30 min in market hours
        </div>
      )}
    </div>
  );
}

function pnlColor(v) { return (v ?? 0) >= 0 ? T.green : T.red; }
const fmt$ = (v) => (v == null ? "—" : `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

function Stat({ label, value, color }) {
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ fontSize: 10.5, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: ".5px" }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 800, fontFamily: T.mono, color: color || T.ink, marginTop: 2 }}>{value}</div>
    </div>
  );
}

function ActionPill({ action }) {
  const buy = action === "BUY" || action === "COVER";
  const c = buy ? T.green : T.red;
  return <span style={{ fontSize: 9.5, fontWeight: 800, color: "#fff", background: c, padding: "2px 8px", borderRadius: 4 }}>{action}</span>;
}

function PortfolioCard({ portfolio, onChanged }) {
  const [busy, setBusy] = useState(false);
  if (!portfolio) return null;
  const { settings = {}, summary = {}, positions = [], trades = [] } = portfolio;

  const toggle = async () => {
    setBusy(true);
    await setWolfExecution({ enabled: !settings.enabled });
    await onChanged(); setBusy(false);
  };
  const reset = async () => {
    if (!window.confirm("Reset the paper portfolio? All positions and trade history will be cleared.")) return;
    setBusy(true);
    await resetWolfPortfolio();
    await onChanged(); setBusy(false);
  };

  return (
    <div style={{ padding: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
        <SectionTitle sub="simulated fills at live prices · virtual capital">⚡ Paper Trading Portfolio</SectionTitle>
        <div style={{ flex: 1 }} />
        <button onClick={toggle} disabled={busy} style={{
          fontSize: 11, fontWeight: 800, padding: "5px 12px", borderRadius: 8, cursor: "pointer",
          border: `1px solid ${settings.enabled ? T.green : T.line}`,
          background: settings.enabled ? T.green + "16" : T.line2,
          color: settings.enabled ? T.green : T.ink3 }}>
          {settings.enabled ? "● Auto-execute ON" : "○ Auto-execute OFF"}
        </button>
        <button onClick={reset} disabled={busy} style={{
          fontSize: 11, fontWeight: 700, padding: "5px 12px", borderRadius: 8, cursor: "pointer",
          border: `1px solid ${T.line}`, background: T.card, color: T.ink3 }}>
          Reset
        </button>
      </div>

      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 16 }}>
        <Stat label="Equity" value={fmt$(summary.equity)} />
        <Stat label="Cash" value={fmt$(summary.cash)} />
        <Stat label="Unrealized P&L" value={fmt$(summary.unrealized_pnl)} color={pnlColor(summary.unrealized_pnl)} />
        <Stat label="Realized P&L" value={fmt$(summary.realized_pnl)} color={pnlColor(summary.realized_pnl)} />
        <Stat label="Return" value={`${(summary.return_pct ?? 0) >= 0 ? "+" : ""}${summary.return_pct ?? 0}%`} color={pnlColor(summary.return_pct)} />
      </div>

      <div style={{ fontSize: 11.5, fontWeight: 700, color: T.ink3, marginBottom: 6 }}>Open positions ({positions.length})</div>
      {positions.length > 0 ? (
        <div style={{ marginBottom: 16, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {["Ticker", "Dir", "Shares", "Entry", "Last", "P&L", "Opened"].map((h, i) => (
                  <th key={h} style={{ textAlign: i >= 2 && i <= 5 ? "right" : "left", padding: "5px 10px", fontSize: 9.5, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4, borderBottom: `1px solid ${T.line}` }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.ticker} style={{ borderBottom: `1px solid ${T.line2}` }}>
                  <td style={{ padding: "6px 10px", fontFamily: T.mono, fontWeight: 800, color: T.ink }}>{p.ticker}</td>
                  <td style={{ padding: "6px 10px" }}>
                    <span style={{ fontSize: 9.5, fontWeight: 800, color: dirColor(p.direction), background: dirColor(p.direction) + "16", padding: "2px 7px", borderRadius: 4, textTransform: "uppercase" }}>{p.direction}</span>
                  </td>
                  <td style={{ padding: "6px 10px", textAlign: "right", fontFamily: T.mono }}>{p.shares}</td>
                  <td style={{ padding: "6px 10px", textAlign: "right", fontFamily: T.mono }}>{fmt$(p.entry_price)}</td>
                  <td style={{ padding: "6px 10px", textAlign: "right", fontFamily: T.mono }}>{fmt$(p.last_price)}</td>
                  <td style={{ padding: "6px 10px", textAlign: "right", fontFamily: T.mono, fontWeight: 800, color: pnlColor(p.pnl) }}>{(p.pnl ?? 0) >= 0 ? "+" : ""}{fmt$(p.pnl)}</td>
                  <td style={{ padding: "6px 10px", fontFamily: T.mono, color: T.ink4 }}>{p.entry_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ fontSize: 12.5, color: T.ink4, marginBottom: 16 }}>No open positions — run the plan to put capital to work.</div>
      )}

      {trades.length > 0 && (<>
        <div style={{ fontSize: 11.5, fontWeight: 700, color: T.ink3, marginBottom: 6 }}>Recent trades</div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          {trades.slice(0, 10).map((t, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 0", borderBottom: i < Math.min(trades.length, 10) - 1 ? `1px solid ${T.line2}` : "none", fontSize: 12 }}>
              <ActionPill action={t.action} />
              <span style={{ fontFamily: T.mono, fontWeight: 800, color: T.ink }}>{t.ticker}</span>
              <span style={{ color: T.ink3, fontFamily: T.mono }}>{t.shares} sh @ {fmt$(t.price)}</span>
              {t.pnl != null && <span style={{ fontFamily: T.mono, fontWeight: 700, color: pnlColor(t.pnl) }}>{t.pnl >= 0 ? "+" : ""}{fmt$(t.pnl)}</span>}
              <span style={{ flex: 1, color: T.ink4, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.reason}</span>
              <span style={{ color: T.ink4, fontSize: 10.5, whiteSpace: "nowrap" }}>{t.ts}</span>
            </div>
          ))}
        </div>
      </>)}
    </div>
  );
}

function PlanBlock({ title, plan, weekly, currentIdx }) {
  const ideas = plan?.ideas || [];
  return (
    <div style={{ padding: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <SectionTitle sub={weekly ? "swing / position horizon" : "today's actionable read"}>{title}</SectionTitle>
        <BiasPill bias={plan?.bias} />
      </div>
      {plan?.summary && <div style={{ fontSize: 13, color: T.ink2, lineHeight: 1.55, marginBottom: 12 }}>{txt(plan.summary)}</div>}
      {!weekly && <SessionTimeline timeline={plan?.timeline} currentIdx={currentIdx} />}
      {weekly && plan?.themes?.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
          {plan.themes.map((t, i) => <span key={i} style={{ fontSize: 11, padding: "3px 10px", borderRadius: 6, background: PURPLE + "14", color: PURPLE, fontWeight: 600 }}>{txt(t)}</span>)}
        </div>
      )}
      {ideas.length > 0 ? (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {["Ticker", "Dir", "Levels", weekly ? "Catalyst" : "Trigger", "Thesis & Risk"].map((h) => (
                  <th key={h} style={{ textAlign: "left", padding: "6px 10px", fontSize: 9.5, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4, borderBottom: `1px solid ${T.line}` }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ideas.map((idea, i) => {
                const dc = dirColor(idea.direction);
                return (
                  <tr key={i} style={{ borderBottom: `1px solid ${T.line2}` }}>
                    <td style={{ padding: "8px 10px", fontFamily: T.mono, fontWeight: 800, color: T.ink, verticalAlign: "top" }}>
                      {txt(idea.ticker)}<br/>
                      {!weekly && idea.when && <span style={{ fontSize: 9, fontWeight: 700, color: PURPLE, fontFamily: T.mono, marginTop: 4, display: "inline-block" }}>⏰ {txt(idea.when)}</span>}
                    </td>
                    <td style={{ padding: "8px 10px", verticalAlign: "top" }}>
                      <span style={{ fontSize: 9, fontWeight: 800, color: dc, background: dc + "16", padding: "2px 7px", borderRadius: 4, textTransform: "uppercase" }}>{txt(idea.direction) || "n/a"}</span>
                    </td>
                    <td style={{ padding: "8px 10px", fontSize: 11, fontFamily: T.mono, verticalAlign: "top", whiteSpace: "nowrap" }}>
                      {!weekly ? (
                        <>
                          <div><span style={{ color: T.ink4, fontSize: 9.5 }}>ENT</span> {txt(idea.entry)}</div>
                          <div><span style={{ color: T.ink4, fontSize: 9.5 }}>TGT</span> {txt(idea.target)}</div>
                          <div><span style={{ color: T.ink4, fontSize: 9.5 }}>STP</span> {txt(idea.stop)}</div>
                        </>
                      ) : "—"}
                    </td>
                    <td style={{ padding: "8px 10px", fontSize: 11.5, color: T.ink2, verticalAlign: "top", maxWidth: 200 }}>
                      {txt(weekly ? idea.catalyst : idea.trigger)}
                    </td>
                    <td style={{ padding: "8px 10px", fontSize: 11.5, color: T.ink3, lineHeight: 1.45, verticalAlign: "top", minWidth: 250 }}>
                      <div style={{ color: T.ink2, marginBottom: 4 }}>{txt(idea.thesis)}</div>
                      {idea.risk && <div style={{ fontSize: 10.5 }}><b style={{ color: T.ink4 }}>RISK:</b> {txt(idea.risk)}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ fontSize: 12.5, color: T.ink4 }}>No specific ideas this run.</div>
      )}
    </div>
  );
}

export default function AlphaWolf({ status, agentError }) {
  const { data, refresh } = useAgentData("alpha_wolf");
  const [refreshing, setRefreshing] = useState(false);
  const [portfolio, setPortfolio] = useState(null);
  const [nowData, setNowData] = useState(null);
  const plan = data?.plan || null;
  const busy = refreshing || status === "running";

  const refreshPortfolio = useCallback(async () => {
    try { setPortfolio(await getWolfPortfolio()); } catch { /* backend offline */ }
  }, []);
  useEffect(() => {
    refreshPortfolio();
    const id = setInterval(refreshPortfolio, 15000);
    return () => clearInterval(id);
  }, [refreshPortfolio]);

  // Live "what to do right now" — market clock + ideas scored vs live quotes
  const refreshNow = useCallback(async () => {
    try { setNowData(await getWolfNow()); } catch { /* backend offline */ }
  }, []);
  useEffect(() => {
    refreshNow();
    const id = setInterval(refreshNow, 60000);
    return () => clearInterval(id);
  }, [refreshNow]);

  const run = async () => {
    setRefreshing(true);
    await triggerAgent("alpha_wolf");
    setTimeout(refresh, 8000); setTimeout(refresh, 20000); setTimeout(refresh, 35000);
    setTimeout(refreshPortfolio, 20000); setTimeout(refreshPortfolio, 36000);
    setTimeout(() => setRefreshing(false), 3000);
  };

  const sourcesUsed = plan?.sources_used || [];
  const inputs = plan?.inputs || {};

  return (
    <div>
      <TabHeader icon="🐺" color={PURPLE} title="Alpha Wolf"
        sub="Master strategist · fuses the pack into a Daily + Weekly plan and executes it (paper)"
        actions={<>
          <Pill mono c={T.ink3}>daily · 08:30</Pill>
          {plan && <Pill c={PURPLE} bg={PURPLE_BG}>{sourcesUsed.length}/6 agents</Pill>}
          <EmailPreviewButton agentId="alpha_wolf" label="Preview plan email" />
          <AgentControls agentId="alpha_wolf" onRun={run} busy={busy} refresh={refresh} runLabel="Run plan" runningLabel="Synthesizing…" />
        </>}
      />
      <div style={{ padding: "0" }}>
        <ErrorBanner error={agentError} />

        <DashboardGrid id="alpha_wolf" defaultLayout={[
          { i: "right_now", x: 0, y: 0, w: 12, h: 7 },
          { i: "pack_status", x: 0, y: 7, w: 12, h: 4 },
          { i: "portfolio", x: 0, y: 11, w: 12, h: 9 },
          { i: "execution", x: 0, y: 20, w: 12, h: 5 },
          { i: "headline", x: 0, y: 25, w: 12, h: 4 },
          { i: "regime", x: 0, y: 29, w: 12, h: 5 },
          { i: "confluence", x: 0, y: 34, w: 12, h: 6 },
          { i: "daily", x: 0, y: 40, w: 12, h: 10 },
          { i: "weekly", x: 0, y: 50, w: 12, h: 10 },
          { i: "catalysts", x: 0, y: 60, w: 4, h: 6 },
          { i: "avoid", x: 4, y: 60, w: 4, h: 6 },
          { i: "risk", x: 8, y: 60, w: 4, h: 6 },
          { i: "inputs", x: 0, y: 66, w: 12, h: 8 }
        ]}>
          <div key="right_now" data-title="Live Decision Maker">
            <RightNowCard now={nowData} />
          </div>

          <div key="pack_status" data-title="The Pack — Sub-Agents" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: T.ink3, marginBottom: 8 }}>The pack — sub-agents feeding Alpha Wolf</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {ALL_SOURCES.map((id) => {
              const on = sourcesUsed.includes(id);
              return (
                <span key={id} style={{ fontSize: 11, padding: "3px 10px", borderRadius: 6, fontWeight: 600,
                  background: on ? PURPLE + "16" : T.line2, color: on ? PURPLE : T.ink4,
                  border: `1px solid ${on ? PURPLE + "44" : "transparent"}` }}>
                  {on ? "● " : "○ "}{SOURCE_LABELS[id]}
                </span>
              );
            })}
          </div>
          {plan?.generated_at && <div style={{ fontSize: 11, color: T.ink4, marginTop: 10 }}>Last synthesized: {plan.generated_at}</div>}
          </div>

          <div key="portfolio" data-title="Paper Trading Portfolio">
            <PortfolioCard portfolio={portfolio} onChanged={refreshPortfolio} />
          </div>

        {/* Execution report from the latest run */}
        {plan?.execution && (
          plan.execution.enabled === false ? (
            <div key="execution" data-title="Execution Report" style={{ padding: 14 }}>
              <div style={{ fontSize: 12.5, color: T.ink3 }}>⏸ {plan.execution.note || "Trade execution was OFF for the last run."}</div>
            </div>
          ) : (plan.execution.executed || []).length > 0 && (
            <div key="execution" data-title="Execution Report" style={{ padding: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 800, color: T.green, marginBottom: 8 }}>
                ⚡ Executed {plan.execution.executed.length} trade{plan.execution.executed.length !== 1 ? "s" : ""} on the last run
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {plan.execution.executed.map((t, i) => (
                  <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5,
                    border: `1px solid ${T.line}`, borderRadius: 8, padding: "4px 10px", background: T.card }}>
                    <ActionPill action={t.action} />
                    <b style={{ fontFamily: T.mono }}>{t.ticker}</b>
                    <span style={{ color: T.ink3, fontFamily: T.mono }}>{t.shares} sh @ {fmt$(t.price)}</span>
                  </span>
                ))}
              </div>
            </div>
          )
        )}

        {!plan ? (
          <div key="empty" data-title="No game-plan yet">
            <EmptyState icon="🐺" title="No game-plan yet"
              hint="Run the sub-agents (Wolf, Compass, Strategy Scout, Capitol Tracker, Options Flow, Earnings), then click 'Run plan'." />
          </div>
        ) : (<>

          {/* Headline action — the single most important move right now */}
          {plan.headline && (
            <div key="headline" data-title="Headline Action" style={{ padding: 15 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <StancePill stance={plan.stance} />
                <div style={{ fontSize: 16, fontWeight: 800, color: "#4c1d95", flex: 1, minWidth: 0, lineHeight: 1.4 }}>{txt(plan.headline)}</div>
              </div>
            </div>
          )}

          {/* Regime read */}
          {plan.regime && (
            <div key="regime" data-title="Market Regime" style={{ padding: 15 }}>
              <div style={{ display: "flex", gap: 14 }}>
                <LufiAvatar size={38} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 5 }}>Market regime <span style={{ fontSize: 11, color: T.ink4 }}>by Alpha Wolf · Qwen3</span></div>
                  <div style={{ fontSize: 13.5, color: "#4c1d95", lineHeight: 1.55 }}>{txt(plan.regime)}</div>
                </div>
              </div>
            </div>
          )}

          {/* Confluence — where multiple agents agree */}
          {(plan.confluence || []).length > 0 && (
            <div key="confluence" data-title="🎯 Confluence" style={{ padding: 15 }}>
              <SectionTitle sub="where multiple agents line up — highest conviction">🎯 Confluence</SectionTitle>
              <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, color: T.ink2, lineHeight: 1.7 }}>
                {plan.confluence.map((c, i) => <li key={i}>{txt(c)}</li>)}
              </ul>
            </div>
          )}

          <div key="daily" data-title="Daily Plan"><PlanBlock title="Daily Plan" plan={plan.daily} weekly={false} currentIdx={nowData?.current_slot?.index} /></div>
          <div key="weekly" data-title="Weekly Plan"><PlanBlock title="Weekly Plan" plan={plan.weekly} weekly={true} /></div>

          {/* Catalysts + avoid + risk */}
          <div key="catalysts" data-title="Catalysts" style={{ padding: 15 }}>
            {(plan.catalysts || []).length > 0 ? (
              <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, color: T.ink2, lineHeight: 1.7 }}>
                {plan.catalysts.map((c, i) => <li key={i}>{txt(c)}</li>)}
              </ul>
            ) : <div style={{ fontSize: 12.5, color: T.ink4, marginTop: 8 }}>None flagged.</div>}
          </div>
          <div key="avoid" data-title="⛔ Avoid" style={{ padding: 15 }}>
            {(plan.avoid || []).length > 0 ? (
              <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, color: T.ink2, lineHeight: 1.7 }}>
                {plan.avoid.map((c, i) => <li key={i}>{txt(c)}</li>)}
              </ul>
            ) : <div style={{ fontSize: 12.5, color: T.ink4, marginTop: 8 }}>Nothing flagged.</div>}
          </div>
          <div key="risk" data-title="Risk management" style={{ padding: 15 }}>
            <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.55, marginTop: 8 }}>{txt(plan.risk_notes) || "—"}</div>
          </div>

          {/* Pack intel snapshot */}
          {Object.keys(inputs).length > 0 && (
            <div key="inputs" data-title="Pack Intel" style={{ padding: 15 }}>
              <SectionTitle sub="the raw signals Alpha Wolf reasoned over">Pack intel</SectionTitle>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                {Object.entries(inputs).map(([k, v]) => (
                  <div key={k} style={{ fontSize: 12, color: T.ink3, lineHeight: 1.45 }}>
                    <span style={{ fontWeight: 800, color: PURPLE, fontFamily: T.mono, fontSize: 11 }}>{k}</span> &nbsp;{txt(v)}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Disclaimer */}
          <div key="disclaimer" data-title="Disclaimer">
            <div style={{ fontSize: 11, color: T.ink4, lineHeight: 1.5, padding: "8px 15px" }}>{txt(plan.disclaimer)}</div>
          </div>
        </>)}
        </DashboardGrid>
      </div>
    </div>
  );
}
