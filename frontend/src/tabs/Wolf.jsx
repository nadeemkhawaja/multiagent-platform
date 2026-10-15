// ============================================================================
// Wolf.jsx — Wallstreet Wolf: the market desk.
//   TAPE    watchlist, gainers/losers, index futures, LLM commentary
//   REGIME  composite bias, VIX, sector lean, scored headlines, pivot levels
// Both halves come from one agent and one fetch (agent3_wallstreet_wolf), so
// the composite can never disagree with the tape shown beside it. The regime
// verdict leads the page — it frames every number under it.
//
// Every number here is exactly what the last agent run fetched. Nothing ticks
// client-side: these prices size real (paper) positions, and an invented tick
// is worse than a stale one. What the tab owes the reader instead is the age of
// the quote, which is what the freshness stamp beside each table says.
// ============================================================================
import { useState, useMemo } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader, DataTable, CardRow, Delta, gridCols, grow } from "../theme/ui";
import { useAgentData, triggerAgent, useModelLabel } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar } from "../components/Common";

function adaptWatch(list) {
  if (!Array.isArray(list) || list.length === 0) return [];
  return list.map((s) => ({ t: s.symbol || s.t, n: s.name || s.n || s.symbol, p: Number(s.price ?? s.p) || 0, ch: Number(s.change_pct ?? s.ch) || 0, h: s.history || s.h || [], lv: s.levels || s.lv || null }));
}

const FUT_LABEL = { "ES=F": ["/ES", "S&P 500 E-mini"], "NQ=F": ["/NQ", "Nasdaq-100 E-mini"] };
function adaptFutures(list) {
  if (!Array.isArray(list)) return [];
  return list.map((s) => {
    const [label, name] = FUT_LABEL[s.symbol] || [s.symbol, ""];
    return { label, name, p: Number(s.price) || 0, ch: Number(s.change_pct) || 0, h: s.history || [] };
  });
}

// Neutral bias uses ink3, not ink4: these render as coloured text on a tint of
// themselves, and the faintest tier lands at 4.4:1 in that pairing.
const biasColor = (b) => (b === "bull" ? T.green : b === "bear" ? T.red : T.ink3);
const biasLabel = (b) => (b === "bull" ? "Bullish" : b === "bear" ? "Bearish" : "Neutral");

function BiasMeter({ score, h = 10 }) {
  const pos = (score + 100) / 2;
  const col = score > 15 ? T.green : score < -15 ? T.red : T.ink4;
  return (
    <div style={{ position: "relative", height: h, borderRadius: h, background: T.trackGrad, marginTop: 6 }}>
      <div style={{ position: "absolute", left: `calc(${pos}% - ${h}px)`, top: -2, width: h + 4, height: h + 4, borderRadius: "50%", background: T.card, border: `3px solid ${col}`, boxShadow: "0 1px 4px rgba(0,0,0,.15)" }} />
    </div>
  );
}

// Sector bias as a sortable table: the "why" moves into the row tooltip so
// each sector is one line and the whole board can be ranked bullish→bearish.
const sectorCols = [
  { key: "k", label: "Sector", sort: (s) => s.k, defaultDir: "asc",
    render: (s) => <span title={s.why || ""} style={{ fontWeight: 700, color: T.ink }}>{s.k}</span> },
  { key: "meter", label: "Lean", width: 110,
    render: (s) => <div style={{ width: 96 }}><BiasMeter score={s.bias} h={8} /></div> },
  { key: "bias", label: "Bias", align: "right", mono: true, sort: (s) => s.bias,
    title: "Sort bullish → bearish",
    render: (s) => {
      const col = s.bias > 15 ? T.green : s.bias < -15 ? T.red : T.ink3;
      return <b style={{ color: col }}>{s.bias > 0 ? "+" : ""}{s.bias}</b>;
    } },
];

// ── Quote freshness ─────────────────────────────────────────────────────────
// The agent writes `fetched_at` with datetime.utcnow().isoformat(), which has
// no timezone marker — JS would read that naive string as LOCAL time and report
// a quote as hours in the future. Pin it to UTC before parsing.
function ageMinutes(iso) {
  if (!iso) return null;
  const d = new Date(/[Z+]|-\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
  if (isNaN(d)) return null;
  return Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
}
const fmtAge = (m) => (m < 1 ? "just now" : m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ${m % 60}m ago`);

// The agent runs hourly, so anything past two cadences is a quote the desk
// should not be sizing off. Stale is labelled stale rather than dressed as live.
const STALE_MIN = 120;
function Freshness({ at }) {
  const age = ageMinutes(at);
  if (age == null) return <Pill mono c={T.ink4}>no timestamp</Pill>;
  const stale = age > STALE_MIN;
  return (
    <Pill mono c={stale ? T.amber : T.ink3} bg={stale ? T.amberBg : undefined}
      style={{ padding: "3px 8px" }}
      title={stale ? "Older than two agent cycles — run the agent for a current tape" : "Time of the last agent fetch"}>
      {stale ? "⚠ " : ""}{fmtAge(age)}
    </Pill>
  );
}

// Every price on this tab goes through here. `toLocaleString()` alone prints at
// whatever precision the source happened to carry, which put "63,966.7" in the
// same right-aligned column as "73.68" and broke the decimal point the eye
// tracks down a level ladder.
const num = (v) => (v == null ? "—" : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const levelCols = [
  { key: "t", label: "Sym", sort: (l) => l.t, defaultDir: "asc",
    render: (l) => <span style={{ fontFamily: T.mono, fontWeight: 800, color: T.ink }}>{l.t}</span> },
  { key: "px", label: "Last", align: "right", mono: true, sort: (l) => l.px,
    render: (l) => <b style={{ color: T.ink }}>{num(l.px)}</b> },
  { key: "piv", label: "Pivot", align: "right", mono: true, sort: (l) => l.piv,
    render: (l) => <span style={{ color: T.ink3 }}>{num(l.piv)}</span> },
  { key: "r1", label: "R1", align: "right", mono: true, sort: (l) => l.r1,
    render: (l) => <span style={{ color: T.red }}>{num(l.r1)}</span> },
  { key: "s1", label: "S1", align: "right", mono: true, sort: (l) => l.s1,
    render: (l) => <span style={{ color: T.green }}>{num(l.s1)}</span> },
  { key: "bias", label: "Bias", align: "center", sort: (l) => l.bias,
    title: "Sort bullish → bearish",
    render: (l) => <span style={{ fontSize: 9.5, fontWeight: 800, color: biasColor(l.bias),
      background: biasColor(l.bias) + "18", padding: "1px 6px", borderRadius: 4 }}>{biasLabel(l.bias)}</span> },
];

function LevelLadder({ f }) {
  const ticks = [
    { k: "R2", v: f.r2, c: T.red }, { k: "R1", v: f.r1, c: T.red },
    { k: "Pivot", v: f.piv, c: T.ink4 },
    { k: "S1", v: f.s1, c: T.green }, { k: "S2", v: f.s2, c: T.green },
  ].filter((t) => t.v != null);
  const min = f.s2 ?? f.s1, max = f.r2 ?? f.r1, span = (max - min) || 1;
  const y = (v) => 100 - ((v - min) / span) * 100;
  return (
    // Generous max: there are usually only two futures (/ES, /NQ), and a ladder
    // is a chart rather than a table — extra width spreads the price ticks apart
    // instead of stranding them, so two of these can own the row.
    <Card pad={12} style={grow(320, 980)}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 700, fontFamily: T.mono }}>{f.t}</div>
          <div style={{ fontSize: 10.5, color: T.ink3 }}>{f.n}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: T.mono, fontSize: 16, fontWeight: 700 }}>{num(f.px)}</div>
          <span style={{ fontSize: 10.5, fontWeight: 700, color: biasColor(f.bias) }}>{biasLabel(f.bias)} bias</span>
        </div>
      </div>
      <div style={{ position: "relative", height: 100, marginLeft: 6 }}>
        <div style={{ position: "absolute", left: 44, top: 0, bottom: 0, width: 2, background: T.line }} />
        {ticks.map((t) => (
          <div key={t.k} style={{ position: "absolute", left: 0, right: 0, top: `calc(${y(t.v)}% - 8px)`, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 36, textAlign: "right", fontFamily: T.mono, fontSize: 9.5, fontWeight: 700, color: t.c }}>{t.k}</span>
            <span style={{ width: 9, height: 9, borderRadius: 9, background: T.card, border: `2px solid ${t.c}`, flex: "0 0 auto" }} />
            <span style={{ flex: 1, height: 1, borderTop: `1px dashed ${t.c}55` }} />
            <span style={{ fontFamily: T.mono, fontSize: 10.5, color: T.ink2 }}>{num(t.v)}</span>
          </div>
        ))}
        <div style={{ position: "absolute", left: 40, right: 0, top: `calc(${y(f.px)}% - 9px)`, display: "flex", alignItems: "center" }}>
          <span style={{ background: biasColor(f.bias), color: T.onAccent, fontFamily: T.mono, fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 5, boxShadow: "0 1px 4px rgba(0,0,0,.18)" }}>▸ {num(f.px)}</span>
          <span style={{ flex: 1, height: 2, background: biasColor(f.bias) }} />
        </div>
      </div>
    </Card>
  );
}

// 1px accent border rather than a left bar. Direction is already stated by the
// ▲/▼ and the coloured percentage beside it.
function FutureCard({ f }) {
  const col = f.ch >= 0 ? T.green : T.red;
  return (
    <Card pad={12} style={{ overflow: "hidden", borderColor: col + "40" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 17, fontWeight: 800, fontFamily: T.mono, letterSpacing: -0.5 }}>{f.label}</span>
            <span style={{ fontSize: 9, fontWeight: 700, color: T.ink3, background: T.line2, padding: "2px 6px", borderRadius: 5, letterSpacing: 0.4 }}>FUTURES</span>
          </div>
          <div style={{ fontSize: 11, color: T.ink4, marginTop: 1 }}>{f.name}</div>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 6 }}>
        <span style={{ fontSize: 22, fontWeight: 800, fontFamily: T.mono, letterSpacing: -1 }}>{num(f.p)}</span>
        {/* The shared Delta, not a local copy: tokens.js documents the ▲/▼ as
            the shape cue that keeps green/red separable under deuteranopia, and
            that promise is only kept if one component owns it. */}
        <Delta v={f.ch} style={{ fontSize: 13 }} />
      </div>
    </Card>
  );
}

const chgCol = (v) => (v >= 0 ? T.green : T.red);
const vwapCol = (lv) => (lv?.vwap_position === "above" ? T.green : lv?.vwap_position === "below" ? T.red : T.ink3);

// One column set for movers and the watchlist alike — the levels that used to
// sit on a second line per row (doubling every row's height for three numbers)
// are columns now, so they can also be sorted and compared down the list.
const tickerCols = [
  { key: "t", label: "Sym", sort: (r) => r.t, defaultDir: "asc",
    render: (r) => <span title={r.n} style={{ fontFamily: T.mono, fontWeight: 800, color: T.ink }}>{r.t}</span> },
  { key: "p", label: "Price", align: "right", mono: true, sort: (r) => r.p,
    render: (r) => <b style={{ color: T.ink }}>{r.p.toFixed(2)}</b> },
  { key: "ch", label: "Chg%", align: "right", mono: true, sort: (r) => r.ch,
    title: "Sort by change — bullish to bearish",
    render: (r) => <b style={{ color: chgCol(r.ch) }}>{r.ch >= 0 ? "+" : ""}{r.ch.toFixed(2)}%</b> },
  { key: "vwap", label: "VWAP", align: "right", mono: true, sort: (r) => r.lv?.vwap ?? null,
    title: "Session VWAP — coloured by which side price is on",
    render: (r) => (r.lv?.vwap != null
      ? <span style={{ color: vwapCol(r.lv) }}>{r.lv.vwap.toFixed(2)}</span> : "—") },
  // Levels are not direction: blue/teal keep green/red reserved for bias and P&L.
  { key: "sup", label: "Sup", align: "right", mono: true, sort: (r) => r.lv?.nearest_support ?? null,
    render: (r) => (r.lv?.nearest_support != null
      ? <span style={{ color: T.blue }}>{r.lv.nearest_support}</span> : "—") },
  { key: "res", label: "Res", align: "right", mono: true, sort: (r) => r.lv?.nearest_resistance ?? null,
    render: (r) => (r.lv?.nearest_resistance != null
      ? <span style={{ color: T.teal }}>{r.lv.nearest_resistance}</span> : "—") },
];

// ── FX & metals ─────────────────────────────────────────────────────────────
// The agent has always fetched these (EUR/USD, GBP/USD, USD/JPY, gold, silver)
// and the tab has always thrown them away. They are the macro backdrop the
// regime read is written against, so they belong beside the tape rather than
// only inside the LLM's prompt. One compact table, same idiom as the movers.
const MACRO_LABEL = {
  "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "JPY=X": "USD/JPY",
  "GC=F": "Gold", "SI=F": "Silver",
};
function adaptMacro(...lists) {
  return lists.flat().filter(Boolean).map((s) => ({
    t: MACRO_LABEL[s.symbol] || s.symbol,
    n: s.name || s.symbol,
    p: Number(s.price) || 0,
    ch: Number(s.change_pct) || 0,
  }));
}
const macroCols = [
  { key: "t", label: "Instrument", sort: (r) => r.t, defaultDir: "asc",
    render: (r) => <span title={r.n} style={{ fontFamily: T.mono, fontWeight: 800, color: T.ink }}>{r.t}</span> },
  { key: "p", label: "Last", align: "right", mono: true, sort: (r) => r.p,
    // Two places, matching what the agent stores. Padding EUR/USD out to four
    // would render 1.15 as "1.1500" and claim a pip we were never given.
    render: (r) => <b style={{ color: T.ink }}>{num(r.p)}</b> },
  { key: "ch", label: "Chg%", align: "right", mono: true, sort: (r) => r.ch,
    title: "Sort by change — strongest to weakest",
    render: (r) => <b style={{ color: chgCol(r.ch) }}>{r.ch >= 0 ? "+" : ""}{r.ch.toFixed(2)}%</b> },
];

function MoverBlock({ title, list, accent }) {
  return (
    <Card pad={12} style={grow(340, 470)}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 7, height: 7, borderRadius: 7, background: accent }} />
        <div style={{ fontSize: 13, fontWeight: 700 }}>{title}</div>
      </div>
      {/* No row tint here — every row in a gainers list is green, so a uniform
          wash carries no information. The watchlist below is mixed and does. */}
      <DataTable fill columns={tickerCols} rows={list} rowKey={(r) => r.t} defaultSort="ch" />
    </Card>
  );
}

export default function Wolf({ status, agentError }) {
  const { data, refresh, error: dataError } = useAgentData("wallstreet_wolf");
  const modelLabel = useModelLabel();
  const [refreshing, setRefreshing] = useState(false);

  const md = data?.market_data || {};
  const c = data?.compass || {};
  const watch = useMemo(() => adaptWatch(md.watchlist), [md.watchlist]);
  // The backend ranks the movers off the same fetch that produced the
  // watchlist, so the three tables can never disagree with each other. This
  // used to re-derive them by sorting the drifting client-side copy, which
  // meant the "Top 5 Gainers" could name a stock the tape below called flat.
  const gainers = useMemo(() => adaptWatch(md.top_gainers), [md.top_gainers]);
  const losers = useMemo(() => adaptWatch(md.top_losers), [md.top_losers]);
  const advancers = watch.filter((w) => w.ch >= 0).length;
  const futures = adaptFutures(md.futures);
  const commentary = md.commentary;
  const fetchedAt = c.fetched_at;
  const macro = useMemo(() => adaptMacro(md.currencies || [], md.metals || []), [md.currencies, md.metals]);

  // Regime half
  const sectors = c.sectors || [];
  const news = c.news || [];
  const pivotFutures = c.futures || [];
  const levels = c.levels || [];
  const vix = c.vix;
  const read = c.read;
  const hasRegime = sectors.length > 0 || levels.length > 0 || pivotFutures.length > 0;
  const overall = c.composite ?? (sectors.length ? Math.round(sectors.reduce((a, s) => a + s.bias, 0) / sectors.length) : 0);
  const toneWord = overall > 15 ? "Bullish" : overall < -15 ? "Bearish" : "Neutral";
  const toneDesc = overall > 15 ? "Risk appetite — buyers in control"
    : overall < -15 ? "Defensive — money rotating to safety"
    : "Range-bound — no clear edge";
  const toneCol = overall > 15 ? T.green : overall < -15 ? T.red : T.ink3;

  const sentChip = (s) => {
    const map = { bull: [T.green, T.greenBg, "Bullish"], bear: [T.red, T.redBg, "Bearish"], neutral: [T.ink3, T.cardAlt, "Neutral"] };
    const [col, bg, t] = map[s] || map.neutral;
    return <span style={{ fontSize: 10.5, fontWeight: 700, color: col, background: bg, padding: "3px 8px", borderRadius: 6 }}>{t}</span>;
  };

  const run = async () => {
    setRefreshing(true);
    await triggerAgent("wallstreet_wolf");
    setTimeout(refresh, 5000); setTimeout(refresh, 12000); setTimeout(refresh, 25000);
    setTimeout(() => setRefreshing(false), 1800);
  };
  const busy = refreshing || status === "running";

  return (
    <div>
      <TabHeader icon="$" color={T.green} title="Wallstreet Wolf" sub="Yahoo Finance · tape, regime bias & key levels"
        actions={<>
          <Pill mono c={T.ink3}>every 60 min</Pill>
          {/* Sticky, so the age of the tape stays on screen for every table
              under it — this is the whole tab's freshness, not one card's. */}
          {(watch.length > 0 || hasRegime) && <Freshness at={fetchedAt} />}
          {watch.length > 0 && <Pill c={advancers >= watch.length / 2 ? T.green : T.red} bg={advancers >= watch.length / 2 ? T.greenBg : T.redBg}>{advancers}/{watch.length} advancing</Pill>}
          <EmailPreviewButton agentId="wallstreet_wolf" label="Preview brief" />
          <AgentControls agentId="wallstreet_wolf" onRun={run} busy={busy} refresh={refresh} runLabel="Manual run" runningLabel="Running…" />
        </>} />
      <div className="om-page om-stagger">
        <ErrorBanner error={agentError} />
        <ErrorBanner error={dataError} kind="data" onRetry={refresh} />
        {watch.length === 0 && !hasRegime ? (
          <EmptyState icon="$" title="No market data yet"
            hint="Click Manual run to pull live Yahoo Finance prices, sector bias, VIX and pivot levels." />
        ) : (
        <>
        {/* The verdict leads: composite bias + the read that produced it. */}
        {hasRegime && (
          <Card pad={14} style={{ display: "grid", gridTemplateColumns: gridCols(2, 18, 280), gap: 18, alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 11.5, color: T.ink3, fontWeight: 600 }}>Today's composite bias</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 2 }}>
                <span style={{ fontSize: 28, fontWeight: 800, letterSpacing: -1.2, color: toneCol }}>{toneWord}</span>
              </div>
              <div style={{ fontSize: 11.5, color: T.ink3, marginTop: 2, fontWeight: 600 }}>{toneDesc}</div>
              <div style={{ marginTop: 6 }}><BiasMeter score={overall} h={11} /></div>
              <div style={{ display: "flex", justifyContent: "space-between", fontFamily: T.mono, fontSize: 10, color: T.ink4, marginTop: 4 }}><span>BEARISH</span><span>{overall > 0 ? "+" : ""}{overall}</span><span>BULLISH</span></div>
              {vix && (
                <div style={{ marginTop: 8 }}>
                  <Pill mono c={vix.regime === "Elevated" ? T.red : vix.regime === "Low" ? T.green : T.amber}
                    bg={vix.regime === "Elevated" ? T.redBg : vix.regime === "Low" ? T.greenBg : T.amberBg}>
                    VIX {vix.level} · {vix.regime} ({vix.change > 0 ? "+" : ""}{vix.change})
                  </Pill>
                </div>
              )}
            </div>
            <div style={{ borderLeft: `1px solid ${T.line2}`, paddingLeft: 18 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <LufiAvatar size={24} />
                <span style={{ fontSize: 12.5, fontWeight: 800, letterSpacing: -0.2 }}>Lufi's read</span>
                <Pill mono c={T.violet} bg={T.violetBg} style={{ padding: "2px 7px" }}>{modelLabel}</Pill>
              </div>
              {read ? (
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: T.ink2, lineHeight: 1.5, listStyleType: "disc" }}>
                  {read.split("\n").map((l) => l.replace(/^[•\-*]\s*/, "").trim()).filter(Boolean).map((l, i) => (
                    <li key={i} style={{ marginBottom: 3 }}>{l}</li>
                  ))}
                </ul>
              ) : (
                <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.5 }}>
                  Run the agent to fetch live sector ETF moves, compute pivot-based key levels for /ES, /NQ and the 10 majors, and have {modelLabel} write today's directional read.
                </div>
              )}
            </div>
          </Card>
        )}

        {/* Commentary + Futures side by side — flex-wrap rather than a fixed
            two-track grid, because the grid's `auto` futures column had a 220px
            floor that a phone viewport could not honour and overflowed instead.
            Wrapped, the futures strip drops below the commentary and fills. */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-start" }}>
          <Card pad={14} style={{ flex: "1 1 340px", minWidth: 0, background: T.cardAlt, borderColor: T.line }}>
            <div style={{ display: "flex", gap: 12 }}>
              <LufiAvatar size={32} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  Market commentary <span style={{ fontSize: 11, fontWeight: 600, color: T.ink4 }}>by Lufi</span>
                  <Pill mono c={T.violet} bg={T.violetBg} style={{ padding: "2px 7px" }}>{modelLabel}</Pill>
                </div>
                {commentary ? (
                  <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: T.ink2, lineHeight: 1.5, listStyleType: "disc" }}>
                    {commentary.split("\n").map((l) => l.replace(/^[•\-*]\s*/, "").trim()).filter(Boolean).map((l, i) => (
                      <li key={i} style={{ marginBottom: 2 }}>{l}</li>
                    ))}
                  </ul>
                ) : (
                  <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.5 }}>
                    {`Breadth is ${advancers >= watch.length / 2 ? "constructive" : "soft"} (${advancers}/${watch.length} advancing). Run a refresh to fetch fresh Yahoo Finance prices and a ${modelLabel} commentary for today's tape.`}
                  </div>
                )}
              </div>
            </div>
          </Card>
          {futures.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: "1 1 220px", maxWidth: 260 }}>
              {futures.map((f) => <FutureCard key={f.label} f={f} />)}
            </div>
          )}
        </div>

        {/* Movers and the watchlist share one row. Stacked, the watchlist was a
            478px table alone on a 1970px line — 1500px of empty page under a
            full-width commentary card. Together the three fill the row and wrap
            to two lines, then one, as the window narrows.

            Watchlist — one sortable table rather than two hand-built columns:
            splitting the list in half made every value impossible to compare
            against its opposite number across the gutter. */}
        <CardRow>
          <MoverBlock title="Top 5 Gainers" list={gainers} accent={T.green} />
          <MoverBlock title="Top 5 Losers" list={losers} accent={T.red} />
          <Card pad={12} style={grow(520, 900)}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Watchlist</span>
            {/* No "live" pill: nothing on this page ticks between agent runs,
                and the header stamp already states the tape's real age. */}
            <span style={{ fontSize: 11, color: T.ink4 }}>{watch.length} tickers · click a header to sort</span>
          </div>
          <DataTable fill rows={watch} rowKey={(r) => r.t} defaultSort="ch"
            rowTint={(r) => (r.ch >= 0 ? T.green : T.red)}
            columns={[...tickerCols,
              { key: "hi", label: "Hi", align: "right", mono: true,
                sort: (r) => (r.h?.length > 1 ? Math.max(...r.h) : null),
                render: (r) => (r.h?.length > 1
                  ? <span style={{ color: T.green }}>{Math.max(...r.h).toFixed(2)}</span> : "—") },
              { key: "lo", label: "Lo", align: "right", mono: true,
                sort: (r) => (r.h?.length > 1 ? Math.min(...r.h) : null),
                render: (r) => (r.h?.length > 1
                  ? <span style={{ color: T.red }}>{Math.min(...r.h).toFixed(2)}</span> : "—") },
            ]} />
          </Card>
          {macro.length > 0 && (
            <Card pad={12} style={grow(280, 380)}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700 }}>FX &amp; metals</span>
                <span style={{ fontSize: 11, color: T.ink4 }}>macro backdrop</span>
              </div>
              <DataTable fill columns={macroCols} rows={macro} rowKey={(r) => r.t} defaultSort="ch" />
            </Card>
          )}
        </CardRow>

        {/* What the composite was computed from: sector lean, the headlines
            that were scored, and the pivot levels for the majors. */}
        {hasRegime && (
          <CardRow>
            <Card pad={12} style={grow(360, 520)}>
              <SectionTitle sub="Directional lean by sector (−100 to +100)">Sector bias</SectionTitle>
              <DataTable fill columns={sectorCols} rows={sectors} rowKey={(s) => s.k} defaultSort="bias"
                rowTint={(s) => (s.bias > 15 ? T.green : s.bias < -15 ? T.red : null)} />
            </Card>
            {news.length > 0 && (
              <Card pad={14} style={grow(400, 680)}>
                <SectionTitle sub="LLM-scored headlines driving today's read" right={<Pill mono c={T.ink3}>live feed</Pill>}>News sentiment</SectionTitle>
                {news.map((n, i) => (
                  <div key={i} style={{ padding: "6px 0", borderBottom: i < news.length - 1 ? `1px solid ${T.line2}` : "none" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: T.ink2, fontFamily: T.mono }}>{n.src}</span>
                      <span style={{ fontSize: 9.5, color: T.ink4, fontFamily: T.mono }}>{n.min}</span>
                      <span style={{ marginLeft: "auto" }}>{sentChip(n.s)}</span>
                    </div>
                    <div style={{ fontSize: 12, color: T.ink, lineHeight: 1.4 }}>{n.t}</div>
                  </div>
                ))}
              </Card>
            )}
            <Card pad={12} style={grow(440, 700)}>
              <SectionTitle sub="Pivot · R1 · S1 for the 10 majors · click a header to sort">Key levels — Stocks</SectionTitle>
              <DataTable fill columns={levelCols} rows={levels} rowKey={(l) => l.t} defaultSort="px"
                rowTint={(l) => (l.bias > 15 ? T.green : l.bias < -15 ? T.red : null)} />
            </Card>
          </CardRow>
        )}

        {pivotFutures.length > 0 && (
          <div>
            <SectionTitle sub="Intraday support & resistance · pivot-based">Key levels — Futures</SectionTitle>
            <CardRow>
              {pivotFutures.map((f) => <LevelLadder key={f.t} f={f} />)}
            </CardRow>
          </div>
        )}
        </>
        )}
      </div>
    </div>
  );
}
