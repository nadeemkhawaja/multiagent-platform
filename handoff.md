# Multi-Agent Platform — AI Handoff (portable)

> **Updated:** 2026-06-18 · **Branch:** `main` (merge `73dca72`) · **Repo:** https://github.com/nadeemkhawaja/multiagent-platform (PUBLIC)
> Drop this file into any AI assistant to resume work. It is self-contained and platform-agnostic.

---

## What this project is
A **Multi-Agent Personal Auto-Scheduling Platform** for a university assignment (Assignment-2, 100 marks). A FastAPI **orchestrator** manages a fleet of agents, monitors system resources, serializes LLM calls, auto-restarts crashes, and serves a React dashboard. **All AI inference is local** via **Ollama + `qwen3.5:4b`** — no hosted LLM APIs for the agents.

## Hard constraints (do not violate)
- **No hosted LLM APIs for agent inference.** Local Ollama only. (A Settings UI lets the *user* optionally route an agent to a frontier model with their own key, but the default and graded path is local Qwen.)
- **Backend port is 5174**, frontend dev is 5173. (Old docs said 8000 — wrong.)
- **Never commit secrets.** `credentials.json`, `token.json`, `*.db`, `.env` are gitignored — keep it that way.
- **Repo must stay PUBLIC** (assignment gives zero marks otherwise).
- **Demo video ≤10 min**, all 5 graded agents live, on YouTube — this is the user's job, not code.

## Architecture (where things live)
```
backend/
  main.py                  FastAPI app, APScheduler jobs, all /api routes, lifespan startup
  orchestrator.py          resource sampler (2s), 90% alarm + ALARM_ACTIONS, watchdog auto-restart, WS broadcast
  llm_client.py            llm_semaphore = asyncio.Semaphore(1); generate_json(); provider routing
  paper_broker.py          Alpha Wolf paper portfolio: _fetch_prices_sync (yfinance), sizing, execute_plan
  email_utils.py           Gmail SMTP HTML email
  database.py              SQLite (SQLAlchemy): AgentData, config, ResourceSample, AgentRun
  agents/agent1_ai_times.py .. agent13_alpha_wolf.py   (13 agents)
  tests/                   pytest; 165 passing
frontend/src/
  App.jsx                  shell: sidebar nav, ⌘K palette, toasts, shortcuts, <Aurora/>, tab cross-fade
  index.css                motion keyframes + .om-stagger utility + prefers-reduced-motion guard
  theme/tokens.js          T (mutable, light/dark), AGENT_COLOR, STAT
  theme/ui.jsx             Card, Pill, Ring(draw-in), Spark, Btn, TabHeader(glass), CountUp, Reveal, LiveDot
  components/Aurora.jsx     ambient animated background (theme-aware blobs + dot-grid)
  tabs/*.jsx               one file per agent + Orchestrator + Settings
  state/api.js             fetch helpers + useSystemState/useAgentData (WS)
architecture.png / .mmd    diagram for the rubric
```

## Mailman (agent2) — rubric behaviour
Rubric: *"classifies with LLM; labels, stars, alerts on **key people**; sends **daily** summary."*
- **Alerting is key-person-only.** `is_alert(email)` = `email['is_key']`; used by `apply_labels_and_stars` (star + `Mailman/<cat>` label in Gmail) and the digest's Key Alerts. Classification runs on *all* mail, but only key-person mail is tagged in the real inbox — do **not** re-add an `or category=='Urgent'` clause (that was the "tagging other mails" bug).
- **Digest is once per calendar day.** Job runs hourly (monitor/classify/label), but the summary email is gated by `summary_due()` + `_summary_due_today()`/`_mark_summary_sent()` (AgentData `last_summary_date`, UTC). `mailman_job(..., force_email=True)` bypasses the guard; the UI trigger forces only when the user explicitly ticks "send email".

## The headline feature — Alpha Wolf (agent13)
The platform's **primary trading decision maker**. It fuses six sub-agents (Wallstreet Wolf, Compass, Strategy Scout, Capitol Tracker, Options Flow, Earnings Calendar) + **live yfinance quotes** into ONE local-LLM game-plan, then paper-trades it.

- Daily plan has a **session timeline** (pre-market → open → midday → power hour → close) and ideas with **entry/stop/target/when** + **dollar sizing**.
- **`GET /api/alpha-wolf/now`** (`decision_now()`) = live "what do I do right now": market clock + each idea scored vs live quote into `WAIT / ACT / IN_WINDOW / STOPPED / TARGET_HIT / WINDOW_PASSED / NEXT_SESSION / MONITOR`.
- **`POST /api/alpha-wolf/pulse`** (`pulse_job`, scheduled every 30 min, self-gates to market hours) emails only on actionable change (window opens, entry hit, stop/target hit), deduped per plan.
- `market_clock()` uses `ZoneInfo("America/New_York")`. `_first_price()` rejects hallucinated levels (>2.5× or <0.4× the live quote). Frontend "Right now" card polls `/now` every 60 s; timeline highlights the active slot with a NOW badge.

## GUI design system (just overhauled — PR #7)
Direction: **refined-modern · animated aurora/mesh · tasteful motion**. NOT photographic backgrounds (they hurt data legibility).
- `Aurora.jsx`: fixed, `pointer-events:none`, theme-aware blurred blobs (`omDriftA/B/C`) + masked dot-grid. Rendered as a **sibling before** the layout; layout root is `background:transparent; zIndex:1`.
- `index.css`: keyframes (`omFadeUp/FadeIn/ScaleIn/Live/Shimmer/DriftA-C`), utilities (`.om-rise/.om-fade/.om-pop/.om-lift`, **`.om-stagger > *`** with nth-child delays), and a global `prefers-reduced-motion` guard.
- `ui.jsx`: `Ring` draws in; `CountUp`/`useCountUp` tween numbers; `Reveal` stagger; `LiveDot` breathing; `Card` `interactive` hover-lift; **`TabHeader` frosted glass** (`backdropFilter: blur(14px)`).
- Orchestrator has a `CommandCenterHero` (live clock, US market-session chip via `Intl` America/New_York, animated KPIs).
- Every tab content column has `className="om-stagger"` (Orchestrator excluded — it uses explicit `Reveal`s).

## Run it
```bash
# Ollama must be running: ollama pull qwen3.5:4b
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cd backend && uvicorn main:app --reload --port 5174
cd frontend && npm install && npm run dev      # http://localhost:5173
# convenience: ./start.sh   ./stop.sh
pytest backend/tests -q                          # 162 passing
```

## Git workflow used
Feature branch → commit (Co-Authored-By trailer) → push → `gh pr create` → merge to `main` → delete branch. Recent merged PRs: #6 Alpha Wolf live decision maker, #7 GUI aurora/motion.

## Open follow-ups (nice-to-have, not blocking)
- Per-card hover-lift on data lists (watchlist rows, email items, video cards); value-flash green/red on price tick; market ticker-tape; skeleton-shimmer loaders.
- Optional real imagery only on a login/splash screen (never behind data tables).
- Surface the Alpha Wolf "Right now" directive on the Orchestrator home; optional browser/desktop push alongside email pulse.

## Gotchas
- Ollama `/api/chat` **404 = model not pulled** (name mismatch with `ollama list` or a DB `agent_models` override). Check `.env` `LLM_MODEL`.
- Root folder name has a **trailing space** ("MultiAgent Platform") — quote paths.
- Backend started in background for verification stays up; `./stop.sh` to clean up.
