// ============================================================================
// DevDaily.jsx — GitHub trending + Dev.to articles + LLM learning digest.
// (Kept from the existing platform; restyled to the Aria design language.)
// ============================================================================
import { useState } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent } from "../state/api";
import { ErrorBanner, AgentControls, LufiAvatar } from "../components/Common";

const ACCENT = AGENT_COLOR.devdaily;

export default function DevDaily({ status, agentError }) {
  const { data, refresh } = useAgentData("devdaily");
  const d = data?.digest || {};
  const repos = d.github_repos || [];
  const articles = d.devto_articles || [];

  const [lang, setLang] = useState("");
  const [count, setCount] = useState(5);
  const [topic, setTopic] = useState("");
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    await triggerAgent("devdaily", { language: lang, count: parseInt(count) || 5, topic });
    setTimeout(refresh, 5000); setTimeout(refresh, 14000);
    setTimeout(() => setRunning(false), 2000);
  };
  const busy = running || status === "running";
  const empty = repos.length === 0 && articles.length === 0;

  return (
    <div>
      <TabHeader icon="⌥" color={ACCENT} title="GitHub Trending" sub="GitHub trending + Dev.to · LLM learning digest"
        actions={<>
          <Pill mono c={T.ink3}>digest 09:00 daily</Pill>
          <AgentControls agentId="devdaily" onRun={run} busy={busy} refresh={refresh} runLabel="Manual run" runningLabel="Fetching…" />
        </>} />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>
        <ErrorBanner error={agentError} />
        <Card pad={18}>
          <SectionTitle sub="Tune the next fetch">Configuration</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 140px 1fr", gap: 14 }}>
            {[["Language filter", lang, setLang, "python, javascript…", "text"],
              ["Result count", count, setCount, "5", "number"],
              ["Topic / tag", topic, setTopic, "ai, webdev…", "text"]].map(([label, val, setter, ph, type]) => (
              <div key={label}>
                <label style={{ fontSize: 11, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</label>
                <input type={type} value={val} placeholder={ph} onChange={(e) => setter(e.target.value)}
                  style={{ width: "100%", marginTop: 6, border: `1px solid ${T.line}`, borderRadius: 9, padding: "9px 12px", fontFamily: T.sans, fontSize: 13, background: T.card, color: T.ink, outline: "none", boxSizing: "border-box" }} />
              </div>
            ))}
          </div>
        </Card>

        {d.llm_summary && (
          <Card pad={20} style={{ background: T.cardAlt }}>
            <div style={{ display: "flex", gap: 14 }}>
              <LufiAvatar size={38} />
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>Daily learning summary <span style={{ fontSize: 11.5, fontWeight: 600, color: T.ink4 }}>by Lufi</span> <Pill mono c={T.violet} bg={T.violetBg} style={{ padding: "2px 7px" }}>Qwen3</Pill></div>
                <div style={{ fontSize: 13, color: T.ink2, lineHeight: 1.55, marginTop: 6 }}>{d.llm_summary}</div>
              </div>
            </div>
          </Card>
        )}

        {empty && (
          <Card pad={24} style={{ color: T.ink3, fontSize: 13 }}>
            No digest yet — click <b style={{ color: ACCENT }}>Manual run</b> to fetch trending repositories and articles.
          </Card>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
          <Card pad={20}>
            <SectionTitle sub="Trending repositories" right={<Pill mono c={T.ink3}>{repos.length}</Pill>}>GitHub</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {repos.map((r, i) => (
                <div key={i}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
                    <a href={r.url} target="_blank" rel="noreferrer" style={{ color: ACCENT, textDecoration: "none", fontWeight: 700, fontSize: 13.5 }}>
                      {r.name}
                      {r.language && <span style={{ marginLeft: 8, fontSize: 10.5, fontFamily: T.mono, color: T.ink4, background: T.line2, padding: "2px 7px", borderRadius: 6 }}>{r.language}</span>}
                    </a>
                    <span style={{ color: T.amber, flexShrink: 0, fontFamily: T.mono, fontSize: 12 }}>★ {Number(r.stars || 0).toLocaleString()}</span>
                  </div>
                  {r.description && <p style={{ fontSize: 12.5, color: T.ink3, marginTop: 4, lineHeight: 1.45 }}>{r.description}</p>}
                </div>
              ))}
            </div>
          </Card>
          <Card pad={20}>
            <SectionTitle sub="Community articles" right={<Pill mono c={T.ink3}>{articles.length}</Pill>}>Dev.to</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {articles.map((a, i) => (
                <div key={i}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
                    <a href={a.url} target="_blank" rel="noreferrer" style={{ color: ACCENT, textDecoration: "none", fontWeight: 700, fontSize: 13.5 }}>{a.title}</a>
                    <span style={{ color: T.red, flexShrink: 0, fontFamily: T.mono, fontSize: 12 }}>♥ {a.reactions}</span>
                  </div>
                  {a.description && <p style={{ fontSize: 12.5, color: T.ink3, marginTop: 4, lineHeight: 1.45 }}>{a.description}</p>}
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
