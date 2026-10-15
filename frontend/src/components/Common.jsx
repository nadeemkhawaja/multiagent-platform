// Shared UI bits: email-preview modal trigger + agent error banner.
import { useState, useCallback } from "react";
import { createPortal } from "react-dom";
import { T } from "../theme/tokens";
import { Btn, Card, SectionTitle, useDialog } from "../theme/ui";
import { emailPreview, stopAgent } from "../state/api";
import { Ico } from "../theme/icons";

// Collapsible section — persists open/closed per `id` in localStorage so a
// busy page (e.g. Alpha Wolf) can default secondary detail to collapsed
// without it re-collapsing on every refresh/poll.
export function Collapsible({ id, title, sub, defaultOpen = false, right, children }) {
  const key = `om-collapse:${id}`;
  const [open, setOpen] = useState(() => {
    try {
      const stored = localStorage.getItem(key);
      return stored === null ? defaultOpen : stored === "1";
    } catch { return defaultOpen; }
  });
  const toggle = () => {
    setOpen((v) => {
      const next = !v;
      try { localStorage.setItem(key, next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });
  };
  // role="button" rather than a real <button>: SectionTitle renders an <h2>,
  // and a heading is not valid content inside a button element. aria-expanded
  // + aria-controls give the disclosure its state either way.
  const panelId = `om-collapse-panel:${id}`;
  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
        }}
        style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", userSelect: "none", borderRadius: 8 }}
      >
        {/* `width` sits before `transition` on purpose: only the transform is
            animated, and the two keys adjacent read as a width transition to
            both the design detector and anyone skimming the line. */}
        <span aria-hidden="true" style={{ fontSize: 11, color: T.ink4, display: "inline-block", width: 10, transform: open ? "rotate(90deg)" : "none", transition: "transform .15s" }}>▶</span>
        <div style={{ flex: 1, minWidth: 0 }}><SectionTitle sub={sub}>{title}</SectionTitle></div>
        {right}
      </div>
      <div id={panelId} hidden={!open} style={{ marginTop: open ? 10 : 0 }}>{open && children}</div>
    </div>
  );
}

// ── Lufi — the platform's AI analyst persona ──────────────────────────────────
// Tries /lufi.png (drop a real photo there) and falls back to the bundled
// /lufi.svg illustration. Used wherever Lufi narrates a "read"/commentary.
export function LufiAvatar({ size = 32 }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%", flex: "0 0 auto",
      background: T.violetBg, border: `2px solid ${T.violet}55`,
      display: "grid", placeItems: "center",
      fontSize: Math.round(size * 0.45), color: T.violet, fontWeight: 800,
    }}>✦</div>
  );
}

// Run / Stop / Restart controls shared by every agent tab.
// `onRun` is the tab's own trigger handler (builds any per-agent config);
// `busy` reflects whether the agent is currently running.
export function AgentControls({ agentId, onRun, busy, refresh, runLabel = "Manual run", runningLabel = "Running…" }) {
  const [stopping, setStopping] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [error, setError] = useState(null);

  const stop = async () => {
    setStopping(true); setError(null);
    try { await stopAgent(agentId); refresh && refresh(); }
    catch (e) { setError(e?.message || "Stop failed"); }
    finally { setTimeout(() => setStopping(false), 600); }
  };

  // Guarded: restart awaits a network round-trip before onRun(), and nothing
  // previously stopped a second click landing inside that window and issuing a
  // duplicate stop+run pair.
  const restart = async () => {
    if (restarting) return;
    setRestarting(true); setError(null);
    try { await stopAgent(agentId); await onRun(); }
    catch (e) { setError(e?.message || "Restart failed"); }
    finally { setRestarting(false); }
  };

  return (
    <>
      <Btn size="sm" onClick={onRun} disabled={busy}>
        <span aria-hidden="true" style={{ display: "inline-block", animation: busy ? "omSpin .8s linear infinite" : "none" }}>↻</span>
        {busy ? runningLabel : runLabel}
      </Btn>
      <Btn size="sm" kind="danger" onClick={stop} disabled={!busy || stopping}>■ {stopping ? "Stopping…" : "Stop"}</Btn>
      <Btn size="sm" kind="ghost" onClick={restart} disabled={busy || restarting}>⟲ {restarting ? "Restarting…" : "Restart"}</Btn>
      {error && (
        <span role="status" style={{ fontSize: 11.5, fontWeight: 600, color: T.red, background: T.redBg, border: `1px solid ${T.red}44`, borderRadius: 6, padding: "3px 9px" }}>
          {error}
        </span>
      )}
    </>
  );
}

// The endpoint currently answers {html:{html:"<!DOCTYPE…"}} but has also used a
// flat {html:"…"}. Reading only one shape put the literal string
// "[object Object]" into srcDoc — invisible until the modal itself was fixed.
function readHtml(r) {
  const v = r?.html ?? r;
  if (typeof v === "string") return v;
  if (typeof v?.html === "string") return v.html;
  return "";
}

export function EmailPreviewButton({ agentId, label = "Preview email" }) {
  const [html, setHtml] = useState(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const show = async () => {
    setLoading(true);
    setError(null);
    // Previously try/finally with no catch: with the backend down this threw an
    // unhandled rejection, no modal opened, and the button simply stopped
    // spinning — the failure was invisible.
    try {
      const r = await emailPreview(agentId);
      setHtml(readHtml(r));
      setOpen(true);
    } catch (e) {
      setError(e?.message || "Could not reach the backend.");
      setOpen(true);
    } finally {
      setLoading(false);
    }
  };

  const close = useCallback(() => setOpen(false), []);
  const dialogRef = useDialog(open, close);
  const titleId = `email-preview-${agentId}`;

  return (
    <>
      <Btn size="sm" kind="soft" onClick={show} disabled={loading}>{loading ? "Loading…" : label}</Btn>
      {/* Portalled to <body>. This button lives inside TabHeader, which sets
          backdrop-filter — that makes the header a containing block for fixed
          positioning, so the overlay was being laid out against the 55px-tall
          header instead of the viewport and rendered clipped and off-centre. */}
      {open && createPortal(
        <div onClick={close} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", zIndex: 50, display: "grid", placeItems: "center", padding: 24 }}>
          <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
            style={{ background: T.card, borderRadius: 14, width: "min(700px,94vw)", maxHeight: "88vh", overflow: "hidden", border: `1px solid ${T.line}`, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 18px", borderBottom: `1px solid ${T.line}` }}>
              <div id={titleId} style={{ fontWeight: 700 }}>Email preview</div>
              <Btn size="sm" kind="ghost" onClick={close}>✕ Close</Btn>
            </div>
            {error ? (
              <div style={{ padding: "28px 22px" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: T.red, marginBottom: 6 }}>Couldn't load the preview</div>
                <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.55, marginBottom: 14 }}>{error}</div>
                <Btn size="sm" onClick={show}>Try again</Btn>
              </div>
            ) : html ? (
              // sandbox with no allowances: this renders agent/LLM-authored HTML,
              // which has no business running scripts or navigating the app.
              <iframe title="Email preview" srcDoc={html} sandbox=""
                style={{ border: "none", width: "100%", height: "72vh", background: "#fff" }} />
            ) : (
              <div style={{ padding: "28px 22px", fontSize: 12.5, color: T.ink3 }}>
                This agent hasn't produced an email yet — run it once and the digest will appear here.
              </div>
            )}
          </div>
        </div>,
        document.body
      )}
    </>
  );
}

export function EmptyState({ icon = "∅", title, hint }) {
  return (
    <Card pad={44} style={{ textAlign: "center" }}>
      <div style={{ display: "flex", justifyContent: "center", color: T.ink4,
        fontSize: 30, opacity: 0.5 }}>{icon}</div>
      <div style={{ fontSize: 14, fontWeight: 700, marginTop: 10 }}>{title}</div>
      {hint && <div style={{ fontSize: 12.5, color: T.ink3, marginTop: 5 }}>{hint}</div>}
    </Card>
  );
}

// `kind="run"` reports what the agent's last execution did; `kind="data"`
// reports that the dashboard couldn't read it. They are different failures and
// conflating them sends you looking in the wrong place.
export function ErrorBanner({ error, kind = "run", onRetry }) {
  if (!error) return null;
  const lead = kind === "data" ? "Couldn't load this agent's data" : "Last run error";
  return (
    <div role="alert" style={{ background: T.redBg, border: `1px solid ${T.red}55`, borderRadius: 12, padding: "11px 16px", display: "flex", alignItems: "center", gap: 11, fontSize: 12.5, color: T.red, fontWeight: 600 }}>
      <Ico name="warn" size={15} style={{ marginTop: 1 }} />
      {/* Backend messages can be long single tokens (paths, tracebacks) — let
          them wrap rather than force the whole banner to overflow. */}
      <span style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{lead}: {error}</span>
      {onRetry && <Btn size="sm" kind="ghost" onClick={onRetry} style={{ flex: "0 0 auto" }}>Retry</Btn>}
    </div>
  );
}
