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
    <Card pad={15} style={{ borderColor: PURPLE + "55", background: T.card }}>
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
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: 8 }}>
          {ideas.map((i, k) => {
            const st = STATE_STYLE[i.state] || STATE_STYLE.MONITOR;
            return (
              <div key={k} style={{ border: `1px solid ${st.c}33`, borderRadius: 10, padding: "9px 12px", background: st.c + "08" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
                  <span style={{ fontFamily: T.mono, fontWeight: 800, fontSize: 13.5, color: T.ink }}>{i.ticker}</span>
                  <span style={{ fontSize: 9, fontWeight: 800, color: dirColor(i.direction), textTransform: "uppercase" }}>{i.direction}</span>
                  {i.live != null && <span style={{ fontFamily: T.mono, fontSize: 11.5, fontWeight: 700, color: T.ink2 }}>{fmt$(i.live)}</span>}
                  <div style={{ flex: 1 }} />
                  <span style={{ fontSize: 9.5, fontWeight: 800, color: "#fff", background: st.c, padding: "2px 8px", borderRadius: 4 }}>{st.label}</span>
                </div>
                <div style={{ fontSize: 11.5, color: T.ink3, marginTop: 5, lineHeight: 1.45 }}>{txt(i.note)}</div>
                {i.size_usd != null && (
                  <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 3, fontFamily: T.mono }}>size ~{fmt$(i.size_usd)} · {i.size_shares} sh</div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {now.pulse?.checked_at && (
        <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 10 }}>
          Pulse: checked {now.pulse.checked_at} ET{now.pulse.alerts?.length ? ` · ${now.pulse.alerts.length} alert${now.pulse.alerts.length !== 1 ? "s" : ""} sent` : " · no alerts"} · auto-checks every 30 min in market hours
        </div>
      )}
    </Card>
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
    <Card pad={15} style={{ borderColor: PURPLE + "33" }}>
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
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 10, marginBottom: 16 }}>
          {positions.map((p) => (
            <div key={p.ticker} style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: "10px 12px", background: T.card }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontFamily: T.mono, fontWeight: 800, fontSize: 14, color: T.ink }}>{p.ticker}</span>
                <span style={{ fontSize: 9.5, fontWeight: 800, color: dirColor(p.direction), background: dirColor(p.direction) + "16", padding: "2px 8px", borderRadius: 4, textTransform: "uppercase" }}>{p.direction}</span>
                <div style={{ flex: 1 }} />
                <span style={{ fontFamily: T.mono, fontWeight: 800, fontSize: 12.5, color: pnlColor(p.pnl) }}>{(p.pnl ?? 0) >= 0 ? "+" : ""}{fmt$(p.pnl)}</span>
              </div>
              <div style={{ fontSize: 11, color: T.ink3, marginTop: 5, fontFamily: T.mono }}>
                {p.shares} sh · in {fmt$(p.entry_price)} · last {fmt$(p.last_price)}
              </div>
              <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 3 }}>{p.entry_date}</div>
            </div>
          ))}
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
    </Card>
  );
}

function PlanBlock({ title, plan, weekly, currentIdx }) {
  const ideas = plan?.ideas || [];
  return (
    <Card pad={15}>
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
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10 }}>
          {ideas.map((idea, i) => <IdeaCard key={i} idea={idea} weekly={weekly} />)}
        </div>
      ) : (
        <div style={{ fontSize: 12.5, color: T.ink4 }}>No specific ideas this run.</div>
      )}
    </Card>
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
      <div className="om-stagger" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 11 }}>
        <ErrorBanner error={agentError} />

        {/* Live decision maker: market clock + what to do right now */}
        <RightNowCard now={nowData} />

        {/* Pack status: which sub-agents have fed the plan */}
        <Card pad={16} style={{ background: T.cardAlt }}>
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
        </Card>

        {/* Paper portfolio — always visible so the trader can track P&L */}
        <PortfolioCard portfolio={portfolio} onChanged={refreshPortfolio} />

        {/* Execution report from the latest run */}
        {plan?.execution && (
          plan.execution.enabled === false ? (
            <Card pad={14} style={{ background: T.cardAlt }}>
              <div style={{ fontSize: 12.5, color: T.ink3 }}>⏸ {plan.execution.note || "Trade execution was OFF for the last run."}</div>
            </Card>
          ) : (plan.execution.executed || []).length > 0 && (
            <Card pad={16} style={{ borderColor: T.green + "44", background: T.green + "08" }}>
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
            </Card>
          )
        )}

        {!plan ? (
          <EmptyState icon="🐺" title="No game-plan yet"
            hint="Run the sub-agents (Wolf, Compass, Strategy Scout, Capitol Tracker, Options Flow, Earnings), then click 'Run plan'." />
        ) : (<>

          {/* Headline action — the single most important move right now */}
          {plan.headline && (
            <Card pad={15} style={{ background: PURPLE_BG, borderColor: PURPLE + "44" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <StancePill stance={plan.stance} />
                <div style={{ fontSize: 16, fontWeight: 800, color: "#4c1d95", flex: 1, minWidth: 0, lineHeight: 1.4 }}>{txt(plan.headline)}</div>
              </div>
            </Card>
          )}

          {/* Regime read */}
          {plan.regime && (
            <Card pad={15} style={{ background: PURPLE_BG, borderColor: PURPLE + "33" }}>
              <div style={{ display: "flex", gap: 14 }}>
                <LufiAvatar size={38} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 5 }}>Market regime <span style={{ fontSize: 11, color: T.ink4 }}>by Alpha Wolf · Qwen3</span></div>
                  <div style={{ fontSize: 13.5, color: "#4c1d95", lineHeight: 1.55 }}>{txt(plan.regime)}</div>
                </div>
              </div>
            </Card>
          )}

          {/* Confluence — where multiple agents agree */}
          {(plan.confluence || []).length > 0 && (
            <Card pad={15} style={{ borderColor: PURPLE + "33" }}>
              <SectionTitle sub="where multiple agents line up — highest conviction">🎯 Confluence</SectionTitle>
              <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, color: T.ink2, lineHeight: 1.7 }}>
                {plan.confluence.map((c, i) => <li key={i}>{txt(c)}</li>)}
              </ul>
            </Card>
          )}

          <PlanBlock title="Daily Plan" plan={plan.daily} weekly={false} currentIdx={nowData?.current_slot?.index} />
          <PlanBlock title="Weekly Plan" plan={plan.weekly} weekly={true} />

          {/* Catalysts + avoid + risk */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
            <Card pad={15}>
              <SectionTitle sub="upcoming events to watch">Catalysts</SectionTitle>
              {(plan.catalysts || []).length > 0 ? (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, color: T.ink2, lineHeight: 1.7 }}>
                  {plan.catalysts.map((c, i) => <li key={i}>{txt(c)}</li>)}
                </ul>
              ) : <div style={{ fontSize: 12.5, color: T.ink4, marginTop: 8 }}>None flagged.</div>}
            </Card>
            <Card pad={15} style={{ borderColor: T.red + "33" }}>
              <SectionTitle sub="what to stay away from">⛔ Avoid</SectionTitle>
              {(plan.avoid || []).length > 0 ? (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, color: T.ink2, lineHeight: 1.7 }}>
                  {plan.avoid.map((c, i) => <li key={i}>{txt(c)}</li>)}
                </ul>
              ) : <div style={{ fontSize: 12.5, color: T.ink4, marginTop: 8 }}>Nothing flagged.</div>}
            </Card>
            <Card pad={15}>
              <SectionTitle sub="how to size and protect">Risk management</SectionTitle>
              <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.55, marginTop: 8 }}>{txt(plan.risk_notes) || "—"}</div>
            </Card>
          </div>

          {/* Pack intel snapshot */}
          {Object.keys(inputs).length > 0 && (
            <Card pad={15}>
              <SectionTitle sub="the raw signals Alpha Wolf reasoned over">Pack intel</SectionTitle>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                {Object.entries(inputs).map(([k, v]) => (
                  <div key={k} style={{ fontSize: 12, color: T.ink3, lineHeight: 1.45 }}>
                    <span style={{ fontWeight: 800, color: PURPLE, fontFamily: T.mono, fontSize: 11 }}>{k}</span> &nbsp;{txt(v)}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Disclaimer */}
          <div style={{ fontSize: 11, color: T.ink4, lineHeight: 1.5, padding: "0 4px" }}>{txt(plan.disclaimer)}</div>
        </>)}
      </div>
    </div>
  );
}
