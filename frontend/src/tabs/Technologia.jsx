// ============================================================================
// Technologia.jsx — VP zones, VWAP, MFI divergence, approximated VSA/CVD.
// Adapts the EminiPlayer /ES thinkScript framework for the stock watchlist
// plus /ES and /NQ futures (informational only — Alpaca can't trade futures).
// ============================================================================
import { T, AGENT_COLOR } from "../theme/tokens";
import { useState, useEffect, useCallback, useRef } from "react";
import { Card, Pill, SectionTitle, TabHeader, DataTable, useNav } from "../theme/ui";
import { useAgentData, triggerAgent, useModelLabel, getWolfNow } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar, Collapsible } from "../components/Common";
import { stateStyle, stateKey, statesByTicker } from "../state/tradeState";

// Read at call time, never captured: T and AGENT_COLOR are mutated in place by
// applyMode(), so module-scope copies would freeze this tab in light mode.
const accent = () => AGENT_COLOR.technologia;
// Alpha Wolf's colour, used wherever this tab points at the master plan.
const purple = () => AGENT_COLOR.alpha_wolf;
const accentBg = () => AGENT_COLOR.technologia + (T.mode === "dark" ? "1f" : "14");

function dirColor(d) {
  return d === "bullish" ? T.green : d === "bearish" ? T.red : T.ink3;
}

// ── Confluence matrix ────────────────────────────────────────────────────────
// The five inputs the backend scores in tools/technologia_signals.bias_score():
// VWAP ±1, MFI extreme ±1, MFI divergence ±2, VSA ±1, CVD ±1 → a -6..+6 total.
// Derived here from the same raw fields the backend scores from (not by parsing
// bias_reasons prose) and rendered as FIXED columns, so the watchlist can be
// read down a column — "every bearish name has the divergence" — instead of
// re-reading a differently-worded sentence on every row.
const MFI_OVERSOLD = 20, MFI_OVERBOUGHT = 80;   // mirrors bias_score()
const VSA_BULL = ["bullish_absorption", "buying_pressure"];
const VSA_BEAR = ["bearish_absorption", "selling_pressure"];

function confluence(s) {
  const mfiV = s.mfi == null ? 0 : s.mfi <= MFI_OVERSOLD ? 1 : s.mfi >= MFI_OVERBOUGHT ? -1 : 0;
  return [
    { key: "vwap", v: s.vwap_position === "above" ? 1 : s.vwap_position === "below" ? -1 : 0,
      why: s.vwap_position ? `price ${s.vwap_position} VWAP` : "no VWAP reading" },
    { key: "mfi", v: mfiV,
      why: s.mfi == null ? "no MFI reading"
        : mfiV > 0 ? `MFI oversold (${s.mfi})`
        : mfiV < 0 ? `MFI overbought (${s.mfi})` : `MFI ${s.mfi} — neutral zone` },
    { key: "div", v: s.mfi_divergence === "bullish" ? 2 : s.mfi_divergence === "bearish" ? -2 : 0,
      why: s.mfi_divergence ? `${s.mfi_divergence} MFI divergence` : "no MFI divergence" },
    { key: "vsa", v: VSA_BULL.includes(s.vsa_signal) ? 1 : VSA_BEAR.includes(s.vsa_signal) ? -1 : 0,
      why: s.vsa_signal ? `VSA approx: ${s.vsa_signal}` : "no VSA signal" },
    { key: "cvd", v: s.cvd_trend === "up" ? 1 : s.cvd_trend === "down" ? -1 : 0,
      why: s.cvd_trend ? `CVD approx trending ${s.cvd_trend}` : "no CVD trend" },
  ];
}

// One confluence signal as a sortable column: sorting by it ranks the whole
// watchlist by that single input (every name whose CVD is trending up, etc).
function confluenceCol(idx, key) {
  const at = (s) => confluence(s)[idx];
  return {
    // Namespaced: "vwap" and "mfi" are also value-column keys, and DataTable
    // uses key as the React key — colliding ones silently drop a column.
    key: `cf_${key}`, label: key, group: "Confluence", align: "center",
    sort: (s) => at(s).v,
    cellStyle: (s) => {
      const v = at(s).v;
      return { padding: "3px 4px", fontWeight: v ? 800 : 400, fontSize: v ? 10.5 : 10,
        color: v > 0 ? T.green : v < 0 ? T.red : T.ink4,
        background: v ? (v > 0 ? T.green : T.red) + "14" : "transparent" };
    },
    render: (s) => {
      const c = at(s);
      return <span title={`${c.why}${c.v ? ` (${c.v > 0 ? "+" : ""}${c.v})` : ""}`}>
        {c.v > 0 ? "▲" : c.v < 0 ? "▼" : "·"}</span>;
    },
  };
}

// Diverging meter — zero at centre, growing right/green or left/red in
// proportion to |score|/6. Down a sorted column it draws the confluence
// falling off, which a bare number can't show.
function BiasMeter({ score, direction, reasons }) {
  const c = dirColor(direction);
  const pct = Math.min(1, Math.abs(score) / 6) * 50;
  return (
    <div title={reasons?.length ? reasons.join(" · ") : undefined}
      style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "flex-end" }}>
      <div style={{ position: "relative", width: 52, height: 6, borderRadius: 3, background: T.line2, flexShrink: 0 }}>
        <div style={{ position: "absolute", left: "50%", top: -1, bottom: -1, width: 1, background: T.line }} />
        <div style={{ position: "absolute", top: 0, bottom: 0, background: c, borderRadius: 3,
          ...(score >= 0 ? { left: "50%", width: `${pct}%` } : { right: "50%", width: `${pct}%` }) }} />
      </div>
      <span style={{ fontFamily: T.mono, fontWeight: 800, fontSize: 11, color: c, minWidth: 30, textAlign: "right" }}>
        {score > 0 ? "+" : ""}{score}
      </span>
    </div>
  );
}

const pctFrom = (price, level) =>
  price && level ? `${((price - level) / level * 100).toFixed(1)}%` : null;

const vwapDirOf = (s) => (s.vwap_position === "above" ? "bullish" : s.vwap_position === "below" ? "bearish" : null);

function Tag({ look, v }) {
  const l = (look[v] || look.NO_DATA);
  const c = l.c();
  return <span style={{ fontSize: 9, fontWeight: 800, color: c, background: c + "18",
    padding: "2px 6px", borderRadius: 4, whiteSpace: "nowrap" }}>{l.label}</span>;
}

// ── The card ────────────────────────────────────────────────────────────────
// One verdict per symbol from tools/playbook.trade_card(), which runs the
// four-stage funnel (auction context → point of interest → trigger → risk).
// It leads the table because it is the answer; every column to its right is
// one of the inputs it was computed from.
const ACTION_LOOK = {
  LONG:       { c: () => T.green, label: "LONG" },
  SHORT:      { c: () => T.red,   label: "SHORT" },
  WAIT:       { c: () => T.amber, label: "WAIT" },
  STAND_DOWN: { c: () => T.ink4,  label: "STAND DOWN" },
};
const CONTEXT_LOOK = {
  TREND_UP:   { c: () => T.green, label: "TREND ↑" },
  TREND_DOWN: { c: () => T.red,   label: "TREND ↓" },
  BALANCE:    { c: () => T.blue,  label: "BALANCE" },
  UNDECIDED:  { c: () => T.ink4,  label: "UNDECIDED" },
};
const ACTION_ORDER = ["STAND_DOWN", "WAIT", "SHORT", "LONG"];
const GRADE_ORDER = { A: 3, B: 2, C: 1 };

const cardCols = [
  { key: "context", label: "Context", group: "Plan", align: "center",
    title: "Sort by the day's auction context — the playbook that is legal today",
    sort: (s) => ["UNDECIDED", "BALANCE", "TREND_DOWN", "TREND_UP"].indexOf(s.context?.context),
    render: (s) => {
      const ctx = s.context?.context;
      if (!ctx) return <span style={{ color: T.ink4 }}>—</span>;
      return <span title={(s.context.reasons || []).join(" · ")}><Tag look={CONTEXT_LOOK} v={ctx} /></span>;
    } },
  { key: "action", label: "Card", group: "Plan", align: "center",
    title: "Sort by the funnel's verdict — tradeable cards first",
    sort: (s) => ACTION_ORDER.indexOf(s.card?.action) * 10 + (GRADE_ORDER[s.card?.grade] || 0),
    render: (s) => {
      const c = s.card;
      if (!c) return <span style={{ color: T.ink4 }}>—</span>;
      return (
        <span title={c.why} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
          <Tag look={ACTION_LOOK} v={c.action} />
          {["A+", "A", "B", "C"].includes(c.grade) && (
            <span style={{ fontSize: 9, fontWeight: 800, fontFamily: T.mono,
              color: c.grade.startsWith("A") ? accent() : T.ink3 }}>{c.grade}</span>
          )}
        </span>);
    } },
  { key: "levels", label: "Entry / Stop / T1", group: "Plan", align: "right", mono: true,
    title: "Sort by reward:risk to the first target",
    sort: (s) => s.card?.rr ?? null,
    render: (s) => {
      const c = s.card;
      if (!c || !["LONG", "SHORT"].includes(c.action)) return <span style={{ color: T.ink4 }}>—</span>;
      return (
        <span style={{ fontSize: 10 }} title={`T2 ${c.t2?.price} · risk $${c.risk_per_share}/share`}>
          <b style={{ color: T.ink }}>{c.entry}</b>
          <span style={{ color: T.red }}> {c.stop}</span>
          <span style={{ color: T.green }}> {c.t1?.price}</span>
          <span style={{ color: T.ink3 }}> · {c.rr}R</span>
        </span>);
    } },
];

// The funnel's liquidity input. Two sibling verdict engines used to live here
// — a VWAP/EMA-cross state and the Decision Point three-pillar screen — each
// publishing its own verdict next to the card's. Nothing consumed either, and a
// symbol could read ENTER, +2 neutral and DEAD at once. The only part that was
// load-bearing is how much the name is actually trading. See
// docs/STRATEGY_REVIEW.md.
const stratCols = [
  { key: "rvol", label: "RVol", group: "Participation", align: "right", mono: true,
    title: "Relative volume — below 0.7x the name is too quiet to trade; 2x+ upgrades a card to A+",
    sort: (s) => s.participation?.rvol_used ?? null,
    render: (s) => {
      const m = s.participation;
      const v = m?.rvol_used;
      if (v == null) return "—";
      const src = m.rvol_opening != null ? "opening window vs prior days"
        : `${m.rvol}x so far · ${Math.round((m.session_progress ?? 1) * 100)}% of the session elapsed`;
      return <b title={src} style={{ color: v >= 2 ? T.green : v < 0.7 ? T.red : T.ink4 }}>{v}x</b>;
    } },
  { key: "liq", label: "Liquidity", group: "Participation", align: "center",
    title: "The hard floor: is anyone trading this name at all today?",
    sort: (s) => (s.liquidity?.pass ? 1 : 0),
    render: (s) => {
      const l = s.liquidity;
      if (!l) return <span style={{ color: T.ink4 }}>—</span>;
      const c = l.pass ? (l.in_play ? T.green : T.ink3) : T.red;
      return <span title={l.pass ? (l.in_play ? "unusually active — grades a card up" : "participating normally")
                                : (l.reasons || []).join(" · ")}
        style={{ fontSize: 9, fontWeight: 800, color: c, background: c + "18",
                 padding: "2px 6px", borderRadius: 4, whiteSpace: "nowrap" }}>
        {l.pass ? (l.in_play ? "IN PLAY" : "OK") : "TOO QUIET"}</span>;
    } },
];

const signalCols = [
  { key: "sym", label: "Sym", sort: (s) => (s.is_futures ? s.label : s.symbol), defaultDir: "asc",
    title: "Sort A-Z by symbol",
    render: (s) => (
      // Company name rides in the tooltip rather than a second line: the ticker
      // is the scannable key, and the name doubled every row's height.
      <span title={s.label}>
        {/* Futures go by contract name (/ES), not the yfinance ticker (ES=F). */}
        <span style={{ fontFamily: T.mono, fontWeight: 800, fontSize: 11.5, color: T.ink }}>
          {s.is_futures ? s.label : s.symbol}
        </span>
        {s.is_futures && <span style={{ fontSize: 7.5, fontWeight: 700, color: T.ink3, background: T.line2,
          padding: "1px 4px", borderRadius: 3, marginLeft: 4, verticalAlign: "middle" }}>FUT</span>}
      </span>) },
  { key: "price", label: "Price", align: "right", mono: true, sort: (s) => s.price,
    render: (s) => <b style={{ color: T.ink }}>{Number(s.price).toFixed(2)}</b> },
  { key: "vwap", label: "VWAP", align: "right", mono: true, sort: (s) => s.vwap ?? null,
    render: (s) => <span style={{ color: dirColor(vwapDirOf(s)) }}>{s.vwap != null ? Number(s.vwap).toFixed(2) : "—"}</span> },
  { key: "vwapd", label: "Δ", align: "right", mono: true, title: "price distance from VWAP",
    sort: (s) => (s.price && s.vwap ? (s.price - s.vwap) / s.vwap : null),
    render: (s) => <span style={{ fontSize: 10, color: dirColor(vwapDirOf(s)) }}>{pctFrom(s.price, s.vwap) ?? "—"}</span> },
  { key: "sup", label: "Sup", align: "right", mono: true, title: "nearest swing support",
    sort: (s) => s.nearest_support ?? null,
    render: (s) => <span style={{ color: T.blue }}>{s.nearest_support ?? "—"}</span> },
  { key: "res", label: "Res", align: "right", mono: true, title: "nearest swing resistance",
    sort: (s) => s.nearest_resistance ?? null,
    render: (s) => <span style={{ color: T.teal }}>{s.nearest_resistance ?? "—"}</span> },
  { key: "mfi", label: "MFI", align: "right", mono: true, sort: (s) => s.mfi ?? null,
    render: (s) => {
      const ext = s.mfi != null && (s.mfi <= MFI_OVERSOLD || s.mfi >= MFI_OVERBOUGHT);
      const col = s.mfi == null ? T.ink3 : s.mfi <= MFI_OVERSOLD ? T.green : s.mfi >= MFI_OVERBOUGHT ? T.red : T.ink2;
      return <span style={{ color: col, fontWeight: ext ? 800 : 400 }}>{s.mfi ?? "—"}</span>;
    } },
  ...cardCols,
  ...["vwap", "mfi", "div", "vsa", "cvd"].map((k, i) => confluenceCol(i, k)),
  ...stratCols,
  { key: "bias", label: "Bias", align: "right", sort: (s) => s.bias_score,
    title: "Sort by confluence — most bullish to most bearish",
    render: (s) => <BiasMeter score={s.bias_score} direction={s.bias_direction} reasons={s.bias_reasons} /> },
];

function SignalsTable({ setups }) {
  return (
    // Sorted and tinted by the CARD, not the bias score. |bias| >= 3 marked the
    // loudest indicator reading, which is a different question from "is there a
    // trade here" — and on the screen it put names with nothing to do at the top.
    <DataTable columns={signalCols} rows={setups} rowKey={(s) => s.symbol} defaultSort="action"
      rowTint={(s) => (s.card?.action === "LONG" ? T.green
        : s.card?.action === "SHORT" ? T.red : null)} />
  );
}

// ── Alpha Wolf's verdict on a symbol, rendered here ────────────────────────
// This tab computes cards; it does not decide whether one is a trade and it
// cannot take one. Showing the master plan's live state next to the card is
// what stops the two screens issuing different instructions from the same
// numbers — Technologia calling AVGO the A+ setup of the day while Alpha Wolf,
// scoring it against the live quote, has already marked the move gone.
function WolfVerdict({ symbol, states, card }) {
  const { goTab } = useNav();
  const idea = states?.[String(symbol || "").toUpperCase()];
  if (!idea) {
    const why = card && !["LONG", "SHORT"].includes(card.action)
      ? "not a trade — Alpha Wolf only carries LONG/SHORT cards"
      : "not in Alpha Wolf's plan yet — it folds new cards in every 30 min";
    return <span style={{ fontSize: 10.5, color: T.ink4 }}>{why}</span>;
  }
  const st = stateStyle(stateKey(idea));
  return (
    <button type="button" onClick={() => goTab && goTab("alpha_wolf")}
      title={`${idea.note || ""}\nOpen Alpha Wolf to act on this`}
      style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: goTab ? "pointer" : "default",
        background: st.c + "16", border: `1px solid ${st.c}44`, borderRadius: 6, padding: "2px 8px",
        fontFamily: T.sans, fontSize: 10, fontWeight: 800, color: st.c }}>
      🐺 {st.label}
    </button>
  );
}

// The trade card: direction, the zone and why it is a zone, the trigger that
// fired, and the four numbers that price the trade. It is an INPUT to Alpha
// Wolf's plan, so it carries that plan's verdict rather than standing alone.
function TradeCard({ s, states }) {
  const c = s.card;
  if (!c) return null;
  const dir = c.action === "LONG" ? T.green : c.action === "SHORT" ? T.red : T.ink3;
  const num = (label, v, col) => (
    <div style={{ minWidth: 74 }}>
      <div style={{ fontSize: 9, fontWeight: 800, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontFamily: T.mono, fontSize: 14, fontWeight: 800, color: col || T.ink }}>{v ?? "—"}</div>
    </div>
  );
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontFamily: T.mono, fontWeight: 800, fontSize: 14 }}>{s.label}</span>
        <Tag look={ACTION_LOOK} v={c.action} />
        {["A+", "A", "B", "C"].includes(c.grade) && (
          <span style={{ fontSize: 10, fontWeight: 800, color: dir, background: dir + "18",
            padding: "2px 7px", borderRadius: 4 }}>GRADE {c.grade}</span>
        )}
        <Tag look={CONTEXT_LOOK} v={c.context} />
        {c.in_play && <Pill c={accent()}>in play · 2x volume</Pill>}
        <WolfVerdict symbol={s.symbol} states={states} card={c} />
      </div>
      {["LONG", "SHORT"].includes(c.action) && (
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", margin: "12px 0 10px" }}>
          {num("Entry", c.entry)}
          {num("Stop", c.stop, T.red)}
          {num("Target 1", c.t1?.price, T.green)}
          {num("Target 2", c.t2?.price, T.green)}
          {num("R:R", c.rr ? `${c.rr}:1` : null, T.ink2)}
          {num("Risk/share", c.risk_per_share ? `$${c.risk_per_share}` : null, T.ink2)}
        </div>
      )}
      {c.poi && (
        <div style={{ fontSize: 11.5, color: T.ink2, marginTop: 6 }}>
          <b>Zone</b> <span style={{ fontFamily: T.mono }}>{c.poi.low}–{c.poi.high}</span>{" "}
          <span style={{ color: T.ink3 }}>
            ({c.poi.confluence}-point confluence: {c.poi.sources.join(", ")})
          </span>
        </div>
      )}
      {c.stop_note && (
        <div style={{ fontSize: 11, color: T.amber, marginTop: 4 }}>{c.stop_note}</div>
      )}
      <div style={{ fontSize: 12, color: T.ink2, marginTop: 6, lineHeight: 1.55 }}>{c.why}</div>
      <div style={{ fontSize: 11, color: T.ink4, marginTop: 6 }}>{c.playbook}</div>
    </div>
  );
}

export default function Technologia({ status, agentError }) {
  const { data, refresh, error: dataError } = useAgentData("technologia");
  // Alpha Wolf holds the master game-plan; this tab computes what goes into it.
  // Reading its funnel record here closes the loop the other way: you can see,
  // without leaving this screen, whether the cards below actually reached the
  // plan or are still sitting in a snapshot the plan hasn't folded in yet.
  const { data: wolfData } = useAgentData("alpha_wolf");
  const funnel = wolfData?.plan?.funnel || null;
  const modelLabel = useModelLabel();
  const { goTab } = useNav();

  // Alpha Wolf's live verdict per ticker. Polled here so a card never reads as
  // an instruction the master plan has already retired. Same in-flight guard
  // and hidden-tab pause the Alpha Wolf tab uses — this endpoint walks every
  // plan ticker through a live quote fetch.
  const [wolfNow, setWolfNow] = useState(null);
  const nowBusy = useRef(false);
  const refreshNow = useCallback(async () => {
    if (nowBusy.current) return;
    nowBusy.current = true;
    try { setWolfNow(await getWolfNow()); } catch { /* the badge just falls back */ }
    finally { nowBusy.current = false; }
  }, []);
  useEffect(() => {
    const tick = (force = false) => { if (force || !document.hidden) refreshNow(); };
    tick(true);
    const id = setInterval(tick, 60000);
    const onVis = () => { if (!document.hidden) tick(true); };
    document.addEventListener("visibilitychange", onVis);
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", onVis); };
  }, [refreshNow]);
  const states = statesByTicker(wolfNow);
  const busy = status === "running";

  const s = data?.signals || null;
  const setups = s?.setups || [];
  const top = s?.top_setup;
  const window_ = s?.entry_window || {};
  const tradeable = setups.filter((t) => ["LONG", "SHORT"].includes(t.card?.action));
  const waiting = setups.filter((t) => t.card?.action === "WAIT");
  const coverage = s?.coverage || {};
  const shortfall = coverage.requested > 0 && coverage.returned < coverage.requested;
  const best = data?.best_of_session;

  const run = async () => {
    await triggerAgent("technologia");
    setTimeout(refresh, 8000); setTimeout(refresh, 20000);
  };

  return (
    <div>
      <TabHeader icon="◭" color={accent()} title="Technologia"
        sub="VP zones · VWAP · MFI divergence · VSA/CVD (approx) — stocks + /ES + /NQ"
        actions={<>
          <Pill mono c={T.ink3}>every 30 min</Pill>
          {window_.in_window && <Pill c={T.green} bg={T.greenBg}>/ES-/NQ window open</Pill>}
          <EmailPreviewButton agentId="technologia" label="Preview digest" />
          <AgentControls agentId="technologia" onRun={run} busy={busy} refresh={refresh} runLabel="Refresh" runningLabel="Computing…" />
        </>}
      />
      <div className="om-page om-stagger">
        <ErrorBanner error={agentError} />
        <ErrorBanner error={dataError} kind="data" onRetry={refresh} />
        {!s ? (
          <EmptyState icon="◭" title="No Technologia signals yet"
            hint="Click 'Refresh' to compute VWAP, volume profile, MFI divergence and VSA/CVD approximations across the watchlist plus /ES and /NQ." />
        ) : (<>

          {/* Said once, at the top: this tab is the screen, not the desk. Every
              card below is an input to Alpha Wolf's plan — which is where the
              live verdict is reached and the only place an order is placed. */}
          <Card pad={12} style={{ borderColor: purple() + "33", background: purple() + (T.mode === "dark" ? "14" : "0c") }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.5, flex: 1, minWidth: 260 }}>
                <b style={{ color: purple() }}>Technologia computes; Alpha Wolf trades.</b>{" "}
                These cards are inputs. Alpha Wolf scores them against live quotes, sizes them and
                places the orders — take every trade there, not here.
              </div>
              <button type="button" onClick={() => goTab && goTab("alpha_wolf")}
                style={{ padding: "6px 14px", background: purple(), border: "none", borderRadius: 8,
                  color: "#fff", cursor: "pointer", fontSize: 12, fontWeight: 700, fontFamily: T.sans }}>
                🐺 Open Alpha Wolf
              </button>
            </div>
          </Card>

          <div style={{ fontSize: 11, color: T.ink4, padding: "0 4px" }}>
            VSA and CVD are approximated from OHLCV bar shape (no tick/bid-ask data available) — directionally useful, not tick-accurate.
          </div>

          {/* Scoreboard first: how many of the watchlist actually produced a
              trade. A quiet tape reading 0 tradeable is the screen working. */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", padding: "0 4px" }}>
            <Pill c={tradeable.length ? T.green : T.ink4}>{tradeable.length} tradeable</Pill>
            <Pill c={T.amber}>{waiting.length} armed / waiting</Pill>
            <Pill c={T.ink4}>{setups.length - tradeable.length - waiting.length} standing down</Pill>
            {coverage.requested > 0 && (
              <Pill c={shortfall ? T.amber : T.ink4}>
                {coverage.returned}/{coverage.requested} symbols priced
              </Pill>
            )}
            {funnel && (
              <Pill c={funnel.generated_at === s.generated_at ? accent() : T.amber}
                title={funnel.generated_at === s.generated_at
                  ? `Alpha Wolf's plan was built from this exact run (synced ${funnel.synced_at || "—"})`
                  : `Alpha Wolf is still on the ${funnel.generated_at || "—"} run — the next pulse folds these cards in`}>
                🐺 {funnel.tradeable || 0} in Alpha Wolf's plan
                {funnel.generated_at === s.generated_at ? "" : " (syncing)"}
              </Pill>
            )}
          </div>

          {/* A run that got no price data finds nothing for a reason that has
              nothing to do with the tape. Saying so is the difference between
              "quiet market" and "the screen was blind". */}
          {shortfall && (
            <Card pad={14} style={{ borderColor: T.amber + "55", background: T.amber + "10" }}>
              <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.55 }}>
                <b style={{ color: T.amber }}>Incomplete price data.</b>{" "}
                Only {coverage.returned} of {coverage.requested} symbols returned bars this run
                {(coverage.missing || []).length > 0 && <> — missing {coverage.missing.join(", ")}</>}.
                Cards are computed only for what was priced, so a low count here is missing data
                rather than a quiet tape. It usually clears on the next run.
              </div>
            </Card>
          )}

          {/* The day's best card, held even after a later quieter run replaced
              the live snapshot — the good setup used to be unrecoverable ten
              minutes after it appeared. */}
          {best?.card && !top && (
            <Card pad={14} style={{ borderColor: accent() + "33" }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: accent(), textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>
                Best card earlier today — {best.at}
              </div>
              <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.55 }}>
                <b>{best.label} ({best.symbol})</b> — {best.card.action} grade {best.card.grade} @ {best.card.entry},
                stop {best.card.stop}, T1 {best.card.t1?.price} ({best.card.rr}R).
                Nothing is tradeable right now; this is what the session produced.
              </div>
            </Card>
          )}

          {top ? (
            <Card pad={16} style={{ background: accentBg(), borderColor: accent() + "44" }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: accent(), textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 }}>
                Highest-conviction card this run — feeds Alpha Wolf
              </div>
              <TradeCard s={top} states={states} />
              <div style={{ fontSize: 11.5, color: T.ink2, marginTop: 10, lineHeight: 1.5 }}>{s.three_stage_exit}</div>
            </Card>
          ) : (
            <Card pad={16} style={{ background: T.cardAlt }}>
              <div style={{ fontSize: 12.5, color: T.ink3 }}>
                No symbol produced a tradeable card this run — the auction, the zone or the trigger is
                missing on every name. Sitting out is the output, not a gap in it.
              </div>
            </Card>
          )}

          {tradeable.length > 1 && (
            <Card pad={15}>
              <SectionTitle sub="every card the funnel cleared, best grade first — each carries Alpha Wolf's live verdict">Other cards</SectionTitle>
              <div style={{ display: "grid", gap: 14, marginTop: 10 }}>
                {tradeable.slice(1).map((t) => (
                  <div key={t.symbol} style={{ borderTop: `1px solid ${T.line2}`, paddingTop: 12 }}>
                    <TradeCard s={t} states={states} />
                  </div>
                ))}
              </div>
            </Card>
          )}

          {s.commentary && (
            <Card pad={15}>
              <div style={{ display: "flex", gap: 14 }}>
                <LufiAvatar size={38} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 5 }}>Technical read <span style={{ fontSize: 11, color: T.ink4 }}>by Lufi · {modelLabel}</span></div>
                  <div style={{ fontSize: 13, color: T.ink2, lineHeight: 1.55, whiteSpace: "pre-line" }}>{s.commentary}</div>
                </div>
              </div>
            </Card>
          )}

          <Card pad={15}>
            <SectionTitle sub={`${setups.length} symbols · sorted by card · click any header to re-sort`}>All signals</SectionTitle>
            <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 6, lineHeight: 1.6 }}>
              <b>Plan</b> is the verdict — context decides which playbook is legal, the card is the trade.
              Everything to its right is an <i>input</i> to that verdict, not a competing opinion:{" "}
              <span style={{ color: T.green, fontWeight: 800 }}>▲</span> bullish ·{" "}
              <span style={{ color: T.red, fontWeight: 800 }}>▼</span> bearish contribution, <b>div</b> counts ±2,
              the other four ±1. Tinted rows have a live card; hover any cell for the reading behind it.
            </div>
            <SignalsTable setups={setups} />
          </Card>

          <Card pad={15}>
            <Collapsible id="technologia-methodology" title="Methodology" sub="EminiPlayer framework adaptation">
              <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.7 }}>
                <p style={{ margin: "0 0 8px" }}><b>Trade location:</b> session volume profile (POC/VAH/VAL) plus a coarse 5-day "weekly" profile, and swing-based support/resistance from daily bars.</p>
                <p style={{ margin: "0 0 8px" }}><b>Intraday bias:</b> VSA approximated from volume vs. range vs. close-in-range (no tick data) — flags absorption and buying/selling pressure.</p>
                <p style={{ margin: "0 0 8px" }}><b>Momentum:</b> session VWAP position, and cumulative volume delta approximated the same way as VSA.</p>
                <p style={{ margin: "0 0 8px" }}><b>Exhaustion:</b> MFI (volume-weighted RSI) divergence against price swings.</p>
                <p style={{ margin: 0 }}><b>Entry window:</b> /ES and /NQ signals only matter inside 10:30-11:55 ET per the source framework — the first opening-range breakout is typically a liquidity grab; trade the reversal, not the breakout.</p>
              </div>
            </Collapsible>
          </Card>

          <Card pad={15}>
            <Collapsible id="technologia-participation" title="Participation"
                         sub="the liquidity input behind every card">
              <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.7 }}>
                <p style={{ margin: "0 0 8px" }}>
                  <b>The floor</b> — is anyone trading this name today? Below 0.7x its own
                  normal pace, under 500k average volume, an ATR too small to pay the spread,
                  or a chart of disconnected dots, and no card trades it however good the
                  pattern looks. A great pattern on a dead stock is a trap.
                </p>
                <p style={{ margin: "0 0 8px" }}>
                  <b>2x relative volume</b> is not a gate — it is a grade upgrade. It is a
                  <i> scanner</i> threshold, meant to find a handful of names out of thousands;
                  applied to a fixed megacap watchlist it returns "dead" nearly every day, which
                  is exactly what it did to all 24 symbols on the first live run.
                </p>
                <p style={{ margin: 0, color: T.ink4 }}>
                  Two sibling engines used to publish their own verdicts in this table — a
                  VWAP/EMA-cross state and the full Decision Point three-pillar screen. Neither
                  reached the broker, and a symbol could read ENTER, +2 neutral and DEAD at the
                  same time. The card is the only verdict now.
                </p>
              </div>
            </Collapsible>
          </Card>
        </>)}
      </div>
    </div>
  );
}
