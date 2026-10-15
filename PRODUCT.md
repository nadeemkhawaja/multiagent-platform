# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Single primary user: the owner.** One trader, on their own machine, running this as a
personal daily trading cockpit. There is no second audience with equal standing — no
graders, no teammates, no customers, no distribution.

The job: **decide what to do in the market right now.** They open the platform around the
trading session, read what the agent fleet gathered, and act on Alpha Wolf's live calls.
The first two things they need on opening the app: **where we are in the trading day**, and
**which way the market leans right now**. Everything else is detail behind those two.

Because the user is also the builder, they carry full context. The product does not need
to explain itself to a newcomer, and design should not spend space on onboarding,
tutorials, or self-justifying copy that a first-time visitor would need.

## Product Purpose

An orchestrator supervises a fleet of autonomous agents that pull real market and industry
data, reason over it with an LLM, persist the results, and surface them in one dashboard.
Alpha Wolf then fuses the trading agents' output into a single actionable game plan and
executes it against a paper account.

Success is a decision, not a dashboard view: the user leaves the app knowing what to do,
at what level, at what size, and when — or knowing to wait. A session where the user reads
everything and still has to assemble the call themselves is a failure.

## Positioning

The meaningfully different mechanism is **Alpha Wolf's "right now" engine.** Where a normal
dashboard shows data and leaves synthesis to the reader, Alpha Wolf takes the six trading
sub-agents' output plus live quotes and a live market clock, and scores every idea into a
present-tense state — WAIT / ACT NOW / STOPPED / TARGET HIT — anchored to a time-of-day
session schedule (pre-market → open → midday → power hour → close), with entry, stop,
target, and dollar position size attached. A pulse loop re-evaluates in-session and alerts
when a window opens or a level trips.

The fleet exists to feed that engine. Multi-source aggregation alone is commodity; the
committed, time-aware, level-anchored call is not.

## Operating Context

- **Desktop, during market hours.** Localhost on the owner's Mac, open alongside broker and
  charting windows during the session. This is the only confirmed usage context.
- **Not a mobile surface.** The user does not check it from a phone. Responsive work below
  desktop widths is not a product requirement — do not spend design budget defending it.
- Density and glanceability at desk size are the governing ergonomics: this competes for
  screen real estate with real trading tools and gets read in short glances under time
  pressure.
- Email digests exist and send (Morning Brief, Alpha Wolf pulse alerts), but the **app is
  the primary surface**; the user was explicit that email is not where the value lands.

## Capabilities and Constraints

**Stack.** FastAPI + APScheduler + SQLAlchemy/SQLite backend, WebSocket live state with
REST polling fallback, `psutil` telemetry. React 19 + Vite frontend, single-page, no UI
framework or component library — styling is inline via a mutable JS token object
(`frontend/src/theme/tokens.js`), not CSS files or utility classes.

**Live agent fleet (3), as implemented in code:**

| Agent | Role |
|---|---|
| `alpha_wolf` | Master decision agent — fuses the trading pack, live quotes, session clock and market bias; paper execution |
| `wallstreet_wolf` | The market desk: watchlist, gainers/losers, FX & metals **and** sector bias, VIX regime, pivot key levels for /ES, /NQ and the majors |
| `technologia` | Volume-profile / VWAP / MFI confluence scoring |

Everything that wasn't feeding a trading decision has been retired (AI-Times, Mailman,
Aegis, Capitol Tracker, Morning Brief, Options Flow, Earnings Calendar, GitHub Trending,
Cisco Pulse, Strategy Scout — the last of these because its headline "Enter Long / Stay
Put" verdict was synthesized from forum chatter with no price or position input, and never
reached the execution gates). Wallstreet Compass was not retired but **merged into
Wallstreet Wolf**: same data source, overlapping symbols, and Alpha Wolf recombined them
downstream regardless. Alpha Wolf is the landing tab; **Settings** is the only other view.

The orchestrator still runs underneath — scheduling, per-agent status, the auto-restart
watchdog, the single-permit LLM semaphore, resource telemetry and the event log, all served
through `/api/state` — but it no longer has a tab competing for attention.

**Platform primitives design must respect:**
- Human-in-the-loop **approvals** (`backend/approvals.py`) — agents can park a side effect
  for sign-off instead of executing it; approving dispatches the registered handler.
- Recency-based **agent memory** (`backend/memory.py`) — agents reference prior runs so
  output can say what changed since yesterday. Not semantic; there is no local embedding
  model in the stack.
- **Multi-provider LLM routing** — `anthropic` (default, `claude-opus-4-8`), `local`
  (any OpenAI-compatible server: vLLM/LM Studio at `LOCAL_LLM_BASE_URL`), `openai`, `grok`.
  Selectable globally and per-agent; keys come from env or the Settings UI.
- **Paper trading only.** Execution runs against Alpaca's paper API
  (`backend/alpaca_broker.py`), with a local fill simulator (`backend/paper_broker.py`) as
  the alternative. No live-money path exists and none is in scope.
- Every agent tab carries Run/Stop/Restart, an email-preview modal, error and progress
  banners, and empty states; a per-tab error boundary keeps one crashed tab from blanking
  the shell.

**Retired — do not preserve, do not design around:**
- The Assignment-2 academic rubric is **finished and no longer binding.** Demo mode, the
  "core/graded agents" subset (`CORE_AGENTS`), and the 7-requirement coverage framing are
  historical scaffolding, free to retire.
- `agent1_ai_times`, `agent2_mailman`, and `agent6_aegis` are deleted. README and
  DOCUMENTATION.md still describe them and still claim Qwen3-via-Ollama as the LLM — both
  documents are stale. **Trust the code over those files.**

**Explicitly undecided:** whether the Lufi persona, the local-first guarantee, and
light/dark parity remain permanent. See Brand Commitments.

## Brand Commitments

**Binding — the one non-negotiable the user confirmed:**

- **Alpha Wolf is the center of the product.** It is the master decision agent, and the
  sidebar hierarchy is literal: Alpha Wolf is the group header and the trading agents are
  its pack of sub-agents. No future design may demote it to a peer in a flat list of
  agents, and no restructure may break the master/sub-agent relationship.

**Present in the product but *not* locked by the user.** These are real, working, and
should not be broken casually — but the user declined to make them permanent, so a
well-argued redesign may change them:

- **Lufi**, the AI analyst persona: all LLM-written prose is attributed to her, with
  avatar and byline components in `frontend/src/components/Common.jsx`.
- **Local-first operation:** the platform can run entirely on the owner's machine against
  a local LLM with no cloud API keys. Note that the current shipped default is
  `AI_PROVIDER=anthropic`, so local-first is a capability, not the active configuration.
- **Light/dark parity** via the single mutable token object.

## Evidence on Hand

- Working software with real data sources — yfinance, GitHub REST, Dev.to, Yahoo RSS,
  Cisco PSIRT RSS, Alpaca paper API. Live telemetry is real `psutil` output.
- `orchestrator.db` (SQLite) holds real accumulated agent data, run history, resource
  samples, and config.
- Prior design source material: `design/prototype` and `design/BACKEND_HANDOFF.md`; three
  earlier direction mockups in `design-mockups/` (`1-polished.html`, `2-terminal.html`,
  `3-saas.html`); `architecture.mmd` / `architecture.png`.
- `frontend/src/assets/hero.png`; Lufi avatar SVG at `frontend/public/lufi.svg` with an
  automatic `/lufi.png` override.

**Absences future work must not fabricate:** there are no users, no testimonials, no
customers, no benchmarks, no pricing, no track record, and no live-money trading results.
Paper-trading P&L is paper-trading P&L and must always be labeled as such. No performance,
accuracy, or profitability claim may be invented for any surface.

## Product Principles

1. **End in a decision.** Every surface earns its space by moving the user toward act,
   wait, or exit. Data that informs no decision is a candidate for deletion.
2. **Alpha Wolf leads; the pack feeds it.** Hierarchy is product truth, not a nav
   convenience. Structure, prominence, and flow follow it.
3. **The session clock is a first-class dimension.** Pre-market, open, midday, power hour,
   and close are different states with different urgency. Time-blind presentation of
   time-sensitive calls is a defect.
4. **One expert reader, at speed.** Optimize for a user who already knows the system and is
   scanning under pressure. Density and precision beat explanation and reassurance.
5. **Never overstate certainty.** Paper is labeled paper, stale is labeled stale, and an
   agent that failed to run says so rather than showing sample data as if it were live.

## Accessibility & Inclusion

No product-specific requirement was established. Single known user, desktop, no stated
assistive-technology need or compliance standard. Baseline craft — legible contrast in
both modes, keyboard operability of the existing shortcut and command-palette system,
visible focus — still applies as ordinary quality, not as a special product constraint.
