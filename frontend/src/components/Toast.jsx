// ============================================================================
// Toast.jsx — lightweight in-app notification toasts
// Usage: addToast(message, type, durationMs)  types: success|error|warning|info
// ============================================================================
import { useState, useEffect, useCallback, useRef } from "react";
import { T } from "../theme/tokens";

const COLORS = {
  success: { bg: "#f0fdf4", border: "#16a34a55", text: "#15803d", icon: "✓" },
  error:   { bg: "#fef2f2", border: "#dc262655", text: "#dc2626", icon: "⚠" },
  warning: { bg: "#fffbeb", border: "#d9770655", text: "#b45309", icon: "!" },
  info:    { bg: "#eff6ff", border: "#2563eb55", text: "#1d4ed8", icon: "ℹ" },
};

function ToastItem({ toast, onDismiss }) {
  const [visible, setVisible] = useState(false);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const t1 = setTimeout(() => setVisible(true), 10);
    const t2 = setTimeout(() => dismiss(), toast.duration || 4200);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []); // eslint-disable-line

  const dismiss = () => {
    setLeaving(true);
    setTimeout(() => onDismiss(toast.id), 280);
  };

  const c = COLORS[toast.type] || COLORS.info;
  return (
    <div onClick={dismiss} style={{
      display: "flex", alignItems: "flex-start", gap: 10,
      background: c.bg, border: `1px solid ${c.border}`,
      borderRadius: 11, padding: "11px 14px",
      boxShadow: "0 4px 16px rgba(0,0,0,.12)",
      cursor: "pointer", userSelect: "none",
      minWidth: 260, maxWidth: 360,
      transform: visible && !leaving ? "translateX(0)" : "translateX(calc(100% + 20px))",
      opacity: visible && !leaving ? 1 : 0,
      transition: leaving
        ? "transform .28s ease-in, opacity .28s ease-in"
        : "transform .3s cubic-bezier(.34,1.56,.64,1), opacity .2s ease",
    }}>
      <div style={{
        width: 22, height: 22, borderRadius: 6, background: c.text + "18",
        color: c.text, fontSize: 12, fontWeight: 800,
        display: "grid", placeItems: "center", flex: "0 0 auto", marginTop: 1,
      }}>{c.icon}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        {toast.title && <div style={{ fontSize: 12.5, fontWeight: 700, color: c.text, marginBottom: 1 }}>{toast.title}</div>}
        <div style={{ fontSize: 12, color: c.text, opacity: 0.85, lineHeight: 1.4 }}>{toast.message}</div>
      </div>
      <div style={{ fontSize: 14, color: c.text, opacity: 0.5, marginTop: 1, flexShrink: 0 }}>×</div>
    </div>
  );
}

export function ToastContainer({ toasts, dismiss }) {
  return (
    <div style={{
      position: "fixed", bottom: 20, right: 20, zIndex: 9999,
      display: "flex", flexDirection: "column", gap: 8,
      pointerEvents: "none",
    }}>
      {toasts.map((t) => (
        <div key={t.id} style={{ pointerEvents: "all" }}>
          <ToastItem toast={t} onDismiss={dismiss} />
        </div>
      ))}
    </div>
  );
}

let _toastId = 0;
export function useToasts() {
  const [toasts, setToasts] = useState([]);

  const add = useCallback((message, type = "info", opts = {}) => {
    const id = ++_toastId;
    setToasts((prev) => [...prev.slice(-4), { id, message, type, ...opts }]);
    return id;
  }, []);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, addToast: add, dismissToast: dismiss };
}

// Hook: watch sys.agents transitions and fire toasts automatically
export function useAgentToasts(sys, addToast) {
  const prev = useRef({});
  const prevAlarm = useRef(null);

  useEffect(() => {
    if (!sys?.agents) return;
    sys.agents.forEach((a) => {
      const p = prev.current[a.id];
      if (p === "running" && a.status === "idle") {
        addToast(`${a.n} completed`, "success", { title: "Agent done", duration: 3500 });
      }
      if (a.status === "crashed" && p !== "crashed") {
        addToast(`${a.n} crashed — auto-restarting`, "error", { title: "Agent crashed", duration: 6000 });
      }
      if (p === undefined && a.status === "running") {
        // first load — skip
      }
      prev.current[a.id] = a.status;
    });

    const alarm = sys.alarm;
    if (alarm && !prevAlarm.current) {
      addToast(`${alarm.label} at ${alarm.value}% — ${alarm.action}`, "warning", { title: "Resource alarm", duration: 8000 });
    }
    prevAlarm.current = alarm;
  }, [sys, addToast]);
}
