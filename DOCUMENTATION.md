# Multi-Agent Auto-Scheduling Platform — Project Documentation

A local-first **multi-agent platform for personal schedule automation**. A single
orchestrator supervises seven autonomous agents that fetch real-world data, reason
over it with a **local LLM (Qwen3 via Ollama)**, persist results, send daily email
digests, and stream live status to a polished React dashboard.

- **Backend:** FastAPI + APScheduler + SQLAlchemy (SQLite), WebSocket live state, `psutil` telemetry
- **Frontend:** React + Vite (single-page dashboard, light/dark, two layouts)
- **LLM:** Qwen3 (`qwen3:8b` default) served locally by Ollama — never a paid API
- **Persistence:** `orchestrator.db` (SQLite) — agent data, run history, resource samples, config
- **Email:** SMTP HTML digests per agent

> Last updated: 2026-06-08 · 7 agents live · all changes committed through `4589226`.

---

## Table of Contents
1. [Assignment Requirements & Coverage](#1-assignment-requirements--coverage)
2. [System Architecture](#2-system-architecture)
3. [The Agent Fleet](#3-the-agent-fleet)
4. [Lufi — the AI Analyst Persona](#4-lufi--the-ai-analyst-persona)
5. [GUI / Dashboard Enhancements](#5-gui--dashboard-enhancements)
6. [Email Design System](#6-email-design-system)
7. [Data Model](#7-data-model)
8. [API Surface](#8-api-surface)
9. [Configuration & Environment](#9-configuration--environment)
10. [Project Structure](#10-project-structure)
11. [Work History / Changelog](#11-work-history--changelog)
12. [Running the Platform](#12-running-the-platform)

---

## 1. Assignment Requirements & Coverage

The brief (*"Assignment-2: MultiAgent Platform for Personal Schedule Automation"*) is
graded out of 100:

| # | Requirement | Marks | Status |
|---|-------------|-------|--------|
| 1 | Orchestrator & Architecture | 15 | ✅ Supervisor, scheduler, auto-restart watchdog, live telemetry |
| 2 | AI-Times (Agent-1) | 15 | ✅ YouTube AI digest, LLM-curated |
| 3 | Mailman (Agent-2) | 15 | ✅ Gmail triage, classify/label/star/alert, daily summary |
| 4 | Wallstreet Wolf (Agent-3) | 15 | ✅ Market tracker + futures + LLM commentary |
| 5 | Agent-4 (Your Choice) | 15 | ✅ Three creative agents: Compass, Aegis, Strategy Scout |
| 6 | Code Quality, Repo & Creativity | 10 | ✅ Modular agents, tests, docs, resilient design |
| 7 | Demo Video | 15 | — (recorded separately) |

**Mailman spec (verbatim):** *"Monitors Gmail inbox; classifies emails with LLM;
labels, stars, alerts on key people; sends daily summary."* — implemented exactly:
emails are classified with the LLM, but **labels/stars are applied only to Urgent or
key-person mail** (never every routine email), and a daily summary email is sent.

---

## 2. System Architecture

```
                 ┌─────────────────────────────────────────────┐
                 │                React Dashboard               │
                 │   (Vite · WebSocket live state + REST)       │
                 └───────────────▲──────────────┬──────────────┘
                          WS /ws  │              │  REST /api/*
                 ┌───────────────┴──────────────▼──────────────┐
                 │                  FastAPI app                 │
                 │  ┌────────────┐  ┌──────────────────────┐    │
                 │  │ APScheduler│  │     Orchestrator      │    │
                 │  │ (cron/int.)│─▶│ status · watchdog ·    │   │
                 │  └────────────┘  │ telemetry · event log │    │
                 │                  └──────────┬────────────┘    │
                 │     ┌───────────────────────┼─────────────┐   │
                 │     ▼        ▼        ▼      ▼       ▼      ▼   │
                 │  Agent1   Agent2   Agent3  Agent5  Agent6 Agent7│
                 │  …each: fetch → LLM → persist → email…         │
                 └──────┬───────────────┬───────────────┬────────┘
                        │               │               │
                   Ollama (Qwen3)   SQLite DB        SMTP email
                   1-permit          orchestrator.db  (HTML digests)
                   semaphore
```

### Core components

- **Orchestrator** (`backend/orchestrator.py`) — single source of truth for agent
  status, run history, restart counts, the rolling event log, and system telemetry.
  Holds `AGENT_META` (display name, glyph, description, schedule label, color) and
  produces the full dashboard state via `get_state()`.
- **Scheduler** (`backend/main.py`) — APScheduler runs each agent on a `cron`
  (daily) or `interval` schedule. Schedules are editable at runtime from the
  Settings tab and persisted in the `config` table (DB override shadows the
  source default).
- **LLM client** (`backend/llm_client.py`) — calls Ollama's `/api/chat`. A **single
  permit `asyncio.Semaphore(1)` serializes all inference** so the local GPU is never
  oversubscribed (no deadlocks, predictable latency). Features: 300 s/5-min response
  cache, 3× retry with backoff, Qwen3 `think:false` to suppress the hidden reasoning
  block, and `format:"json"` enforced JSON mode (`generate_json`).
- **Telemetry sampler** — every 2 s samples CPU / RAM / Disk / GPU / **Network**
  (`psutil`), keeps a 24-point rolling history, persists periodically, and broadcasts
  the full state over the WebSocket. GPU uses NVML when present, else an Ollama-VRAM
  estimate.
- **Watchdog & auto-restart** — crashed agents are detected and restarted (up to
  `MAX_RESTARTS = 3`), with events logged.
- **Resilience pattern (applied fleet-wide):** every blocking call (`yfinance`,
  `googleapiclient`) runs via `asyncio.to_thread` so the event loop and WebSocket
  stay responsive; independent fetches run concurrently with `asyncio.gather`; the
  LLM step is isolated in `try/except` so a model failure never aborts the data save
  or the email.

---

## 3. The Agent Fleet

| # | Agent | Glyph | Schedule | Sources | Output |
|---|-------|-------|----------|---------|--------|
| 1 | **AI-Times** | ▶ | Daily 08:00 | YouTube Data API | LLM-curated AI video digest |
| 2 | **Mailman** | ✉ | Every 60 min | Gmail (OAuth) | Inbox triage + daily summary |
| 3 | **Wallstreet Wolf** | $ | Every 2 h | Yahoo Finance | Market brief: futures, movers, FX, metals |
| 4 | **Wallstreet Compass** | ◎ | Every 60 min | Yahoo Finance + Yahoo RSS | Pre-market bias + key levels |
| 5 | **Aegis** | ❖ | Every 60 min | Reddit + Hacker News | Islamophobia watch & moderation |
| 6 | **GitHub Trending** | ⌥ | Daily 09:00 | GitHub + Dev.to | Developer learning digest |
| 7 | **Strategy Scout** | ✦ | Daily 10:00 | Reddit + TradingView | Top trading strategies |

> All schedules are editable at runtime (Settings tab). Each agent can also be run
> on demand (Manual run / Scan now), Stopped, or Restarted from its tab, and offers
> a live **email preview**.

### 3.1 AI-Times (`agent1_ai_times.py`)
- **Logic:** queries the YouTube Data API for recent AI videos (7-day window),
  then asks Qwen3 to curate/rank the best. If curation exceeds `CURATE_TIMEOUT`
  (60 s) it falls back to YouTube's view-count ranking so a run always finishes.
- **Output:** dashboard list (title, channel, views, duration, thumbnail) + a daily
  HTML email at 08:00.
- **Resilience:** ~13× faster than the original; live progress + completion feedback.

### 3.2 Mailman (`agent2_mailman.py`)
- **Auth:** Gmail OAuth 2.0 (`gmail.modify` scope, `token.json`/`credentials.json`).
- **Logic:** scans the inbox, runs **one batched LLM call** classifying each email
  into `Urgent · Action Required · Follow-Up · Newsletter · Notification · Personal ·
  Other` with a **crisp ≤12-word summary**. Flags **key people** (configurable list).
- **Side effects (scoped):** Gmail **stars + `Mailman/<category>` labels are applied
  only to Urgent or key-person mail** — routine email is classified but never tagged.
- **Output:** dashboard (category breakdown bar, key-people panel, inbox list with AI
  summaries) + a **light-theme** daily summary email (category chips, key-alert cards,
  compact list).
- **Config:** `KEY_PEOPLE` (env) or the Settings field / per-run override.

### 3.3 Wallstreet Wolf (`agent3_wallstreet_wolf.py`)
- **Data:** Yahoo Finance via `yfinance` — a 20-symbol watchlist
  (AAPL, MSFT, GOOGL, AMZN, META, TSLA, NVDA, NFLX, JPM, V, WMT, JNJ, PG, MA, HD,
  UNH, DIS, BAC, PYPL, ADBE), **index futures `/ES` (ES=F) & `/NQ` (NQ=F)**, gold &
  silver, and EUR/GBP/JPY FX.
- **Logic:** computes % change vs previous close (history fallback for weekends/gaps),
  ranks top-5 gainers/losers, and has **Lufi (Qwen3)** write a 3-sentence commentary
  referencing the futures + movers.
- **Output:** dashboard (futures strip, gainers/losers, live-ticking watchlist with
  sparklines, FX, metals, Lufi commentary) + a light-theme daily market brief email.
- **Watchlist** is overridable via Settings (≥20 symbols).

### 3.4 Wallstreet Compass (`agent5_compass.py`)
- **Data:** 6 sector ETFs (XLK/XLE/XLF/XLV/XLY/XLI), `/ES` & `/NQ` futures, the 10
  megacaps, and Yahoo Finance RSS headlines.
- **Logic:** computes a **sector-bias composite** (−100…+100) and classic floor-trader
  **pivot levels** (Pivot/R1-R2/S1-S2, all math, not LLM). The LLM scores headline
  sentiment and writes a directional **"Lufi's read."**
- **Plain-English tone (replaces jargon):**
  - composite > 15 → **Bullish** — *"Risk appetite — buyers in control"*
  - composite < −15 → **Bearish** — *"Defensive — money rotating to safety"*
  - otherwise → **Neutral** — *"Range-bound — no clear edge"*
- **Output:** dashboard (composite meter, sector bias bars, news sentiment, pivot
  ladders for futures + a stock key-levels table) + a 07:00 pre-market brief email.

### 3.5 Aegis — Islamophobia Watch & Moderation (`agent6_aegis.py`)
- **Purpose:** a **forum-moderation assistant** that monitors public discussion
  (Reddit search + Hacker News via Algolia) for **Islamophobic / anti-Muslim content**.
- **Logic:** for each post the LLM (enforced JSON mode) returns
  `{risk, sentiment, reason, suggested_reply}` — risk = hate-speech severity
  (high = clear hate speech, med = biased/stereotyping, low = neutral/supportive),
  sentiment = stance toward Muslims (−100…+100), and a **calm counter-speech /
  de-escalation draft** for a human moderator.
- **Human-in-the-loop:** suggested replies are **DRAFTS only** — approved or dismissed
  from the UI, **never auto-posted** (`post_reply` is an explicit stub).
- **Output:** dashboard (stat cards, severity-sorted flagged-post feed, moderation
  composer) + an 18:00 moderation digest email.
- **Topic:** `AEGIS_BRAND` env / Settings (default `Islamophobia`).

### 3.6 GitHub Trending (`agent4_devdaily.py`)
- **Data:** GitHub Search API (trending repos, language filter) + Dev.to top articles.
- **Logic:** fetches both concurrently; **Lufi** writes a 3-sentence learning summary.
- **Output:** dashboard (config panel, Lufi summary, GitHub + Dev.to columns) + a
  09:00 developer digest email.
- *(Formerly "DevDaily" / "Dev Hunt"; renamed to GitHub Trending — display only, the
  `devdaily` id and filenames are unchanged to preserve DB references.)*

### 3.7 Strategy Scout (`agent7_strategy_scout.py`) — **new**
- **Purpose:** surface the **top trading strategies traders are discussing right now.**
- **Data:** 6 Reddit trading subreddits (algotrading, Daytrading, swingtrading,
  options, Forex, stocks) via `top.json` with an **`.rss` fallback** (datacenter IPs
  often 403 the JSON API), plus **TradingView's public Ideas feed** (HTML parse).
- **Logic:** **Lufi distills** the raw chatter into a ranked list of strategies, each
  with `{name, type, timeframe, summary, source}`, and keeps the source-discussion feed.
- **Output:** dashboard (Lufi byline + source counts, ranked strategy cards colored by
  type, trending-discussions list with upvotes/comments) + a 10:00 digest email.
- **Disclaimer:** clearly labeled *"not financial advice."*

---

## 4. Lufi — the AI Analyst Persona

All LLM-written prose is attributed to **Lufi**, the platform's AI analyst (powered by
Qwen3 locally). She narrates **Compass's "Lufi's read,"** Wolf's market commentary,
GitHub Trending's learning summary, and Strategy Scout's distillation.

- **Avatar:** illustrated SVG at `frontend/public/lufi.svg` (a beret-wearing artist
  reading a chart). The `LufiAvatar` component tries **`/lufi.png` first** and falls
  back to the SVG — **drop a real photo at `frontend/public/lufi.png`** and it's used
  automatically, no code change.
- **Components:** `LufiAvatar`, `LufiByline` in `frontend/src/components/Common.jsx`.

---

## 5. GUI / Dashboard Enhancements

### Orchestrator dashboard (market-app polish)
- **Five live metric cards** — CPU, Memory, Disk, GPU·LLM, and **Network throughput
  (Mb/s)** — each with a crisp SVG icon, a ring gauge, a NOMINAL/CRITICAL status chip,
  and a colored top accent bar.
- **Threshold-aware area charts:** the line is drawn segment-by-segment — **green
  below the threshold, red on any segment that crosses it** — with a dashed threshold
  marker and a glowing end-dot. Charts fill their container width via a
  `ResizeObserver` (no SVG stretch / distortion).
- **Network metric** added end-to-end: backend samples `psutil.net_io_counters()`
  deltas → Mb/s with rolling history; surfaced in both Aria cards and the Atlas strip.
- Crisp icon set in `frontend/src/theme/icons.jsx` (CPU chip, RAM stick, disk cylinder,
  GPU card, network arrows, strategy candlesticks, shield).

### Shell & theming
- **Two layouts:** *Aria* (calm cards) and *Atlas* (ops table/strip), toggled live.
- **Light / Dark** mode with a single mutable token object (`theme/tokens.js`) re-skinned
  in place at render time.
- **Sidebar** with per-agent status dots, live system stats (CPU/RAM/GPU), transport
  indicator (`live · ws` / `poll`), and the active model.
- **LLM Semaphore panel** (current holder, token/s, queue) and a rolling **Event log**.
- **Alarm banner** with a suggested remediation action when a resource crosses 90%.

### Per-agent tabs
- Consistent **Run / Stop / Restart** controls, **email preview** modal (faithful
  `iframe srcDoc` render), error + progress banners, and graceful empty states.
- Wolf watchlist **ticks client-side** between backend refreshes for an "alive" feel.
- Aegis moderation composer; Compass pivot ladders & bias meters; Strategy Scout
  type-colored strategy cards.

---

## 6. Email Design System

All agents send **HTML email digests** via SMTP, each with a per-agent sender name.

**Dark-mode legibility fix (applied to Wallstreet Wolf and Mailman):** the original
dark-navy templates rendered as **dark-on-dark** in Gmail/Apple Mail, because those
clients' auto dark-mode *darkens near-white text while leaving dark backgrounds intact*.
The fix is a **light theme** (white card, dark text, category-tinted chips) plus
`<meta name="color-scheme" content="light">` and `supported-color-schemes` tags so no
client tries to "correct" it. Colors are inlined for maximum client compatibility, and
all interpolated subjects/senders are HTML-escaped.

Mailman's summary is also **crisp**: per-email AI summaries are capped at ~12 words
(prompt rule), shown as light category chips + key-alert cards + a compact one-line list.

---

## 7. Data Model

SQLite (`orchestrator.db`) via SQLAlchemy (`backend/database.py`):

| Table | Purpose |
|-------|---------|
| `agent_data` | Per-agent results (`agent_name`, `key`, JSON `value`) — what each tab/email reads |
| `resource_samples` | Telemetry history (cpu/ram/disk/gpu/threads) |
| `events` | Orchestrator event log (message + color) |
| `agent_runs` | Run history (started/finished/status/error) |
| `agent_state` | Restart counts, last run, last error per agent |
| `config` | Runtime config overrides (schedules, recipient, key_people, watchlist, aegis_brand) |
| `system_logs` | General log sink |
| `memories` | Long-term agent memory: text + local embedding vector for semantic recall |
| `approvals` | Human-in-the-loop queue: pending/approved/denied actions with payloads |

`agent_runs` also carries per-run telemetry (`llm_calls`, `tokens_in`,
`tokens_out`, `llm_ms`, `stages`) filled in by `tracing.py`; `init_db()`
ALTERs these columns into pre-existing databases.

---

## 8. API Surface

| Method | Path | Purpose |
|--------|------|---------|
| WS | `/ws` | Live dashboard state stream |
| GET | `/api/state` | Full dashboard state (poll fallback) |
| GET | `/api/system/resources` | CPU/RAM/Disk/GPU/Net + alarms |
| GET | `/api/health` | Ollama reachability, DB, model, LLM call stats |
| GET | `/api/agent/{name}/data` | Persisted agent result |
| GET | `/api/agent/{name}/email-preview` | Rendered HTML email |
| POST | `/api/agent/{name}/trigger` | Run an agent now (optional config) |
| POST | `/api/agent/{name}/stop` | Cancel a running agent |
| GET/POST | `/api/schedules[/{name}]` | View / edit schedules |
| GET/POST | `/api/config` | Settings (recipient, key_people, watchlist, aegis_brand) |
| POST | `/api/aegis/approve` · `/api/aegis/dismiss` | Moderation decisions |
| POST | `/api/demo/spike` · `/api/demo/crash` | Demo alarm / crash-recovery |
| POST | `/api/test-llm` | Ad-hoc LLM call |
| GET | `/api/agent/{name}/memories` | Recent long-term memories for an agent |
| POST | `/api/agent/{name}/memories/recall` | Semantic search over an agent's memories |
| GET | `/api/mcp` | MCP availability + registered servers |
| GET | `/api/mcp/servers/{name}/tools` · `/ping` | List a server's tools / reachability probe |
| POST/DELETE | `/api/mcp/servers[/{name}]` | Register / remove an MCP server |
| POST | `/api/mcp/call` | Call a tool on a registered MCP server |
| GET | `/api/agent/{name}/runs` | Run history with per-run tokens, LLM time, stage timings |
| GET | `/api/metrics` | Per-agent aggregates: success rate, avg duration, token totals |
| GET | `/api/llm/providers` | Provider status (ollama/openai/anthropic) + per-agent overrides |
| POST | `/api/llm/models` | Route an agent to a model, e.g. `anthropic:claude-haiku-4-5` |
| GET | `/api/tools` | Registered platform tools with JSON schemas |
| POST | `/api/tools/call` | Invoke a registered tool by name |
| GET | `/api/approvals` | Approval queue (filter by `?status=pending`) |
| POST | `/api/approvals/{id}/approve` · `/deny` | Decide a pending approval (approve runs the action) |

### LLM providers (`backend/llm_client.py`)

Local Ollama stays the default. Per-agent overrides route through OpenAI- or
Anthropic-compatible APIs: set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` and map
an agent via `POST /api/llm/models` (`{"agent_id": "morning_brief", "model":
"anthropic:claude-haiku-4-5"}`). Bare model names mean Ollama. Token usage per
call is recorded onto the agent's open run trace.

### Run tracing (`backend/tracing.py`)

Every run accumulates LLM calls, tokens in/out, LLM wall time, and named stage
timings (`with tracing.stage(agent_id, "fetch"): …`); the orchestrator
persists them onto the run's `agent_runs` row. `/api/metrics` aggregates
success rate, average duration, and token totals per agent.

### Tool registry (`backend/tools/`)

Capabilities are declared once with `@tool(name, description)` — the registry
derives a JSON schema from type hints, so the same definition serves direct
agent imports, `/api/tools`, and future LLM function-calling. Built-ins:
`web.fetch_json`, `weather.current`, `market.quotes` (Wolf's yfinance fetch,
shared), and `mcp.call` / `mcp.list_tools` bridging registered MCP servers.

### Approvals (`backend/approvals.py`)

Human-in-the-loop primitive: agents park an action (`approvals.request`)
instead of executing it; approving from the API runs the handler registered
for that kind. With the `require_email_approval` setting on, **every** agent
email queues for sign-off — `email_utils.send_html_email` is the single
chokepoint — and goes out when approved. Default off (behavior unchanged).

### Agent memory (`backend/memory.py`)

Agents store what they reported (`remember`) and read it back before the next
run (`recent` / `recall` / `seen_before`), so output can lead with *what
changed* instead of restating state. Embeddings come from a local Ollama model
(`EMBED_MODEL`, default `nomic-embed-text`) — fully local, and every operation
degrades gracefully to recency-based recall if the embed model is missing.
Wired into Wallstreet Wolf (commentary references the previous brief) and
Morning Brief (avoids repeating yesterday's narrative). Capped at
`MEMORY_MAX_PER_AGENT` rows (default 500), oldest pruned first.

### MCP client (`backend/mcp_client.py`)

Agents and the API can call tools on any [MCP](https://modelcontextprotocol.io)
server (Gmail, GitHub, market data, 10k+ community servers) through one
protocol instead of hand-rolled integrations. Servers are registered in the
`config` table under `mcp_servers` and run as local stdio subprocesses — data
never leaves the machine. Connections are opened per call so a wedged server
can't poison shared state; the `mcp` package is optional and its absence just
disables the feature.

---

## 9. Configuration & Environment

Environment variables (`.env`, see `.env.example`) — **values are never stored here:**

| Var | Used by | Notes |
|-----|---------|-------|
| `LLM_MODEL` | all | default `qwen3:8b` |
| `OLLAMA_BASE_URL` | all | default `http://localhost:11434` |
| `EMBED_MODEL` | memory | local embedding model, default `nomic-embed-text` |
| `MEMORY_MAX_PER_AGENT` | memory | memory rows kept per agent, default `500` |
| `DAILY_DIGEST_EMAIL` | all | digest recipient |
| `SMTP_*` / `SMTP_APP_PASSWORD` | email | SMTP credentials |
| `YOUTUBE_API_KEY` | AI-Times | YouTube Data API |
| `GITHUB_TOKEN` | GitHub Trending | higher GitHub rate limit |
| `KEY_PEOPLE` | Mailman | comma-separated names/emails to always alert |
| `AEGIS_BRAND` | Aegis | topic to watch (default `Islamophobia`) |
| `AI_TIMES_CURATE_TIMEOUT` | AI-Times | LLM curation cap (s) |

Schedules and the recipient / key-people / watchlist / aegis-topic are also editable
at runtime from the **Settings** tab (stored in the `config` table, which overrides
the source defaults).

**Default schedules:** AI-Times 08:00 · Mailman 60 min · Wolf 2 h · Compass 60 min ·
Aegis 60 min · GitHub Trending 09:00 · Strategy Scout 10:00.

---

## 10. Project Structure

```
MultiAgent Platform/
├── backend/
│   ├── main.py                 # FastAPI app, scheduler, routes, triggers
│   ├── orchestrator.py         # supervisor, telemetry, watchdog, AGENT_META
│   ├── llm_client.py           # Ollama client, 1-permit semaphore, cache/retry
│   ├── database.py             # SQLAlchemy models + helpers
│   ├── email_utils.py          # SMTP HTML sender
│   ├── ws.py                   # WebSocket manager
│   └── agents/
│       ├── agent1_ai_times.py
│       ├── agent2_mailman.py
│       ├── agent3_wallstreet_wolf.py
│       ├── agent4_devdaily.py        # "GitHub Trending"
│       ├── agent5_compass.py         # "Wallstreet Compass"
│       ├── agent6_aegis.py           # "Aegis — Islamophobia Watch"
│       └── agent7_strategy_scout.py  # "Strategy Scout"  (new)
├── frontend/
│   ├── public/lufi.svg         # Lufi avatar (override with /lufi.png)
│   └── src/
│       ├── App.jsx             # shell: nav, routing, appearance
│       ├── state/api.js        # WS live state + REST client
│       ├── theme/{tokens.js, ui.jsx, icons.jsx}
│       ├── components/Common.jsx   # controls, email preview, Lufi, banners
│       └── tabs/{Orchestrator, AITimes, Mailman, Wolf, Compass, Aegis,
│                 DevDaily, StrategyScout, Settings}.jsx
├── orchestrator.db             # SQLite (gitignored runtime data)
├── architecture.png / .mmd     # architecture diagram
├── run.sh · start.sh · stop.sh # launch helpers
├── requirements.txt
└── DOCUMENTATION.md            # ← this file
```

---

## 11. Work History / Changelog

Chronological highlights (newest first):

| Commit | Date | Summary |
|--------|------|---------|
| `4589226` | 2026-06-08 | **Mailman email** → light theme + crisp ≤12-word AI summaries |
| `3c0ed86` | 2026-06-08 | **Dashboard polish + Network metric + Lufi + Aegis refocus + Strategy Scout** |
| `8663123` | 2026-06-07 | Mailman surfaces only notable mail; Wolf wider watchlist, slower scans |
| `f136f8d` | 2026-06-07 | Rename Compass → Wallstreet Compass; DevDaily → Dev Hunt |
| `4116950` | 2026-06-07 | Mailman labels/stars scoped to alerts; intervals relaxed to ~1 h |
| `d212ca7` | 2026-06-07 | Reliability sweep across the fleet + tests + email fix |
| `4b5b819` | 2026-06-06 | Compass: unblock event loop, parallel fetches, isolate LLM failures |
| `acbc2d7` | 2026-06-06 | Per-agent display name on outgoing emails |
| `3334e7d` | 2026-06-06 | websockets 12→16 (yfinance compat) |
| `c686436` | 2026-06-06 | yfinance 0.2.40 → 1.4.1 (Yahoo rate-limit fix) |
| `acd2380` | 2026-06-06 | Wolf: unblock event loop, isolate LLM from data save |
| `ed0f644` | 2026-06-06 | AI-Times ~13× faster + live progress/completion |
| `51ecd17` | 2026-06-06 | Run/Stop/Restart controls on every agent tab |
| `0dc9eb2` | 2026-06-05 | Drop mock data; live data with empty states |
| `a2a46e9` | 2026-06-05 | AI-Times curation, WebSocket, durable history, settings + previews |
| `d16815f` | 2026-06-05 | Merge Claude Design frontend; add Compass + Aegis |
| `37e2094` | 2026-06-03 | Fix 12 audit gaps (real email, watchdog, summaries, alarms, hardening) |
| `b0e97c5` | 2026-06-03 | Initial backend agents, frontend dashboard, architecture |

### This session's themes
1. **Reliability sweep** — unblocked the event loop everywhere, parallelized fetches,
   isolated LLM failures from data/email, fixed dependency conflicts, added a watchdog.
2. **Email legibility** — diagnosed the email-client dark-mode inversion bug and moved
   Wolf + Mailman to a robust light theme with `color-scheme` meta tags.
3. **Scope correctness** — Mailman labels/stars only Urgent/key-person mail; intervals
   relaxed to ~1 h; crisp ≤12-word summaries.
4. **Naming & clarity** — Compass → Wallstreet Compass, DevDaily → GitHub Trending,
   Risk-On/Off → plain-English Bullish/Bearish/Neutral.
5. **Creativity** — the **Lufi** persona, the **Aegis** refocus to Islamophobia
   moderation, and a brand-new **Strategy Scout** agent.
6. **Dashboard depth** — Network metric, threshold-colored charts, crisp icons.

---

## 12. Running the Platform

**Prerequisites:** Python 3.11+, Node 18+, and **Ollama** running locally with the
model pulled (`ollama pull qwen3:8b`).

```bash
# 1. Backend
cd backend
python3 -m venv ../venv && source ../venv/bin/activate
pip install -r ../requirements.txt
uvicorn main:app --host 0.0.0.0 --port 5174 --reload

# 2. Frontend
cd frontend
npm install
npm run dev        # http://localhost:5173

# …or use the helper that starts both and opens the browser:
./start.sh         # ./stop.sh to stop
```

Then open **http://localhost:5173**. Configure `.env` (copy from `.env.example`),
set the digest recipient / key people / watchlist / Aegis topic in **Settings**, and
trigger any agent with **Manual run / Scan now** — or wait for its schedule.

---

*Generated as a project deliverable. Secrets (SMTP password, API keys, recipient
address, key-people list) live only in the local `.env` and are never committed.*
