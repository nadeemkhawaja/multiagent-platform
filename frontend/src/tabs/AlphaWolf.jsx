// ============================================================================
// AlphaWolf.jsx — Master agent. Synthesizes the trading pack (Wolf, Technologia) into
// a Daily + Weekly trade game-plan, then executes the daily ideas on a
// simulated paper-trading portfolio (virtual capital, live prices — no real money).
// ============================================================================
import { useState, useEffect, useCallback, useRef } from "react";
import { T, AGENT_COLOR } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent, getWolfPortfolio, setWolfExecution, resetWolfPortfolio, getWolfNow, getWolfJournal, runWolfRiskCheck, cancelWolfPending } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar, Collapsible } from "../components/Common";
import { stateStyle, stateKey } from "../state/tradeState";
import { Ico } from "../theme/icons";

// Alpha Wolf is the product's centre, so this tab wears the identity token
// itself — the highest-chroma colour in the app. Read at call time: T and
// AGENT_COLOR are mutated in place by applyMode().
const purple = () => AGENT_COLOR.alpha_wolf;
const purpleBg = () => AGENT_COLOR.alpha_wolf + (T.mode === "dark" ? "1f" : "14");

const SOURCE_LABELS = {
  wallstreet_wolf: "Wallstreet Wolf",
  technologia: "Technologia",
};
const ALL_SOURCES = Object.keys(SOURCE_LABELS);

// The plan comes from a local LLM and is not guaranteed to match the schema —
// a field that should be a string sometimes arrives as an object or array.
// React throws on object children, so coerce everything to text before render.
function txt(v) {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map(txt).filter(Boolean).join(", ");
  if (typeof v === "object") return Object.values(v).map(txt).filter(Boolean).join(" — ");
  return String(v);
}

function dirColor(d) {
  const v = txt(d).toLowerCase();
  return v === "long" ? T.green : v === "short" ? T.red : T.ink3;
}
function biasColor(b) {
  const v = String(b || "NEUTRAL").toUpperCase();
  return v === "BULLISH" ? T.green : v === "BEARISH" ? T.red : T.ink3;
}

function BiasPill({ bias }) {
  const c = biasColor(bias);
  const v = String(bias || "NEUTRAL").toUpperCase();
  return <span style={{ fontSize: 10.5, fontWeight: 800, color: c, background: c + "16", padding: "3px 10px", borderRadius: 6 }}>{v}</span>;
}

function StancePill({ stance }) {
  const v = String(stance || "NEUTRAL").toUpperCase();
  const c = v === "RISK-ON" ? T.green : v === "RISK-OFF" ? T.red : T.ink3;
  return <span style={{ fontSize: 11, fontWeight: 800, color: T.onAccent, background: c, padding: "4px 12px", borderRadius: 999, whiteSpace: "nowrap" }}>{v}</span>;
}

function fmtCountdown(min) {
  if (min == null) return "";
  return min >= 60 ? `${Math.floor(min / 60)}h ${min % 60}m` : `${min}m`;
}

// ── The session banner — WHEN we are and WHICH WAY the market leans ─────────
// The two questions a trader asks before anything else, answered at a glance:
// the part of the day (with what that window is for) and one bullish/bearish
// call built from the tape, the Wolf composite and the plan's own bias.
const BIAS_LOOK = (d) => ({
  bullish: { c: T.green, label: "BULLISH", arrow: "▲" },
  bearish: { c: T.red,   label: "BEARISH", arrow: "▼" },
  mixed:   { c: T.amber, label: "MIXED",   arrow: "⇄" },
  neutral: { c: T.ink3,  label: "NEUTRAL", arrow: "—" },
}[d] || { c: T.ink4, label: "NO READ", arrow: "?" });

// Signed meter: the weighted bias score laid out from -max (bearish) through
// zero to +max (bullish), so how *close* the call was is visible, not just
// which side won.
function BiasMeter({ score = 0, max = 0, color }) {
  if (!max) return null;
  const pct = Math.max(-1, Math.min(1, score / max));
  const half = Math.abs(pct) * 50;
  return (
    <div style={{ position: "relative", width: 132, height: 6, borderRadius: 3, background: T.line2, marginTop: 8 }}>
      <div style={{ position: "absolute", top: 0, bottom: 0, borderRadius: 3, background: color,
        left: pct >= 0 ? "50%" : `${50 - half}%`, width: `${half}%` }} />
      <div style={{ position: "absolute", left: "50%", top: -3, bottom: -3, width: 1, background: T.ink4 }} />
    </div>
  );
}

const TICK_GAP = 12;   // percent of the bar two tick labels need between them
function tickLabels(phases) {
  const out = [];
  let last = -TICK_GAP;
  for (const p of phases) {
    if (p.pct - last < TICK_GAP) continue;
    out.push(p);
    last = p.pct;
  }
  // The 20:00 end tick is pinned to the right edge, so drop a start tick that
  // would land underneath it.
  return out.filter((p) => p.pct <= 100 - TICK_GAP);
}

// Once /now has answered once, nowData sticks. A later failure would otherwise
// leave a frozen clock and quotes minutes old looking exactly like live ones —
// on a tab whose whole job is "what do I do right now", silently stale is worse
// than visibly broken.
function StaleBanner({ error, onRetry }) {
  if (!error) return null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 12,
      padding: "7px 12px", borderRadius: 8, background: T.amberBg, border: `1px solid ${T.amber}44`,
      fontSize: 11.5, fontWeight: 600, color: T.amber }}>
      <Ico name="warn" size={13} style={{ display: "inline", verticalAlign: "-2px", marginRight: 5 }} />Not live — everything below is the last good read. {error.message || String(error)}
      <button onClick={onRetry} style={{ fontSize: 11, fontWeight: 700, padding: "2px 9px", borderRadius: 6,
        cursor: "pointer", border: `1px solid ${T.amber}66`, background: "transparent", color: T.amber }}>
        Retry
      </button>
    </div>
  );
}

function SessionBanner({ now }) {
  const clock = now.clock;
  const bias = now.bias || {};
  const look = BIAS_LOOK(bias.direction);
  const open = clock.is_open;
  const next = clock.next_event || {};
  const phases = clock.phases || [];
  return (
    <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "stretch" }}>

      {/* WHERE WE ARE IN THE DAY */}
      <div style={{ flex: "3 1 340px", minWidth: 280 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontSize: 24, fontWeight: 800, color: T.ink, letterSpacing: -0.4, lineHeight: 1.1 }}>
            {clock.session_label}
          </span>
          <span style={{ fontSize: 10.5, fontWeight: 800, color: T.onAccent, background: open ? T.green : T.ink3, padding: "3px 10px", borderRadius: 999, whiteSpace: "nowrap" }}>
            {open ? "● OPEN" : "○ CLOSED"}
          </span>
          <span style={{ fontSize: 13, fontFamily: T.mono, fontWeight: 700, color: T.ink2 }}>{clock.et} ET</span>
          <span style={{ fontSize: 12, color: T.ink4 }}>{clock.weekday}</span>
        </div>
        {clock.session_note && (
          <div style={{ fontSize: 12.5, color: T.ink3, lineHeight: 1.45, marginTop: 4 }}>{clock.session_note}</div>
        )}

        {/* The trading day as one bar, 4:00 → 20:00 ET, with a live marker. */}
        <div style={{ marginTop: 12 }}>
          <div style={{ position: "relative", display: "flex", height: 26, borderRadius: 7, overflow: "hidden", border: `1px solid ${T.line}` }}>
            {phases.map((p) => (
              <div key={p.key} title={`${p.label} · ${p.start_label}–${p.end_label} ET`}
                style={{ width: `${p.width}%`, display: "grid", placeItems: "center", overflow: "hidden",
                  background: p.current ? purple() : T.cardAlt,
                  color: p.current ? T.onAccent : T.ink4,
                  borderRight: `1px solid ${T.line}`,
                  fontSize: 9.5, fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.3, whiteSpace: "nowrap" }}>
                {/* The open and power hour are ~6% of the bar; a label there
                    truncates to "OPE"/"POW", which is worse than none. The
                    session name above already says which window we're in. */}
                {p.width >= 9 ? (p.short || p.label) : ""}
              </div>
            ))}
            {clock.in_day_band && (
              <div aria-hidden="true" style={{ position: "absolute", top: -2, bottom: -2, left: `${clock.day_pct}%`,
                width: 2, background: T.ink, boxShadow: `0 0 0 1px ${T.card}` }} />
            )}
          </div>
          {/* Ticks sit at their real position on the bar, not spread evenly —
              9:30 is 34% along a 4:00→20:00 band, and an evenly-spaced label
              row would put the opening bell in the wrong place. Ticks closer
              than TICK_GAP to the previous one are dropped: the open and power
              hour are 6% of the bar each, so their labels would collide with
              the neighbour's at every width. */}
          <div style={{ position: "relative", height: 12, marginTop: 3 }}>
            {tickLabels(phases).map((p, i) => (
              <span key={p.key} style={{ position: "absolute", left: `${p.pct}%`, fontSize: 9.5, color: T.ink4, fontFamily: T.mono,
                transform: i === 0 ? "none" : "translateX(-50%)", whiteSpace: "nowrap" }}>
                {p.start_label}
              </span>
            ))}
            <span style={{ position: "absolute", right: 0, fontSize: 9.5, color: T.ink4, fontFamily: T.mono }}>
              {phases.length ? phases[phases.length - 1].end_label : ""}
            </span>
          </div>
        </div>

        {next.label && (
          <div style={{ fontSize: 11.5, color: T.ink4, marginTop: 8 }}>
            Next: <b style={{ color: T.ink2 }}>{next.label}</b> at <span style={{ fontFamily: T.mono }}>{next.at}</span>
            {" · in "}<b style={{ color: purple(), fontFamily: T.mono }}>{fmtCountdown(next.in_min)}</b>
          </div>
        )}
      </div>

      {/* WHICH WAY IT LEANS */}
      <div style={{ flex: "2 1 260px", minWidth: 240, borderLeft: `1px solid ${T.line}`, paddingLeft: 18,
        display: "flex", flexDirection: "column" }}>
        <div style={{ fontSize: 10, fontWeight: 800, color: T.ink4, textTransform: "uppercase", letterSpacing: ".6px" }}>
          Market bias right now
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 5 }}>
          <span aria-hidden="true" style={{ fontSize: 22, color: look.c, lineHeight: 1 }}>{look.arrow}</span>
          <span style={{ fontSize: 24, fontWeight: 800, color: look.c, letterSpacing: -0.4, lineHeight: 1.1 }}>{look.label}</span>
        </div>
        <BiasMeter score={bias.score} max={bias.max_score} color={look.c} />
        {bias.why && <div style={{ fontSize: 12.5, color: T.ink2, lineHeight: 1.45, marginTop: 8 }}>{bias.why}</div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 8 }}>
          {(bias.drivers || []).map((d) => {
            const dc = BIAS_LOOK(d.direction).c;
            return (
              <div key={d.key} style={{ display: "flex", alignItems: "baseline", gap: 6, fontSize: 11 }}>
                <span aria-hidden="true" style={{ color: dc, fontWeight: 800, width: 10 }}>{BIAS_LOOK(d.direction).arrow}</span>
                <span style={{ color: T.ink3, fontWeight: 600 }}>{d.label}</span>
                <span style={{ color: T.ink4, fontFamily: T.mono, fontSize: 10.5, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.detail}</span>
                {d.gating && <span title="This read blocks counter-trend entries at the broker" style={{ fontSize: 9, fontWeight: 800, color: dc }}>GATING</span>}
              </div>
            );
          })}
        </div>
        {bias.agreement && <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 6 }}>{bias.agreement}</div>}
      </div>
    </div>
  );
}

// Stands in for the live card while /now has not answered. A one-line strip,
// not a Card: an empty bordered box the height of the banner it replaces is
// exactly the "blank white slab" this tab used to show.
function LiveStatus({ error, onRetry }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
      fontSize: 12.5, color: error ? T.red : T.ink4, padding: "2px 4px" }}>
      {error ? (<>
        <span><Ico name="warn" size={13} style={{ display: "inline", verticalAlign: "-2px", marginRight: 5 }} />Live session data unavailable — {error.message || String(error)}</span>
        <button onClick={onRetry} style={{ fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 6,
          cursor: "pointer", border: `1px solid ${T.line}`, background: T.card, color: T.ink3 }}>Retry</button>
      </>) : <span>Loading the session clock…</span>}
    </div>
  );
}

// ── The action strip — one row per name, and nothing you can't act on ───────
// This replaced a pair of tables that printed the same five tickers twice: the
// plan's levels in one, the live state in the other. Reading them meant
// matching rows by ticker across two grids to answer one question. Here each
// name is a single row carrying its own verdict, its three numbers and its
// size; the reasoning behind it — trigger, thesis, risk — is one click away,
// because it is what you check *before* the day, not while acting.

function Level({ k, v, dim }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 4 }}>
      <span style={{ fontSize: 9, fontWeight: 800, color: T.ink4, letterSpacing: ".4px" }}>{k}</span>
      <span style={{ fontFamily: T.mono, fontSize: 13, fontWeight: 800,
        color: dim ? T.ink4 : T.ink, textDecoration: dim ? "line-through" : "none" }}>
        {v == null ? "—" : Number(v).toFixed(2)}
      </span>
    </span>
  );
}

function ActionRow({ idea }) {
  const [open, setOpen] = useState(false);
  const st = stateStyle(stateKey(idea));
  const dc = dirColor(idea.direction);
  const dead = st.levels === "none";
  const detail = [idea.trigger, idea.thesis, idea.risk].some(Boolean);
  const b = idea.banked;
  return (
    <div style={{ borderBottom: `1px solid ${T.line2}`, background: st.rank === 0 ? st.c + "10" : "transparent" }}>
      <div onClick={detail ? () => setOpen((v) => !v) : undefined}
        role={detail ? "button" : undefined} tabIndex={detail ? 0 : undefined}
        aria-expanded={detail ? open : undefined}
        onKeyDown={detail ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen((v) => !v); } } : undefined}
        style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
          padding: "10px 12px", cursor: detail ? "pointer" : "default",
          boxShadow: `inset 3px 0 0 ${st.c}` }}>

        {/* WHAT and WHICH WAY */}
        <div style={{ minWidth: 96 }}>
          <span style={{ fontFamily: T.mono, fontSize: 15, fontWeight: 800, color: T.ink }}>{txt(idea.ticker)}</span>
          <span style={{ marginLeft: 7, fontSize: 9.5, fontWeight: 800, color: dc, textTransform: "uppercase" }}>{txt(idea.direction)}</span>
        </div>

        {/* THE VERDICT — the widest-set element in the row on purpose */}
        <span style={{ fontSize: 10, fontWeight: 800, color: T.onAccent, background: st.c,
          padding: "4px 10px", borderRadius: 5, whiteSpace: "nowrap", minWidth: 92, textAlign: "center" }}>
          {st.label}
        </span>

        {/* THE THREE NUMBERS */}
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", minWidth: 250 }}>
          {st.levels === "done" ? (
            <span style={{ fontFamily: T.mono, fontSize: 14, fontWeight: 800, color: pnlColor(b?.pnl) }}>
              {(b?.pnl ?? 0) >= 0 ? "+" : ""}{fmt$(b?.pnl)}
              {b?.r_multiple != null && (
                <span style={{ fontSize: 11.5, marginLeft: 7, color: T.ink4 }}>
                  {b.r_multiple >= 0 ? "+" : ""}{b.r_multiple}R
                </span>
              )}
            </span>
          ) : (<>
            {st.levels !== "manage" && <Level k="ENT" v={idea.entry} dim={dead} />}
            <Level k="STP" v={idea.stop} dim={dead} />
            <Level k="TGT" v={idea.target} dim={dead} />
          </>)}
        </div>

        {/* SIZE — only where there is still a position to open */}
        <div style={{ minWidth: 104, fontFamily: T.mono, fontSize: 11.5, color: T.ink3 }}>
          {st.levels === "full" && idea.size_shares
            ? <b style={{ color: T.ink2 }}>{idea.size_shares} sh</b>
            : <span style={{ color: T.ink4 }}>{st.levels === "full" && idea.size_note ? "no size" : ""}</span>}
        </div>

        {/* LIVE */}
        <div style={{ fontFamily: T.mono, fontSize: 11.5, color: T.ink4, minWidth: 74 }}>
          {idea.live != null ? `live ${fmt$(idea.live)}` : ""}
        </div>

        {detail && <span aria-hidden="true" style={{ marginLeft: "auto", fontSize: 11, color: T.ink4 }}>{open ? "▴ why" : "▾ why"}</span>}
      </div>

      {/* The one-line reason always shows: a verdict with no reason is a
          command, and this tab is supposed to be arguable. */}
      <div style={{ padding: "0 12px 9px 15px", fontSize: 12, color: T.ink3, lineHeight: 1.45 }}>{txt(idea.note)}</div>

      {open && (
        <div style={{ padding: "10px 14px 13px 15px", background: T.cardAlt, borderTop: `1px solid ${T.line2}`,
          fontSize: 12, color: T.ink3, lineHeight: 1.55, display: "grid", gap: 6 }}>
          {idea.trigger && <div><b style={{ color: T.ink4, fontSize: 10, letterSpacing: ".4px" }}>TRIGGER </b>{txt(idea.trigger)}</div>}
          {idea.thesis && <div><b style={{ color: T.ink4, fontSize: 10, letterSpacing: ".4px" }}>THESIS </b>{txt(idea.thesis)}</div>}
          {idea.risk && <div><b style={{ color: T.ink4, fontSize: 10, letterSpacing: ".4px" }}>RISK </b>{txt(idea.risk)}</div>}
          <div style={{ fontSize: 10.5, color: T.ink4, fontFamily: T.mono }}>
            {[idea.rr != null && `R:R ${idea.rr}`,
              idea.grade && `grade ${txt(idea.grade)}`,
              idea.zone && `zone ${txt(idea.zone)}`,
              idea.confluence != null && `${idea.confluence}-pt confluence`,
              idea.size_usd != null && `~${fmt$(idea.size_usd)}`,
              idea.size_note].filter(Boolean).join("  ·  ")}
          </div>
        </div>
      )}
    </div>
  );
}

function RightNowBlock({ now }) {
  const ideas = [...(now.ideas || [])].sort(
    (a, b) => stateStyle(stateKey(a)).rank - stateStyle(stateKey(b)).rank);
  if (!now.directive && !ideas.length && !now.pulse?.checked_at) return null;
  const live = ideas.filter((i) => stateStyle(stateKey(i)).rank <= 5);
  // "Act now" is a different kind of sentence from "market closed" — one is an
  // instruction, the other is the absence of one. Only the instruction earns
  // the board scale.
  const acting = /^ACT NOW/i.test(String(now.directive || ""));
  return (
    // THE call. This is the one element in the app allowed the board scale, and
    // it is the reason the app is open: "what do I do right now". It read at
    // 14.5px — a quarter-step above body copy — so the answer the whole product
    // exists to produce was the same size as the caveat under it.
    //
    // An ACT directive gets the full board figure; everything else (waiting,
    // closed, market shut) is a statement of fact and steps down to `title`,
    // because shouting "market closed" at 44px is how a scale stops meaning
    // anything.
    <div style={{ padding: 0, marginTop: 18, borderTop: `1px solid ${T.brass}44`, paddingTop: 16 }}>
      <div style={{
        fontSize: acting ? T.type.board : T.type.title,
        fontWeight: acting ? 800 : 600,
        fontStretch: acting ? "112%" : "100%",
        letterSpacing: acting ? "-0.025em" : "-0.01em",
        color: acting ? T.ink : T.ink2,
        lineHeight: 1.08, marginBottom: ideas.length ? 14 : 0,
        textWrap: "balance",
      }}>
        {txt(now.directive)}
      </div>
      {ideas.length > 0 && (
        <div style={{ borderTop: `1px solid ${T.line}` }}>
          {ideas.map((i, k) => <ActionRow key={`${i.ticker}-${k}`} idea={i} />)}
        </div>
      )}
      {ideas.length > 0 && !live.length && (
        <div style={{ fontSize: 12, color: T.ink4, marginTop: 9 }}>
          Nothing left to act on today — every name above is closed, invalidated or gated.
        </div>
      )}
      {now.pulse?.checked_at && (
        <div style={{ fontSize: 10.5, color: T.ink4, marginTop: 10 }}>
          Pulse: checked {now.pulse.checked_at} ET{now.pulse.alerts?.length ? ` · ${now.pulse.alerts.length} alert${now.pulse.alerts.length !== 1 ? "s" : ""} sent` : " · no alerts"} · auto-checks every 30 min in market hours
        </div>
      )}
    </div>
  );
}

// The five tables on this tab are hand-built (each has bespoke cells — meters,
// progress bars, action pills — that a generic column list would obscure), so
// they take the shared LOOK rather than the shared component: content width so
// they sit left instead of stretching, and full gridlines to hold a row across.
const RULE = () => `1px solid ${T.line}`;
// nowrap on the TABLE, inherited by all forty hand-written cells. Without it a
// narrow window doesn't scroll the table — width:auto simply lets the columns
// collapse, and a share price comes out as "$30 8.5 2" stacked over three
// lines. The handful of cells holding prose opt back out with whiteSpace:
// "normal"; everything else here is a ticker, a price or a state pill.
const tableSt = () => ({ width: "auto", borderCollapse: "collapse", fontSize: 11.5, border: RULE(), whiteSpace: "nowrap" });
const wrapSt = { overflowX: "auto", maxWidth: "100%", display: "flex", alignItems: "flex-start",
  overscrollBehaviorX: "contain" };
const thSt = (align = "left") => ({ textAlign: align, padding: "3px 7px", fontSize: 9,
  fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.3,
  borderBottom: RULE(), borderRight: RULE(), whiteSpace: "nowrap" });
// Flat is not a gain. This returned green for 0, so a fresh account with
// nothing in it showed UNREALIZED, REALIZED, RETURN and TODAY'S P&L all in
// profit green — four valence marks carrying no direction at all, which is the
// colour noise the board palette exists to remove. Valence is for numbers that
// actually moved; zero and unknown are neutral.
function pnlColor(v) {
  if (v == null || Math.abs(v) < 0.005) return T.ink3;
  return v > 0 ? T.green : T.red;
}
const fmt$ = (v) => (v == null ? "—" : `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

function Stat({ label, value, color }) {
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ fontSize: T.type.micro, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: ".6px", fontStretch: "88%" }}>{label}</div>
      <div style={{ fontSize: 19, fontWeight: 700, fontStretch: "106%", letterSpacing: "-0.015em",
        color: color || T.ink, marginTop: 3, ...T.tnum }}>{value}</div>
    </div>
  );
}

function ActionPill({ action }) {
  const buy = action === "BUY" || action === "COVER";
  const c = buy ? T.green : T.red;
  return <span style={{ fontSize: 9.5, fontWeight: 800, color: T.onAccent, background: c, padding: "2px 8px", borderRadius: 4 }}>{action}</span>;
}

// ── Live position monitor: where price sits between stop ⟵⟶ target ─────────
// One formula covers both directions: (last − stop) / (target − stop) is 0 at
// the stop and 1 at the target for longs AND shorts (both terms flip sign).
function positionProgress(p) {
  const { stop, target, last_price: last, entry_price: entry } = p;
  if (!stop || !target || !last || target === stop) return null;
  const pct = (last - stop) / (target - stop);
  const entryPct = (entry - stop) / (target - stop);
  return { pct: Math.min(1, Math.max(0, pct)), entryPct: Math.min(1, Math.max(0, entryPct)) };
}

function positionR(p) {
  const init = p.initial_stop ?? p.stop;
  const { entry_price: entry, last_price: last } = p;
  if (!init || !entry || !last || init === entry) return null;
  const risk = Math.abs(entry - init);
  const move = p.direction === "short" ? entry - last : last - entry;
  return move / risk;
}

function holdDays(entryDate) {
  if (!entryDate) return null;
  const d = new Date(String(entryDate).replace(" ", "T"));
  if (isNaN(d)) return null;
  return (Date.now() - d.getTime()) / 86400000;
}

function StopTargetBar({ p }) {
  const prog = positionProgress(p);
  if (!prog) return <span style={{ color: T.ink4 }}>—</span>;
  const liveC = prog.pct >= prog.entryPct ? T.green : T.red;
  return (
    <div title={`stop ${fmt$(p.stop)} · live ${fmt$(p.last_price)} · target ${fmt$(p.target)}`}
      style={{ position: "relative", width: 120, height: 6, borderRadius: 3, background: T.line2, display: "inline-block" }}>
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${prog.pct * 100}%`, borderRadius: 3, background: liveC + "55" }} />
      <div style={{ position: "absolute", left: `${prog.entryPct * 100}%`, top: -2, bottom: -2, width: 2, background: T.ink4, borderRadius: 1 }} />
      <div style={{ position: "absolute", left: `calc(${prog.pct * 100}% - 4px)`, top: -1, width: 8, height: 8, borderRadius: 4, background: liveC, border: `1.5px solid ${T.card}` }} />
    </div>
  );
}

// ── Sync status: is what this tab shows actually what Alpaca has? ───────────
function SyncStrip({ sync, pendingCount }) {
  if (!sync) return null;
  const drift = (sync.untracked || []).length > 0;
  const pendingRec = (sync.unreconciled || []).length > 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12, fontSize: 11, color: T.ink4 }}>
      <span style={{ fontWeight: 700, color: drift ? T.amber : T.green }}>
        {drift ? "partial sync" : "in sync"}
      </span>
      <span>equity read live from Alpaca</span>
      {sync.last_check && <span>· last reconcile {sync.last_check}</span>}
      {pendingCount > 0 && <span>· {pendingCount} working entry order{pendingCount !== 1 ? "s" : ""}</span>}
      {drift && (
        <span style={{ color: T.amber, fontWeight: 600 }}>
          · {sync.untracked.join(", ")} held at Alpaca but not opened by Alpha Wolf — unmanaged (no stop discipline)
        </span>
      )}
      {pendingRec && (
        <span>· {sync.unreconciled.join(", ")} closed at Alpaca — journals on next sync</span>
      )}
    </div>
  );
}

// ── Working entry orders — placed at the plan's level, waiting for a fill ───
function PendingEntries({ pending, onChanged }) {
  const [busy, setBusy] = useState(false);
  if (!pending?.length) return null;
  const cancel = async (id) => {
    setBusy(true);
    try { await cancelWolfPending(id); await onChanged(); } finally { setBusy(false); }
  };
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11.5, fontWeight: 700, color: T.ink3, marginBottom: 6 }}>
        Working entry orders ({pending.length})
        <span style={{ fontWeight: 400, color: T.ink4 }}> · fills when price reaches the level · auto-cancelled 15:50 ET</span>
      </div>
      <div style={wrapSt}>
        <table style={tableSt()}>
          <thead>
            <tr>
              {["Ticker", "Dir", "Entry", "Stop", "Target", "Conf", "Submitted", ""].map((h, i) => (
                <th key={h || "x"} style={{ ...thSt(i >= 2 && i <= 5 ? "right" : "left")  }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pending.map((p) => (
              <tr key={p.order_id} style={{ borderBottom: RULE() }}>
                <td style={{ padding: "3px 7px", borderRight: RULE(), fontFamily: T.mono, fontWeight: 800, color: T.ink }}>{p.ticker}</td>
                <td style={{ padding: "3px 7px", borderRight: RULE() }}>
                  <span style={{ fontSize: 9.5, fontWeight: 800, color: dirColor(p.direction), background: dirColor(p.direction) + "16", padding: "2px 7px", borderRadius: 4, textTransform: "uppercase" }}>{p.direction}</span>
                </td>
                <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono }}>
                  <span style={{ fontSize: 9, color: T.ink4, textTransform: "uppercase" }}>{p.kind} </span>{fmt$(p.entry)}
                </td>
                <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, color: T.red }}>{fmt$(p.stop)}</td>
                <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, color: T.green }}>{fmt$(p.target)}</td>
                <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, color: T.ink3 }}>{p.grade || "—"}</td>
                <td style={{ padding: "3px 7px", borderRight: RULE(), fontFamily: T.mono, color: T.ink4 }}>{p.submitted_at}</td>
                <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right" }}>
                  <button onClick={() => cancel(p.order_id)} disabled={busy} style={{
                    fontSize: 10.5, fontWeight: 700, padding: "3px 10px", borderRadius: 6, cursor: "pointer",
                    border: `1px solid ${T.red}44`, background: T.card, color: T.red }}>
                    Cancel
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// One risk gate. The four of these were four near-identical inline blocks that
// had already drifted apart (one carried no tooltip at all), and none of them
// showed that the value commits on blur rather than as you type.
function RiskField({ label, suffix, width, step, min, max, value, onCommit, disabled, title }) {
  return (
    <label title={title} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 700, color: T.ink3 }}>
      {label}
      {/* Uncontrolled so a 15s portfolio poll can't yank the cursor mid-edit,
          but keyed on the stored value so that when the backend clamps what you
          typed the field shows what was actually saved rather than your input. */}
      <input key={String(value)} type="number" step={step} min={min} max={max} defaultValue={value}
        onBlur={onCommit} disabled={disabled}
        // Enter commits too: on a settings field that saves on blur, typing a
        // new limit and hitting Enter otherwise looked like it had saved.
        onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
        style={{ width, fontSize: 11, fontWeight: 700, padding: "4px 6px", borderRadius: 6, textAlign: "right",
          border: `1px solid ${T.line}`, background: T.card, color: T.ink }} />
      {suffix}
    </label>
  );
}

function PortfolioCard({ portfolio, onChanged }) {
  const [busy, setBusy] = useState(false);
  if (!portfolio) return null;
  const { settings = {}, summary = {}, positions = [], trades = [], note, daily_breaker,
          pending_entries = [], sync: syncInfo } = portfolio;

  if (settings.configured === false) {
    return (
      <div style={{ padding: 0 }}>
        <SectionTitle sub="simulated fills via a real Alpaca paper account · live prices">Paper Trading Portfolio</SectionTitle>
        <div style={{ marginTop: 10, padding: "12px 14px", borderRadius: 10, background: T.amberBg, border: `1px solid ${T.amber}44`, fontSize: 12.5, color: T.ink2, lineHeight: 1.55 }}>
          <Ico name="warn" size={13} style={{ display: "inline", verticalAlign: "-2px", marginRight: 5 }} />{note || "Alpaca isn't configured yet."} Sign up free at <a href="https://alpaca.markets" target="_blank" rel="noreferrer" style={{ color: T.amber, fontWeight: 700 }}>alpaca.markets</a>, grab your Paper Trading API keys, and add them to <code>.env</code>.
        </div>
      </div>
    );
  }

  const toggle = async () => {
    setBusy(true);
    await setWolfExecution({ enabled: !settings.enabled });
    await onChanged(); setBusy(false);
  };
  const reset = async () => {
    if (!window.confirm("Reset the paper portfolio? All positions and trade history will be cleared.")) return;
    setBusy(true);
    await resetWolfPortfolio();
    await onChanged(); setBusy(false);
  };
  const sync = async () => {
    setBusy(true);
    await runWolfRiskCheck();
    await onChanged(); setBusy(false);
  };
  const setLossLimit = async (e) => {
    const v = parseFloat(e.target.value);
    if (!Number.isFinite(v)) return;
    setBusy(true);
    await setWolfExecution({ max_daily_loss_pct: v });
    await onChanged(); setBusy(false);
  };
  const setRiskPct = async (e) => {
    const v = parseFloat(e.target.value);
    if (!Number.isFinite(v)) return;
    setBusy(true);
    await setWolfExecution({ risk_pct: v });
    await onChanged(); setBusy(false);
  };
  const setMinGrade = async (e) => {
    setBusy(true);
    await setWolfExecution({ min_grade: e.target.value });
    await onChanged(); setBusy(false);
  };
  const setAllowShorts = async (e) => {
    setBusy(true);
    await setWolfExecution({ allow_shorts: e.target.checked });
    await onChanged(); setBusy(false);
  };
  const setMaxNew = async (e) => {
    const v = parseInt(e.target.value, 10);
    if (!Number.isFinite(v)) return;
    setBusy(true);
    await setWolfExecution({ max_new_trades_per_day: v });
    await onChanged(); setBusy(false);
  };
  const setOneTrade = async (e) => {
    setBusy(true);
    await setWolfExecution({ one_trade_per_symbol: e.target.checked });
    await onChanged(); setBusy(false);
  };
  const setMinRR = async (e) => {
    const v = parseFloat(e.target.value);
    if (!Number.isFinite(v)) return;
    setBusy(true);
    await setWolfExecution({ min_rr: v });
    await onChanged(); setBusy(false);
  };

  return (
    <div style={{ padding: 0 }}>
      {/* Two tiers, not one row of seven peers. What arms the broker (the
          auto-execute switch) and what talks to it (sync, reset) are decisions
          you make now; the four risk gates are settings you tune once and read
          back later. Flattened together they all wore 11px semibold and the
          switch that lets an agent place orders looked like a number field. */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <SectionTitle sub="real fills via Alpaca paper trading · virtual capital">Paper Trading Portfolio</SectionTitle>
        <div style={{ flex: 1 }} />
        <button onClick={toggle} disabled={busy}
          aria-pressed={!!settings.enabled}
          title={settings.enabled
            ? "Alpha Wolf is placing orders against the paper account on every run"
            : "Alpha Wolf will plan but not place any orders"}
          style={{
            fontSize: 12, fontWeight: 800, padding: "7px 14px", borderRadius: 9, cursor: "pointer",
            border: `1px solid ${settings.enabled ? T.green : T.line}`,
            background: settings.enabled ? T.green + "1c" : T.line2,
            color: settings.enabled ? T.green : T.ink3 }}>
          {settings.enabled ? "● Auto-execute ON" : "○ Auto-execute OFF"}
        </button>
        <button onClick={sync} disabled={busy} title="Reconcile against live Alpaca positions — picks up trades closed directly in Alpaca or via a hit stop/target" style={{
          fontSize: 11, fontWeight: 700, padding: "6px 12px", borderRadius: 8, cursor: "pointer",
          border: `1px solid ${T.line}`, background: T.card, color: T.ink3 }}>
          ⟳ Sync with Alpaca
        </button>
        {/* Reset wipes every position and the whole trade history. It read as
            the twin of Sync; it is the one destructive control on the tab. */}
        <button onClick={reset} disabled={busy} title="Clear all positions and trade history — cannot be undone" style={{
          fontSize: 11, fontWeight: 700, padding: "6px 12px", borderRadius: 8, cursor: "pointer",
          border: `1px solid ${T.red}44`, background: T.card, color: T.red }}>
          Reset
        </button>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 14,
        padding: "8px 12px", borderRadius: 10, background: T.cardAlt, border: `1px solid ${T.line}` }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.6 }}>
          Risk gates
        </span>
        <RiskField label="Risk/trade" suffix="%" width={54} step="0.05" min="0.05" max="10"
          value={settings.risk_pct ?? 0.5} onCommit={setRiskPct} disabled={busy}
          title="Equity risked per trade on the entry→stop distance. Position size is derived from this, capped by the per-position concentration limit." />
        <RiskField label="Daily loss limit" suffix="%" width={54} step="0.5" min="0.5" max="50"
          value={settings.max_daily_loss_pct ?? 3} onCommit={setLossLimit} disabled={busy}
          title="Once the day is down this much, the circuit breaker blocks new entries until tomorrow." />
        <label title="The funnel's own grade for the setup. This replaced a 1-10 confidence score the model gave its own ideas, which over 100 live trades predicted nothing (grade 8: -$2,030; grade 9: +$1,010)."
          style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, color: T.ink2 }}>
          Min grade
          <select value={settings.min_grade ?? "B"} onChange={setMinGrade} disabled={busy}
            style={{ fontSize: 11.5, fontFamily: T.mono, padding: "2px 4px", borderRadius: 6,
                     border: `1px solid ${T.line}`, background: T.card, color: T.ink,
                     accentColor: purple(), cursor: "pointer" }}>
            {["A+", "A", "B", "C"].map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
        <RiskField label="Min R:R" width={50} step="0.1" min="1" max="10"
          value={settings.min_rr ?? 2.0} onCommit={setMinRR} disabled={busy}
          title="Quality gate: cards whose reward/risk (entry→target vs entry→stop) is below this don't trade." />
        <RiskField label="New trades/day" width={44} step="1" min="1" max="20"
          value={settings.max_new_trades_per_day ?? 3} onCommit={setMaxNew} disabled={busy}
          title="Hard ceiling on NEW positions opened in one session. The first account opened four correlated shorts in the same minute; those same-minute baskets lost $1,912 of its $2,331." />
        <label title="Shorts are OFF by default. On the first account the short side was 38 of 100 trades and -$2,160 of the -$2,331 — the long side was roughly flat. Turn this on only once the long side shows positive expectancy over a real sample."
          style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5,
                   color: settings.allow_shorts ? T.red : T.ink2, cursor: "pointer" }}>
          <input type="checkbox" checked={!!settings.allow_shorts}
            onChange={setAllowShorts} disabled={busy} style={{ accentColor: T.red, cursor: "pointer" }} />
          Allow shorts
        </label>
        <label title="One entry per symbol per session. The funnel re-runs every 30 minutes and its verdict changes with the tape — without this, a name that filled at 14:00 can be closed and reversed at 15:51, and a stop-out becomes an invitation to re-enter an hour later."
          style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, color: T.ink2, cursor: "pointer" }}>
          <input type="checkbox" checked={settings.one_trade_per_symbol !== false}
            onChange={setOneTrade} disabled={busy} style={{ accentColor: purple(), cursor: "pointer" }} />
          One trade per symbol / session
        </label>
        <span style={{ fontSize: 10.5, color: T.ink4, marginLeft: "auto" }}>saved on blur · applies to the next run</span>
      </div>

      <SyncStrip sync={syncInfo} pendingCount={pending_entries.length} />

      {daily_breaker?.tripped && (
        <div style={{ marginBottom: 14, padding: "10px 14px", borderRadius: 10, background: T.redBg, border: `1px solid ${T.red}44`, fontSize: 12.5, color: T.red, fontWeight: 600, lineHeight: 1.5 }}>
          <Ico name="stop" size={13} style={{ display: "inline", verticalAlign: "-2px", marginRight: 5 }} />Daily loss circuit breaker tripped — down {daily_breaker.daily_pnl_pct}% today (limit -{daily_breaker.max_daily_loss_pct}%). No new entries until tomorrow; open positions still exit normally on stop/target.
        </div>
      )}

      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 16 }}>
        <Stat label="Equity" value={fmt$(summary.equity)} />
        <Stat label="Cash" value={fmt$(summary.cash)} />
        <Stat label="Unrealized P&L" value={fmt$(summary.unrealized_pnl)} color={pnlColor(summary.unrealized_pnl)} />
        <Stat label="Realized P&L" value={fmt$(summary.realized_pnl)} color={pnlColor(summary.realized_pnl)} />
        <Stat label="Return" value={`${(summary.return_pct ?? 0) >= 0 ? "+" : ""}${summary.return_pct ?? 0}%`} color={pnlColor(summary.return_pct)} />
        {daily_breaker && <Stat label="Today's P&L" value={`${daily_breaker.daily_pnl_pct >= 0 ? "+" : ""}${daily_breaker.daily_pnl_pct}%`} color={pnlColor(daily_breaker.daily_pnl_pct)} />}
      </div>

      <PendingEntries pending={pending_entries} onChanged={onChanged} />

      <div style={{ fontSize: 11.5, fontWeight: 700, color: T.ink3, marginBottom: 6 }}>Open positions ({positions.length})</div>
      {positions.length > 0 ? (
        <div style={{ ...wrapSt, marginBottom: 14 }}>
          <table style={tableSt()}>
            <thead>
              <tr>
                {["Ticker", "Dir", "Shares", "Entry", "Stop", "Target", "Last", "Stop ⟷ Target", "R", "P&L", "Held"].map((h, i) => (
                  <th key={h} style={{ ...thSt((i >= 2 && i <= 6) || i === 8 || i === 9 ? "right" : "left"), whiteSpace: "nowrap"  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const r = positionR(p);
                const held = holdDays(p.entry_date);
                const maxHold = settings.max_hold_days ?? 10;
                const beMoved = p.initial_stop != null && p.stop != null && p.stop !== p.initial_stop;
                return (
                  <tr key={p.ticker} style={{ borderBottom: RULE() }}>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), fontFamily: T.mono, fontWeight: 800, color: T.ink }}>{p.ticker}</td>
                    <td style={{ padding: "3px 7px", borderRight: RULE() }}>
                      <span style={{ fontSize: 9.5, fontWeight: 800, color: dirColor(p.direction), background: dirColor(p.direction) + "16", padding: "2px 7px", borderRadius: 4, textTransform: "uppercase" }}>{p.direction}</span>
                    </td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono }}>{p.shares}</td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono }}>{fmt$(p.entry_price)}</td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, color: T.red, whiteSpace: "nowrap" }}>
                      {p.stop ? fmt$(p.stop) : "—"}
                      {beMoved && <span title={`stop tightened from ${fmt$(p.initial_stop)} (breakeven/trail)`} style={{ marginLeft: 4, fontSize: 9, color: T.green, fontWeight: 800 }}>🛡</span>}
                    </td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, color: T.green }}>{p.target ? fmt$(p.target) : "—"}</td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono }}>{fmt$(p.last_price)}</td>
                    <td style={{ padding: "3px 7px", borderRight: RULE() }}><StopTargetBar p={p} /></td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, fontWeight: 700, color: r == null ? T.ink4 : pnlColor(r) }}>
                      {r == null ? "—" : `${r >= 0 ? "+" : ""}${r.toFixed(1)}R`}
                    </td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, fontWeight: 800, color: pnlColor(p.pnl) }}>{(p.pnl ?? 0) >= 0 ? "+" : ""}{fmt$(p.pnl)}</td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), fontFamily: T.mono, color: held != null && held > maxHold * 0.8 ? T.amber : T.ink4, whiteSpace: "nowrap" }}
                        title={p.entry_date ? `opened ${p.entry_date} · auto-closes after ${maxHold}d` : undefined}>
                      {held != null ? `${held < 1 ? "<1" : Math.floor(held)}d / ${maxHold}d` : p.entry_date || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ fontSize: 12.5, color: T.ink4, marginBottom: 16 }}>No open positions — run the plan to put capital to work.</div>
      )}

      {trades.length > 0 && (
        <Collapsible id="alphawolf-recent-trades" title="Recent trades" sub={`${trades.length} logged`}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {trades.slice(0, 10).map((t, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 0", borderBottom: i < Math.min(trades.length, 10) - 1 ? `1px solid ${T.line2}` : "none", fontSize: 12 }}>
                <ActionPill action={t.action} />
                <span style={{ fontFamily: T.mono, fontWeight: 800, color: T.ink }}>{t.ticker}</span>
                <span style={{ color: T.ink3, fontFamily: T.mono }}>{t.shares} sh @ {fmt$(t.price)}</span>
                {t.pnl != null && <span style={{ fontFamily: T.mono, fontWeight: 700, color: pnlColor(t.pnl) }}>{t.pnl >= 0 ? "+" : ""}{fmt$(t.pnl)}</span>}
                <span style={{ flex: 1, color: T.ink4, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.reason}</span>
                <span style={{ color: T.ink4, fontSize: 10.5, whiteSpace: "nowrap" }}>{t.ts}</span>
              </div>
            ))}
          </div>
        </Collapsible>
      )}
    </div>
  );
}

function PerformanceCard({ journal }) {
  const stats = journal?.stats || {};
  const rows = journal?.journal || [];
  if (!stats.trades) {
    return (
      <div>
        <SectionTitle sub="win rate · profit factor · closed-trade journal">Performance</SectionTitle>
        <div style={{ fontSize: 12.5, color: T.ink4, marginTop: 8 }}>
          No closed trades yet — stats appear once positions exit (plan rotation, stop, or target).
        </div>
      </div>
    );
  }
  const s = stats;
  const exits = s.by_exit || {};
  return (
    <div>
      <SectionTitle sub="closed paper trades · stops and targets enforced every 10 min in-session">Performance</SectionTitle>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", margin: "12px 0 14px" }}>
        <Stat label="Closed trades" value={s.trades} />
        <Stat label="Win rate" value={`${s.win_rate}%`} color={s.win_rate >= 50 ? T.green : T.red} />
        <Stat label="Total P&L" value={fmt$(s.total_pnl)} color={pnlColor(s.total_pnl)} />
        {s.expectancy_r != null && (
          <Stat label="Expectancy" value={`${s.expectancy_r >= 0 ? "+" : ""}${s.expectancy_r}R`} color={pnlColor(s.expectancy_r)} />
        )}
        {s.avg_win_r != null && <Stat label="Avg win (R)" value={`+${s.avg_win_r}R`} color={T.green} />}
        {s.avg_loss_r != null && <Stat label="Avg loss (R)" value={`${s.avg_loss_r}R`} color={T.red} />}
        <Stat label="Profit factor" value={s.profit_factor ?? "∞"} color={(s.profit_factor ?? 99) >= 1 ? T.green : T.red} />
        {s.avg_hold_days != null && <Stat label="Avg hold" value={`${s.avg_hold_days}d`} />}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {Object.entries(exits).map(([k, v]) => (
          <span key={k} style={{ fontSize: 11, padding: "3px 10px", borderRadius: 6, fontWeight: 600, background: T.line2, color: T.ink3 }}>
            {k === "stop" ? "stop exits" : k === "target" ? "target exits" : "plan rotations"}: {v.n} · <span style={{ fontFamily: T.mono, color: pnlColor(v.pnl) }}>{v.pnl >= 0 ? "+" : ""}{fmt$(v.pnl)}</span>
          </span>
        ))}
      </div>
      {Object.keys(s.by_grade || {}).length > 1 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 5 }}
            title="Does the funnel's grade predict outcomes? An A should win more often than a B — if it doesn't, the grading is noise. The LLM confidence score this replaced measured nothing: grade 8 lost $2,030 while grade 9 made $1,010.">
            Win rate by card grade
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {Object.entries(s.by_grade)
              .sort(([a], [b]) => ["A+", "A", "B", "C", "n/a"].indexOf(a) - ["A+", "A", "B", "C", "n/a"].indexOf(b))
              .map(([conf, v]) => {
                const wr = v.n ? Math.round((v.wins / v.n) * 100) : 0;
                return (
                  <span key={conf} style={{ fontSize: 11, padding: "3px 10px", borderRadius: 6, fontWeight: 600, background: T.line2, color: T.ink3 }}>
                    grade {conf === "n/a" ? "—" : conf}: {v.n} trade{v.n !== 1 ? "s" : ""} ·{" "}
                    <b style={{ color: wr >= 50 ? T.green : T.red }}>{wr}% win</b> ·{" "}
                    <span style={{ fontFamily: T.mono, color: pnlColor(v.pnl) }}>{v.pnl >= 0 ? "+" : ""}{fmt$(v.pnl)}</span>
                  </span>
                );
              })}
          </div>
        </div>
      )}
      <Collapsible id="alphawolf-closed-trades" title="Closed-trade journal" sub={`${rows.length} entries`}>
        <div style={wrapSt}>
          <table style={tableSt()}>
            <thead>
              <tr>
                {["Closed", "Ticker", "Dir", "Entry", "Exit", "P&L", "%", "R", "Hold", "Exit reason"].map((h, i) => (
                  <th key={h} style={{ ...thSt(i >= 3 && i <= 8 ? "right" : "left")  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 12).map((j, i) => (
                <tr key={i} style={{ borderBottom: RULE() }}>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), fontFamily: T.mono, color: T.ink4, whiteSpace: "nowrap" }}>{j.ts}</td>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), fontFamily: T.mono, fontWeight: 800 }}>{j.ticker}</td>
                  <td style={{ padding: "3px 7px", borderRight: RULE() }}>
                    <span style={{ fontSize: 9.5, fontWeight: 800, color: dirColor(j.direction), background: dirColor(j.direction) + "16", padding: "2px 7px", borderRadius: 4, textTransform: "uppercase" }}>{j.direction}</span>
                  </td>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono }}>{fmt$(j.entry_price)}</td>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono }}>{fmt$(j.exit_price)}</td>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, fontWeight: 800, color: pnlColor(j.pnl) }}>{j.pnl >= 0 ? "+" : ""}{fmt$(j.pnl)}</td>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, color: pnlColor(j.pnl_pct) }}>{j.pnl_pct >= 0 ? "+" : ""}{j.pnl_pct}%</td>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, fontWeight: 700, color: j.r_multiple == null ? T.ink4 : pnlColor(j.r_multiple) }}>
                    {j.r_multiple == null ? "—" : `${j.r_multiple >= 0 ? "+" : ""}${j.r_multiple}R`}
                  </td>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), textAlign: "right", fontFamily: T.mono, color: T.ink4 }}>{j.hold_days != null ? `${j.hold_days}d` : "—"}</td>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), color: T.ink3, fontSize: 11.5 }}>{j.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Collapsible>
    </div>
  );
}

// ── The funnel's board, as Alpha Wolf sees it ───────────────────────────────
// Every card Technologia computed, with the reason each one is or is not an
// idea in this plan. Before this existed the two tabs showed different worlds:
// Technologia listed the whole board, Alpha Wolf silently kept only the
// LONG/SHORT cards, and there was no way to tell a card the plan had REJECTED
// from one it had never been given.
const CARD_ACTION_COLOR = { LONG: () => T.green, SHORT: () => T.red, WAIT: () => T.amber };

function FunnelCards({ funnel }) {
  const cards = funnel?.cards || [];
  if (!cards.length) return null;
  // Age is computed HERE, from the run's own timestamp — not read from the
  // `age_min` the backend stamped at sync time. That number froze the moment it
  // was written, so a snapshot taken at 15:51 still read "cards 0m old" at
  // 22:51: the one line whose whole job is to tell you these levels are stale
  // was the line insisting they were fresh.
  // No stamp (a plan written before the field existed) means the age is
  // genuinely unknown — show WHEN the run was instead of a number that was only
  // true at the moment it was written. `age_min` is deliberately not used as a
  // fallback: it is frozen, so it would keep insisting the cards are fresh.
  const ageMin = funnel.generated_ts != null
    ? Math.max(0, Math.floor((Date.now() / 1000 - funnel.generated_ts) / 60))
    : null;
  const stale = ageMin != null && ageMin > 45;    // over a run and a half old
  const gated = cards.filter((c) => c.in_plan && c.gate).length;
  // Technologia latches the day's best card and keeps showing it after the
  // funnel has moved on. Saying so here is the difference between the two tabs
  // agreeing and the trader wondering where this morning's A+ setup went.
  const best = funnel.best_of_session;
  const bestCard = best?.symbol && cards.find((c) => c.symbol === best.symbol);
  const bestLive = !!bestCard?.in_plan;
  return (
    <Card pad={14}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <SectionTitle sub="the same board Technologia shows — and what this plan did with each card">
          Funnel cards
        </SectionTitle>
        {/* These four buckets add up to the table below, so a card count that
            disagrees with the Technologia tab always has an answer on screen. */}
        <Pill c={T.green}>{funnel.tradeable || 0} in the plan</Pill>
        {gated > 0 && <Pill c={T.amber} title="in the plan, but the broker declined the entry — reason on the row">{gated} gated</Pill>}
        <Pill c={T.amber}>{funnel.armed || 0} armed</Pill>
        <Pill c={T.ink4}>{funnel.stand_down || 0} standing down</Pill>
        {funnel.futures > 0 && <Pill c={T.ink4} title="/ES and /NQ are context — Alpaca can't trade futures">{funnel.futures} futures</Pill>}
        <Pill mono c={stale ? T.amber : T.ink3}
          title={`Technologia run ${funnel.generated_at || "—"} · folded into this plan ${funnel.synced_at || "—"}`}>
          {ageMin == null ? (funnel.generated_at ? `cards from ${funnel.generated_at}` : "card age unknown")
            : ageMin >= 60 ? `cards ${Math.floor(ageMin / 60)}h ${ageMin % 60}m old`
            : `cards ${ageMin}m old`}
        </Pill>
      </div>
      <div style={wrapSt}>
        <table style={tableSt()}>
          <thead>
            <tr>{["Symbol", "Card", "Zone", "Entry / Stop / T1", "In this plan"].map((h) => (
              <th key={h} style={thSt("left")}>{h}</th>))}</tr>
          </thead>
          <tbody>
            {cards.map((c, i) => {
              const ac = (CARD_ACTION_COLOR[c.action] || (() => T.ink4))();
              return (
                <tr key={`${c.symbol}-${i}`} style={{ borderBottom: RULE(),
                  background: c.in_plan ? ac + "0d" : "transparent" }}>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), fontFamily: T.mono, fontWeight: 800, color: T.ink }}>
                    {txt(c.label || c.symbol)}
                  </td>
                  <td style={{ padding: "3px 7px", borderRight: RULE() }}>
                    <span title={c.why} style={{ fontSize: 9, fontWeight: 800, color: ac, background: ac + "16",
                      padding: "2px 7px", borderRadius: 4 }}>
                      {txt(c.action).replace("_", " ")}{c.grade && c.grade !== "NONE" ? ` ${c.grade}` : ""}
                    </span>
                  </td>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), fontFamily: T.mono, fontSize: 10.5, color: T.ink3 }}>
                    {c.zone ? <span title={`${c.confluence ?? "?"}-point confluence`}>{txt(c.zone)}</span>
                            : <span style={{ color: T.ink4 }}>—</span>}
                  </td>
                  <td style={{ padding: "3px 7px", borderRight: RULE(), fontFamily: T.mono, fontSize: 10.5 }}>
                    {c.entry != null
                      ? <span><b style={{ color: T.ink }}>{txt(c.entry)}</b> <span style={{ color: T.ink4 }}>/</span> {txt(c.stop)} <span style={{ color: T.ink4 }}>/</span> {txt(c.target)}{c.rr ? <span style={{ color: T.ink4 }}> · {c.rr}R</span> : null}</span>
                      : <span style={{ color: T.ink4 }}>—</span>}
                  </td>
                  {/* A tick means the plan is carrying this trade. A card the
                      broker refused is NOT that, and marking it with the same
                      symbol as a working idea is how a rejection reads as a
                      success at a glance. */}
                  <td style={{ padding: "3px 7px", borderRight: RULE(), fontSize: 11,
                    color: c.gate ? T.amber : c.in_plan ? T.green : T.ink3,
                    minWidth: 220, whiteSpace: "normal", lineHeight: 1.4 }}>
                    {c.gate ? "! " : c.in_plan ? "\u2713 " : "\u00b7 "}
                    {txt(c.gate
                      || (c.in_plan ? "in the plan"
                        : c.action === "WAIT" ? "armed — waiting on a trigger"
                        : c.action === "STAND_DOWN" ? "standing down"
                        : "context only — futures aren't routed to the broker"))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {best?.symbol && (
        <div style={{ fontSize: 11.5, color: bestLive ? T.green : T.ink3, marginTop: 8, lineHeight: 1.5 }}>
          {bestLive ? "★" : "☆"} Best card of the session — <b style={{ fontFamily: T.mono }}>{txt(best.label || best.symbol)}</b> at {txt(best.at)}
          {bestLive ? " — still live in this plan."
            : bestCard ? ` — now ${txt(bestCard.action).toLowerCase().replace("_", " ")}.`
            : " — the funnel has since retired it, so this plan no longer carries it."}
        </div>
      )}
      {(funnel.coverage?.missing || []).length > 0 && (
        <div style={{ fontSize: 11, color: T.amber, marginTop: 8 }}>
          <Ico name="warn" size={12} style={{ display: "inline", verticalAlign: "-2px", marginRight: 4 }} />Price data covered {funnel.coverage.returned}/{funnel.coverage.requested} symbols —
          a missing card here may be missing data, not a quiet tape.
        </div>
      )}
    </Card>
  );
}

function PlanBlock({ title, plan, currentIdx }) {
  const ideas = plan?.ideas || [];
  return (
    <div style={{ padding: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <SectionTitle sub="today's actionable read">{title}</SectionTitle>
        <BiasPill bias={plan?.bias} />
      </div>
      {plan?.summary && <div style={{ fontSize: 13, color: T.ink2, lineHeight: 1.55, marginBottom: 12 }}>{txt(plan.summary)}</div>}
      {ideas.length > 0 ? (
        <div style={wrapSt}>
          <table style={tableSt()}>
            <thead>
              <tr>
                {["Ticker", "Dir", "Levels", "Trigger", "Thesis & Risk"].map((h) => (
                  <th key={h} style={{ ...thSt("left")  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ideas.map((idea, i) => {
                const dc = dirColor(idea.direction);
                return (
                  <tr key={i} style={{ borderBottom: RULE() }}>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), fontFamily: T.mono, fontWeight: 800, color: T.ink, verticalAlign: "top" }}>
                      {txt(idea.ticker)}<br/>
                      {idea.when && <span style={{ fontSize: 9.5, fontWeight: 700, color: T.ink4, marginTop: 4, display: "inline-flex", alignItems: "center", gap: 3 }}><Ico name="clock" size={10} />{txt(idea.when)}</span>}
                    </td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), verticalAlign: "top" }}>
                      <span style={{ fontSize: 9, fontWeight: 800, color: dc, background: dc + "16", padding: "2px 7px", borderRadius: 4, textTransform: "uppercase" }}>{txt(idea.direction) || "n/a"}</span>
                    </td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), fontSize: 11, fontFamily: T.mono, verticalAlign: "top", whiteSpace: "nowrap" }}>
                      <div><span style={{ color: T.ink4, fontSize: 9.5 }}>ENT</span> {txt(idea.entry)}</div>
                      <div><span style={{ color: T.ink4, fontSize: 9.5 }}>TGT</span> {txt(idea.target)}</div>
                      <div><span style={{ color: T.ink4, fontSize: 9.5 }}>STP</span> {txt(idea.stop)}</div>
                    </td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), fontSize: 11.5, color: T.ink2, verticalAlign: "top", minWidth: 150, maxWidth: 200, whiteSpace: "normal" }}>
                      {txt(idea.trigger)}
                    </td>
                    <td style={{ padding: "3px 7px", borderRight: RULE(), fontSize: 11.5, color: T.ink3, lineHeight: 1.45, verticalAlign: "top", minWidth: 250, whiteSpace: "normal" }}>
                      <div style={{ color: T.ink2, marginBottom: 4 }}>{txt(idea.thesis)}</div>
                      {idea.risk && <div style={{ fontSize: 10.5 }}><b style={{ color: T.ink4 }}>RISK:</b> {txt(idea.risk)}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ fontSize: 12.5, color: T.ink4 }}>No specific ideas this run.</div>
      )}
    </div>
  );
}

export default function AlphaWolf({ status, agentError }) {
  const { data, refresh, error: dataError } = useAgentData("alpha_wolf");
  const [refreshing, setRefreshing] = useState(false);
  const [portfolio, setPortfolio] = useState(null);
  const [journal, setJournal] = useState(null);
  const [nowData, setNowData] = useState(null);
  const [nowError, setNowError] = useState(null);
  const plan = data?.plan || null;
  const busy = refreshing || status === "running";

  // Both polls share one in-flight guard apiece. /now walks every plan ticker
  // through a live quote fetch and the portfolio call reaches Alpaca; when
  // either runs slower than its interval the old code just stacked another
  // request on top, and a backend having a bad minute got hammered by the tab
  // that was waiting on it.
  const portfolioBusy = useRef(false);
  const refreshPortfolio = useCallback(async () => {
    if (portfolioBusy.current) return;
    portfolioBusy.current = true;
    // Independent endpoints — no reason for the journal to wait on the
    // portfolio round trip.
    const [p, j] = await Promise.allSettled([getWolfPortfolio(), getWolfJournal()]);
    if (p.status === "fulfilled") setPortfolio(p.value);
    if (j.status === "fulfilled") setJournal(j.value);
    portfolioBusy.current = false;
  }, []);

  // Live "what to do right now" — market clock + ideas scored vs live quotes
  const nowBusy = useRef(false);
  const refreshNow = useCallback(async () => {
    if (nowBusy.current) return;
    nowBusy.current = true;
    try { setNowData(await getWolfNow()); setNowError(null); }
    catch (e) { setNowError(e); }   // was swallowed — which is why an offline
                                    // backend showed blank chrome and no reason
    finally { nowBusy.current = false; }
  }, []);

  // One timer drives both polls at their own cadence, and it stops while the
  // tab is hidden: this page polls the broker every 15s and live quotes every
  // 60s forever, so a backgrounded tab left open overnight was thousands of
  // pointless upstream quote fetches. Coming back refreshes immediately, so
  // what you see on return is current rather than however old the last poll is.
  useEffect(() => {
    let ticks = 0;
    // `force` means "we need data on screen now" — the first paint and the
    // return from a hidden tab. It must NOT consult document.hidden: some
    // embedded and headless contexts report the page hidden even while it is
    // being rendered, and gating the *initial* fetch on that left the tab
    // showing its loading line forever.
    const tick = (force = false) => {
      if (!force && document.hidden) return;
      refreshPortfolio();
      if (force || ticks % 4 === 0) refreshNow();
      ticks++;
    };
    tick(true);
    const id = setInterval(tick, 15000);
    const onVis = () => { if (!document.hidden) { ticks = 0; tick(true); } };
    document.addEventListener("visibilitychange", onVis);
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", onVis); };
  }, [refreshPortfolio, refreshNow]);

  // A run kicks off five delayed refetches. Unmounting the tab before the last
  // one fired left them all pending — they still fired, still hit the backend,
  // and still called setState on a component that was gone.
  const timers = useRef([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  const run = async () => {
    setRefreshing(true);
    await triggerAgent("alpha_wolf");
    timers.current.forEach(clearTimeout);
    timers.current = [
      setTimeout(refresh, 8000), setTimeout(refresh, 20000), setTimeout(refresh, 35000),
      setTimeout(refreshPortfolio, 20000), setTimeout(refreshPortfolio, 36000),
      setTimeout(() => setRefreshing(false), 3000),
    ];
  };

  // Intersect with the current pack: an older stored plan can still name a
  // retired agent, which would otherwise read as 7/6.
  const sourcesUsed = (plan?.sources_used || []).filter((id) => ALL_SOURCES.includes(id));

  return (
    <div>
      <TabHeader icon={<Ico name="wolf" size={19} />} color={purple()} title="Alpha Wolf"
        sub="Master strategist · fuses the pack into a Daily + Weekly plan and executes it (paper)"
        actions={<>
          <Pill mono c={T.ink3} title="Synthesized once at 08:30 ET, then re-synced with Technologia's cards every 30 min through the session">
            08:30 · synced 30m
          </Pill>
          {/* The pack used to also get its own collapsible Card lower down,
              repeating this exact count over two chips. With a two-agent pack
              that was a whole card to say "both". The names and the synthesis
              time live on the pill now. */}
          {plan && (
            <Pill c={purple()} bg={purpleBg()}
              title={ALL_SOURCES.map((id) => `${sourcesUsed.includes(id) ? "●" : "○"} ${SOURCE_LABELS[id]}`).join("  ")
                + (plan.generated_at ? `\nSynthesized ${plan.generated_at}` : "")}>
              {sourcesUsed.length}/{ALL_SOURCES.length} agents
            </Pill>
          )}
          <EmailPreviewButton agentId="alpha_wolf" label="Preview plan email" />
          <AgentControls agentId="alpha_wolf" onRun={run} busy={busy} refresh={refresh} runLabel="Run plan" runningLabel="Synthesizing…" />
        </>}
      />
      <div className="om-page om-stagger">
        <ErrorBanner error={agentError} />
        <ErrorBanner error={dataError} kind="data" onRetry={refresh} />

        {/* The clock, the bias and "what do I do right now" are one thought,
            so they are one card. They used to be two Cards rendered
            unconditionally around components that return null until /now
            answers — which painted two empty white bars on every cold load,
            every backend restart and every failed poll. */}
        {nowData?.clock ? (
          <Card pad={16}>
            <StaleBanner error={nowError} onRetry={refreshNow} />
            <SessionBanner now={nowData} />
            <RightNowBlock now={nowData} />
          </Card>
        ) : (
          <LiveStatus error={nowError} onRetry={refreshNow} />
        )}

        {portfolio && (
          <Card pad={14}>
            <PortfolioCard portfolio={portfolio} onChanged={refreshPortfolio} />
          </Card>
        )}

        {journal && (
          <Card pad={14}>
            <PerformanceCard journal={journal} />
          </Card>
        )}

        {/* Execution report from the latest run */}
        {plan?.execution && (
          plan.execution.enabled === false ? (
            <Card pad={14}>
              <div style={{ fontSize: 12.5, color: T.ink3 }}>⏸ {plan.execution.note || "Trade execution was OFF for the last run."}</div>
            </Card>
          ) : ((plan.execution.executed || []).length > 0
               || (plan.execution.skipped || []).length > 0) && (
            <Card pad={14}>
              {(plan.execution.executed || []).length > 0 && (<>
                <div style={{ fontSize: 12, fontWeight: 800, color: T.green, marginBottom: 8 }}>
                  <Ico name="bolt" size={13} style={{ display: "inline", verticalAlign: "-2px", marginRight: 5 }} />Executed {plan.execution.executed.length} trade{plan.execution.executed.length !== 1 ? "s" : ""} on the last run
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {plan.execution.executed.map((t, i) => (
                    <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5,
                      border: `1px solid ${T.line}`, borderRadius: 8, padding: "4px 10px", background: T.card }}>
                      <ActionPill action={t.action} />
                      <b style={{ fontFamily: T.mono }}>{t.ticker}</b>
                      <span style={{ color: T.ink3, fontFamily: T.mono }}>{t.shares} sh @ {fmt$(t.price)}</span>
                    </span>
                  ))}
                </div>
              </>)}
              {/* Everything the run did NOT do, and why. This was computed and
                  stored on every run and rendered nowhere: an order rejected by
                  the broker, or an idea the gate refused, simply failed to
                  appear and the trader was left comparing a plan against an
                  empty account with no explanation in between. */}
              {(plan.execution.skipped || []).length > 0 && (
                <Collapsible id="alphawolf-skipped"
                  title={`Not taken — ${plan.execution.skipped.length}`}
                  sub="orders the gate refused or the broker rejected, with the reason">
                  <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
                    {plan.execution.skipped.map((o, i) => {
                      const rejected = /reject|fail|error/i.test(String(o.why || ""));
                      return (
                        <div key={i} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 11.5,
                          lineHeight: 1.45, paddingBottom: 6, borderBottom: i < plan.execution.skipped.length - 1 ? RULE() : "none" }}>
                          <b style={{ fontFamily: T.mono, minWidth: 54, color: T.ink }}>{txt(o.ticker) || "—"}</b>
                          <span style={{ fontSize: 9.5, fontWeight: 800, textTransform: "uppercase",
                            color: rejected ? T.red : T.ink4, minWidth: 44 }}>{txt(o.action)}</span>
                          <span style={{ color: rejected ? T.red : T.ink3, whiteSpace: "normal" }}>{txt(o.why)}</span>
                        </div>
                      );
                    })}
                  </div>
                </Collapsible>
              )}
            </Card>
          )
        )}

        {!plan ? (
          <EmptyState icon={<Ico name="wolf" size={26} />} title="No game-plan yet"
            hint="Run the sub-agents (Wolf, Technologia), then click 'Run plan'." />
        ) : (<>

          <FunnelCards funnel={plan.funnel} />

          {/* Everything below the action strip is background: the reasoning
              that produced those rows, not a second set of instructions. It
              stays one click away rather than on screen, because reading it
              while deciding is how five clear rows turned into a wall. */}
          <Card pad={14}>
            <Collapsible id="alphawolf-thinking" title="Today's thinking"
              sub="stance · regime · confluence · the full plan table"
              right={<StancePill stance={plan.stance} />}>

              {plan.headline && (
                <div style={{ fontSize: 14, fontWeight: 800, color: purple(), lineHeight: 1.4, margin: "10px 0 4px" }}>
                  {txt(plan.headline)}
                </div>
              )}

              {plan.regime && (
                <div style={{ display: "flex", gap: 14, marginTop: 12 }}>
                  <LufiAvatar size={38} />
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 5 }}>Market regime <span style={{ fontSize: 11, color: T.ink4 }}>by Alpha Wolf</span></div>
                    <div style={{ fontSize: 13.5, color: purple(), lineHeight: 1.55 }}>{txt(plan.regime)}</div>
                  </div>
                </div>
              )}

              {(plan.confluence || []).length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <SectionTitle sub="where multiple agents line up — highest conviction">Confluence</SectionTitle>
                  <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, color: T.ink2, lineHeight: 1.7 }}>
                    {plan.confluence.map((c, i) => <li key={i}>{txt(c)}</li>)}
                  </ul>
                </div>
              )}

              <div style={{ marginTop: 18 }}>
                <PlanBlock title="Daily Plan" plan={plan.daily} />
              </div>
            </Collapsible>
          </Card>

          {/* Disclaimer */}
          <div style={{ fontSize: 11, color: T.ink4, lineHeight: 1.5, padding: "0 4px" }}>{txt(plan.disclaimer)}</div>
        </>)}
      </div>
    </div>
  );
}
