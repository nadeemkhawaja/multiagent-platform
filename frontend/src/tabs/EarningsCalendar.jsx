// ============================================================================
// EarningsCalendar.jsx — Upcoming earnings + expected move + IV crush signals
// ============================================================================
import { useState } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar } from "../components/Common";

const GREEN = "#16a34a"; const GREEN_BG = "#f0fdf4";
const AMBER = "#d97706"; const AMBER_BG = "#fffbeb";
const RED   = "#dc2626"; const RED_BG   = "#fef2f2";
const VIOLET= "#7c5cf6"; const VIOLET_BG= "#f1edfe";
const BLUE  = "#2563eb"; const BLUE_BG  = "#eff6ff";

function dteColor(dte) {
  if (dte === null || dte === undefined) return T.ink4;
  if (dte <= 3)  return RED;
  if (dte <= 7)  return AMBER;
  if (dte <= 14) return BLUE;
  return T.ink3;
}

function dteBg(dte) {
  if (dte === null || dte === undefined) return T.cardAlt;
  if (dte <= 3)  return RED_BG;
  if (dte <= 7)  return AMBER_BG;
  if (dte <= 14) return BLUE_BG;
  return T.cardAlt;
}

function urgencyLabel(dte) {
  if (dte === null || dte === undefined) return "";
  if (dte <= 3)  return "THIS WEEK";
  if (dte <= 7)  return "NEXT WEEK";
  if (dte <= 14) return "2 WEEKS";
  return "";
}

function EarningsCard({ e }) {
  const dc = dteColor(e.dte);
  const db = dteBg(e.dte);
  const crush = e.iv_crush_flag;
  return (
    <Card pad={16} style={{ borderColor: crush ? AMBER + "55" : dc + "33", position: "relative" }}>
      {crush && (
        <div style={{ position: "absolute", top: 10, right: 12, fontSize: 10, fontWeight: 700, color: AMBER, background: AMBER_BG, padding: "2px 8px", borderRadius: 5 }}>🔥 IV CRUSH OPP</div>
      )}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 800, fontFamily: T.mono, color: T.ink }}>{e.ticker}</div>
          <div style={{ fontSize: 11.5, color: T.ink4, marginTop: 1 }}>{e.company || e.sector || ""}</div>
        </div>
        <div style={{ marginLeft: "auto", textAlign: "right" }}>
          <div style={{ fontSize: 13, fontWeight: 800, fontFamily: T.mono, color: dc, background: db, padding: "4px 12px", borderRadius: 8 }}>{e.dte}d</div>
          {urgencyLabel(e.dte) && <div style={{ fontSize: 9.5, color: dc, fontWeight: 700, marginTop: 2 }}>{urgencyLabel(e.dte)}</div>}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        <div style={{ background: T.cardAlt, borderRadius: 8, padding: "9px 10px", textAlign: "center" }}>
          <div style={{ fontSize: 10, color: T.ink4, fontWeight: 600, marginBottom: 3 }}>Expected move</div>
          <div style={{ fontSize: 16, fontWeight: 800, fontFamily: T.mono, color: VIOLET }}>
            {e.expected_pct != null ? `±${e.expected_pct}%` : "—"}
          </div>
        </div>
        <div style={{ background: T.cardAlt, borderRadius: 8, padding: "9px 10px", textAlign: "center" }}>
          <div style={{ fontSize: 10, color: T.ink4, fontWeight: 600, marginBottom: 3 }}>Avg IV</div>
          <div style={{ fontSize: 16, fontWeight: 800, fontFamily: T.mono, color: e.avg_iv > 60 ? AMBER : T.ink }}>
            {e.avg_iv > 0 ? `${e.avg_iv.toFixed(0)}%` : "—"}
          </div>
        </div>
        <div style={{ background: T.cardAlt, borderRadius: 8, padding: "9px 10px", textAlign: "center" }}>
          <div style={{ fontSize: 10, color: T.ink4, fontWeight: 600, marginBottom: 3 }}>Spot</div>
          <div style={{ fontSize: 16, fontWeight: 800, fontFamily: T.mono, color: T.ink }}>
            ${(e.spot || 0).toFixed(2)}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, fontSize: 11.5 }}>
        <span style={{ color: T.ink4 }}>Earnings date: <span style={{ fontFamily: T.mono, color: T.ink2 }}>{e.earnings_date || "—"}</span></span>
        {e.eps_estimate != null && <span style={{ color: T.ink4 }}>EPS est: <span style={{ fontFamily: T.mono, color: T.ink2 }}>${e.eps_estimate?.toFixed(2)}</span></span>}
      </div>
    </Card>
  );
}

function TimelineRow({ e }) {
  const dc = dteColor(e.dte);
  const crush = e.iv_crush_flag;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "52px 1fr 90px 100px 90px 80px 80px", gap: 10, alignItems: "center", padding: "10px 20px", borderBottom: `1px solid ${T.line2}`, fontSize: 13 }}>
      <span style={{ fontWeight: 800, fontFamily: T.mono, color: T.ink }}>{e.ticker}</span>
      <div style={{ minWidth: 0 }}>
        <span style={{ fontSize: 12, color: T.ink3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.company || e.sector || "—"}</span>
      </div>
      <span style={{ fontFamily: T.mono, fontWeight: 700, color: dc, background: dc + "18", padding: "2px 8px", borderRadius: 6, textAlign: "center", fontSize: 12 }}>{e.dte}d</span>
      <span style={{ fontFamily: T.mono, fontSize: 12, color: T.ink3 }}>{e.earnings_date || "—"}</span>
      <span style={{ fontFamily: T.mono, fontWeight: 700, color: VIOLET, textAlign: "right" }}>{e.expected_pct != null ? `±${e.expected_pct}%` : "—"}</span>
      <span style={{ fontFamily: T.mono, color: e.avg_iv > 60 ? AMBER : T.ink2, textAlign: "right" }}>{e.avg_iv > 0 ? `${e.avg_iv.toFixed(0)}%` : "—"}</span>
      <span style={{ fontSize: 11, fontWeight: 700, color: AMBER, textAlign: "right" }}>{crush ? "🔥 Crush" : ""}</span>
    </div>
  );
}

export default function EarningsCalendar({ status, agentError }) {
  const { data, refresh } = useAgentData("earnings_cal");
  const [refreshing, setRefreshing] = useState(false);
  const [view, setView] = useState("cards");
  const [window, setWindow] = useState("all"); // all | week | 2weeks | crush

  const cal = data?.calendar || null;
  const allEvents = cal?.events || [];
  const commentary = cal?.commentary || "";
  const busy = refreshing || status === "running";

  const run = async () => {
    setRefreshing(true);
    await triggerAgent("earnings_cal");
    setTimeout(refresh, 12000); setTimeout(refresh, 30000);
    setTimeout(() => setRefreshing(false), 3000);
  };

  const filtered = allEvents.filter((e) => {
    if (window === "week")   return (e.dte || 99) <= 7;
    if (window === "2weeks") return (e.dte || 99) <= 14;
    if (window === "crush")  return e.iv_crush_flag;
    return true;
  });

  const crushCount = allEvents.filter((e) => e.iv_crush_flag).length;
  const weekCount  = allEvents.filter((e) => (e.dte || 99) <= 7).length;

  return (
    <div>
      <TabHeader icon="📅" color={GREEN} title="Earnings Calendar"
        sub="Upcoming earnings · expected move · IV crush signals · TOS options prep"
        actions={<>
          <Pill mono c={T.ink3}>every 6h</Pill>
          {cal && <>
            <Pill c={RED} bg={RED_BG}>{weekCount} this week</Pill>
            <Pill c={AMBER} bg={AMBER_BG}>{crushCount} crush opp</Pill>
          </>}
          <EmailPreviewButton agentId="earnings_cal" label="Preview email" />
          <AgentControls agentId="earnings_cal" onRun={run} busy={busy} refresh={refresh} runLabel="Refresh" runningLabel="Fetching…" />
        </>}
      />
      <div className="om-stagger" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 13 }}>
        <ErrorBanner error={agentError} />
        {!cal ? (
          <EmptyState icon="📅" title="No earnings data yet" hint="Click 'Refresh' to fetch upcoming earnings for your watchlist." />
        ) : (<>

          {/* Commentary */}
          {commentary && (
            <Card pad={20} style={{ background: GREEN_BG, borderColor: GREEN + "33" }}>
              <div style={{ display: "flex", gap: 14 }}>
                <LufiAvatar size={36} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Earnings Analyst <span style={{ fontSize: 11, color: T.ink4 }}>by Lufi · Qwen3</span></div>
                  <div style={{ fontSize: 13.5, color: "#166534", lineHeight: 1.55, whiteSpace: "pre-line" }}>{commentary}</div>
                </div>
              </div>
            </Card>
          )}

          {/* IV Crush explanation */}
          <Card pad={12} style={{ background: AMBER_BG, borderColor: AMBER + "44" }}>
            <div style={{ fontSize: 11.5, color: "#92400e" }}>
              <b>🔥 IV Crush:</b> When a stock has elevated implied volatility (IV &gt; 40%) and reports earnings within 14 days, selling premium (iron condors, straddles, strangles) can benefit from the post-earnings IV collapse. Flagged positions show this opportunity. Not financial advice.
            </div>
          </Card>

          {/* Filter bar */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ display: "flex", gap: 6 }}>
              {[["all","All"], ["week","This week"], ["2weeks","Next 2 weeks"], ["crush","IV Crush only"]].map(([v, l]) => (
                <button key={v} onClick={() => setWindow(v)} style={{ padding: "5px 13px", borderRadius: 7, border: `1px solid ${window === v ? GREEN : T.line}`, background: window === v ? GREEN : "transparent", color: window === v ? "#fff" : T.ink2, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: T.sans }}>
                  {l}
                </button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {["cards","timeline"].map((v) => (
                <button key={v} onClick={() => setView(v)} style={{ padding: "4px 11px", borderRadius: 7, border: `1px solid ${view === v ? GREEN : T.line}`, background: view === v ? GREEN : "transparent", color: view === v ? "#fff" : T.ink2, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: T.sans }}>
                  {v === "cards" ? "⊞" : "☰"} {v}
                </button>
              ))}
            </div>
          </div>

          {filtered.length === 0 && <div style={{ color: T.ink4, fontSize: 13, padding: "12px 0" }}>No events match the current filter.</div>}

          {view === "cards" ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))", gap: 14 }}>
              {filtered.map((e) => <EarningsCard key={e.ticker} e={e} />)}
            </div>
          ) : (
            <Card pad={0} style={{ overflow: "hidden" }}>
              <div style={{ display: "grid", gridTemplateColumns: "52px 1fr 90px 100px 90px 80px 80px", gap: 10, padding: "9px 20px", borderBottom: `1px solid ${T.line}`, background: T.cardAlt }}>
                {["Ticker","Company","DTE","Date","Exp Move","IV","Signal"].map((h) => (
                  <span key={h} style={{ fontSize: 10, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4 }}>{h}</span>
                ))}
              </div>
              {filtered.map((e) => <TimelineRow key={e.ticker} e={e} />)}
            </Card>
          )}

          <div style={{ fontSize: 11, color: T.ink4, textAlign: "center" }}>
            {cal.found} earnings events found across {cal.scanned} watchlist tickers · {cal.generated_at} · Educational use only
          </div>
        </>)}
      </div>
    </div>
  );
}
