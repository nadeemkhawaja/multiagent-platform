// ============================================================================
// Wolf.jsx — Wallstreet Wolf: gainers/losers/watchlist + FX/metals + LLM read.
// Live prices tick client-side between backend refreshes for an "alive" feel.
// ============================================================================
import { useState, useEffect, useRef } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, Btn, Spark, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState } from "../components/Common";

const fmtFx = (sym = "") => {
  const s = sym.replace("=X", "");
  return s.length === 6 ? s.slice(0, 3) + "/" + s.slice(3) : s;
};

function adaptWatch(list) {
  if (!Array.isArray(list) || list.length === 0) return [];
  return list.map((s) => ({ t: s.symbol || s.t, n: s.name || s.n || s.symbol, p: Number(s.price ?? s.p) || 0, ch: Number(s.change_pct ?? s.ch) || 0, h: s.history || s.h || [] }));
}
function adaptFx(list) {
  if (!Array.isArray(list) || list.length === 0) return [];
  return list.map((s) => ({ p: fmtFx(s.symbol || s.p), v: Number(s.price ?? s.v) || 0, ch: Number(s.change_pct ?? s.ch) || 0 }));
}
function adaptMetals(list) {
  if (!Array.isArray(list) || list.length === 0) return [];
  return list.map((s) => {
    const gold = (s.symbol || "").includes("GC") || s.p === "Gold";
    return { p: gold ? "Gold" : "Silver", sym: gold ? "XAU/USD" : "XAG/USD", v: Number(s.price ?? s.v) || 0, ch: Number(s.change_pct ?? s.ch) || 0 };
  });
}

function MoverRow({ s, rank }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "20px 1fr auto auto", gap: 10, alignItems: "center", padding: "10px 0", borderBottom: `1px solid ${T.line2}` }}>
      <span style={{ fontFamily: T.mono, fontSize: 11, color: T.ink4 }}>{rank}</span>
      <div>
        <div style={{ fontSize: 13, fontWeight: 700 }}>{s.t}</div>
        <div style={{ fontSize: 10.5, color: T.ink4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 110 }}>{s.n}</div>
      </div>
      <span style={{ fontFamily: T.mono, fontSize: 12.5, fontWeight: 600, textAlign: "right" }}>{s.p.toFixed(2)}</span>
      <span style={{ fontFamily: T.mono, fontSize: 12, fontWeight: 700, color: s.ch >= 0 ? T.green : T.red, textAlign: "right", minWidth: 64 }}>{s.ch >= 0 ? "+" : ""}{s.ch.toFixed(2)}%</span>
    </div>
  );
}
function MoverBlock({ title, list, accent, badge }) {
  return (
    <Card pad={18}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span style={{ width: 8, height: 8, borderRadius: 8, background: accent }} />
        <div style={{ fontSize: 14, fontWeight: 700 }}>{title}</div>
        <span style={{ marginLeft: "auto", fontSize: 10.5, fontFamily: T.mono, color: accent, background: accent + "16", padding: "3px 8px", borderRadius: 6 }}>{badge}</span>
      </div>
      {list.map((s, i) => <MoverRow key={s.t} s={s} rank={i + 1} />)}
    </Card>
  );
}

export default function Wolf({ status, agentError }) {
  const { data, refresh } = useAgentData("wallstreet_wolf");
  const [refreshing, setRefreshing] = useState(false);
  const [watch, setWatch] = useState([]);
  const seeded = useRef(null);

  const md = data?.market_data || {};
  // reseed local ticking state whenever the backend delivers a new snapshot
  const sig = JSON.stringify((md.watchlist || []).map((w) => w.symbol));
  useEffect(() => {
    if (seeded.current !== sig) { setWatch(adaptWatch(md.watchlist)); seeded.current = sig; }
  }, [sig]); // eslint-disable-line

  // gentle random-walk between refreshes
  useEffect(() => {
    const id = setInterval(() => {
      setWatch((prev) => prev.map((w) => {
        const drift = (Math.random() - 0.5) * 0.7;
        return { ...w, p: Math.round(w.p * (1 + drift / 100) * 100) / 100, ch: Math.round((w.ch + drift) * 100) / 100 };
      }));
    }, 2000);
    return () => clearInterval(id);
  }, []);

  const sorted = [...watch].sort((a, b) => b.ch - a.ch);
  const gainers = sorted.slice(0, 5);
  const losers = sorted.slice(-5).reverse();
  const advancers = watch.filter((w) => w.ch >= 0).length;
  const fx = adaptFx(md.currencies);
  const metals = adaptMetals(md.metals);
  const commentary = md.commentary;

  const run = async () => {
    setRefreshing(true);
    await triggerAgent("wallstreet_wolf");
    setTimeout(refresh, 5000); setTimeout(refresh, 12000);
    setTimeout(() => setRefreshing(false), 1800);
  };
  const busy = refreshing || status === "running";

  return (
    <div>
      <TabHeader icon="$" color={T.green} title="Wallstreet Wolf" sub="Yahoo Finance · live watchlist · gainers / losers / FX / metals"
        actions={<>
          <Pill mono c={T.ink3}>brief 16:30 daily</Pill>
          {watch.length > 0 && <Pill c={advancers >= watch.length / 2 ? T.green : T.red} bg={advancers >= watch.length / 2 ? T.greenBg : T.redBg}>{advancers}/{watch.length} advancing</Pill>}
          <EmailPreviewButton agentId="wallstreet_wolf" label="Preview brief" />
          <Btn size="sm" onClick={run} disabled={busy}><span style={{ display: "inline-block", animation: busy ? "omSpin .8s linear infinite" : "none" }}>↻</span>{busy ? "Running…" : "Refresh"}</Btn>
        </>} />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>
        <ErrorBanner error={agentError} />
        {watch.length === 0 ? (
          <EmptyState icon="$" title="No market data yet"
            hint="Click Refresh to pull live Yahoo Finance prices for the watchlist, FX and metals." />
        ) : (
        <>
        <Card pad={20} style={{ background: T.cardAlt, borderColor: T.line }}>
          <div style={{ display: "flex", gap: 14 }}>
            <div style={{ width: 38, height: 38, borderRadius: 11, background: T.violetBg, color: T.violet, display: "grid", placeItems: "center", fontSize: 17, flex: "0 0 auto" }}>◇</div>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>Market commentary <Pill mono c={T.violet} bg={T.violetBg} style={{ padding: "2px 7px" }}>Qwen3</Pill></div>
              <div style={{ fontSize: 13, color: T.ink2, lineHeight: 1.55, marginTop: 6, maxWidth: 920 }}>
                {commentary || `Breadth is ${advancers >= watch.length / 2 ? "constructive" : "soft"} (${advancers}/${watch.length} advancing). Run a refresh to fetch fresh Yahoo Finance prices and a Qwen3 commentary for today's tape.`}
              </div>
            </div>
          </div>
        </Card>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <MoverBlock title="Top 5 Gainers" list={gainers} accent={T.green} badge="Block 1" />
          <MoverBlock title="Top 5 Losers" list={losers} accent={T.red} badge="Block 2" />
        </div>

        <Card pad={20}>
          <SectionTitle sub="Full watchlist · live prices" right={<Pill mono c={T.ink3}>updating · 2s</Pill>}>Watchlist <span style={{ fontSize: 11, fontFamily: T.mono, color: T.ink4 }}>Block 3</span></SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "0 28px" }}>
            {watch.map((w) => (
              <div key={w.t} style={{ display: "grid", gridTemplateColumns: "1fr 60px auto auto", gap: 12, alignItems: "center", padding: "9px 0", borderBottom: `1px solid ${T.line2}` }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
                  <span style={{ fontSize: 12.5, fontWeight: 700, width: 48 }}>{w.t}</span>
                  <span style={{ fontSize: 11, color: T.ink4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{w.n}</span>
                </div>
                <div style={{ height: 22 }}>{w.h && w.h.length > 1 ? <Spark data={w.h} w={56} h={22} color={w.ch >= 0 ? T.green : T.red} fill={false} /> : null}</div>
                <span style={{ fontFamily: T.mono, fontSize: 12.5, textAlign: "right" }}>{w.p.toFixed(2)}</span>
                <span style={{ fontFamily: T.mono, fontSize: 11.5, fontWeight: 700, color: w.ch >= 0 ? T.green : T.red, textAlign: "right", minWidth: 62 }}>{w.ch >= 0 ? "+" : ""}{w.ch.toFixed(2)}%</span>
              </div>
            ))}
          </div>
        </Card>

        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 16 }}>
          <Card pad={18}>
            <SectionTitle sub="Major pairs">Currencies</SectionTitle>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
              {fx.map((f) => (
                <div key={f.p} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: `1px solid ${T.line2}` }}>
                  <span style={{ fontSize: 12.5, fontWeight: 700, fontFamily: T.mono }}>{f.p}</span>
                  <div style={{ textAlign: "right" }}>
                    <span style={{ fontFamily: T.mono, fontSize: 13, fontWeight: 600 }}>{f.v.toFixed(4)}</span>
                    <span style={{ fontFamily: T.mono, fontSize: 11, fontWeight: 700, marginLeft: 8, color: f.ch >= 0 ? T.green : T.red }}>{f.ch >= 0 ? "+" : ""}{f.ch}%</span>
                  </div>
                </div>
              ))}
            </div>
          </Card>
          <Card pad={18}>
            <SectionTitle sub="Spot">Precious metals</SectionTitle>
            {metals.map((m) => (
              <div key={m.p} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 0", borderBottom: `1px solid ${T.line2}` }}>
                <span style={{ width: 30, height: 30, borderRadius: 8, background: m.p === "Gold" ? "#f59e0b1a" : "#94a3b81a", color: m.p === "Gold" ? "#d4920a" : "#64748b", display: "grid", placeItems: "center", fontWeight: 700, fontSize: 13 }}>{m.p[0]}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{m.p}</div>
                  <div style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono }}>{m.sym}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontFamily: T.mono, fontSize: 13, fontWeight: 600 }}>${m.v.toFixed(2)}</div>
                  <span style={{ fontFamily: T.mono, fontSize: 11, fontWeight: 700, color: m.ch >= 0 ? T.green : T.red }}>{m.ch >= 0 ? "+" : ""}{m.ch}%</span>
                </div>
              </div>
            ))}
          </Card>
        </div>
        </>
        )}
      </div>
    </div>
  );
}
