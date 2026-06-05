// Shared UI bits: email-preview modal trigger + agent error banner.
import { useState } from "react";
import { T } from "../theme/tokens";
import { Btn, Card } from "../theme/ui";
import { emailPreview } from "../state/api";

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
