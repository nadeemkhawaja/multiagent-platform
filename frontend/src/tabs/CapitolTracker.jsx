// ============================================================================
// CapitolTracker.jsx — Congressional Stock Disclosure Monitor
// Party filter · politician drill-down · date range · performance chart
// ============================================================================
import { useState, useMemo } from "react";
import { T } from "../theme/tokens";
import { Card, Pill, SectionTitle, TabHeader } from "../theme/ui";
import { useAgentData, triggerAgent } from "../state/api";
import { EmailPreviewButton, ErrorBanner, EmptyState, AgentControls, LufiAvatar } from "../components/Common";

const RED = "#dc2626"; const RED_BG = "#fef2f2";
const GREEN = "#16a34a"; const GREEN_BG = "#f0fdf4";
const AMBER = "#d97706"; const AMBER_BG = "#fffbeb";
const BLUE = "#2563eb"; const BLUE_BG = "#eff6ff";
const VIOLET = "#7c5cf6";

const CHAMBER_COLOR = { House: "#2563eb", Senate: "#7c5cf6", Executive: "#dc2626" };
const TYPE_BUY_WORDS = ["purchase", "buy", "exercise", "calls", "call"];
const TYPE_SELL_WORDS = ["sale", "sell", "sold"];

// Client-side party lookup (D = Democrat, R = Republican)
const PARTY_LOOKUP = {
  "Pelosi": "D", "Gottheimer": "D", "Khanna": "D", "Blumenthal": "D",
  "Cisneros": "D", "Fields": "D", "Suozzi": "D", "Doggett": "D",
  "Lee": "D", "Walberg": "R", "Moore": "R", "Cruz": "R",
  "McClain": "R", "Boozman": "R", "Romney": "R", "Tuberville": "R",
  "Crenshaw": "R", "McCaul": "R", "McCormick": "R", "Issa": "R",
  "Shreve": "R", "Ricketts": "R", "Greene": "R", "Trump": "R",
};
function partyOf(name = "") {
  for (const [k, v] of Object.entries(PARTY_LOOKUP)) {
    if (name.toLowerCase().includes(k.toLowerCase())) return v;
  }
  return null;
}
const PARTY_COLOR = { R: RED, D: BLUE, Index: "#6b7280" };
const PARTY_BG = { R: RED_BG, D: BLUE_BG };

function tradeColor(type = "") {
  const t = type.toLowerCase();
  if (TYPE_BUY_WORDS.some((w) => t.includes(w))) return GREEN;
  if (TYPE_SELL_WORDS.some((w) => t.includes(w))) return RED;
  return AMBER;
}
function tradeBg(type = "") {
  const t = type.toLowerCase();
  if (TYPE_BUY_WORDS.some((w) => t.includes(w))) return GREEN_BG;
  if (TYPE_SELL_WORDS.some((w) => t.includes(w))) return RED_BG;
  return AMBER_BG;
}

function StatCard({ label, value, sub, color = T.ink }) {
  return (
    <Card pad={18} style={{ textAlign: "center" }}>
      <div style={{ fontSize: 28, fontWeight: 800, fontFamily: T.mono, color, letterSpacing: -1 }}>{value}</div>
      <div style={{ fontSize: 13, fontWeight: 700, marginTop: 2 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: T.ink4, marginTop: 2 }}>{sub}</div>}
    </Card>
  );
}

function PartyBadge({ party }) {
  if (!party) return null;
  const col = PARTY_COLOR[party] || T.ink4;
  const bg = PARTY_BG[party] || T.cardAlt;
  return <span style={{ fontSize: 9.5, fontWeight: 800, color: col, background: bg, padding: "2px 6px", borderRadius: 4, letterSpacing: 0.3 }}>{party}</span>;
}

function TradeRow({ t, idx, onPoliticianClick }) {
  const tc = tradeColor(t.type);
  const tb = tradeBg(t.type);
  const cc = CHAMBER_COLOR[t.chamber] || T.ink3;
  const party = partyOf(t.politician);

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "28px 160px 68px 1fr 140px 110px 110px 110px",
      gap: 10, alignItems: "center",
      padding: "11px 20px",
      borderBottom: `1px solid ${T.line2}`,
      background: idx % 2 === 0 ? "transparent" : T.cardAlt + "55",
      transition: "background .12s",
    }}>
      <span style={{ fontSize: 11, color: T.ink4, fontFamily: T.mono }}>{idx + 1}</span>

      {/* Politician + party */}
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <button onClick={() => onPoliticianClick(t.politician)} style={{ fontSize: 12.5, fontWeight: 700, background: "none", border: "none", padding: 0, cursor: "pointer", color: T.ink, textAlign: "left", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 110, fontFamily: T.sans }}>
            {t.politician}
          </button>
          <PartyBadge party={party} />
        </div>
        {t.holder && t.holder !== t.politician && (
          <div style={{ fontSize: 10, color: T.ink4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.holder}</div>
        )}
      </div>

      <span style={{ fontSize: 10.5, fontWeight: 700, color: cc, background: cc + "18", padding: "3px 8px", borderRadius: 5, textAlign: "center", whiteSpace: "nowrap" }}>{t.chamber}</span>

      <div style={{ minWidth: 0 }}>
        <span style={{ fontSize: 13, fontWeight: 800, fontFamily: T.mono, color: T.ink }}>{t.ticker || "—"}</span>
        {t.asset && t.ticker !== t.asset && (
          <span style={{ fontSize: 10.5, color: T.ink4, marginLeft: 7 }}>{t.asset.slice(0, 30)}{t.asset.length > 30 ? "…" : ""}</span>
        )}
      </div>

      <span style={{ fontSize: 11, fontWeight: 700, color: tc, background: tb, padding: "4px 10px", borderRadius: 6, whiteSpace: "nowrap", textAlign: "center" }}>
        {t.type || "—"}
      </span>

      <span style={{ fontSize: 11.5, fontFamily: T.mono, fontWeight: 600, textAlign: "right", color: T.ink2 }}>{t.amount || "—"}</span>

      <div style={{ textAlign: "right" }}>
        {t.estimated_avg_price && t.estimated_avg_price !== "N/A (Private)" && t.estimated_avg_price !== "" ? (
          <>
            <div style={{ fontSize: 12.5, fontWeight: 700, fontFamily: T.mono, color: tc }}>{t.estimated_avg_price}</div>
            <div style={{ fontSize: 9.5, color: T.ink4, fontFamily: T.mono }}>avg est.</div>
          </>
        ) : <span style={{ fontSize: 11, color: T.ink4 }}>—</span>}
      </div>

      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 11.5, fontFamily: T.mono, color: T.ink2 }}>{t.transaction_date}</div>
        {t.disclosure_date && (
          <div style={{ fontSize: 9.5, color: T.ink4 }}>disclosed {t.disclosure_date.slice(0, 10)}</div>
        )}
      </div>
    </div>
  );
}

function TableHeader() {
  const s = { fontSize: 10, fontWeight: 700, color: T.ink4, textTransform: "uppercase", letterSpacing: 0.4 };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "28px 160px 68px 1fr 140px 110px 110px 110px", gap: 10, padding: "10px 20px", borderBottom: `1px solid ${T.line}`, background: T.cardAlt }}>
      <span style={s}>#</span><span style={s}>Politician</span><span style={s}>Chamber</span>
      <span style={s}>Asset</span><span style={s}>Type</span>
      <span style={{ ...s, textAlign: "right" }}>Amount</span>
      <span style={{ ...s, textAlign: "right" }}>Est. Price</span>
      <span style={{ ...s, textAlign: "right" }}>Tx Date</span>
    </div>
  );
}

function PerformanceBar({ item, maxReturn, onClick }) {
  const isIndex = item.party === "Index";
  const pct = Math.min(100, (item.return_pct / maxReturn) * 88);
  const color = PARTY_COLOR[item.party] || "#6b7280";
  return (
    <div onClick={onClick} style={{ display: "flex", alignItems: "center", gap: 12, padding: "7px 0", borderBottom: `1px solid ${T.line2}`, cursor: isIndex ? "default" : "pointer" }}>
      <div style={{ width: 180, fontSize: 12, fontWeight: isIndex ? 700 : 600, color: isIndex ? T.ink3 : T.ink, textAlign: "right", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", flexShrink: 0 }}>
        {item.name.replace("Rep. ", "").replace("Sen. ", "")}
      </div>
      <PartyBadge party={item.party} />
      <div style={{ flex: 1, height: 18, background: T.line2, borderRadius: 4, overflow: "hidden", position: "relative" }}>
        <div style={{ width: pct + "%", height: "100%", background: isIndex ? "#9ca3af" : color, borderRadius: 4, transition: "width .4s ease", opacity: isIndex ? 0.6 : 1 }} />
      </div>
      <span style={{ fontSize: 12.5, fontWeight: 700, fontFamily: T.mono, color, width: 52, textAlign: "right", flexShrink: 0 }}>+{item.return_pct}%</span>
    </div>
  );
}

function FilterBtn({ label, active, onClick, color }) {
  const c = color || T.violet;
  return (
    <button onClick={onClick} style={{
      padding: "5px 14px", borderRadius: 7,
      border: `1px solid ${active ? c : T.line}`,
      background: active ? c : "transparent",
      color: active ? "#fff" : T.ink2,
      fontWeight: 600, fontSize: 12, cursor: "pointer", fontFamily: T.sans,
    }}>{label}</button>
  );
}

export default function CapitolTracker({ status, agentError }) {
  const { data, refresh } = useAgentData("capitol_tracker");
  const [refreshing, setRefreshing] = useState(false);
  const [typeFilter, setTypeFilter] = useState("all");
  const [partyFilter, setPartyFilter] = useState("all");   // all | D | R
  const [polFilter, setPolFilter] = useState(null);         // politician name or null
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const payload = data?.tracker || null;
  const trades = payload?.trades || [];
  const stats = payload?.stats || {};
  const commentary = payload?.commentary || "";
  const politicians = payload?.politicians || [];
  const months = payload?.months || 2;
  const since = payload?.since || "";
  const perfRankings = payload?.performance_rankings || [];
  const sp500 = payload?.sp500_2025 || 16.6;
  const maxReturn = Math.max(...perfRankings.map((r) => r.return_pct), sp500, 1);

  // Count trades per politician for chips
  const polCounts = useMemo(() => {
    const c = {};
    trades.forEach((t) => { c[t.politician] = (c[t.politician] || 0) + 1; });
    return c;
  }, [trades]);

  // Multi-filter pipeline
  const filtered = useMemo(() => {
    return trades.filter((t) => {
      const ty = t.type.toLowerCase();
      const party = partyOf(t.politician);

      if (typeFilter === "purchase" && !TYPE_BUY_WORDS.some((w) => ty.includes(w))) return false;
      if (typeFilter === "sale" && !TYPE_SELL_WORDS.some((w) => ty.includes(w))) return false;
      if (typeFilter === "exercise" && !ty.includes("exercise") && !ty.includes("call")) return false;
      if (partyFilter !== "all" && party !== partyFilter) return false;
      if (polFilter && t.politician !== polFilter) return false;
      if (dateFrom && t.transaction_date < dateFrom) return false;
      if (dateTo && t.transaction_date > dateTo) return false;
      return true;
    });
  }, [trades, typeFilter, partyFilter, polFilter, dateFrom, dateTo]);

  const clearFilters = () => { setTypeFilter("all"); setPartyFilter("all"); setPolFilter(null); setDateFrom(""); setDateTo(""); };
  const anyFilter = typeFilter !== "all" || partyFilter !== "all" || polFilter || dateFrom || dateTo;

  const run = async () => {
    setRefreshing(true);
    await triggerAgent("capitol_tracker");
    setTimeout(refresh, 6000); setTimeout(refresh, 14000);
    setTimeout(() => setRefreshing(false), 2000);
  };
  const busy = refreshing || status === "running";

  // Unique active politicians in current filtered results
  const activePols = [...new Set(trades.map((t) => t.politician))];

  return (
    <div>
      <TabHeader icon="🏛" color={RED} title="Capitol Tracker"
        sub={`STOCK Act disclosures · last ${months} months · ${trades.length} trades`}
        actions={<>
          <Pill mono c={T.ink3}>daily · 07:00</Pill>
          {stats.total > 0 && <>
            <Pill c={GREEN} bg={GREEN_BG}>{stats.purchases} purchases</Pill>
            <Pill c={RED} bg={RED_BG}>{stats.sales} sales</Pill>
          </>}
          <EmailPreviewButton agentId="capitol_tracker" label="Preview digest" />
          <AgentControls agentId="capitol_tracker" onRun={run} busy={busy} refresh={refresh} runLabel="Refresh" runningLabel="Fetching…" />
        </>}
      />

      <div style={{ padding: 28, display: "flex", flexDirection: "column", gap: 20 }}>
        <ErrorBanner error={agentError} />

        {trades.length === 0 ? (
          <EmptyState icon="🏛" title="No disclosure data yet"
            hint="Click 'Refresh' to fetch STOCK Act filings from House and Senate public APIs." />
        ) : (<>

          {/* Stats */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
            <StatCard label="Total Trades" value={stats.total || 0} sub={`last ${months} months`} color={RED} />
            <StatCard label="Purchases" value={stats.purchases || 0} sub="options + shares" color={GREEN} />
            <StatCard label="Sales" value={stats.sales || 0} sub="all sale types" color={RED} />
            <StatCard label="Politicians" value={stats.politicians_found || 0} sub="with activity" color={VIOLET} />
          </div>

          {/* Commentary */}
          {commentary && (
            <Card pad={20} style={{ background: T.cardAlt }}>
              <div style={{ display: "flex", gap: 14 }}>
                <LufiAvatar size={38} />
                <div>
                  <div style={{ fontSize: 13.5, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
                    Analyst Commentary <span style={{ fontSize: 11.5, fontWeight: 600, color: T.ink4 }}>by Lufi</span>
                    <Pill mono c={VIOLET} bg={VIOLET + "1a"}>Qwen3</Pill>
                  </div>
                  <div style={{ fontSize: 13, color: T.ink2, lineHeight: 1.55, marginTop: 6, maxWidth: 920, whiteSpace: "pre-line" }}>{commentary}</div>
                </div>
              </div>
            </Card>
          )}

          {/* Politician chips — clickable drill-down */}
          {activePols.length > 0 && (
            <div>
              <SectionTitle sub={`Click a name to filter · tracking since ${since}`}>Politicians tracked</SectionTitle>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
                {activePols.map((name) => {
                  const party = partyOf(name);
                  const active = polFilter === name;
                  const pc = party ? PARTY_COLOR[party] : RED;
                  return (
                    <button key={name} onClick={() => setPolFilter(active ? null : name)} style={{
                      display: "inline-flex", alignItems: "center", gap: 6,
                      background: active ? pc : T.card,
                      border: `1px solid ${active ? pc : T.line}`,
                      borderRadius: 8, padding: "5px 12px", fontSize: 12.5, fontWeight: 600,
                      cursor: "pointer", color: active ? "#fff" : T.ink, fontFamily: T.sans,
                      transition: "all .14s",
                    }}>
                      <span style={{ fontSize: 11 }}>🏛</span>
                      {name.replace("Rep. ", "").replace("Sen. ", "")}
                      {party && <PartyBadge party={party} />}
                      {polCounts[name] > 0 && (
                        <span style={{ fontSize: 10.5, fontFamily: T.mono, background: active ? "#ffffff30" : pc + "18", color: active ? "#fff" : pc, padding: "1px 6px", borderRadius: 5 }}>
                          {polCounts[name]}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Methodology note */}
          <Card pad={14} style={{ borderColor: AMBER + "44", background: AMBER_BG }}>
            <div style={{ fontSize: 11.5, color: "#92400e", lineHeight: 1.55 }}>
              <b>📊 Price methodology:</b> Estimated price = <span style={{ fontFamily: T.mono, background: "#fde68a", padding: "0 4px", borderRadius: 3 }}>(Market Open + Close) / 2</span> on the disclosed transaction date. STOCK Act requires disclosure within 45 days but does not require exact execution prices — only broad value-range tiers.
            </div>
          </Card>

          {/* Performance rankings */}
          {perfRankings.length > 0 && (
            <Card pad={20}>
              <SectionTitle sub={`2025 calendar year · S&P 500 baseline +${sp500}%`}>Congressional Trading Performance · 2025</SectionTitle>
              <div style={{ marginTop: 8 }}>
                {perfRankings.map((item) => (
                  <PerformanceBar key={item.name} item={item} maxReturn={maxReturn}
                    onClick={() => item.party !== "Index" && setPolFilter(polFilter === item.name ? null : item.name.replace("Rep. ", "").replace("Sen. ", ""))} />
                ))}
              </div>
              <div style={{ marginTop: 10, fontSize: 11, color: T.ink4 }}>
                32.2% of trading lawmakers outperformed the S&P 500 in 2025. Returns calculated using midpoint valuation assumption.
              </div>
            </Card>
          )}

          {/* Trade table with filters */}
          <Card pad={0} style={{ overflow: "hidden" }}>
            {/* Filter bar */}
            <div style={{ padding: "14px 20px", borderBottom: `1px solid ${T.line2}`, display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 700 }}>Disclosure Feed</div>
                <div style={{ fontSize: 11, color: T.ink4 }}>
                  {anyFilter ? `${filtered.length} of ${trades.length} trades` : `${trades.length} trades`} · House + Senate + Executive
                </div>
              </div>

              {/* Party filter */}
              <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                <span style={{ fontSize: 11, color: T.ink4, fontWeight: 600 }}>Party:</span>
                {["all", "D", "R"].map((p) => (
                  <FilterBtn key={p} label={p === "all" ? "All" : p} active={partyFilter === p}
                    onClick={() => setPartyFilter(p)}
                    color={p === "D" ? BLUE : p === "R" ? RED : T.violet} />
                ))}
              </div>

              {/* Type filter */}
              <div style={{ display: "flex", gap: 5 }}>
                {["all", "purchase", "sale", "exercise"].map((f) => (
                  <FilterBtn key={f} label={f === "all" ? "All types" : f} active={typeFilter === f}
                    onClick={() => setTypeFilter(f)} />
                ))}
              </div>

              {/* Date range */}
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{ fontSize: 11, color: T.ink4, fontWeight: 600 }}>From:</span>
                <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                  style={{ fontSize: 12, border: `1px solid ${T.line}`, borderRadius: 6, padding: "4px 8px", background: T.card, color: T.ink, fontFamily: T.mono }} />
                <span style={{ fontSize: 11, color: T.ink4 }}>To:</span>
                <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                  style={{ fontSize: 12, border: `1px solid ${T.line}`, borderRadius: 6, padding: "4px 8px", background: T.card, color: T.ink, fontFamily: T.mono }} />
              </div>

              {anyFilter && (
                <button onClick={clearFilters} style={{ fontSize: 11.5, color: RED, background: RED_BG, border: `1px solid ${RED}44`, borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontFamily: T.sans, fontWeight: 600 }}>
                  ✕ Clear filters
                </button>
              )}
            </div>

            <TableHeader />
            {filtered.length === 0 && (
              <div style={{ padding: 24, color: T.ink4, fontSize: 13 }}>No trades match the current filters.</div>
            )}
            {filtered.map((t, i) => (
              <TradeRow key={`${t.politician}-${t.ticker}-${t.transaction_date}-${i}`} t={t} idx={i}
                onPoliticianClick={(name) => setPolFilter(polFilter === name ? null : name)} />
            ))}
          </Card>

          <div style={{ fontSize: 11, color: T.ink4, textAlign: "center", lineHeight: 1.5 }}>
            Source: housestockwatcher.com & senatestockwatcher.com · STOCK Act public disclosures · educational use only.
          </div>
        </>)}
      </div>
    </div>
  );
}
