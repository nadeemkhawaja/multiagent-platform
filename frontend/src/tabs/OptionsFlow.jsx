// ============================================================================
// OptionsFlow.jsx — Unusual options activity dashboard for TOS traders
// ============================================================================
import { useState } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader, Delta } from "../theme/ui";
import { useAgentData, triggerAgent } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar } from "../components/Common";

const VIOLET = "#7c5cf6"; const VIOLET_BG = "#f1edfe";
const GREEN = "#16a34a"; const GREEN_BG = "#f0fdf4";
const RED = "#dc2626"; const RED_BG = "#fef2f2";
const AMBER = "#d97706"; const AMBER_BG = "#fffbeb";

function StatChip({ label, value, color, bg }) {
  return (
    <Card pad={14} style={{ textAlign: "center", background: bg || T.cardAlt, borderColor: color + "33" }}>
      <div style={{ fontSize: 24, fontWeight: 800, fontFamily: T.mono, color }}>{value}</div>
      <div style={{ fontSize: 11.5, color: T.ink4, marginTop: 2, fontWeight: 600 }}>{label}</div>
    </Card>
  );
}

function SignalCard({ s }) {
  const isCall = s.type === "call";
  const col = isCall ? VIOLET : RED;
  const bg  = isCall ? VIOLET_BG : RED_BG;
  const ivHot = s.elevated_iv;
  return (
    <Card pad={16} style={{ borderColor: col + "33" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 10 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 20, fontWeight: 800, fontFamily: T.mono, color: col }}>{s.ticker}</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: col, background: bg, padding: "3px 9px", borderRadius: 6 }}>{s.type?.toUpperCase()}-HEAVY</span>
            {ivHot && <span style={{ fontSize: 10, fontWeight: 700, color: AMBER, background: AMBER_BG, padding: "2px 6px", borderRadius: 5 }}>HIGH IV</span>}
          </div>
          <div style={{ fontSize: 12, color: T.ink4, marginTop: 3 }}>Spot ${s.spot?.toFixed(2)}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 13, fontWeight: 700, fontFamily: T.mono, color: ivHot ? AMBER : T.ink }}>{s.avg_iv?.toFixed(1)}% IV</div>
          <div style={{ fontSize: 11, color: T.ink4 }}>~{s.iv_pct}%ile rank</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 10 }}>
        <div style={{ background: T.cardAlt, borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
          <div style={{ fontSize: 11, color: T.ink4, fontWeight: 600 }}>P/C Ratio</div>
          <div style={{ fontSize: 15, fontWeight: 700, fontFamily: T.mono, color: s.pc_ratio > 1.2 ? RED : s.pc_ratio < 0.7 ? GREEN : T.ink }}>{s.pc_ratio?.toFixed(2)}</div>
        </div>
        <div style={{ background: T.cardAlt, borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
          <div style={{ fontSize: 11, color: T.ink4, fontWeight: 600 }}>Call Vol</div>
          <div style={{ fontSize: 15, fontWeight: 700, fontFamily: T.mono, color: GREEN }}>{(s.call_vol || 0).toLocaleString()}</div>
        </div>
        <div style={{ background: T.cardAlt, borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
          <div style={{ fontSize: 11, color: T.ink4, fontWeight: 600 }}>Put Vol</div>
          <div style={{ fontSize: 15, fontWeight: 700, fontFamily: T.mono, color: RED }}>{(s.put_vol || 0).toLocaleString()}</div>
        </div>
      </div>

      {/* Unusual contracts */}
      {s.signals?.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>Unusual contracts</div>
          {s.signals.slice(0, 3).map((sig, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0", fontSize: 12, borderBottom: i < Math.min(s.signals.length, 3) - 1 ? `1px solid ${T.line2}` : "none" }}>
              <span style={{ fontWeight: 700, color: sig.side === "call" ? VIOLET : RED, width: 38, fontFamily: T.mono }}>{sig.side?.toUpperCase()}</span>
              <span style={{ fontFamily: T.mono, color: T.ink3 }}>@${sig.strike}</span>
              <span style={{ fontFamily: T.mono, fontSize: 11, color: T.ink4 }}>{sig.expiry}</span>
              <span style={{ fontFamily: T.mono, color: T.ink2 }}>{(sig.vol || 0).toLocaleString()} vol</span>
              <span style={{ marginLeft: "auto", fontWeight: 700, fontFamily: T.mono, color: AMBER }}>${sig.premium_k?.toFixed(0)}K</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function TableHeader() {
  const s = { fontSize: 10, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4 };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "52px 1fr 80px 80px 80px 70px 70px", gap: 8, padding: "9px 18px", borderBottom: `1px solid ${T.line}`, background: T.cardAlt }}>
      <span style={s}>Ticker</span><span style={s}>Spot</span><span style={{ ...s, textAlign: "right" }}>IV%</span>
      <span style={{ ...s, textAlign: "right" }}>IV Rank</span><span style={{ ...s, textAlign: "right" }}>P/C</span>
      <span style={{ ...s, textAlign: "right" }}>Call Vol</span><span style={{ ...s, textAlign: "right" }}>Bias</span>
    </div>
  );
}

export default function OptionsFlow({ status, agentError }) {
  const { data, refresh } = useAgentData("options_flow");
  const [refreshing, setRefreshing] = useState(false);
  const [view, setView] = useState("cards"); // cards | table

  const flow = data?.flow || null;
  const signals = flow?.signals || [];
  const top5 = flow?.top5 || [];
  const commentary = flow?.commentary || "";
  const busy = refreshing || status === "running";

  const run = async () => {
    setRefreshing(true);
    await triggerAgent("options_flow");
    setTimeout(refresh, 10000); setTimeout(refresh, 25000);
    setTimeout(() => setRefreshing(false), 3000);
  };

  const highIV = signals.filter((s) => s.elevated_iv);
  const callHeavy = signals.filter((s) => s.type === "call" && s.pc_ratio < 0.7);
  const putHeavy  = signals.filter((s) => s.type === "put"  && s.pc_ratio > 1.3);

  return (
    <div>
      <TabHeader icon="⚡" color={VIOLET} title="Options Flow"
        sub="Unusual options activity scanner · IV percentile · P/C ratio · TOS-ready"
        actions={<>
          <Pill mono c={T.ink3}>every 2h</Pill>
          {flow && <>
            <Pill c={VIOLET} bg={VIOLET_BG}>{flow.unusual_count} unusual</Pill>
            <Pill c={AMBER} bg={AMBER_BG}>{highIV.length} high IV</Pill>
          </>}
          <EmailPreviewButton agentId="options_flow" label="Preview email" />
          <AgentControls agentId="options_flow" onRun={run} busy={busy} refresh={refresh} runLabel="Scan now" runningLabel="Scanning…" />
        </>}
      />
      <div className="om-stagger" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 11 }}>
        <ErrorBanner error={agentError} />
        {!flow ? (
          <EmptyState icon="⚡" title="No options data yet" hint="Click 'Scan now' to analyze your watchlist for unusual options activity." />
        ) : (<>

          {/* Stats */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
            <StatChip label="Scanned"       value={flow.scanned || 0}         color={T.ink3}  />
            <StatChip label="Unusual signals" value={flow.unusual_count || 0} color={VIOLET} bg={VIOLET_BG} />
            <StatChip label="High IV"        value={highIV.length}             color={AMBER}  bg={AMBER_BG} />
            <StatChip label="Call-heavy"     value={callHeavy.length}          color={GREEN}  bg={GREEN_BG} />
          </div>

          {/* Commentary */}
          {commentary && (
            <Card pad={15} style={{ background: T.cardAlt }}>
              <div style={{ display: "flex", gap: 14 }}>
                <LufiAvatar size={38} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 5 }}>Flow Analysis <span style={{ fontSize: 11, color: T.ink4 }}>by Lufi · Qwen3</span></div>
                  <div style={{ fontSize: 13.5, color: T.ink2, lineHeight: 1.55, whiteSpace: "pre-line" }}>{commentary}</div>
                </div>
              </div>
            </Card>
          )}

          {/* Disclaimer */}
          <Card pad={12} style={{ background: AMBER_BG, borderColor: AMBER + "44" }}>
            <div style={{ fontSize: 11.5, color: "#92400e" }}>
              <b>⚠ Trading disclaimer:</b> Options flow data is educational only. Unusual volume does not confirm direction. Always apply your own analysis before entering any TOS position.
            </div>
          </Card>

          {/* View toggle */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <SectionTitle sub={`${signals.length} tickers with unusual activity · ${flow.generated_at}`}>Unusual activity</SectionTitle>
            <div style={{ display: "flex", gap: 6 }}>
              {["cards", "table"].map((v) => (
                <button key={v} onClick={() => setView(v)} style={{ padding: "4px 12px", borderRadius: 7, border: `1px solid ${view === v ? VIOLET : T.line}`, background: view === v ? VIOLET : "transparent", color: view === v ? "#fff" : T.ink2, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: T.sans }}>
                  {v === "cards" ? "⊞ Cards" : "☰ Table"}
                </button>
              ))}
            </div>
          </div>

          {view === "cards" ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(310px, 1fr))", gap: 14 }}>
              {top5.map((s) => <SignalCard key={s.ticker} s={s} />)}
            </div>
          ) : (
            <Card pad={0} style={{ overflow: "hidden" }}>
              <TableHeader />
              {signals.map((s, i) => {
                const col = s.type === "call" ? VIOLET : RED;
                return (
                  <div key={s.ticker} style={{ display: "grid", gridTemplateColumns: "52px 1fr 80px 80px 80px 70px 70px", gap: 8, padding: "10px 18px", borderBottom: `1px solid ${T.line2}`, fontSize: 13, background: i % 2 === 0 ? "transparent" : T.cardAlt + "44" }}>
                    <span style={{ fontWeight: 800, fontFamily: T.mono, color: col }}>{s.ticker}</span>
                    <span style={{ fontFamily: T.mono, color: T.ink2 }}>${s.spot?.toFixed(2)}</span>
                    <span style={{ fontFamily: T.mono, textAlign: "right", color: s.elevated_iv ? AMBER : T.ink }}>{s.avg_iv?.toFixed(1)}%</span>
                    <span style={{ fontFamily: T.mono, textAlign: "right", color: T.ink3 }}>~{s.iv_pct}%</span>
                    <span style={{ fontFamily: T.mono, textAlign: "right", color: s.pc_ratio > 1.2 ? RED : s.pc_ratio < 0.7 ? GREEN : T.ink }}>{s.pc_ratio?.toFixed(2)}</span>
                    <span style={{ fontFamily: T.mono, textAlign: "right", color: GREEN }}>{(s.call_vol || 0).toLocaleString()}</span>
                    <span style={{ textAlign: "right", fontSize: 11, fontWeight: 700, color: col, background: col + "18", padding: "2px 7px", borderRadius: 5 }}>{s.type?.toUpperCase()}</span>
                  </div>
                );
              })}
            </Card>
          )}
        </>)}
      </div>
    </div>
  );
}
