// ============================================================================
// AlphaWolf.jsx — Master agent. Synthesizes the trading pack (Wolf, Compass,
// Strategy Scout, Capitol Tracker, Options Flow, Earnings) into a Daily +
// Weekly trade game-plan. Educational only — never places trades.
// ============================================================================
import { useState } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent } from "../state/api";
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

function dirColor(d) {
  const v = String(d || "").toLowerCase();
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

function IdeaCard({ idea, weekly }) {
  const dc = dirColor(idea.direction);
  const thirdLabel = weekly ? "Catalyst" : "Trigger";
  const thirdVal = weekly ? idea.catalyst : idea.trigger;
  return (
    <div style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: "12px 14px", background: T.card }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontFamily: T.mono, fontWeight: 800, fontSize: 15, color: T.ink }}>{idea.ticker || "—"}</span>
        <span style={{ fontSize: 9.5, fontWeight: 800, color: dc, background: dc + "16", padding: "2px 8px", borderRadius: 4, textTransform: "uppercase" }}>{idea.direction || "n/a"}</span>
      </div>
      {idea.thesis && <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.45, marginTop: 6 }}>{idea.thesis}</div>}
      <div style={{ fontSize: 11.5, color: T.ink3, marginTop: 6, lineHeight: 1.5 }}>
        {thirdVal && <div><b style={{ color: T.ink2 }}>{thirdLabel}:</b> {thirdVal}</div>}
        {idea.risk && <div><b style={{ color: T.ink2 }}>Risk:</b> {idea.risk}</div>}
      </div>
    </div>
  );
}

function PlanBlock({ title, plan, weekly }) {
  const ideas = plan?.ideas || [];
  return (
    <Card pad={20}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <SectionTitle sub={weekly ? "swing / position horizon" : "today's actionable read"}>{title}</SectionTitle>
        <BiasPill bias={plan?.bias} />
      </div>
      {plan?.summary && <div style={{ fontSize: 13, color: T.ink2, lineHeight: 1.55, marginBottom: 12 }}>{plan.summary}</div>}
      {weekly && plan?.themes?.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
          {plan.themes.map((t, i) => <span key={i} style={{ fontSize: 11, padding: "3px 10px", borderRadius: 6, background: PURPLE + "14", color: PURPLE, fontWeight: 600 }}>{t}</span>)}
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
  const plan = data?.plan || null;
  const busy = refreshing || status === "running";

  const run = async () => {
    setRefreshing(true);
    await triggerAgent("alpha_wolf");
    setTimeout(refresh, 8000); setTimeout(refresh, 20000); setTimeout(refresh, 35000);
    setTimeout(() => setRefreshing(false), 3000);
  };

  const sourcesUsed = plan?.sources_used || [];
  const inputs = plan?.inputs || {};

  return (
    <div>
      <TabHeader icon="🐺" color={PURPLE} title="Alpha Wolf"
        sub="Master strategist · fuses the trading pack into a Daily + Weekly plan"
        actions={<>
          <Pill mono c={T.ink3}>daily · 08:30</Pill>
          {plan && <Pill c={PURPLE} bg={PURPLE_BG}>{sourcesUsed.length}/6 agents</Pill>}
          <EmailPreviewButton agentId="alpha_wolf" label="Preview plan email" />
          <AgentControls agentId="alpha_wolf" onRun={run} busy={busy} refresh={refresh} runLabel="Run plan" runningLabel="Synthesizing…" />
        </>}
      />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 18 }}>
        <ErrorBanner error={agentError} />

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

        {!plan ? (
          <EmptyState icon="🐺" title="No game-plan yet"
            hint="Run the sub-agents (Wolf, Compass, Strategy Scout, Capitol Tracker, Options Flow, Earnings), then click 'Run plan'." />
        ) : (<>

          {/* Regime read */}
          {plan.regime && (
            <Card pad={20} style={{ background: PURPLE_BG, borderColor: PURPLE + "33" }}>
              <div style={{ display: "flex", gap: 14 }}>
                <LufiAvatar size={38} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 5 }}>Market regime <span style={{ fontSize: 11, color: T.ink4 }}>by Alpha Wolf · Qwen3</span></div>
                  <div style={{ fontSize: 13.5, color: "#4c1d95", lineHeight: 1.55 }}>{plan.regime}</div>
                </div>
              </div>
            </Card>
          )}

          <PlanBlock title="Daily Plan" plan={plan.daily} weekly={false} />
          <PlanBlock title="Weekly Plan" plan={plan.weekly} weekly={true} />

          {/* Catalysts + risk */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Card pad={20}>
              <SectionTitle sub="upcoming events to watch">Catalysts</SectionTitle>
              {(plan.catalysts || []).length > 0 ? (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, color: T.ink2, lineHeight: 1.7 }}>
                  {plan.catalysts.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              ) : <div style={{ fontSize: 12.5, color: T.ink4, marginTop: 8 }}>None flagged.</div>}
            </Card>
            <Card pad={20}>
              <SectionTitle sub="how to size and protect">Risk management</SectionTitle>
              <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.55, marginTop: 8 }}>{plan.risk_notes || "—"}</div>
            </Card>
          </div>

          {/* Pack intel snapshot */}
          {Object.keys(inputs).length > 0 && (
            <Card pad={20}>
              <SectionTitle sub="the raw signals Alpha Wolf reasoned over">Pack intel</SectionTitle>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                {Object.entries(inputs).map(([k, v]) => (
                  <div key={k} style={{ fontSize: 12, color: T.ink3, lineHeight: 1.45 }}>
                    <span style={{ fontWeight: 800, color: PURPLE, fontFamily: T.mono, fontSize: 11 }}>{k}</span> &nbsp;{v}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Disclaimer */}
          <div style={{ fontSize: 11, color: T.ink4, lineHeight: 1.5, padding: "0 4px" }}>{plan.disclaimer}</div>
        </>)}
      </div>
    </div>
  );
}
