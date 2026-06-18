// ============================================================================
// MorningBrief.jsx — Daily 6am personalized digest tab
// ============================================================================
import { useState } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar } from "../components/Common";

const AMBER = "#d97706"; const AMBER_BG = "#fffbeb";
const GREEN = "#16a34a"; const RED = "#dc2626";

function WeatherCard({ detail }) {
  if (!detail) return null;
  const { temp_f, feels_f, desc, humidity, wind_mph } = detail;
  return (
    <Card pad={18} style={{ background: "#eff6ff", borderColor: "#2563eb33" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ fontSize: 36 }}>🌤</div>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, fontFamily: T.mono, color: "#1e40af" }}>{temp_f}°F</div>
          <div style={{ fontSize: 13, color: "#1d4ed8", marginTop: 2 }}>{desc} · Feels {feels_f}°F</div>
          <div style={{ fontSize: 12, color: "#3b82f6", marginTop: 2 }}>Humidity {humidity}% · Wind {wind_mph} mph · Murphy, TX</div>
        </div>
      </div>
    </Card>
  );
}

function MoverRow({ s, side }) {
  const col = side === "gain" ? GREEN : RED;
  const sign = side === "gain" ? "+" : "";
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 0", borderBottom: `1px solid ${T.line2}`, fontSize: 13 }}>
      <span style={{ fontWeight: 700, fontFamily: T.mono }}>{s.ticker}</span>
      <span style={{ fontSize: 11, color: T.ink3, flex: 1, marginLeft: 10, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name || ""}</span>
      <span style={{ fontFamily: T.mono, fontWeight: 600, color: col }}>{sign}{(s.pct || 0).toFixed(2)}%</span>
    </div>
  );
}

function TradeRow({ t }) {
  const isBuy = /purchase|buy|exercise/i.test(t.type);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", borderBottom: `1px solid ${T.line2}`, fontSize: 12.5 }}>
      <span style={{ fontWeight: 800, fontFamily: T.mono, width: 52, color: isBuy ? GREEN : RED }}>{t.ticker || "—"}</span>
      <span style={{ flex: 1, color: T.ink2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.politician}</span>
      <span style={{ fontSize: 11, fontWeight: 700, color: isBuy ? GREEN : RED, background: isBuy ? "#f0fdf4" : "#fef2f2", padding: "2px 8px", borderRadius: 5 }}>{t.type}</span>
    </div>
  );
}

function VideoRow({ v }) {
  return (
    <div style={{ display: "flex", gap: 12, padding: "8px 0", borderBottom: `1px solid ${T.line2}` }}>
      {v.thumbnail && <img src={v.thumbnail} alt="" style={{ width: 72, height: 46, objectFit: "cover", borderRadius: 6, flexShrink: 0 }} />}
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: T.ink, lineHeight: 1.3, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>{v.title}</div>
        <div style={{ fontSize: 11, color: T.ink4, marginTop: 3 }}>{v.channel}</div>
      </div>
    </div>
  );
}

export default function MorningBrief({ status, agentError }) {
  const { data, refresh } = useAgentData("morning_brief");
  const [refreshing, setRefreshing] = useState(false);

  const brief = data?.brief || null;
  const busy = refreshing || status === "running";

  const run = async () => {
    setRefreshing(true);
    await triggerAgent("morning_brief");
    setTimeout(refresh, 8000); setTimeout(refresh, 20000);
    setTimeout(() => setRefreshing(false), 3000);
  };

  return (
    <div>
      <TabHeader icon="☀" color={AMBER} title="Morning Brief"
        sub="Daily 06:00 digest · weather · markets · politics · AI news"
        actions={<>
          <Pill mono c={T.ink3}>daily · 06:00</Pill>
          <EmailPreviewButton agentId="morning_brief" label="Preview digest" />
          <AgentControls agentId="morning_brief" onRun={run} busy={busy} refresh={refresh} runLabel="Generate now" runningLabel="Generating…" />
        </>}
      />
      <div className="om-stagger" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 13 }}>
        <ErrorBanner error={agentError} />
        {!brief ? (
          <EmptyState icon="☀" title="No brief yet" hint="Click 'Generate now' or wait for the 06:00 daily run." />
        ) : (<>
          {/* Generated timestamp */}
          <div style={{ fontSize: 12, color: T.ink4, display: "flex", alignItems: "center", gap: 6 }}>
            <span>Generated</span>
            <span style={{ fontFamily: T.mono, color: T.ink3 }}>{brief.generated_at}</span>
          </div>

          {/* Weather */}
          <WeatherCard detail={brief.weather_detail} />

          {/* Narrative */}
          <Card pad={22}>
            <div style={{ display: "flex", gap: 14 }}>
              <LufiAvatar size={40} />
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 6 }}>Your Morning Brief <span style={{ fontSize: 11.5, fontWeight: 500, color: T.ink4 }}>by Lufi · Qwen3</span></div>
                <div style={{ fontSize: 14.5, color: T.ink, lineHeight: 1.65, whiteSpace: "pre-line" }}>{brief.narrative}</div>
              </div>
            </div>
          </Card>

          {/* Market movers */}
          {(brief.wolf_gainers?.length > 0 || brief.wolf_losers?.length > 0) && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              <Card pad={18}>
                <SectionTitle sub="Pre-market leaders">Top gainers</SectionTitle>
                {(brief.wolf_gainers || []).map((s) => <MoverRow key={s.ticker} s={s} side="gain" />)}
              </Card>
              <Card pad={18}>
                <SectionTitle sub="Biggest declines">Top losers</SectionTitle>
                {(brief.wolf_losers || []).map((s) => <MoverRow key={s.ticker} s={s} side="loss" />)}
              </Card>
            </div>
          )}

          {/* Capitol trades */}
          {brief.capitol_trades?.length > 0 && (
            <Card pad={18}>
              <SectionTitle sub="Recent STOCK Act disclosures">Congressional trades</SectionTitle>
              {(brief.capitol_trades || []).map((t, i) => <TradeRow key={i} t={t} />)}
            </Card>
          )}

          {/* AI Videos */}
          {brief.ai_videos?.length > 0 && (
            <Card pad={18}>
              <SectionTitle sub="From AI-Times">AI news highlights</SectionTitle>
              {(brief.ai_videos || []).map((v, i) => <VideoRow key={i} v={v} />)}
            </Card>
          )}
        </>)}
      </div>
    </div>
  );
}
