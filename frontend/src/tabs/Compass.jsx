// ============================================================================
// Compass.jsx — market bias engine + key support/resistance levels.
// ============================================================================
import { useState } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar } from "../components/Common";

const biasColor = (b) => (b === "bull" ? T.green : b === "bear" ? T.red : "#94a3b8");
const biasLabel = (b) => (b === "bull" ? "Bullish" : b === "bear" ? "Bearish" : "Neutral");

function BiasMeter({ score, h = 10 }) {
  const pos = (score + 100) / 2;
  const col = score > 15 ? T.green : score < -15 ? T.red : "#94a3b8";
  return (
    <div style={{ position: "relative", height: h, borderRadius: h, background: T.trackGrad, marginTop: 6 }}>
      <div style={{ position: "absolute", left: `calc(${pos}% - ${h}px)`, top: -2, width: h + 4, height: h + 4, borderRadius: "50%", background: T.card, border: `3px solid ${col}`, boxShadow: "0 1px 4px rgba(0,0,0,.15)" }} />
    </div>
  );
}

function SectorRow({ s }) {
  const col = s.bias > 15 ? T.green : s.bias < -15 ? T.red : "#94a3b8";
  return (
    <div style={{ padding: "8px 0", borderBottom: `1px solid ${T.line2}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, width: 110 }}>{s.k}</span>
        <div style={{ flex: 1 }}><BiasMeter score={s.bias} /></div>
        <span style={{ fontFamily: T.mono, fontSize: 12, fontWeight: 700, color: col, width: 48, textAlign: "right" }}>{s.bias > 0 ? "+" : ""}{s.bias}</span>
      </div>
      {s.why && <div style={{ fontSize: 11, color: T.ink3, marginTop: 3, marginLeft: 120 }}>{s.why}</div>}
    </div>
  );
}

function LevelLadder({ f }) {
  const ticks = [
    { k: "R2", v: f.r2, c: T.red }, { k: "R1", v: f.r1, c: T.red },
    { k: "Pivot", v: f.piv, c: "#94a3b8" },
    { k: "S1", v: f.s1, c: T.green }, { k: "S2", v: f.s2, c: T.green },
  ].filter((t) => t.v != null);
  const min = f.s2 ?? f.s1, max = f.r2 ?? f.r1, span = (max - min) || 1;
  const y = (v) => 100 - ((v - min) / span) * 100;
  return (
    <Card pad={16}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: T.mono }}>{f.t}</div>
          <div style={{ fontSize: 11, color: T.ink3 }}>{f.n}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: T.mono, fontSize: 17, fontWeight: 700 }}>{f.px.toLocaleString()}</div>
          <span style={{ fontSize: 11, fontWeight: 700, color: biasColor(f.bias) }}>{biasLabel(f.bias)} bias</span>
        </div>
      </div>
      <div style={{ position: "relative", height: 112, marginLeft: 6 }}>
        <div style={{ position: "absolute", left: 44, top: 0, bottom: 0, width: 2, background: T.line }} />
        {ticks.map((t) => (
          <div key={t.k} style={{ position: "absolute", left: 0, right: 0, top: `calc(${y(t.v)}% - 8px)`, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 36, textAlign: "right", fontFamily: T.mono, fontSize: 9.5, fontWeight: 700, color: t.c }}>{t.k}</span>
            <span style={{ width: 9, height: 9, borderRadius: 9, background: T.card, border: `2px solid ${t.c}`, flex: "0 0 auto" }} />
            <span style={{ flex: 1, height: 1, borderTop: `1px dashed ${t.c}55` }} />
            <span style={{ fontFamily: T.mono, fontSize: 11, color: T.ink2 }}>{t.v.toLocaleString()}</span>
          </div>
        ))}
        <div style={{ position: "absolute", left: 40, right: 0, top: `calc(${y(f.px)}% - 9px)`, display: "flex", alignItems: "center" }}>
          <span style={{ background: biasColor(f.bias), color: "#fff", fontFamily: T.mono, fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 5, boxShadow: "0 1px 4px rgba(0,0,0,.18)" }}>▸ {f.px.toLocaleString()}</span>
          <span style={{ flex: 1, height: 2, background: biasColor(f.bias) }} />
        </div>
      </div>
    </Card>
  );
}

export default function Compass({ status, agentError }) {
  const { data, refresh } = useAgentData("compass");
  const [running, setRunning] = useState(false);
  const c = data?.compass || {};
  const sectors = c.sectors || [];
  const news = c.news || [];
  const futures = c.futures || [];
  const levels = c.levels || [];
  const vix = c.vix;
  const empty = !sectors.length && !news.length && !futures.length && !levels.length;
  const overall = c.composite ?? (sectors.length ? Math.round(sectors.reduce((a, s) => a + s.bias, 0) / sectors.length) : 0);
  const read = c.read;
  // Plain-English market tone (replaces jargon "Risk-On / Risk-Off / Mixed").
  const toneWord = overall > 15 ? "Bullish" : overall < -15 ? "Bearish" : "Neutral";
  const toneDesc = overall > 15 ? "Risk appetite — buyers in control"
    : overall < -15 ? "Defensive — money rotating to safety"
    : "Range-bound — no clear edge";
  const toneCol = overall > 15 ? T.green : overall < -15 ? T.red : "#64748b";

  const sentChip = (s) => {
    const map = { bull: [T.green, T.greenBg, "Bullish"], bear: [T.red, T.redBg, "Bearish"], neutral: ["#64748b", "#f1f5f9", "Neutral"] };
    const [col, bg, t] = map[s] || map.neutral;
    return <span style={{ fontSize: 10.5, fontWeight: 700, color: col, background: bg, padding: "3px 8px", borderRadius: 6 }}>{t}</span>;
  };

  const run = async () => {
    setRunning(true);
    await triggerAgent("compass");
    setTimeout(refresh, 6000); setTimeout(refresh, 15000);
    setTimeout(() => setRunning(false), 2000);
  };
  const busy = running || status === "running";

  return (
    <div>
      <TabHeader icon="◎" color={T.amber} title="Wallstreet Compass" sub="Market bias engine + key levels · pre-market brief"
        actions={<>
          <Pill mono c={T.ink3}>brief 07:00 daily</Pill>
          <EmailPreviewButton agentId="compass" label="Preview brief" />
          <AgentControls agentId="compass" onRun={run} busy={busy} refresh={refresh} runLabel="Run analysis" runningLabel="Analyzing…" />
        </>} />
      <div className="om-stagger" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 11 }}>
        <ErrorBanner error={agentError} />
        {empty ? (
          <EmptyState icon="◎" title="No analysis yet"
            hint="Click Run analysis to compute sector bias, pivot key levels for /ES, /NQ & the 10 majors, and a Qwen3 read." />
        ) : (
        <>
        <Card pad={16} style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 20, alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 12, color: T.ink3, fontWeight: 600 }}>Today's composite bias</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 2 }}>
              <span style={{ fontSize: 30, fontWeight: 800, letterSpacing: -1.2, color: toneCol }}>{toneWord}</span>
            </div>
            <div style={{ fontSize: 12, color: T.ink3, marginTop: 2, fontWeight: 600 }}>{toneDesc}</div>
            <div style={{ marginTop: 8 }}><BiasMeter score={overall} h={12} /></div>
            <div style={{ display: "flex", justifyContent: "space-between", fontFamily: T.mono, fontSize: 10.5, color: T.ink4, marginTop: 5 }}><span>BEARISH</span><span>{overall > 0 ? "+" : ""}{overall}</span><span>BULLISH</span></div>
            {vix && (
              <div style={{ marginTop: 10 }}>
                <Pill mono c={vix.regime === "Elevated" ? T.red : vix.regime === "Low" ? T.green : T.amber}
                  bg={vix.regime === "Elevated" ? T.redBg : vix.regime === "Low" ? T.greenBg : T.amberBg}>
                  VIX {vix.level} · {vix.regime} ({vix.change > 0 ? "+" : ""}{vix.change})
                </Pill>
              </div>
            )}
          </div>
          <div style={{ borderLeft: `1px solid ${T.line2}`, paddingLeft: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <LufiAvatar size={26} />
              <span style={{ fontSize: 13, fontWeight: 800, letterSpacing: -0.2 }}>Lufi's read</span>
              <Pill mono c={T.violet} bg={T.violetBg} style={{ padding: "2px 7px" }}>Qwen3</Pill>
            </div>
            <div style={{ fontSize: 13, color: T.ink2, lineHeight: 1.55, whiteSpace: "pre-line" }}>
              {read || "Run analysis to fetch live sector ETF moves, compute pivot-based key levels for /ES, /NQ and the 10 majors, and have Qwen3 write today's directional read."}
            </div>
          </div>
        </Card>

        <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 16, alignItems: "start" }}>
          <Card pad={15}>
            <SectionTitle sub="Directional lean by sector (−100 to +100)">Sector bias</SectionTitle>
            {sectors.map((s) => <SectorRow key={s.k} s={s} />)}
          </Card>
          <Card pad={15}>
            <SectionTitle sub="LLM-scored headlines driving today's read" right={<Pill mono c={T.ink3}>live feed</Pill>}>News sentiment</SectionTitle>
            {news.map((n, i) => (
              <div key={i} style={{ padding: "8px 0", borderBottom: i < news.length - 1 ? `1px solid ${T.line2}` : "none" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                  <span style={{ fontSize: 10.5, fontWeight: 700, color: T.ink2, fontFamily: T.mono }}>{n.src}</span>
                  <span style={{ fontSize: 10, color: T.ink4, fontFamily: T.mono }}>{n.min}</span>
                  <span style={{ marginLeft: "auto" }}>{sentChip(n.s)}</span>
                </div>
                <div style={{ fontSize: 12.5, color: T.ink, lineHeight: 1.4 }}>{n.t}</div>
              </div>
            ))}
          </Card>
        </div>

        <div>
          <SectionTitle sub="Intraday support & resistance · pivot-based">Key levels — Futures</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {futures.map((f) => <LevelLadder key={f.t} f={f} />)}
          </div>
        </div>

        <Card pad={15}>
          <SectionTitle sub="Pivot · R1 · S1 for the 10 majors">Key levels — Stocks</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "1.3fr repeat(4, 1fr) 90px", padding: "8px 6px", fontSize: 10.5, color: T.ink4, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, borderBottom: `1px solid ${T.line2}` }}>
            <span>Symbol</span><span style={{ textAlign: "right" }}>Last</span><span style={{ textAlign: "right" }}>Pivot</span><span style={{ textAlign: "right" }}>R1</span><span style={{ textAlign: "right" }}>S1</span><span style={{ textAlign: "right" }}>Bias</span>
          </div>
          {levels.map((l) => (
            <div key={l.t} style={{ display: "grid", gridTemplateColumns: "1.3fr repeat(4, 1fr) 90px", padding: "9px 6px", alignItems: "center", borderBottom: `1px solid ${T.line2}`, fontFamily: T.mono, fontSize: 12.5 }}>
              <span style={{ fontWeight: 700, fontFamily: T.sans }}>{l.t}</span>
              <span style={{ textAlign: "right", fontWeight: 600 }}>{l.px.toLocaleString()}</span>
              <span style={{ textAlign: "right", color: T.ink3 }}>{l.piv.toLocaleString()}</span>
              <span style={{ textAlign: "right", color: T.red }}>{l.r1.toLocaleString()}</span>
              <span style={{ textAlign: "right", color: T.green }}>{l.s1.toLocaleString()}</span>
              <span style={{ textAlign: "right" }}><span style={{ fontSize: 10.5, fontFamily: T.sans, fontWeight: 700, color: biasColor(l.bias), background: biasColor(l.bias) + "18", padding: "3px 8px", borderRadius: 6 }}>{biasLabel(l.bias)}</span></span>
            </div>
          ))}
        </Card>
        </>
        )}
      </div>
    </div>
  );
}
