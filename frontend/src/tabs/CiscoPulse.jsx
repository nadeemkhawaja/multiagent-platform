// ============================================================================
// CiscoPulse.jsx — Cisco PSIRT, ACI/NDFC, DevNet intel dashboard
// Built for Cisco SA / Director Professional Services
// ============================================================================
import { useState } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar } from "../components/Common";

const TEAL   = "#0d9488"; const TEAL_BG   = "#f0fdfa";
const RED    = "#dc2626"; const RED_BG    = "#fef2f2";
const AMBER  = "#d97706"; const AMBER_BG  = "#fffbeb";
const BLUE   = "#2563eb"; const BLUE_BG   = "#eff6ff";
const GRAY   = "#6b7280"; const GRAY_BG   = "#f9fafb";

const SEV = {
  critical: { color: RED,   bg: RED_BG,   label: "CRITICAL" },
  high:     { color: AMBER, bg: AMBER_BG, label: "HIGH" },
  medium:   { color: BLUE,  bg: BLUE_BG,  label: "MEDIUM" },
  low:      { color: GRAY,  bg: GRAY_BG,  label: "LOW" },
  info:     { color: GRAY,  bg: GRAY_BG,  label: "INFO" },
};

const CAT_ICON = { security: "🔒", devnet: "⚙", networking: "☁", datacenter: "🏢" };

function SeverityBadge({ severity }) {
  const s = SEV[severity] || SEV.info;
  return <span style={{ fontSize: 9.5, fontWeight: 800, color: s.color, background: s.bg, padding: "2px 8px", borderRadius: 4, letterSpacing: 0.3, flexShrink: 0 }}>{s.label}</span>;
}

function AdvisoryCard({ item }) {
  const s = SEV[item.severity] || SEV.info;
  const icon = CAT_ICON[item.category] || "📰";
  return (
    <div style={{ display: "flex", gap: 12, padding: "14px 0", borderBottom: `1px solid ${T.line2}` }}>
      <div style={{ paddingTop: 2, flexShrink: 0 }}>
        <SeverityBadge severity={item.severity} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 6, marginBottom: 4 }}>
          <span style={{ fontSize: 14 }}>{icon}</span>
          {item.link ? (
            <a href={item.link} target="_blank" rel="noreferrer" style={{ fontSize: 13, fontWeight: 700, color: T.ink, textDecoration: "none", lineHeight: 1.35, flex: 1 }}
              onMouseEnter={(e) => e.currentTarget.style.color = TEAL}
              onMouseLeave={(e) => e.currentTarget.style.color = T.ink}>
              {item.title}
            </a>
          ) : (
            <span style={{ fontSize: 13, fontWeight: 700, color: T.ink, lineHeight: 1.35 }}>{item.title}</span>
          )}
        </div>
        {item.desc && <div style={{ fontSize: 12, color: T.ink3, lineHeight: 1.45, marginBottom: 4 }}>{item.desc.slice(0, 220)}{item.desc.length > 220 ? "…" : ""}</div>}
        <div style={{ fontSize: 11, color: T.ink4 }}>{item.source} · {item.date?.slice(0, 16) || ""}</div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color, bg, sub }) {
  return (
    <Card pad={16} style={{ textAlign: "center", background: bg, borderColor: color + "33" }}>
      <div style={{ fontSize: 28, fontWeight: 800, fontFamily: T.mono, color, letterSpacing: -1 }}>{value}</div>
      <div style={{ fontSize: 12.5, fontWeight: 700, marginTop: 2 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: T.ink4, marginTop: 2 }}>{sub}</div>}
    </Card>
  );
}

export default function CiscoPulse({ status, agentError }) {
  const { data, refresh } = useAgentData("cisco_pulse");
  const [refreshing, setRefreshing] = useState(false);
  const [section, setSection] = useState("all"); // all | security | devnet | datacenter | networking

  const pulse = data?.pulse || null;
  const busy = refreshing || status === "running";

  const run = async () => {
    setRefreshing(true);
    await triggerAgent("cisco_pulse");
    setTimeout(refresh, 10000); setTimeout(refresh, 25000);
    setTimeout(() => setRefreshing(false), 3000);
  };

  const allItems = pulse?.all_items || [];
  const critical = pulse?.critical || [];
  const high     = pulse?.high     || [];
  const events   = pulse?.events   || [];
  const commentary = pulse?.commentary || "";

  const filtered = section === "all" ? allItems : allItems.filter((i) => i.category === section);

  return (
    <div>
      <TabHeader icon="◈" color={TEAL} title="Cisco Pulse"
        sub="PSIRT advisories · ACI/NDFC releases · DevNet blog · weekly intel"
        actions={<>
          <Pill mono c={T.ink3}>daily · 07:30</Pill>
          {pulse && <>
            {critical.length > 0 && <Pill c={RED} bg={RED_BG}>{critical.length} critical</Pill>}
            {high.length > 0 && <Pill c={AMBER} bg={AMBER_BG}>{high.length} high</Pill>}
            {events.length > 0 && <Pill c="#7c3aed" bg="#f5f3ff">{events.length} news</Pill>}
            <Pill c={TEAL} bg={TEAL_BG}>{pulse.total || 0} total</Pill>
          </>}
          <EmailPreviewButton agentId="cisco_pulse" label="Preview digest" />
          <AgentControls agentId="cisco_pulse" onRun={run} busy={busy} refresh={refresh} runLabel="Refresh" runningLabel="Fetching…" />
        </>}
      />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 18 }}>
        <ErrorBanner error={agentError} />
        {!pulse ? (
          <EmptyState icon="◈" title="No Cisco Pulse data yet" hint="Click 'Refresh' to fetch PSIRT advisories, ACI/NDFC updates, and DevNet blog." />
        ) : (<>

          {/* Critical alert banner */}
          {critical.length > 0 && (
            <div style={{ background: RED_BG, border: `1px solid ${RED}55`, borderRadius: 12, padding: "14px 18px" }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: RED, marginBottom: 8 }}>🔴 {critical.length} Critical Advisory{critical.length > 1 ? "ies" : ""} — Immediate Review Required</div>
              {critical.slice(0, 3).map((item, i) => (
                <div key={i} style={{ fontSize: 13, color: "#b91c1c", padding: "4px 0" }}>
                  {item.link ? <a href={item.link} target="_blank" rel="noreferrer" style={{ color: "#b91c1c", textDecoration: "none", fontWeight: 600 }}>{item.title}</a> : item.title}
                </div>
              ))}
            </div>
          )}

          {/* Stats */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
            <StatCard label="Critical" value={critical.length} color={RED}   bg={RED_BG}   sub="action required" />
            <StatCard label="High"     value={high.length}     color={AMBER} bg={AMBER_BG} sub="review soon" />
            <StatCard label="Medium"   value={(pulse.medium || []).length} color={BLUE} bg={BLUE_BG} sub="track" />
            <StatCard label="Total"    value={pulse.total || 0} color={TEAL} bg={TEAL_BG}  sub={pulse.week_of || ""} />
          </div>

          {/* Commentary */}
          {commentary && (
            <Card pad={20} style={{ background: TEAL_BG, borderColor: TEAL + "33" }}>
              <div style={{ display: "flex", gap: 14 }}>
                <LufiAvatar size={38} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 5 }}>SA Summary <span style={{ fontSize: 11, color: T.ink4 }}>by Lufi · Qwen3 · {pulse.week_of}</span></div>
                  <div style={{ fontSize: 13.5, color: "#134e4a", lineHeight: 1.55 }}>{commentary}</div>
                </div>
              </div>
            </Card>
          )}

          {/* Conferences & News */}
          {events.length > 0 && (
            <Card pad={20} style={{ borderColor: "#7c3aed33" }}>
              <SectionTitle sub="Cisco Live, product launches & announcements">📰 Conferences & News</SectionTitle>
              {events.slice(0, 8).map((item, i) => <AdvisoryCard key={i} item={item} />)}
            </Card>
          )}

          {/* Category filter */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {[["all","All"],["news","📰 News"],["security","🔒 Security"],["datacenter","🏢 Data Center"],["devnet","⚙ DevNet"],["networking","☁ Networking"]].map(([v, l]) => (
              <button key={v} onClick={() => setSection(v)} style={{ padding: "5px 13px", borderRadius: 7, border: `1px solid ${section === v ? TEAL : T.line}`, background: section === v ? TEAL : "transparent", color: section === v ? "#fff" : T.ink2, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: T.sans }}>
                {l} {v !== "all" && `(${allItems.filter((i) => i.category === v).length})`}
              </button>
            ))}
          </div>

          {/* Advisory feed */}
          <Card pad={20}>
            <SectionTitle sub={`${filtered.length} items · sorted by relevance`}>
              {section === "all" ? "All advisories" : section.charAt(0).toUpperCase() + section.slice(1)}
            </SectionTitle>
            {filtered.length === 0 && <div style={{ color: T.ink4, fontSize: 13 }}>No items in this category.</div>}
            {filtered.map((item, i) => <AdvisoryCard key={i} item={item} />)}
          </Card>

          {/* Monitoring scope */}
          <Card pad={16} style={{ background: T.cardAlt }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: T.ink3, marginBottom: 8 }}>Monitoring scope</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {["Cisco PSIRT RSS", "Security Blog", "DevNet Blog", "Networking Blog", "Data Center Blog", "Innovation Blog", "Newsroom & Events", "Cisco Live", "ACI/NDFC", "Nexus 9K", "AI DC infra"].map((t) => (
                <span key={t} style={{ fontSize: 11, padding: "3px 10px", borderRadius: 6, background: TEAL + "18", color: TEAL, fontWeight: 600 }}>{t}</span>
              ))}
            </div>
            <div style={{ fontSize: 11, color: T.ink4, marginTop: 10 }}>Last refreshed: {pulse.generated_at}</div>
          </Card>
        </>)}
      </div>
    </div>
  );
}
