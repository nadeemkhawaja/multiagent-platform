// ============================================================================
// tab-aitimes.jsx — AI YouTube digest (5 news + 5 personality)
// ============================================================================
function VideoCard({ v }) {
  return (
    <div style={{ border: `1px solid ${T.line}`, borderRadius: 12, overflow: "hidden", background: T.card, cursor: "pointer", transition: "transform .15s, box-shadow .15s" }}
      onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 24px rgba(20,24,40,.08)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "none"; }}>
      <div style={{ position: "relative" }}>
        <StripedSlot h={132} color={v.c} label="thumbnail" glyph="▶" />
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
          <div style={{ width: 44, height: 44, borderRadius: 44, background: "rgba(255,255,255,.92)", display: "grid", placeItems: "center", color: v.c, fontSize: 16, boxShadow: "0 4px 14px rgba(0,0,0,.12)" }}>▶</div>
        </div>
        <span style={{ position: "absolute", bottom: 8, right: 8, background: "rgba(15,17,22,.82)", color: "#fff", fontFamily: T.mono, fontSize: 10.5, padding: "2px 6px", borderRadius: 5 }}>{v.dur}</span>
      </div>
      <div style={{ padding: 13 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.35, textWrap: "pretty", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", minHeight: 38 }}>{v.title}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 9, fontSize: 11.5, color: T.ink3 }}>
          <span style={{ width: 18, height: 18, borderRadius: 18, background: v.c + "22", color: v.c, display: "grid", placeItems: "center", fontSize: 9, fontWeight: 700 }}>{v.ch[0]}</span>
          <span style={{ fontWeight: 600, color: T.ink2 }}>{v.ch}</span>
          <span style={{ color: T.ink4 }}>·</span>
          <span style={{ fontFamily: T.mono }}>{v.views}</span>
          <span style={{ marginLeft: "auto", fontFamily: T.mono, color: T.ink4 }}>{v.date}</span>
        </div>
      </div>
    </div>
  );
}

function AITimesTab() {
  const [refreshing, setRefreshing] = React.useState(false);
  const [last, setLast] = React.useState("08:00");
  const refresh = () => {
    setRefreshing(true);
    setTimeout(() => { setRefreshing(false); setLast(new Date().toTimeString().slice(0, 5)); }, 1200);
  };
  return (
    <div>
      <TabHeader icon="▶" color={T.red} title="AI-Times" sub="Latest AI videos · YouTube Data API v3 · last 24–48h"
        actions={<>
          <Pill mono c={T.ink3}>digest 08:00 daily</Pill>
          <Btn size="sm" onClick={refresh}>
            <span style={{ display: "inline-block", animation: refreshing ? "omSpin .8s linear infinite" : "none" }}>↻</span>
            {refreshing ? "Refreshing…" : "Refresh"}
          </Btn>
        </>} />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 24 }}>
        {/* digest summary strip */}
        <Card pad={18} style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
          <div style={{ width: 40, height: 40, borderRadius: 11, background: T.redBg, color: T.red, display: "grid", placeItems: "center", fontSize: 19 }}>✉</div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 13.5, fontWeight: 700 }}>Daily HTML digest is scheduled</div>
            <div style={{ fontSize: 12.5, color: T.ink3, marginTop: 2 }}>10 videos (5 news · 5 personality) compiled and emailed to <b>you@gmail.com</b> every day at 08:00.</div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Pill c={T.green} bg={T.greenBg} bd="#c7eed5"><Dot c={T.green} />Sent today {last}</Pill>
            <Btn size="sm" kind="soft">Preview digest email</Btn>
          </div>
        </Card>

        <div>
          <SectionTitle sub="Top 5 from the AI news cycle" right={<Pill mono c={T.ink3}>5 videos</Pill>}>📰 AI News</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 14 }}>
            {AI_NEWS.map((v) => <VideoCard key={v.id} v={v} />)}
          </div>
        </div>

        <div>
          <SectionTitle sub="Interviews & long-form conversations" right={<Pill mono c={T.ink3}>5 videos</Pill>}>🎙 Personality &amp; Interviews</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 14 }}>
            {AI_PEOPLE.map((v) => <VideoCard key={v.id} v={v} />)}
          </div>
        </div>
      </div>
    </div>
  );
}

window.AITimesTab = AITimesTab;
