// ============================================================================
// Mailman.jsx — Gmail triage: category breakdown + AI-summarized inbox.
// ============================================================================
import { useState, useEffect } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, Dot, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent, getConfig } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls } from "../components/Common";

const CAT_PALETTE = {
  Urgent: "#e5484d", "Action Required": "#f59e0b", "Follow-Up": "#7c5cf6",
  Personal: "#0d9488", Newsletter: "#2f6feb", Notification: "#94a3b8", Other: "#c0c6d0",
};

// "Needs attention" surfaces ONLY mail from the configured key-people list —
// not every email the LLM happened to call Urgent / Action Required.
const isNotable = (m) => m.key;

function parseSender(sender = "") {
  const m = sender.match(/^(.*?)\s*<(.+?)>$/);
  if (m) return { from: m[1].replace(/"/g, "").trim() || m[2], email: m[2] };
  return { from: sender, email: sender.includes("@") ? sender : "" };
}

function adaptEmails(list) {
  if (!Array.isArray(list) || list.length === 0) return [];
  return list.map((e, i) => {
    const { from, email } = parseSender(e.sender || e.from || "");
    return {
      id: e.id || i,
      from: from || "Unknown",
      email,
      subj: e.subject || e.subj || "(no subject)",
      cat: e.category || e.cat || "Other",
      // Only LLM-mentioning mail is actually starred + labeled in Gmail now.
      llm: !!(e.is_llm ?? e.llm),
      star: !!(e.is_llm ?? e.starred),
      key: !!(e.is_key ?? e.key),
      sum: e.ai_summary || e.sum || e.snippet || "",
      t: e.t || e.time || "",
    };
  });
}

function adaptCats(breakdown) {
  if (!breakdown || Object.keys(breakdown).length === 0) return [];
  return Object.entries(breakdown).map(([k, n]) => ({ k, n, c: CAT_PALETTE[k] || "#94a3b8" }));
}

function CatBar({ cats }) {
  const total = cats.reduce((s, c) => s + c.n, 0) || 1;
  return (
    <Card pad={15}>
      <SectionTitle sub={`${total} emails classified by Qwen3 in the last scan`} right={<Pill mono c={T.ink3}>{total} total</Pill>}>Category breakdown</SectionTitle>
      <div style={{ display: "flex", height: 12, borderRadius: 7, overflow: "hidden", marginBottom: 16 }}>
        {cats.map((c) => <div key={c.k} style={{ width: (c.n / total * 100) + "%", background: c.c }} title={`${c.k}: ${c.n}`} />)}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
        {cats.map((c) => (
          <div key={c.k} style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <Dot c={c.c} s={9} />
            <div>
              <div style={{ fontSize: 12.5, fontWeight: 600 }}>{c.k}</div>
              <div style={{ fontSize: 11, color: T.ink4, fontFamily: T.mono }}>{c.n} email{c.n !== 1 ? "s" : ""}</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function MailRow({ m, onStar }) {
  const cc = CAT_PALETTE[m.cat] || "#94a3b8";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "26px 1.1fr 2.2fr 110px", gap: 12, padding: "14px 4px", borderBottom: `1px solid ${T.line2}`, alignItems: "start" }}>
      <button onClick={() => onStar(m.id)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 16, color: m.star ? T.amber : "#d4d8df", padding: 0, lineHeight: 1 }}>★</button>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.from}</span>
          {m.key && <span style={{ fontSize: 9, fontWeight: 700, color: T.violet, background: T.violetBg, padding: "1px 5px", borderRadius: 5, flex: "0 0 auto" }}>KEY</span>}
        </div>
        <div style={{ fontSize: 11, color: T.ink4, fontFamily: T.mono, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.email}</div>
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 3 }}>{m.subj}</div>
        {m.sum && <div style={{ fontSize: 12, color: T.ink2, lineHeight: 1.4, display: "flex", gap: 6 }}>
          <span style={{ color: T.violet, fontWeight: 700, flex: "0 0 auto" }}>AI</span><span>{m.sum}</span>
        </div>}
      </div>
      <div style={{ textAlign: "right" }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: cc, background: cc + "18", padding: "4px 9px", borderRadius: 7, whiteSpace: "nowrap" }}>{m.cat}</span>
        {m.t && <div style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono, marginTop: 6 }}>{m.t}</div>}
      </div>
    </div>
  );
}

export default function Mailman({ status, agentError }) {
  const { data, refresh } = useAgentData("mailman");
  const [scanning, setScanning] = useState(false);
  const [keyPeople, setKeyPeople] = useState("");
  const [configuredKeyPeople, setConfiguredKeyPeople] = useState("");
  const [sendEmail, setSendEmail] = useState(false);
  const [starOverride, setStarOverride] = useState({});

  // The input below is a per-scan override; the panel should still show the
  // people actually configured (Settings → Key people / KEY_PEOPLE) by default.
  useEffect(() => { getConfig().then((c) => setConfiguredKeyPeople(c?.key_people || "")).catch(() => {}); }, []);
  const keyPeopleList = (keyPeople || configuredKeyPeople).split(",").map((s) => s.trim()).filter(Boolean);

  const cats = adaptCats(data?.emails?.breakdown);
  const baseMails = adaptEmails(data?.emails?.emails);
  const mails = baseMails.map((m) => (m.id in starOverride ? { ...m, star: starOverride[m.id] } : m));
  const shown = mails.filter(isNotable);
  // Gmail starring + labeling is gated on the "LLM" keyword; key people drive
  // the Needs-attention list. The two are tracked independently now.
  const llmCount = mails.filter((m) => m.llm).length;
  const keyCount = mails.filter((m) => m.key).length;
  const onStar = (id) => setStarOverride((o) => ({ ...o, [id]: !mails.find((m) => m.id === id)?.star }));

  const scan = async () => {
    setScanning(true);
    await triggerAgent("mailman", { key_people: keyPeople, send_email: sendEmail });
    setTimeout(refresh, 4000); setTimeout(refresh, 12000);
    setTimeout(() => setScanning(false), 1800);
  };
  const busy = scanning || status === "running";

  return (
    <div>
      <TabHeader icon="✉" color={T.blue} title="Mailman" sub="Gmail · OAuth 2.0 · LLM inbox triage"
        actions={<>
          <Pill mono c={T.ink3}>scan every 60m</Pill>
          <EmailPreviewButton agentId="mailman" label="Preview summary" />
          <AgentControls agentId="mailman" onRun={scan} busy={busy} refresh={refresh} runLabel="Scan now" runningLabel="Scanning…" />
        </>} />
      <div className="om-stagger" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 11 }}>
        <ErrorBanner error={agentError} />
        {(llmCount > 0 || keyCount > 0) && (
          <div style={{ background: T.amberBg, border: `1px solid ${T.amber}55`, borderRadius: 12, padding: "11px 16px", display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 16 }}>⭐</span>
            <div style={{ fontSize: 12.5, color: "#92400e", fontWeight: 600 }}>
              {llmCount > 0
                ? <>{llmCount} email{llmCount !== 1 ? "s" : ""} mention “LLM” — auto-starred &amp; labeled in Gmail.</>
                : <>No “LLM” mail this scan — nothing labeled in Gmail.</>}
              {keyCount > 0 && <span style={{ fontWeight: 500, opacity: 0.85 }}> · {keyCount} from key people need attention.</span>}
            </div>
          </div>
        )}

        <Card pad={14}>
          <SectionTitle sub="Override key-people list and email behaviour for the next scan">Scan configuration</SectionTitle>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <label style={{ fontSize: 11, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4 }}>Key people (comma-separated)</label>
              <input value={keyPeople} onChange={(e) => setKeyPeople(e.target.value)} placeholder="Sarah Chen, Marcus Webb…"
                style={{ width: "100%", marginTop: 6, border: `1px solid ${T.line}`, borderRadius: 9, padding: "9px 12px", fontFamily: T.sans, fontSize: 13, background: T.card, color: T.ink, outline: "none", boxSizing: "border-box" }} />
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 13, color: T.ink2, paddingBottom: 9 }}>
              <input type="checkbox" checked={sendEmail} onChange={(e) => setSendEmail(e.target.checked)} /> Send email summary
            </label>
          </div>
        </Card>

        {mails.length === 0 ? (
          <EmptyState icon="✉" title="No inbox scan yet"
            hint="Click Scan now to triage your Gmail inbox with the LLM (requires Gmail OAuth)." />
        ) : (
          <>
            <CatBar cats={cats} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 16, alignItems: "start" }}>
              <Card pad={15}>
                <SectionTitle sub="Mail from your key people only — routine inbox stays out of sight" right={<Pill mono c={T.ink3}>{shown.length} of {mails.length}</Pill>}>Needs attention</SectionTitle>
                {shown.length === 0 ? (
                  <div style={{ padding: "30px 6px", textAlign: "center", color: T.ink3, fontSize: 12.5, lineHeight: 1.6 }}>
                    Nothing from your key people in the last scan.<br />
                    {mails.length} routine email{mails.length !== 1 ? "s" : ""} stayed out of view.
                  </div>
                ) : shown.map((m) => <MailRow key={m.id} m={m} onStar={onStar} />)}
              </Card>
              <Card pad={15}>
                <SectionTitle sub={keyPeople ? "Override for the next scan" : "From Settings · surfaced under Needs attention"}>Key people</SectionTitle>
                <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                  {keyPeopleList.map((p) => (
                    <div key={p} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 9px", borderRadius: 9, background: T.cardAlt, border: `1px solid ${T.line2}` }}>
                      <span style={{ width: 26, height: 26, borderRadius: 26, background: T.violet + "1a", color: T.violet, display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700 }}>{p.split(/[\s@]/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase()}</span>
                      <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p}</span>
                      <Dot c={T.green} s={7} />
                    </div>
                  ))}
                  {keyPeopleList.length === 0 && <div style={{ fontSize: 12, color: T.ink4 }}>No key people configured yet — add some in Settings or the override above.</div>}
                </div>
              </Card>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
