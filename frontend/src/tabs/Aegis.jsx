// ============================================================================
// Aegis.jsx — Islamophobia watch: flagged-post feed + human-in-the-loop
// moderation composer. Suggested replies are drafts for human moderators;
// approving/dismissing posts to the backend (never auto-posts).
// ============================================================================
import { useState, useEffect } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, Dot, Btn, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent, aegisApprove, aegisDismiss } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls } from "../components/Common";

const risk = (k) => ({
  high: { t: "Hate speech", c: T.red, bg: T.redBg },
  med: { t: "Biased", c: T.amber, bg: T.amberBg },
  low: { t: "Low", c: T.ink3, bg: T.line2 },
}[k] || { t: "Low", c: T.ink3, bg: T.line2 });
const srcGlyph = { Reddit: "🟠", X: "𝕏", News: "📰", Mastodon: "🐘" };

function SentBar({ v }) {
  const pos = (v + 100) / 2;
  const col = v >= 20 ? T.green : v <= -20 ? T.red : "#94a3b8";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ position: "relative", flex: 1, height: 6, borderRadius: 6, background: T.line2 }}>
        <div style={{ position: "absolute", left: pos < 50 ? pos + "%" : "50%", right: pos < 50 ? "50%" : (100 - pos) + "%", top: 0, bottom: 0, background: col, borderRadius: 6 }} />
        <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: T.ink4 }} />
      </div>
      <span style={{ fontFamily: T.mono, fontSize: 11, fontWeight: 700, color: col, width: 34, textAlign: "right" }}>{v > 0 ? "+" : ""}{v}</span>
    </div>
  );
}

function computeStats(mentions) {
  if (!mentions.length) return { mentions: 0, net_sentiment: 0, high_risk: 0, avg_response: "—" };
  const net = Math.round(mentions.reduce((a, m) => a + (m.sent || 0), 0) / mentions.length);
  const high = mentions.filter((m) => m.risk === "high" && m.status !== "dismissed").length;
  return { mentions: mentions.length, net_sentiment: net, high_risk: high, avg_response: "12m" };
}

export default function Aegis({ status, agentError }) {
  const { data, refresh } = useAgentData("aegis");
  const live = data?.aegis;
  const mentions = live?.mentions || [];
  const stats = live?.stats || computeStats(mentions);

  const [sel, setSel] = useState(mentions[0]?.id);
  const [drafts, setDrafts] = useState({});
  const [editing, setEditing] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [brand, setBrand] = useState(live?.brand || "");

  useEffect(() => { if (!mentions.find((m) => m.id === sel)) setSel(mentions[0]?.id); }, [mentions, sel]);

  const m = mentions.find((x) => x.id === sel) || mentions[0];
  const draft = sel in drafts ? drafts[sel] : (m?.reply || "");
  const highCount = mentions.filter((x) => x.risk === "high" && x.status !== "dismissed" && x.status !== "approved").length;

  const approve = async () => {
    if (live) { await aegisApprove(sel, draft); refresh(); }
    setEditing(false);
  };
  const dismiss = async () => {
    if (live) { await aegisDismiss(sel); refresh(); }
  };
  const scan = async () => {
    setScanning(true);
    await triggerAgent("aegis", { brand: brand || undefined });
    setTimeout(refresh, 6000); setTimeout(refresh, 16000);
    setTimeout(() => setScanning(false), 2000);
  };
  const busy = scanning || status === "running";
  const handled = live ? m?.status : null; // optimistic only when wired

  return (
    <div>
      <TabHeader icon="❖" color={T.teal} title="Aegis · Islamophobia Watch" sub="Forum-moderation assistant · Reddit + Hacker News · LLM-flagged for review"
        actions={<>
          <Pill mono c={T.ink3}>digest 18:00 daily</Pill>
          <EmailPreviewButton agentId="aegis" label="Preview digest" />
          <AgentControls agentId="aegis" onRun={scan} busy={busy} refresh={refresh} runLabel="Scan forums" runningLabel="Scanning…" />
        </>} />
      <div className="om-stagger" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 11 }}>
        <ErrorBanner error={agentError} />
        {highCount > 0 && (
          <div style={{ background: T.redBg, border: `1px solid ${T.red}55`, borderRadius: 12, padding: "13px 18px", display: "flex", alignItems: "center", gap: 13 }}>
            <span style={{ fontSize: 18 }}>🛡</span>
            <div style={{ fontSize: 13, color: T.red, fontWeight: 600, flex: 1 }}>
              {highCount} Islamophobic post{highCount !== 1 ? "s" : ""} flagged for moderation — review the suggested replies below.
            </div>
          </div>
        )}

        <Card pad={16}>
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 12.5, fontWeight: 700 }}>Topic / keyword to watch</span>
            <input value={brand} onChange={(e) => setBrand(e.target.value)} placeholder={live?.brand || "Islamophobia"}
              style={{ flex: 1, minWidth: 180, border: `1px solid ${T.line}`, borderRadius: 9, padding: "8px 12px", fontFamily: T.sans, fontSize: 13, background: T.card, color: T.ink, outline: "none" }} />
            <span style={{ fontSize: 11.5, color: T.ink4 }}>Scans Reddit + Hacker News for anti-Muslim content to flag for moderators.</span>
          </div>
        </Card>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
          {[["Posts scanned", String(stats.mentions), T.ink, "Reddit + Hacker News"],
            ["Sentiment", (stats.net_sentiment > 0 ? "+" : "") + stats.net_sentiment, stats.net_sentiment < 0 ? T.red : T.green, "toward Muslims"],
            ["Flagged", String(stats.high_risk), T.red, "for moderation"],
            ["Avg response", stats.avg_response, T.green, "moderation SLA"]].map(([l, v, c, sub]) => (
            <Card key={l} pad={16}>
              <div style={{ fontSize: 12, color: T.ink3, fontWeight: 600 }}>{l}</div>
              <div style={{ fontSize: 26, fontWeight: 700, fontFamily: T.mono, letterSpacing: -0.5, color: c, marginTop: 2 }}>{v}</div>
              <div style={{ fontSize: 11, color: T.ink4, marginTop: 1 }}>{sub}</div>
            </Card>
          ))}
        </div>

        {mentions.length === 0 ? (
          <EmptyState icon="❖" title="No posts flagged yet"
            hint="Click Scan forums to monitor Reddit + Hacker News for Islamophobic content and draft moderation replies with the LLM." />
        ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.15fr", gap: 16, alignItems: "start" }}>
          <Card pad={15}>
            <SectionTitle sub="Sorted by severity · LLM-flagged">Flagged posts</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {mentions.map((x) => {
                const active = x.id === sel;
                const r = risk(x.risk);
                const done = x.status === "approved" || x.status === "dismissed" ? x.status : null;
                return (
                  <button key={x.id} onClick={() => { setSel(x.id); setEditing(false); }} style={{
                    textAlign: "left", cursor: "pointer", border: `1px solid ${active ? r.c + "99" : T.line}`, borderRadius: 11, padding: 13,
                    background: active ? r.bg : T.card, opacity: done ? 0.62 : 1, transition: "all .15s", font: "inherit",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <span style={{ fontSize: 13 }}>{srcGlyph[x.src] || "•"}</span>
                      <span style={{ fontSize: 11.5, fontWeight: 700 }}>{x.src}</span>
                      <span style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono }}>{x.sub}</span>
                      <span style={{ marginLeft: "auto", fontSize: 9.5, fontWeight: 700, color: r.c, background: T.card, border: `1px solid ${r.c}44`, padding: "2px 7px", borderRadius: 5 }}>{r.t}</span>
                    </div>
                    <div style={{ fontSize: 12.5, color: T.ink, lineHeight: 1.4, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{x.text}</div>
                    <div style={{ marginTop: 8 }}><SentBar v={x.sent || 0} /></div>
                    {done && <div style={{ fontSize: 10.5, fontWeight: 700, color: done === "approved" ? T.green : T.ink4, marginTop: 7 }}>{done === "approved" ? "✓ Moderation reply approved" : "✕ Dismissed"}</div>}
                  </button>
                );
              })}
            </div>
          </Card>

          {m && (
            <Card pad={16} style={{ position: "sticky", top: 84 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 14 }}>
                <span style={{ fontSize: 15 }}>{srcGlyph[m.src] || "•"}</span>
                <span style={{ fontSize: 13.5, fontWeight: 700 }}>{m.src} · {m.sub}</span>
                <span style={{ fontSize: 11.5, color: T.ink4, fontFamily: T.mono }}>{m.author}</span>
                <span style={{ marginLeft: "auto", fontSize: 10, fontWeight: 700, color: risk(m.risk).c, background: risk(m.risk).bg, padding: "3px 9px", borderRadius: 6 }}>{risk(m.risk).t}</span>
              </div>
              <div style={{ fontSize: 13.5, color: T.ink, lineHeight: 1.5, padding: "14px 16px", background: T.cardAlt, border: `1px solid ${T.line2}`, borderRadius: 10 }}>“{m.text}”</div>

              {m.why && <div style={{ display: "flex", gap: 10, marginTop: 14, padding: "11px 14px", background: T.violetBg, borderRadius: 10 }}>
                <span style={{ color: T.violet, fontWeight: 700, fontSize: 12, flex: "0 0 auto" }}>◇ Why flagged</span>
                <span style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.45 }}>{m.why}</span>
              </div>}

              <div style={{ fontSize: 12, fontWeight: 700, margin: "18px 0 8px", display: "flex", alignItems: "center", gap: 8 }}>
                Suggested moderation reply <Pill mono c={T.violet} bg={T.violetBg} style={{ padding: "2px 7px" }}>Qwen3 draft</Pill>
                <span style={{ marginLeft: "auto", fontSize: 11, fontWeight: 600, color: T.ink4 }}>for human moderators · never auto-posted</span>
              </div>
              <textarea value={draft} onChange={(e) => setDrafts((d) => ({ ...d, [sel]: e.target.value }))} readOnly={!editing}
                style={{ width: "100%", minHeight: 96, resize: "vertical", border: `1px solid ${editing ? T.violet : T.line}`, borderRadius: 10, padding: 13, fontFamily: T.sans, fontSize: 13, lineHeight: 1.5, color: T.ink, background: editing ? T.card : T.cardAlt, outline: "none", boxSizing: "border-box" }} />

              <div style={{ display: "flex", gap: 9, marginTop: 14, alignItems: "center" }}>
                {handled === "approved" ? (
                  <Pill c={T.green} bg={T.greenBg} bd={T.green + "55"}><Dot c={T.green} />Reply approved</Pill>
                ) : handled === "dismissed" ? (
                  <Pill c={T.ink3}>Dismissed</Pill>
                ) : (
                  <>
                    <Btn kind="primary" onClick={approve}>✓ Approve reply</Btn>
                    <Btn onClick={() => setEditing((e) => !e)}>{editing ? "Done editing" : "Edit"}</Btn>
                    <Btn kind="ghost" onClick={dismiss} style={{ marginLeft: "auto" }}>Dismiss</Btn>
                  </>
                )}
              </div>
            </Card>
          )}
        </div>
        )}
      </div>
    </div>
  );
}
