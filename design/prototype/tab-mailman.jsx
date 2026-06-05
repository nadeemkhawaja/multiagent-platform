// ============================================================================
// tab-mailman.jsx — Gmail triage: category breakdown + AI-summarized inbox
// ============================================================================
function CatBar() {
  const total = MAIL_CATS.reduce((s, c) => s + c.n, 0);
  return (
    <Card pad={20}>
      <SectionTitle sub={`${total} emails classified by Qwen3 in the last scan`} right={<Pill mono c={T.ink3}>{total} total</Pill>}>Category breakdown</SectionTitle>
      <div style={{ display: "flex", height: 12, borderRadius: 7, overflow: "hidden", marginBottom: 16 }}>
        {MAIL_CATS.map((c) => <div key={c.k} style={{ width: (c.n / total * 100) + "%", background: c.c }} title={`${c.k}: ${c.n}`} />)}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
        {MAIL_CATS.map((c) => (
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

const CAT_COLOR = Object.fromEntries(MAIL_CATS.map((c) => [c.k, c.c]));

function MailRow({ m, onStar }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "26px 1.1fr 2.2fr 110px", gap: 12, padding: "14px 4px", borderBottom: `1px solid ${T.line2}`, alignItems: "start" }}>
      <button onClick={() => onStar(m.id)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 16, color: m.star ? T.amber : "#d4d8df", padding: 0, lineHeight: 1 }}>★</button>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.from}</span>
          {m.key && <span title="Key person" style={{ fontSize: 9, fontWeight: 700, color: T.violet, background: T.violetBg, padding: "1px 5px", borderRadius: 5, flex: "0 0 auto" }}>KEY</span>}
        </div>
        <div style={{ fontSize: 11, color: T.ink4, fontFamily: T.mono, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.email}</div>
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 3 }}>{m.subj}</div>
        <div style={{ fontSize: 12, color: T.ink2, lineHeight: 1.4, textWrap: "pretty", display: "flex", gap: 6 }}>
          <span style={{ color: T.violet, fontWeight: 700, flex: "0 0 auto" }}>AI</span>
          <span>{m.sum}</span>
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: CAT_COLOR[m.cat], background: CAT_COLOR[m.cat] + "18", padding: "4px 9px", borderRadius: 7, whiteSpace: "nowrap" }}>{m.cat}</span>
        <div style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono, marginTop: 6 }}>{m.t}</div>
      </div>
    </div>
  );
}

function MailmanTab() {
  const [mails, setMails] = React.useState(MAILS);
  const [scanning, setScanning] = React.useState(false);
  const onStar = (id) => setMails((ms) => ms.map((m) => m.id === id ? { ...m, star: !m.star } : m));
  const scan = () => { setScanning(true); setTimeout(() => setScanning(false), 1500); };
  const urgent = mails.filter((m) => m.cat === "Urgent").length;
  return (
    <div>
      <TabHeader icon="✉" color={T.blue} title="Mailman" sub="Gmail · OAuth 2.0 · LLM inbox triage"
        actions={<>
          <Pill mono c={T.ink3}>scan every 15m</Pill>
          <Btn size="sm" onClick={scan}>
            <span style={{ display: "inline-block", animation: scanning ? "omSpin .8s linear infinite" : "none" }}>↻</span>
            {scanning ? "Scanning…" : "Scan now"}
          </Btn>
        </>} />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>
        {/* key-people alert */}
        {urgent > 0 && (
          <div style={{ background: T.redBg, border: `1px solid ${T.red}55`, borderRadius: 12, padding: "13px 18px", display: "flex", alignItems: "center", gap: 13 }}>
            <span style={{ fontSize: 18 }}>🔔</span>
            <div style={{ fontSize: 13, color: T.red, fontWeight: 600 }}>
              {urgent} urgent email{urgent !== 1 ? "s" : ""} — including <b>Sarah Chen</b> (key person) needs an answer by EOD. Auto-starred &amp; labeled <b>Urgent</b>.
            </div>
          </div>
        )}
        <CatBar />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 16, alignItems: "start" }}>
          <Card pad={20}>
            <SectionTitle sub="Auto-labeled, starred & summarized" right={<Btn size="sm" kind="ghost">Daily summary →</Btn>}>Inbox</SectionTitle>
            {mails.map((m) => <MailRow key={m.id} m={m} onStar={onStar} />)}
          </Card>
          <Card pad={20}>
            <SectionTitle sub="Always alert on these senders">Key people</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {KEY_PEOPLE.map((p) => (
                <div key={p} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 9px", borderRadius: 9, background: T.cardAlt, border: `1px solid ${T.line2}` }}>
                  <span style={{ width: 26, height: 26, borderRadius: 26, background: T.violet + "1a", color: T.violet, display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700 }}>{p.split(" ").map(w => w[0]).join("")}</span>
                  <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1 }}>{p}</span>
                  <Dot c={T.green} s={7} />
                </div>
              ))}
              <Btn size="sm" kind="soft" style={{ marginTop: 4, justifyContent: "center" }}>+ Add key person</Btn>
            </div>
            <div style={{ marginTop: 18, paddingTop: 16, borderTop: `1px solid ${T.line2}` }}>
              <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Daily summary</div>
              <div style={{ fontSize: 11.5, color: T.ink3, lineHeight: 1.5, fontFamily: T.mono }}>Sent 08:05 · 65 emails · 3 urgent · 7 action · 22 auto-archived</div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

window.MailmanTab = MailmanTab;
