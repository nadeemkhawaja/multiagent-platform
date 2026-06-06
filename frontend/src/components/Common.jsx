// Shared UI bits: email-preview modal trigger + agent error banner.
import { useState } from "react";
import { T } from "../theme/tokens";
import { Btn, Card } from "../theme/ui";
import { emailPreview, stopAgent } from "../state/api";

// Run / Stop / Restart controls shared by every agent tab.
// `onRun` is the tab's own trigger handler (builds any per-agent config);
// `busy` reflects whether the agent is currently running.
export function AgentControls({ agentId, onRun, busy, refresh, runLabel = "Manual run", runningLabel = "Running…" }) {
  const [stopping, setStopping] = useState(false);
  const stop = async () => {
    setStopping(true);
    try { await stopAgent(agentId); refresh && refresh(); }
    finally { setTimeout(() => setStopping(false), 600); }
  };
  const restart = async () => {
    await stopAgent(agentId);
    onRun();
  };
  return (
    <>
      <Btn size="sm" onClick={onRun} disabled={busy}>
        <span style={{ display: "inline-block", animation: busy ? "omSpin .8s linear infinite" : "none" }}>↻</span>
        {busy ? runningLabel : runLabel}
      </Btn>
      <Btn size="sm" kind="danger" onClick={stop} disabled={!busy || stopping}>■ {stopping ? "Stopping…" : "Stop"}</Btn>
      <Btn size="sm" kind="ghost" onClick={restart} disabled={busy}>⟲ Restart</Btn>
    </>
  );
}

export function EmailPreviewButton({ agentId, label = "Preview email" }) {
  const [html, setHtml] = useState(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const show = async () => {
    setLoading(true);
    try { const r = await emailPreview(agentId); setHtml(r.html || ""); setOpen(true); }
    finally { setLoading(false); }
  };
  return (
    <>
      <Btn size="sm" kind="soft" onClick={show}>{loading ? "Loading…" : label}</Btn>
      {open && (
        <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", zIndex: 50, display: "grid", placeItems: "center", padding: 24 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ background: T.card, borderRadius: 14, width: "min(700px,94vw)", maxHeight: "88vh", overflow: "hidden", border: `1px solid ${T.line}`, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 18px", borderBottom: `1px solid ${T.line}` }}>
              <div style={{ fontWeight: 700 }}>Email preview</div>
              <Btn size="sm" kind="ghost" onClick={() => setOpen(false)}>✕ Close</Btn>
            </div>
            <iframe title="email-preview" srcDoc={html} style={{ border: "none", width: "100%", height: "72vh", background: "#fff" }} />
          </div>
        </div>
      )}
    </>
  );
}

export function EmptyState({ icon = "∅", title, hint }) {
  return (
    <Card pad={44} style={{ textAlign: "center" }}>
      <div style={{ fontSize: 30, opacity: 0.45 }}>{icon}</div>
      <div style={{ fontSize: 14, fontWeight: 700, marginTop: 10 }}>{title}</div>
      {hint && <div style={{ fontSize: 12.5, color: T.ink3, marginTop: 5 }}>{hint}</div>}
    </Card>
  );
}

export function ErrorBanner({ error }) {
  if (!error) return null;
  return (
    <div style={{ background: T.redBg, border: `1px solid ${T.red}55`, borderRadius: 12, padding: "11px 16px", display: "flex", alignItems: "center", gap: 11, fontSize: 12.5, color: T.red, fontWeight: 600 }}>
      <span style={{ fontSize: 16 }}>⚠</span> Last run error: {error}
    </div>
  );
}
