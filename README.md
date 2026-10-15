# Multi-Agent Personal Auto-Scheduling Platform

A fully operational Multi-Agent Auto-Scheduling Platform running entirely on a local machine using a locally hosted LLM (Gemma via an OpenAI-compatible vLLM server), with Claude/OpenAI/Grok available as alternate providers. A central orchestrator manages a fleet of specialized agents, handles resource scheduling, and serves a web-based dashboard.

## Dashboard (Claude Design merge)

The frontend is a faithful implementation of the **Claude Design** "Aria" direction (a clean light-SaaS dashboard):

- **Sidebar nav** with live per-agent status dots, an Appearance panel, and a system/LLM readout.
- **Dark mode** toggle re-skinning the entire app via a single mutable token system. Persists.
- **Alpha Wolf is the landing tab** — it opens on the **session banner**: which part of the trading day we're in (pre-market → open → midday → power hour → after-hours, on a live 4:00–20:00 ET bar) and one **BULLISH / BEARISH / MIXED / NEUTRAL** call for right now, built from the /ES-/NQ tape, the Compass composite and the plan's own bias, with every driver shown.
- **Agent tabs** — Wallstreet Wolf, Technologia — each wired to its live `/api/agent/{id}/data` endpoint with manual run/scan controls, falling back to realistic sample data until the agent first runs.
- The orchestrator still runs underneath (scheduling, status, watchdog restarts, the LLM semaphore, the event log) and is reachable through `/api/state`; it no longer has a tab of its own.

Design source bundle (prototype HTML + backend spec) is preserved under [`design/`](design/).

### Agents

| Tab | Agent | What it does |
|---|---|---|
| Wallstreet Wolf | `wallstreet_wolf` | The market desk — watchlist, gainers/losers, FX & metals **plus** sector bias, VIX regime and pivot key levels for /ES, /NQ & the majors · two LLM passes (tape commentary + regime read) |
| Technologia | `technologia` | Volume-profile / VWAP / MFI confluence scoring on /ES, /NQ & majors, plus two named strategies: **VWAP + EMA cross** (long while price holds VWAP and the 8 EMA leads the 20) and **Decision Point** (Catalyst / Participation / Structure in-play screen — participation is a hard gate) |
| 🐺 Alpha Wolf | `alpha_wolf` | **Master agent & live decision maker** — fuses two trading sub-agents + **live quotes** into one LLM game-plan: a time-of-day session schedule (pre-market → open → midday → power hour → close), daily ideas with live-anchored entry/stop/target levels and dollar position sizing, then executes them on a simulated paper portfolio. A **"Right now" engine** scores every idea against a live market clock + quotes (WAIT / ACT NOW / STOPPED / TARGET HIT), and a **30-min pulse** emails you when a window opens or a level is hit. |

> Wallstreet Compass has been **merged into Wallstreet Wolf** — both halves hit Yahoo
> Finance for an overlapping symbol set and were fused downstream anyway, so they now share
> one fetch and one run; the composite can no longer disagree with the tape beside it.
> AI-Times, Options Flow, Earnings Calendar, GitHub Trending, Cisco Pulse and Strategy
> Scout have been retired — the platform is a focused trading desk, not a digest tool.

### Key API endpoints

The dev server proxies `/api` and `/ws` to the backend, so **5173 is the only port you
open** — the API listens on `127.0.0.1:5174` and is not reachable from the network.
Interactive docs: <http://localhost:5173/api/docs>.

```
GET  /api/state                     # full orchestrator snapshot (agents, llm, events)
GET  /api/agent/{id}/data           # per-agent cached data
POST /api/agent/{id}/trigger        # manual run
POST /api/agent/{id}/stop
GET  /api/demo/mode                 # demo-mode state + core (graded) agents
POST /api/demo/mode    {enabled}    # demo mode: show/schedule only the graded agents
GET  /api/alpha-wolf/portfolio      # paper portfolio (equity, positions, trades)
GET  /api/alpha-wolf/now            # LIVE decision: session clock + market bias + ideas scored vs live quotes
POST /api/alpha-wolf/pulse          # run the in-session pulse check now (alerts on changes)
POST /api/alpha-wolf/execution      # toggle/size paper-trade execution
```

## Agent-4 Use-Case Proposal: GitHub Trending *(retired)*

> Kept for the original submission record. The GitHub Trending agent has since been
> removed from the platform along with the other non-trading agents.

**Problem:** Software engineers and developers often struggle to keep up with the fast-paced ecosystem of new repositories, tools, and technical articles published daily. Manually curating these sources is time-consuming and often leads to information overload or missing out on key industry trends.

**Solution:** I propose **Agent-4: GitHub Trending**, a specialized agent designed to solve this professional challenge. It will connect to the GitHub REST API to fetch the top trending repositories of the day and use the Dev.to API to pull the most popular programming articles. 

The local LLM will then process these disparate data sources, filtering out noise, categorizing the content by relevance (e.g., frontend, backend, AI), and generating a concise, actionable summary of the best learning opportunities. This personalized digest will be accessible via the orchestrator dashboard and sent automatically as a scheduled daily email, ensuring developers stay continuously updated with minimal friction.

## Setup Instructions

### Prerequisites
- Python 3.12+
- Node.js (for React frontend)
- An OpenAI-compatible local LLM server (vLLM/LM Studio) for the default `local` provider — or an API key for Claude/OpenAI/Grok
- API Keys: YouTube Data API v3, GitHub PAT.

### Backend Setup
1. Create a virtual environment: `python -m venv venv`
2. Activate it: `source venv/bin/activate` (Mac/Linux) or `venv\Scripts\activate` (Windows)
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and fill in your API keys.
5. Run the backend: `uvicorn main:app --reload`

### Frontend Setup
1. Navigate to the `frontend` folder: `cd frontend`
2. Install dependencies: `npm install`
3. Start the dev server: `npm run dev`
