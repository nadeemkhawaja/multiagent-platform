# Multi-Agent Platform — Session Summary

> **Last updated:** 2026-06-18 · **Branch:** `main` · **Status:** Assignment-complete; Alpha Wolf upgraded to a live decision maker; full GUI overhaul (aurora + motion) merged.

---

## 1. Key Requirements & Constraints (Assignment-2)

- **Local LLM only** — Ollama, model `qwen3.5:4b` (assignment says "Qwen3"). **No hosted LLM APIs** for inference (no OpenAI/Anthropic for the agents).
- **Stack** — Python 3.12 backend (FastAPI + APScheduler + SQLAlchemy/SQLite), React + Vite frontend (inline-styled, single mutable token object `T`).
- **Orchestrator** — live CPU/RAM/disk/threads (+GPU/VRAM) monitoring, dashboard updates **≤5 s** (we push every **2 s** over WebSocket); **90 % alarm** with a suggested corrective action; **LLM semaphore** = `asyncio.Semaphore(1)` (one agent calls the model at a time, no deadlocks); **watchdog** auto-restarts crashed agents (max 3 attempts).
- **Graded agents (rubric, 15 pts each):** Agent-1 AI-Times (YouTube digest), Agent-2 Mailman (Gmail OAuth triage), Agent-3 Wallstreet Wolf (20+ stocks), Agent-4 "Your Choice" = **GitHub Trending** (GitHub + Dev.to APIs, 150-word proposal in README). Plus Orchestrator (15), Code Quality/Creativity (10), Demo Video (15).
- **Deliverables** — public GitHub repo (zero marks if not public), README setup, architecture diagram, **demo video ≤10 min** on YouTube showing all 5 agents live.
- **Security** — no committed secrets; `credentials.json`, `token.json`, `*.db`, `.env` are gitignored.

## 2. Current Status

- **Repo:** `https://github.com/nadeemkhawaja/multiagent-platform` — **PUBLIC**. Default branch `main` at merge `73dca72`.
- **Backend** runs on **port 5174** (was 8000 in old docs); frontend dev on **5173**.
- **All assignment gaps audited and closed.** Watchlist now 22 tickers (20+). AI-Times recency window is env-configurable (`AI_TIMES_WINDOW_HOURS`, default 168 = 7 days for richer curation; set 48 to match the literal 24–48 h wording).
- **Alpha Wolf (agent13)** is the headline creativity feature: a master agent + **live, time-of-day trading decision maker**. Done and verified live during real market hours.
- **GUI overhaul** merged (PR #7): ambient aurora background, motion system, frosted-glass headers, Orchestrator command-center hero, staggered entrances across all 14 tabs.
- **Tests:** `165 passed` in the backend suite.
- **Mailman tightened to the rubric line:** star/label/alert on **key people only** (no longer tags every mail the LLM calls "Urgent"), and the digest now emails **once per calendar day** instead of every hourly scan. See §4 "Mailman triage fixes".
- **Outstanding (user-only):** record the ≤10-min demo video; optionally enter API keys (`YOUTUBE_API_KEY`, Gmail app password) in `.env` for live email.

## 3. Key Decisions

1. **Alpha Wolf = primary decision maker**, not just a daily digest. It answers "what do I do right now, this hour, today" using a market clock + **live yfinance quotes**. (See memory `alpha-wolf-primary-decision-maker.md`.)
2. **LLM levels anchored to live prices** — synthesis is fed a `LIVE PRICES` feed; parsed entry/stop/target are sanity-checked against the live quote (`_first_price` rejects values 0.4×–2.5× off) to kill hallucinations.
3. **GUI direction (user-chosen):** Refined & modern · animated **aurora/mesh** background (NOT photographic — photos behind data hurt legibility) · tasteful micro + entrance motion · started with the Orchestrator hero, then rolled app-wide.
4. **Accessibility first** — all motion gated behind `prefers-reduced-motion`.
5. **AI-Times window kept at 7 days** (user call) for better content, but made an env knob.
6. **Git workflow:** feature branch → commit → push → PR → merge to `main` → delete branch. PRs #6 (Alpha Wolf) and #7 (GUI) both merged.

## 4. Finalized Code / Logic

### Alpha Wolf live decision engine — `backend/agents/agent13_alpha_wolf.py`
- `market_clock(now=None)` → US/Eastern session via `ZoneInfo("America/New_York")`: pre-market (4:00–9:30), open (9:30–10:30 grouped), midday (10:30–15:00), power (15:00–16:00), after (16:00–20:00), else closed; `is_open` = weekday & 9:30–16:00; `next_event` countdown.
- `decision_now()` → `GET /api/alpha-wolf/now`: scores each daily idea vs live quote + clock into states `WAIT / ACT / IN_WINDOW / STOPPED / TARGET_HIT / WINDOW_PASSED / NEXT_SESSION / MONITOR`.
- `_first_price(text, live)` parses `$146.20 zone (9:35 ET)`, ignores bare times, rejects far-off (hallucinated) levels.
- `_window_minutes(text)` parses `9:30-10:30`, `3:45 PM`, or session words → minute range.
- `_apply_sizing(ideas, prices, budget)` adds `size_shares`/`size_usd` from paper-portfolio equity × `position_pct`.
- `pulse_job(force, send_email)` → `POST /api/alpha-wolf/pulse`, scheduled every 30 min (self-gates to market hours via `clock["in_pulse_hours"]`), emails only on actionable change, deduped via saved `pulse.sent` keyed by `plan_id`.
- LLM plan schema gained a daily `timeline` (session slots) and per-idea `entry/stop/target/when`. `email_preview()` now returns an **HTML string** (was a dict → rendered as `[object Object]`).
- Scheduler hook in `backend/main.py`: `scheduler.add_job(agent13_alpha_wolf.pulse_job, "interval", minutes=30, id="alpha_wolf_pulse")`.

### GUI foundation
- `frontend/src/components/Aurora.jsx` — fixed full-viewport, `pointer-events:none`, theme-aware blurred radial blobs animated by `omDriftA/B/C` keyframes + faint dot-grid with radial mask. Rendered as a **sibling before** the layout (not nested) so stacking is clean; layout root is `background:transparent; position:relative; zIndex:1`.
- `frontend/src/index.css` — keyframes `omFadeUp/omFadeIn/omScaleIn/omShimmer/omLive/omDriftA-C`; utilities `.om-rise/.om-fade/.om-pop/.om-lift`; **`.om-stagger > *`** with `:nth-child` delays (drop-in staggered entrance); global `@media (prefers-reduced-motion: reduce)` guard.
- `frontend/src/theme/ui.jsx` — `Ring` draws in on mount (state 0→val); `useCountUp`/`CountUp` rAF tween (easeOutCubic, honors reduced-motion); `Reveal` stagger wrapper; `LiveDot` breathing dot; `Card` gains `interactive` (hover-lift) + default `boxShadow: T.shadow`; **`TabHeader` is frosted glass** (`background: T.card + "c2"`, `backdropFilter: blur(14px) saturate(1.4)`).
- `frontend/src/tabs/Orchestrator.jsx` — `CommandCenterHero` with `useClock()` (1 s tick), `marketStatus(now)` via `Intl.DateTimeFormat` timeZone `America/New_York`, greeting, animated KPI tiles (`HeroKpi` + `CountUp`); resource cards & agent grid wrapped in `Reveal` stagger; agent cards use `om-lift` + hover glow; big resource numbers use `CountUp`.
- `frontend/src/App.jsx` — imports `Aurora`; renders `<Aurora/>` then the layout in a fragment; tab content wrapped `<div className="om-fade">` (keyed remount → cross-fade on every tab switch).
- Rollout: every agent tab + Settings content container got `className="om-stagger"` (applied via a verified one-line perl transform across 14 files; Orchestrator excluded because it has explicit `Reveal`s).

### Mailman triage fixes (`backend/agents/agent2_mailman.py`) — aligns to the rubric line
The rubric says Mailman *"classifies emails with LLM; labels, stars, alerts on **key people**; sends **daily** summary."* Two behaviours drifted from that and were corrected:
- **Star/label/alert on key people only.** The gate was `is_key OR category == 'Urgent'`, so any mail the LLM merely *called* Urgent (even from strangers) got starred + labeled in the real inbox. Extracted `is_alert(email)` = `is_key` and used it in `apply_labels_and_stars`, the summary's `key_alerts`, and the done-log count. Classification still runs on **all** mail (category breakdown + All-Emails list in the digest are unchanged); only the in-inbox tagging is now key-person-only.
- **Daily summary is actually daily.** Job is on a 60-min interval, and scheduled runs default `send_email=True`, so the "daily summary" was emailing **every hour**. Added `summary_due(last_sent, today)` (pure, tested) + DB-backed `_summary_due_today()`/`_mark_summary_sent()` (AgentData key `last_summary_date`, UTC). The send is now gated: monitor/classify/label every hour, email the digest **once per calendar day**. `mailman_job` gained `force_email`; the UI trigger passes `force_email=cfg.send_email` so an explicit "send now" still works for demos (`backend/main.py`).
- Tests: +3 in `test_agents_pure.py` (`test_mailman_is_alert_only_key_people`, `test_mailman_summary_key_alerts_only_key_people`, `test_mailman_summary_due_once_per_calendar_day`). Suite now **165 passed**.

### Other finalized
- `agent3_wallstreet_wolf.py` `DEFAULT_WATCHLIST` = 22 tickers (added ORCL, MSTR).
- `agent1_ai_times.py` `FETCH_WINDOW_HOURS = int(os.getenv("AI_TIMES_WINDOW_HOURS", "168"))`.
- Test updated: `test_agents_pure.py::test_sanitize_plan_*` expects new idea fields `entry/stop/target/when` + `daily.timeline`; added 5 tests for clock/level-parse/window/idea-state.

## 5. How to Run

```bash
# prereqs: Python 3.12, Node, Ollama running with: ollama pull qwen3.5:4b
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cd backend && uvicorn main:app --reload --port 5174     # backend  (NOTE: 5174, not 8000)
cd frontend && npm install && npm run dev                # frontend (5173)
# or ./start.sh
```

## 6. Memory files (`~/.claude/.../memory/`)
- `ollama-404-means-model-not-pulled.md` — `/api/chat` 404 = model not in `ollama list`; check `.env` `LLM_MODEL` + DB `agent_models` overrides.
- `alpha-wolf-primary-decision-maker.md` — agent13 = live clock + quotes + 30-min pulse; the "what do I do right now" engine.
