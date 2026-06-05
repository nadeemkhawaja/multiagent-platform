// ============================================================================
// AITimes.jsx — AI YouTube digest (5 news + 5 personality). Wired to backend.
// ============================================================================
import { useState } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, Dot, Btn, SectionTitle, TabHeader, StripedSlot } from "../theme/ui";
import { useAgentData, triggerAgent } from "../state/api";
import { AI_NEWS, AI_PEOPLE } from "../data/mock";

const PALETTE = ["#e5484d", "#2f6feb", "#16a34a", "#f59e0b", "#0d9488", "#7c5cf6"];

function adapt(list, fallback) {
  if (!Array.isArray(list) || list.length === 0) return fallback;
  return list.map((v, i) => ({
    id: v.id || v.video_id || i,
    title: v.title || "Untitled",
    ch: v.channel || v.ch || "—",
    dur: v.duration || v.dur || "",
    date: v.date ? (String(v.date).length > 10 ? new Date(v.date).toLocaleDateString() : v.date) : "",
    views: v.views || "",
    thumbnail: v.thumbnail || v.thumbnail_url || null,
    url: v.url || null,
    c: PALETTE[i % PALETTE.length],
  }));
}

function VideoCard({ v }) {
  const inner = (
    <>
      <div style={{ position: "relative" }}>
        {v.thumbnail
          ? <img src={v.thumbnail} alt="" style={{ width: "100%", height: 132, objectFit: "cover", display: "block" }} />
          : <StripedSlot h={132} color={v.c} label="thumbnail" glyph="▶" />}
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
          <div style={{ width: 44, height: 44, borderRadius: 44, background: "rgba(255,255,255,.92)", display: "grid", placeItems: "center", color: v.c, fontSize: 16, boxShadow: "0 4px 14px rgba(0,0,0,.12)" }}>▶</div>
        </div>
        {v.dur && <span style={{ position: "absolute", bottom: 8, right: 8, background: "rgba(15,17,22,.82)", color: "#fff", fontFamily: T.mono, fontSize: 10.5, padding: "2px 6px", borderRadius: 5 }}>{v.dur}</span>}
      </div>
      <div style={{ padding: 13 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.35, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", minHeight: 38 }}>{v.title}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 9, fontSize: 11.5, color: T.ink3 }}>
          <span style={{ width: 18, height: 18, borderRadius: 18, background: v.c + "22", color: v.c, display: "grid", placeItems: "center", fontSize: 9, fontWeight: 700 }}>{(v.ch || "?")[0]}</span>
          <span style={{ fontWeight: 600, color: T.ink2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{v.ch}</span>
          {v.views && <><span style={{ color: T.ink4 }}>·</span><span style={{ fontFamily: T.mono }}>{v.views}</span></>}
          {v.date && <span style={{ marginLeft: "auto", fontFamily: T.mono, color: T.ink4 }}>{v.date}</span>}
        </div>
      </div>
    </>
  );
  const base = { border: `1px solid ${T.line}`, borderRadius: 12, overflow: "hidden", background: T.card, cursor: "pointer", textDecoration: "none", color: "inherit", display: "block", transition: "transform .15s, box-shadow .15s" };
  const hov = {
    onMouseEnter: (e) => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 24px rgba(20,24,40,.08)"; },
    onMouseLeave: (e) => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "none"; },
  };
  return v.url
    ? <a href={v.url} target="_blank" rel="noreferrer" style={base} {...hov}>{inner}</a>
    : <div style={base} {...hov}>{inner}</div>;
}

export default function AITimes({ status }) {
  const { data, refresh } = useAgentData("ai_times");
  const [refreshing, setRefreshing] = useState(false);
  const videos = data?.videos || {};
  const news = adapt(videos.news, AI_NEWS);
  const people = adapt(videos.personality, AI_PEOPLE);

  const refreshNow = async () => {
    setRefreshing(true);
    await triggerAgent("ai_times");
    setTimeout(refresh, 4000); setTimeout(refresh, 10000);
    setTimeout(() => setRefreshing(false), 1500);
  };
  const busy = refreshing || status === "running";

  return (
    <div>
      <TabHeader icon="▶" color={T.red} title="AI-Times" sub="Latest AI videos · YouTube Data API v3 · last 24–48h"
        actions={<>
          <Pill mono c={T.ink3}>digest 08:00 daily</Pill>
          <Btn size="sm" onClick={refreshNow} disabled={busy}>
            <span style={{ display: "inline-block", animation: busy ? "omSpin .8s linear infinite" : "none" }}>↻</span>
            {busy ? "Refreshing…" : "Refresh"}
          </Btn>
        </>} />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 24 }}>
        <Card pad={18} style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
          <div style={{ width: 40, height: 40, borderRadius: 11, background: T.redBg, color: T.red, display: "grid", placeItems: "center", fontSize: 19 }}>✉</div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 13.5, fontWeight: 700 }}>Daily HTML digest is scheduled</div>
            <div style={{ fontSize: 12.5, color: T.ink3, marginTop: 2 }}>10 videos (5 news · 5 personality) compiled and emailed every day at 08:00.</div>
          </div>
          <Pill c={T.green} bg={T.greenBg} bd="#c7eed5"><Dot c={T.green} />Digest scheduled</Pill>
        </Card>

        <div>
          <SectionTitle sub="Top from the AI news cycle" right={<Pill mono c={T.ink3}>{news.length} videos</Pill>}>📰 AI News</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 14 }}>
            {news.slice(0, 5).map((v) => <VideoCard key={v.id} v={v} />)}
          </div>
        </div>
        <div>
          <SectionTitle sub="Interviews & long-form conversations" right={<Pill mono c={T.ink3}>{people.length} videos</Pill>}>🎙 Personality &amp; Interviews</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 14 }}>
            {people.slice(0, 5).map((v) => <VideoCard key={v.id} v={v} />)}
          </div>
        </div>
      </div>
    </div>
  );
}
