// ============================================================================
// AskLufi.jsx — per-agent AI assistant. A floating panel on every agent tab:
// ask the agent's model to do ad-hoc work over that agent's latest data
// ("summarize today's movers", "draft a reply", "which idea is riskiest?").
// Uses the agent's configured model (Settings → AI models).
// ============================================================================
import { useState, useRef, useEffect } from "react";
import { T } from "../theme/tokens";
import { agentAssist } from "../state/api";

export default function AskLufi({ agentId, agentName, color, mobile }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [msgs, setMsgs] = useState([]);   // {role: "user"|"ai"|"error", text}
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);
  const launcherRef = useRef(null);
  const col = color || T.violet;

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [msgs, busy]);

  // Escape closes, and focus goes back to the launcher. This panel is
  // deliberately NOT a modal — it sits over a table you are meant to keep
  // reading, so it gets no focus trap and no backdrop — but "opened with the
  // keyboard, closable only with the mouse" was a dead end all the same.
  // App's own Escape handler can't do this: it bails on anything focused
  // inside an input, which is where you are the moment the panel opens.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setOpen(false);
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open]);
  // Restore focus on the way out, once the launcher is back in the DOM. Guarded
  // on "was open", or the first render of every agent tab would yank focus to
  // this button before the user has touched anything.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (!open && wasOpen.current) launcherRef.current?.focus?.({ preventScroll: true });
    wasOpen.current = open;
  }, [open]);

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

  // env() keeps the button off the iOS home indicator, which otherwise sits
  // directly under it and swallows roughly every other tap.
  const bottom = mobile ? "calc(14px + env(safe-area-inset-bottom))" : 22;

  if (!open) {
    return (
      <button ref={launcherRef} type="button" onClick={() => setOpen(true)} title={`Ask Lufi about ${agentName}`}
        aria-label={`Ask Lufi about ${agentName}`} aria-expanded={false} style={{
        position: "fixed", right: mobile ? 14 : 22, bottom, zIndex: 900,
        display: "flex", alignItems: "center", gap: 8,
        // Shrinks to a round icon on a phone: a labelled pill covers a column of
        // whichever table is on screen, and this button is on every agent tab.
        padding: mobile ? 0 : "10px 16px", width: mobile ? 52 : "auto", height: mobile ? 52 : "auto",
        justifyContent: "center",
        background: col, color: T.onAccent, border: "none", borderRadius: 999,
        fontSize: mobile ? 20 : 13, fontWeight: 800, fontFamily: T.sans, cursor: "pointer",
        boxShadow: "0 6px 20px rgba(0,0,0,.22)",
      }}>{mobile ? "✦" : "✦ Ask Lufi"}</button>
    );
  }

  return (
    <div style={{
      position: "fixed", zIndex: 900,
      // Phone: a bottom sheet pinned to both edges. A 380px floating card on a
      // 390px screen is a floating card with 5px of margin — all the cost of the
      // chrome and none of the benefit.
      ...(mobile
        ? { left: 8, right: 8, bottom: "calc(8px + env(safe-area-inset-bottom))",
            maxHeight: "min(76dvh, calc(100dvh - 80px))" }
        : { right: 22, bottom: 22, width: 380, maxWidth: "calc(100vw - 44px)",
            maxHeight: "min(560px, calc(100vh - 44px))" }),
      background: T.card, border: `1px solid ${T.line}`, borderRadius: 16,
      boxShadow: "0 16px 50px rgba(0,0,0,.25)", display: "flex", flexDirection: "column",
      overflow: "hidden", fontFamily: T.sans,
    }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "12px 16px", background: col + "14", borderBottom: `1px solid ${T.line}` }}>
        <span style={{ width: 26, height: 26, borderRadius: 8, background: col, color: T.onAccent, display: "grid", placeItems: "center", fontSize: 13, fontWeight: 800 }}>✦</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 800, color: T.ink }}>Ask Lufi · {agentName}</div>
          <div style={{ fontSize: 10.5, color: T.ink3 }}>works on this agent's latest data · uses its configured model</div>
        </div>
        <button type="button" onClick={() => setOpen(false)} aria-label="Close Ask Lufi"
          style={{ border: "none", background: "transparent", color: T.ink3, fontSize: 16, cursor: "pointer", padding: 4 }}>✕</button>
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
            color: m.role === "user" ? T.onAccent : m.role === "error" ? T.red : T.ink2,
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
          style={{ flex: 1, minWidth: 0, border: `1px solid ${T.line}`, borderRadius: 9, padding: "9px 12px", fontSize: 13, fontFamily: T.sans, background: T.cardAlt, color: T.ink }} />
        <button onClick={send} disabled={busy || !input.trim()} style={{
          padding: "9px 16px", background: input.trim() && !busy ? col : T.line2, color: input.trim() && !busy ? T.onAccent : T.ink4,
          border: "none", borderRadius: 9, fontSize: 13, fontWeight: 800, fontFamily: T.sans, cursor: input.trim() && !busy ? "pointer" : "default",
        }}>Send</button>
      </div>
    </div>
  );
}
