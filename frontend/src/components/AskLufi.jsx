// ============================================================================
// AskLufi.jsx — per-agent AI assistant. A floating panel on every agent tab:
// ask the agent's model to do ad-hoc work over that agent's latest data
// ("summarize today's movers", "draft a reply", "which idea is riskiest?").
// Uses the agent's configured model (Settings → AI models).
// ============================================================================
import { useState, useRef, useEffect } from "react";
import { T } from "../theme/tokens";
import { agentAssist } from "../state/api";

export default function AskLufi({ agentId, agentName, color }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [msgs, setMsgs] = useState([]);   // {role: "user"|"ai"|"error", text}
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);
  const col = color || T.violet;

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [msgs, busy]);

  const send = async () => {
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setBusy(true);
    try {
      const r = await agentAssist(agentId, q);
      if (r.error) setMsgs((m) => [...m, { role: "error", text: r.error }]);
      else setMsgs((m) => [...m, { role: "ai", text: r.response || "(empty response)" }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "error", text: String(e.message || e) }]);
    }
    setBusy(false);
  };

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} title={`Ask Lufi about ${agentName}`} style={{
        position: "fixed", right: 22, bottom: 22, zIndex: 900,
        display: "flex", alignItems: "center", gap: 8, padding: "10px 16px",
        background: col, color: "#fff", border: "none", borderRadius: 999,
        fontSize: 13, fontWeight: 800, fontFamily: T.sans, cursor: "pointer",
        boxShadow: "0 6px 20px rgba(0,0,0,.22)",
      }}>✦ Ask Lufi</button>
    );
  }

  return (
    <div style={{
      position: "fixed", right: 22, bottom: 22, zIndex: 900, width: 380, maxWidth: "calc(100vw - 44px)",
      background: T.card, border: `1px solid ${T.line}`, borderRadius: 16,
      boxShadow: "0 16px 50px rgba(0,0,0,.25)", display: "flex", flexDirection: "column",
      maxHeight: "min(560px, calc(100vh - 44px))", overflow: "hidden", fontFamily: T.sans,
    }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "12px 16px", background: col + "14", borderBottom: `1px solid ${T.line}` }}>
        <span style={{ width: 26, height: 26, borderRadius: 8, background: col, color: "#fff", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 800 }}>✦</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 800, color: T.ink }}>Ask Lufi · {agentName}</div>
          <div style={{ fontSize: 10.5, color: T.ink3 }}>works on this agent's latest data · uses its configured model</div>
        </div>
        <button onClick={() => setOpen(false)} style={{ border: "none", background: "transparent", color: T.ink3, fontSize: 16, cursor: "pointer", padding: 4 }}>✕</button>
      </div>

      {/* messages */}
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10, minHeight: 120 }}>
        {msgs.length === 0 && (
          <div style={{ fontSize: 12, color: T.ink4, lineHeight: 1.6 }}>
            Ask anything about this agent's data — e.g. “summarize the latest run”,
            “what's the riskiest idea and why?”, “draft an email about today's findings”.
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} style={{
            alignSelf: m.role === "user" ? "flex-end" : "flex-start",
            maxWidth: "88%", padding: "9px 12px", borderRadius: 12, fontSize: 12.5, lineHeight: 1.55,
            whiteSpace: "pre-wrap", wordBreak: "break-word",
            background: m.role === "user" ? col : m.role === "error" ? T.redBg : T.cardAlt,
            color: m.role === "user" ? "#fff" : m.role === "error" ? T.red : T.ink2,
            border: m.role === "user" ? "none" : `1px solid ${T.line}`,
          }}>{m.text}</div>
        ))}
        {busy && <div style={{ alignSelf: "flex-start", fontSize: 12, color: T.ink3, padding: "6px 2px" }}>Thinking…</div>}
      </div>

      {/* input */}
      <div style={{ display: "flex", gap: 8, padding: "12px 14px", borderTop: `1px solid ${T.line}` }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} autoFocus
          onKeyDown={(e) => { if (e.key === "Enter") send(); }}
          placeholder={busy ? "Working…" : "Ask about this agent…"}
          disabled={busy}
          style={{ flex: 1, border: `1px solid ${T.line}`, borderRadius: 9, padding: "9px 12px", fontSize: 13, fontFamily: T.sans, background: T.cardAlt, color: T.ink, outline: "none" }} />
        <button onClick={send} disabled={busy || !input.trim()} style={{
          padding: "9px 16px", background: input.trim() && !busy ? col : T.line2, color: input.trim() && !busy ? "#fff" : T.ink4,
          border: "none", borderRadius: 9, fontSize: 13, fontWeight: 800, fontFamily: T.sans, cursor: input.trim() && !busy ? "pointer" : "default",
        }}>Send</button>
      </div>
    </div>
  );
}
