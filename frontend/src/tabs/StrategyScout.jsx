// ============================================================================
// StrategyScout.jsx — top trading strategies trending on Reddit + TradingView,
// distilled into a ranked list by Lufi (LLM).
// ============================================================================
import { useState } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader } from "../theme/ui";
import { StrategyIcon } from "../theme/icons";
import { useAgentData, triggerAgent } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar } from "../components/Common";

const ACCENT = AGENT_COLOR.strategy_scout;

const TYPE_COLOR = {
  momentum: T.green, breakout: T.blue, "mean-reversion": T.violet,
  "trend-following": T.teal, options: T.red, scalping: T.amber, swing: "#0ea5e9", other: T.ink3,
};
const typeCol = (t) => TYPE_COLOR[t] || T.ink3;
const srcCol = (s) => (s === "TradingView" ? "#2563eb" : "#ff4500");

function StrategyCard({ s, rank }) {
  const col = typeCol(s.type);
  return (
    <Card pad={16} style={{ position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: 0, left: 0, bottom: 0, width: 3, background: col }} />
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <div style={{ width: 26, height: 26, borderRadius: 7, background: ACCENT + "16", color: ACCENT, display: "grid", placeItems: "center", fontWeight: 800, fontSize: 12, fontFamily: T.mono, flex: "0 0 auto" }}>{rank}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 700, letterSpacing: -0.2 }}>{s.name}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 5, flexWrap: "wrap" }}>
            <span style={{ fontSize: 10, fontWeight: 700, color: col, background: col + "18", padding: "2px 8px", borderRadius: 6, textTransform: "capitalize" }}>{s.type}</span>
            <span style={{ fontSize: 10, fontWeight: 600, color: T.ink4, fontFamily: T.mono }}>{s.timeframe}</span>
            {s.source && <span style={{ fontSize: 10, color: T.ink4 }}>· {s.source}</span>}
          </div>
        </div>
      </div>
      {s.summary && <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.5, marginTop: 10 }}>{s.summary}</div>}
    </Card>
  );
}

export default function StrategyScout({ status, agentError }) {
  const { data, refresh } = useAgentData("strategy_scout");
  const d = data?.scout || {};
  const strategies = d.strategies || [];
  const discussions = d.discussions || [];
  const sources = d.sources || {};
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    await triggerAgent("strategy_scout");
    setTimeout(refresh, 6000); setTimeout(refresh, 15000);
    setTimeout(() => setRunning(false), 2000);
  };
  const busy = running || status === "running";
  const empty = strategies.length === 0 && discussions.length === 0;

  return (
    <div>
      <TabHeader icon="✦" color={ACCENT} title="Strategy Scout" sub="Reddit + TradingView · top trading strategies, distilled by Lufi"
        actions={<>
          <Pill mono c={T.ink3}>digest 10:00 daily</Pill>
          <EmailPreviewButton agentId="strategy_scout" label="Preview digest" />
          <AgentControls agentId="strategy_scout" onRun={run} busy={busy} refresh={refresh} runLabel="Scan now" runningLabel="Scanning…" />
        </>} />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>
        <ErrorBanner error={agentError} />

        {empty ? (
          <EmptyState icon="✦" title="No strategies scanned yet"
            hint="Click Scan now to pull trending posts from Reddit's trading subreddits and TradingView, then have Lufi distill the top strategies." />
        ) : (
          <>
            <Card pad={16} style={{ background: T.cardAlt }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <LufiAvatar size={34} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 800 }}>Lufi distilled {strategies.length} strategies <span style={{ fontWeight: 600, color: T.ink4 }}>from this week's chatter</span></div>
                  <div style={{ fontSize: 11.5, color: T.ink4, marginTop: 1 }}>Synthesized from trending Reddit posts + TradingView ideas — not financial advice.</div>
                </div>
                <Pill mono c={ACCENT} bg={ACCENT + "16"}>{sources.reddit || 0} Reddit · {sources.tradingview || 0} TradingView</Pill>
              </div>
            </Card>

            {strategies.length > 0 && (
              <div>
                <SectionTitle sub="Ranked by how much they're being discussed right now">Top strategies</SectionTitle>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
                  {strategies.map((s, i) => <StrategyCard key={i} s={s} rank={i + 1} />)}
                </div>
              </div>
            )}

            {discussions.length > 0 && (
              <Card pad={20}>
                <SectionTitle sub="Source posts feeding the analysis" right={<Pill mono c={T.ink3}>{discussions.length}</Pill>}>Trending discussions</SectionTitle>
                <div style={{ display: "flex", flexDirection: "column" }}>
                  {discussions.map((p, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 11, padding: "10px 0", borderBottom: i < discussions.length - 1 ? `1px solid ${T.line2}` : "none" }}>
                      <span style={{ fontSize: 9.5, fontWeight: 700, color: srcCol(p.src), background: srcCol(p.src) + "18", padding: "3px 8px", borderRadius: 6, whiteSpace: "nowrap", flex: "0 0 auto", width: 92, textAlign: "center" }}>{p.sub}</span>
                      <a href={p.url} target="_blank" rel="noreferrer" style={{ flex: 1, minWidth: 0, fontSize: 13, color: T.ink, textDecoration: "none", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.title}</a>
                      {p.score != null && <span style={{ fontFamily: T.mono, fontSize: 11, color: T.green, flex: "0 0 auto" }}>▲ {Number(p.score).toLocaleString()}</span>}
                      {p.comments != null && <span style={{ fontFamily: T.mono, fontSize: 11, color: T.ink4, flex: "0 0 auto" }}>💬 {p.comments}</span>}
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}
