// ============================================================================
// tab-wolf.jsx — Wallstreet Wolf: gainers/losers/watchlist + FX/metals + LLM
// ============================================================================
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

function WolfTab() {
  const s = useSim();
  const sorted = [...s.watch].sort((a, b) => b.ch - a.ch);
  const gainers = sorted.slice(0, 5);
  const losers = sorted.slice(-5).reverse();
  const advancers = s.watch.filter((w) => w.ch >= 0).length;
  return (
    <div>
      <TabHeader icon="$" color={T.green} title="Wallstreet Wolf" sub="Yahoo Finance · 22-ticker watchlist · live + historical"
        actions={<>
          <Pill mono c={T.ink3}>brief 16:30 daily</Pill>
          <Pill c={advancers >= 11 ? T.green : T.red} bg={advancers >= 11 ? T.greenBg : T.redBg} bd={advancers >= 11 ? "#c7eed5" : "#f3b4b6"}>
            {advancers}/{s.watch.length} advancing
          </Pill>
        </>} />
      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>
        {/* LLM commentary */}
        <Card pad={20} style={{ background: T.cardAlt, borderColor: T.line }}>
          <div style={{ display: "flex", gap: 14 }}>
            <div style={{ width: 38, height: 38, borderRadius: 11, background: T.violetBg, color: T.violet, display: "grid", placeItems: "center", fontSize: 17, flex: "0 0 auto" }}>◇</div>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>Market commentary <Pill mono c={T.violet} bg={T.violetBg} style={{ padding: "2px 7px" }}>Qwen3</Pill></div>
              <div style={{ fontSize: 13, color: T.ink2, lineHeight: 1.55, marginTop: 6, textWrap: "pretty", maxWidth: 920 }}>
                Risk-on tone as semis lead — <b>NVDA</b>, <b>AMD</b> and <b>AVGO</b> pace gains on sustained AI-capex demand, lifting the tape. <b>COIN</b> and <b>PLTR</b> top the board on momentum. Weakness is idiosyncratic: <b>TSLA</b> and <b>UBER</b> lag on demand concerns rather than a broad rotation. Breadth is constructive ({advancers}/{s.watch.length} advancing); watch <b>/ES 5921</b> support into the payrolls print.
              </div>
            </div>
          </div>
        </Card>

        {/* Block 1/2/3 */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <MoverBlock title="Top 5 Gainers" list={gainers} accent={T.green} badge="Block 1" />
          <MoverBlock title="Top 5 Losers" list={losers} accent={T.red} badge="Block 2" />
        </div>

        <Card pad={20}>
          <SectionTitle sub="Full watchlist · live prices" right={<Pill mono c={T.ink3}>updating · 5s</Pill>}>Watchlist <span style={{ fontSize: 11, fontFamily: T.mono, color: T.ink4 }}>Block 3</span></SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "0 28px" }}>
            {s.watch.map((w) => (
              <div key={w.t} style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 12, alignItems: "center", padding: "9px 0", borderBottom: `1px solid ${T.line2}` }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
                  <span style={{ fontSize: 12.5, fontWeight: 700, width: 48 }}>{w.t}</span>
                  <span style={{ fontSize: 11, color: T.ink4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{w.n}</span>
                </div>
                <span style={{ fontFamily: T.mono, fontSize: 12.5, textAlign: "right" }}>{w.p.toFixed(2)}</span>
                <span style={{ fontFamily: T.mono, fontSize: 11.5, fontWeight: 700, color: w.ch >= 0 ? T.green : T.red, textAlign: "right", minWidth: 62 }}>{w.ch >= 0 ? "+" : ""}{w.ch.toFixed(2)}%</span>
              </div>
            ))}
          </div>
        </Card>

        {/* FX + metals */}
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 16 }}>
          <Card pad={18}>
            <SectionTitle sub="Major pairs">Currencies</SectionTitle>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
              {FX.map((f) => (
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
            {METALS.map((m) => (
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
      </div>
    </div>
  );
}

window.WolfTab = WolfTab;
