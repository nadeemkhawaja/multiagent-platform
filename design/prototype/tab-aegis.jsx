// ============================================================================
// tab-aegis.jsx — Aegis: reputation guardian (mention feed + reply composer)
// ============================================================================
// risk styling is mode-aware: getters read the live tokens (T) so the
// selected mention card stays legible in dark mode.
const RISK = {
  high: { t: "High risk", get c() { return T.red; }, get bg() { return T.redBg; } },
  med: { t: "Medium", get c() { return T.amber; }, get bg() { return T.amberBg; } },
  low: { t: "Low", get c() { return T.ink3; }, get bg() { return T.line2; } },
};
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

function AegisTab() {
  const [sel, setSel] = React.useState(MENTIONS[0].id);
  const [drafts, setDrafts] = React.useState(Object.fromEntries(MENTIONS.map((m) => [m.id, m.reply])));
  const [handled, setHandled] = React.useState({});
  const [editing, setEditing] = React.useState(false);
  const m = MENTIONS.find((x) => x.id === sel);
  const highCount = MENTIONS.filter((x) => x.risk === "high" && !handled[x.id]).length;

  const approve = () => { setHandled((h) => ({ ...h, [sel]: "approved" })); setEditing(false); };
  const dismiss = () => { setHandled((h) => ({ ...h, [sel]: "dismissed" })); };

  return (
    <div>
      <TabHeader icon="❖" color={T.teal || "#0d9488"} title="Aegis" sub="Reputation guardian · mentions across Reddit · X · News · Mastodon"
        actions={<>
          <Pill mono c={T.ink3}>digest 18:00 daily</Pill>
          <Btn size="sm">↻ Scan sources</Btn>
        </>} />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>
        {/* high-risk alert */}
        {highCount > 0 && (
          <div style={{ background: T.redBg, border: `1px solid ${T.red}55`, borderRadius: 12, padding: "13px 18px", display: "flex", alignItems: "center", gap: 13 }}>
            <span style={{ fontSize: 18 }}>🛡</span>
            <div style={{ fontSize: 13, color: T.red, fontWeight: 600, flex: 1 }}>
              {highCount} high-risk mention{highCount !== 1 ? "s" : ""} need review — a defamatory claim naming you is spreading on Reddit. Real-time alert sent.
            </div>
          </div>
        )}

        {/* risk stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
          {[["Mentions today", "27", T.ink, "+8 vs avg"], ["Net sentiment", "−21", T.red, "trending down"], ["High risk", String(highCount), T.red, "needs action"], ["Avg response", "12m", T.green, "within SLA"]].map(([l, v, c, sub]) => (
            <Card key={l} pad={16}>
              <div style={{ fontSize: 12, color: T.ink3, fontWeight: 600 }}>{l}</div>
              <div style={{ fontSize: 26, fontWeight: 700, fontFamily: T.mono, letterSpacing: -0.5, color: c, marginTop: 2 }}>{v}</div>
              <div style={{ fontSize: 11, color: T.ink4, marginTop: 1 }}>{sub}</div>
            </Card>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.15fr", gap: 16, alignItems: "start" }}>
          {/* mention feed */}
          <Card pad={20}>
            <SectionTitle sub="Sorted by risk · LLM-scored">Mention feed</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {MENTIONS.map((x) => {
                const active = x.id === sel;
                const r = RISK[x.risk];
                const done = handled[x.id];
                return (
                  <button key={x.id} onClick={() => { setSel(x.id); setEditing(false); }} style={{
                    textAlign: "left", cursor: "pointer", border: `1px solid ${active ? r.c + "99" : T.line}`, borderRadius: 11, padding: 13,
                    background: active ? r.bg : T.card, opacity: done ? 0.62 : 1, transition: "all .15s", font: "inherit",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <span style={{ fontSize: 13 }}>{srcGlyph[x.src]}</span>
                      <span style={{ fontSize: 11.5, fontWeight: 700 }}>{x.src}</span>
                      <span style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono }}>{x.sub}</span>
                      <span style={{ marginLeft: "auto", fontSize: 9.5, fontWeight: 700, color: r.c, background: T.card, border: `1px solid ${r.c}44`, padding: "2px 7px", borderRadius: 5 }}>{r.t}</span>
                    </div>
                    <div style={{ fontSize: 12.5, color: T.ink, lineHeight: 1.4, textWrap: "pretty", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{x.text}</div>
                    <div style={{ marginTop: 8 }}><SentBar v={x.sent} /></div>
                    {done && <div style={{ fontSize: 10.5, fontWeight: 700, color: done === "approved" ? T.green : T.ink4, marginTop: 7 }}>{done === "approved" ? "✓ Reply approved & posted" : "✕ Dismissed"}</div>}
                  </button>
                );
              })}
            </div>
          </Card>

          {/* detail + composer */}
          <Card pad={22} style={{ position: "sticky", top: 84 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 14 }}>
              <span style={{ fontSize: 15 }}>{srcGlyph[m.src]}</span>
              <span style={{ fontSize: 13.5, fontWeight: 700 }}>{m.src} · {m.sub}</span>
              <span style={{ fontSize: 11.5, color: T.ink4, fontFamily: T.mono }}>{m.author}</span>
              <span style={{ marginLeft: "auto", fontSize: 10, fontWeight: 700, color: RISK[m.risk].c, background: RISK[m.risk].bg, padding: "3px 9px", borderRadius: 6 }}>{RISK[m.risk].t}</span>
            </div>
            <div style={{ fontSize: 13.5, color: T.ink, lineHeight: 1.5, padding: "14px 16px", background: T.cardAlt, border: `1px solid ${T.line2}`, borderRadius: 10, textWrap: "pretty" }}>“{m.text}”</div>

            <div style={{ display: "flex", gap: 10, marginTop: 14, padding: "11px 14px", background: T.violetBg, borderRadius: 10 }}>
              <span style={{ color: T.violet, fontWeight: 700, fontSize: 12, flex: "0 0 auto" }}>◇ Why flagged</span>
              <span style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.45, textWrap: "pretty" }}>{m.why}</span>
            </div>

            <div style={{ fontSize: 12, fontWeight: 700, margin: "18px 0 8px", display: "flex", alignItems: "center", gap: 8 }}>
              Suggested response <Pill mono c={T.violet} bg={T.violetBg} style={{ padding: "2px 7px" }}>Qwen3 draft</Pill>
              <span style={{ marginLeft: "auto", fontSize: 11, fontWeight: 600, color: T.ink4 }}>human-approved · never auto-posted</span>
            </div>
            <textarea value={drafts[sel]} onChange={(e) => setDrafts((d) => ({ ...d, [sel]: e.target.value }))}
              readOnly={!editing}
              style={{ width: "100%", minHeight: 96, resize: "vertical", border: `1px solid ${editing ? T.violet : T.line}`, borderRadius: 10, padding: 13, fontFamily: T.sans, fontSize: 13, lineHeight: 1.5, color: T.ink, background: editing ? T.card : T.cardAlt, outline: "none", boxSizing: "border-box" }} />

            <div style={{ display: "flex", gap: 9, marginTop: 14, alignItems: "center" }}>
              {handled[sel] === "approved" ? (
                <Pill c={T.green} bg={T.greenBg} bd={T.green + "55"}><Dot c={T.green} />Approved &amp; posted</Pill>
              ) : handled[sel] === "dismissed" ? (
                <Pill c={T.ink3}>Dismissed</Pill>
              ) : (
                <>
                  <Btn kind="primary" onClick={approve}>✓ Approve &amp; post</Btn>
                  <Btn onClick={() => setEditing((e) => !e)}>{editing ? "Done editing" : "Edit"}</Btn>
                  <Btn kind="ghost" onClick={dismiss} style={{ marginLeft: "auto" }}>Dismiss</Btn>
                </>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

window.AegisTab = AegisTab;
