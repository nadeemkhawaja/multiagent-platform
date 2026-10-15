# Why this lost money — and what changed

Written 2026-10-15, from the 100 closed trades in the Alpha Wolf journal
(2026-07-26 → 2026-10-15) on the now-deleted Alpaca paper account.

## The headline

| | |
|---|---|
| Closed trades | 100 |
| Net P&L | **−$2,331.70** |
| Win rate | 26% |
| Average win | $195 |
| Average loss | $100 |
| Payoff | 1.95 : 1 |
| **Expectancy** | **−$23.32 per trade** |

At a 1.95:1 payoff the break-even win rate is **34%**. The system ran at 26%.
It was not unlucky — it was structurally negative, and more trades meant more
loss. 75 of 97 trades never reached +1R; 43 stopped out at a clean −1R.

## Where the money actually went

The loss is not spread evenly. Four cuts of the same 100 trades:

| Cut | Trades | P&L | Win rate |
|---|---|---|---|
| Shorts | 38 | **−$2,160** | 24% |
| Longs | 62 | −$171 | 27% |
| Pre-market entries (before 09:00 ET) | 16 | **−$1,391** | 38% |
| Opened in the same minute as another trade | 26 | **−$1,912** | 19% |
| **Pre-market shorts** | **7** | **−$1,506** | 14% |
| Longs, regular hours, one at a time | 40 | +$65 | 25% |

Read the last two rows together. **Seven pre-market short trades produced 65%
of the total loss.** And the cleanest subset of the strategy — one long at a
time, during the regular session — was flat over 40 trades.

That is the real finding: the edge was never there, but three specific
behaviours turned "flat and noisy" into "−$2,300".

### 1. The 08:30 cron placed real orders on pre-market bars
`alpha_wolf` runs at 08:30 ET. `execute_plan` only checked that it was a
weekday, never the time of day, so cards computed from one or two thin
pre-market bars became live bracket orders. 42 of 200 fills landed in the 08:00
hour. Session VWAP, the volume profile and the initial balance — every input
behind those cards — barely exist at 08:34.

### 2. Four correlated positions counted as four trades
`max_positions` was 8, and the plan opened whatever cleared the gate in one
pass: on 2026-10-15 that was AAPL, CSCO, GOOGL and PLTR, all short, all at
09:36, ~$9,800 each. That is one bet on the Nasdaq at 4× size, not four trades,
and the position sizer has no concept of correlation.

### 3. The LLM originated trades, and its confidence score was noise
Two things produced trade ideas: the deterministic funnel (auction context →
zone → trigger → risk) and the LLM's synthesis. The LLM's self-rated
`confidence` then gated execution at a floor of 6. It carried no information:

| Confidence | Trades | P&L |
|---|---|---|
| 8 | 48 | −$2,030 |
| 9 | 38 | +$1,010 |
| none (traded anyway) | 3 | −$1,149 |

A model scoring its own paraphrase of a computed card is not a risk control.
`CSCO short @ 109.41` — open at reset time — came from the LLM reading "RSI
45.2, below VWAP", not from a funnel card.

### 4. Stops were structural, but R was fiction when they were not
`MIN_STOP_ATR` floored the stop at 2× the *intraday median true range*, which on
a megacap is cents: GOOGL went on with entry 350.2336 and stop 350.23. One
NFLX short recorded a −20.84R loss against a two-cent stop. When R is the
denominator of every ratio the system trades off, a nonsense R produces
nonsense "1.95R to target" cards.

## What changed

Nothing here tries to invent an edge. It removes the ways the platform lost
money that had nothing to do with being right about direction, and it shrinks
the surface so the next 100 trades are actually measurable.

**Risk and execution**
- Entries only between **09:45 and 15:30 ET**. No pre-market, no last-half-hour
  entries. Closes, stop/target management and reconciliation are unaffected.
- **One new position at a time**, `max_positions` 8 → 2, and at most **3 new
  trades per day**. A second entry cannot be opened in the same minute as the
  first.
- **Long-only by default.** Shorts are a setting, off until the long side shows
  positive expectancy over a real sample.
- Stop floor is now the **daily** ATR (0.5×), not the intraday median, so R
  means something and a two-cent stop cannot be priced.
- First target must pay **2R** (was 1.3R), and only A/A+/B cards trade.

**Simplification — one source of truth**
- The LLM no longer originates, prices or gates trades. It writes the regime
  narrative; the funnel decides. `confidence` is gone from the risk settings.
- The funnel's cards are the only trade source, so Technologia and Alpha Wolf
  render the same board by construction. The reconciliation layer that existed
  to detect drift between the two tabs (`in_plan`, `plan_note`, `measured`,
  card diffing) is deleted along with the drift.
- The simulated-fill broker (`paper_broker.py`, 780 lines) is deleted. Alpaca is
  the only broker; its pure rules live in `broker_rules.py`.
- The two unused verdict engines (`vwap_ema_cross`, the full `decision_point`
  three-pillar screen) are gone. Only the participation metrics the liquidity
  floor needs survive, as `participation()`.
- The LLM-written session timeline is gone — with a fixed 09:45–15:30 entry
  window there is nothing for it to schedule.

## What to do next

1. The long side is unproven, not proven. Run it flat for a sample — 30+ trades
   — and read the expectancy before touching size or re-enabling shorts.
2. `risk_pct` is 0.5% of equity per trade. Leave it there. The concentration cap
   (`position_pct` 10%) is what actually bound size on most trades, which means
   stops were tight enough that risk-based sizing never engaged; wider stops now
   make the risk setting the real constraint.
3. Keep the journal. Everything in this review came out of it, and it is the
   only thing that can tell you whether a change helped.

## Verified on live data, 2026-10-15

Twelve megacaps through the rebuilt funnel:

```
AAPL   SHORT  A    entry 344.06  stop 346.63  T1 336.22  3.05R
                   risk $2.57 = 0.40 daily ATR, T1 is a real level (not a measured move)
CSCO   WAIT        "no real level pays 2R from 108.96 against the stop at 110.14"
MSFT   WAIT  C     armed at 539.14–539.32, waiting on a trigger
...                5 STAND_DOWN, 6 WAIT
```

One actionable card out of twelve, and the gate chain then refused even that one:

| Time | Verdict |
|---|---|
| 08:34 | refused — entries open at 9:45 ET |
| 11:00 | refused — shorts are off |
| 15:40 | refused — entries closed at 15:30 ET |
| 11:00, shorts on | 7 shares, $2,408 notional, **$18 at risk** |

Compare the two AAPL shorts. The one that traded on the old account had a $1.09
stop — 0.17 daily ATR, inside the noise — against a target that was arithmetic
rather than a level. The one the rebuilt funnel produced has a $2.57 stop and a
first target somebody else's orders are actually resting at.

CSCO is the clearest result: it was an open losing position at reset time, taken
on an LLM thesis ("RSI 45.2, below VWAP"). It is now a WAIT, refused by the rule
that T1 must be a real level — the exact trade the old system manufactured a 2R
target to justify.

## What was deleted

| | |
|---|---|
| `paper_broker.py` | 780 lines — a complete second broker nothing called |
| `strategies.py` | 517 → 289 lines — two unused verdict engines removed |
| `agent13_alpha_wolf.py` | 1,504 → 1,313 lines — LLM level-parsing, the timeline, the merge |
| Reconciliation layer | `in_plan` measurement, `plan_note`, `measured`, card diffing |
| Settings | `min_confidence` — the score that predicted nothing |

Three verdict engines became one. Two brokers became one. Two sources of trade
ideas became one. The machinery that existed to detect disagreement between the
two tabs is gone along with the disagreement.
