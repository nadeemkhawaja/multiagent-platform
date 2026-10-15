# The Playbook

One page. What the platform computes, in what order, and what you do with it at
each point in the session.

---

## The one structural idea

The old stack asked three questions in parallel and got three answers that
disagreed. This one asks four questions in sequence, and **each stage can only
narrow what the last one allowed**.

```
1. CONTEXT   what kind of day is this?      → which playbook is legal
2. LOCATION  where would I act?             → the zone (POI)
3. TRIGGER   what must happen first?        → sweep-and-reclaim, or a structure shift
4. RISK      what does the trade cost?      → entry, stop, T1/T2, R
```

If stage 1 says UNDECIDED, there is no stage 2. If the zone is 3 ATR away, there
is no stage 3. **A card only exists when all four agree**, which is why most
symbols on most days correctly produce nothing.

| Stage | Code | Output |
|---|---|---|
| Context | [auction.py](../backend/tools/auction.py) `day_context` | `TREND_UP` · `TREND_DOWN` · `BALANCE` · `UNDECIDED` |
| Location | [playbook.py](../backend/tools/playbook.py) `points_of_interest` | ranked zones with a confluence weight |
| Trigger | [smc.py](../backend/tools/smc.py) + `trigger_state` | `NONE` · `ARMED` · `TRIGGERED` |
| Risk | `trade_card` | `LONG`/`SHORT`/`WAIT`/`STAND_DOWN`, graded A/B/C |

---

## Stage 1 — Context

Computed from the auction, not from an indicator: the opening type, whether the
initial balance was extended, where the session opened relative to yesterday's
value area, and where price is accepted against session VWAP.

| Context | What you may do | What you may **not** do |
|---|---|---|
| **TREND_UP** | buy pullbacks into support zones | short anything, fade strength |
| **TREND_DOWN** | sell rallies into resistance zones | buy anything, catch knives |
| **BALANCE** | fade the *edges* back toward the POC | trade breakouts, trade the middle |
| **UNDECIDED** | nothing | everything |

This is the stage that fixes the deepest flaw in the old model. The bias score
added "price above VWAP" (+1, momentum) to "MFI overbought" (−1, mean reversion)
and netted zero — so a strong trend, the easiest day to trade, read *neutral*.
Momentum and reversion aren't ends of one axis. They're different playbooks for
different days.

**Opening types** (Dalton, and what EminiPlayer's morning plan is built on):

- **Open Drive** — one way from the bell, never looks back. Highest conviction.
- **Open Test Drive** — probes the other way, rejects it, then drives. High.
- **Open Rejection Reverse** — drives, gets rejected, reverses *through* the open. Medium.
- **Open Auction** — rotating around the open, nobody in control. Lowest.

---

## Stage 2 — Location (the POI)

A point of interest is **not** an indicator reading. It's a price band where
several *independent* methods land on the same number. Confluence is the
weighted sum of what's in the band:

| Weight 3 | Weight 2 | Weight 1 |
|---|---|---|
| naked POC, prior VAH/VAL/POC | PDH, PDL, session VWAP/POC/VAH/VAL, IB high/low, overnight high/low, order block, FVG | swing levels, prior close |

A **naked POC** — a prior session's point of control price hasn't returned to —
carries the most weight for a reason: everyone who positioned around it is still
waiting, so the first revisit reliably produces a reaction.

**A zone is capped at 0.40 × intraday ATR wide.** Without the cap, chained
clustering produces one "zone" spanning both the prior-day high and low, and a
zone that contains everything locates nothing.

---

## Stage 3 — Trigger

**Touching a level is not a signal.** One of these must happen first:

- **Sweep and reclaim** — price wicks *through* the zone, finds no continuation,
  and closes back on the original side. This is the mechanical form of the rule
  the platform already stated in prose: the first breakout is usually a
  liquidity grab; trade the reversal, not the breakout.
- **Structure shift (MSS/BOS)** — a close through the swing that created the
  pullback, at or near the zone.

States: `ARMED` (in the zone, unconfirmed — a resting limit is legal, a market
order is not) → `TRIGGERED` (act).

---

## Stage 4 — Risk

- **Entry** — the trigger bar's close if TRIGGERED, otherwise a resting limit at
  the zone's near edge.
- **Stop** — beyond the zone's *far* edge plus 0.15 ATR, floored at one full
  intraday ATR. Anything tighter is inside the noise, gets taken by the spread,
  and inflates every R downstream. The card says so when the floor applied.
- **T1 / T2** — the next liquidity magnets (other people's levels), never round
  multiples of risk, capped at 2.5 daily ATR so a target is reachable today.
- **Minimum 1.3R to T1**, or there is no trade.
- **Grades** — **A**: ≥5 confluence, ≥2R, and the name is genuinely in play
  (2× relative volume). **B**: a good ordinary setup. **C**: armed, not triggered.

---

## The daily routine

All times ET.

| Window | What you do |
|---|---|
| **08:00–09:15** | **Prep.** Run Technologia. Read prior-day levels, prior value area, naked POCs, overnight range. Mark the zones **before** the open — this is the single habit that separates the source framework from screen-staring. |
| **09:30–09:45** | **Watch. Do not trade.** The opening range is where stops get taken. Let the opening type declare itself. |
| **09:45–10:30** | Initial balance forms. Context firms up. Cards go from UNDECIDED to a real label. Note which zones price is approaching. |
| **10:30–11:55** | **The window.** A-grade cards only. For /ES and /NQ this is the *only* window the framework endorses. |
| **11:55–14:00** | Lunch. Liquidity thins, ranges compress, and reversion signals lie. No new risk. Manage what's open. |
| **14:00–15:30** | Second window. B-grade allowed **only if the day is trending** — a balance-day fade this late has no time to work. |
| **15:30–15:45** | Stop initiating. Take T1 partials. |
| **15:45** | **Flat on intraday positions.** Enforced in code. Every level that opened the trade — session VWAP, session profile, IB, context — is rebuilt from scratch tomorrow, so holding overnight keeps the risk and discards the reason for it. |
| **15:50** | Unfilled entry orders cancelled. Tomorrow's plan re-decides from scratch. |

### Exit management (in code, not just documented)

1. **+1R** → stop to breakeven.
2. **+1.5R** → trail behind the last swing low/high, with an ATR envelope as
   fallback. A fixed ATR trail sits wherever volatility puts it, often
   mid-consolidation where the rotation that the trend is pausing in sweeps it.
   The last swing is the level whose break actually means the trend is over.
3. **15:45** → flat.

---

## What the platform will not do for you

- **Catalyst is never auto-verified.** There is no per-ticker news feed. An
  A-grade card on a stock with no reason to move today is a pattern, not a trade.
- **VSA and CVD are approximations.** No tick or bid/ask data, so "buy volume"
  is inferred from where a bar closed in its range. Treat them as the weakest
  two inputs.
- **/ES and /NQ never reach the broker.** Alpaca has no futures. They are
  context only.
- **The funnel vetoes, it does not originate.** Alpha Wolf's LLM plan still
  proposes trades; the computed card refuses the two cases it can be sure about
  (wrong side of the auction, below the liquidity floor). A missing card never
  blocks anything.

## Verified Alpaca constraints

Checked read-only against the live paper account:

- Account ACTIVE, shorting enabled, 4× multiplier. All 24 watchlist symbols are
  `tradable`, `shortable`, `easy_to_borrow` and `fractionable`.
- Paper accounts don't track `pattern_day_trader` / `daytrade_count`, so the PDT
  rule won't bite here — it will on a funded account under $25k.
- Brackets are GTC (day-TIF legs get cancelled at the close, leaving overnight
  positions naked). Extended hours are **not** supported on brackets, and stop
  and market orders don't exist pre/post-market — only limit orders do.
- Fractional orders can't be GTC, which is why sizing stays in whole shares.
