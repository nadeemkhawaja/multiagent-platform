# Multi-Agent Personal Auto-Scheduling Platform

A fully operational Multi-Agent Auto-Scheduling Platform running entirely on a local machine using a locally hosted LLM (Qwen3 via Ollama). A central orchestrator manages a fleet of specialized agents, handles resource scheduling, and serves a web-based dashboard.

## Dashboard (Claude Design merge)

The frontend is a faithful implementation of the **Claude Design** "Aria" direction (a clean light-SaaS dashboard):

- **Sidebar nav** with live per-agent status dots, an Appearance panel, and a system/LLM readout.
- **Dark mode** toggle re-skinning the entire app via a single mutable token system. Persists.
- **Orchestrator tab** — live CPU/RAM/Disk/GPU rings + sparklines (polls `/api/state` every 2 s), the **LLM semaphore** panel (single permit, holder + live queue), an event log, and **Demo controls**: *Spike CPU/RAM/GPU > 90 %* fires the alarm banner with a suggested corrective action, and *Crash random agent* flips an agent to crashed → the orchestrator auto-restarts it ~4 s later.
- **Agent tabs** — AI-Times, Mailman, Wallstreet Wolf, Compass, Aegis, GitHub Trending — each wired to its live `/api/agent/{id}/data` endpoint with manual run/scan controls, falling back to realistic sample data until the agent first runs.

Design source bundle (prototype HTML + backend spec) is preserved under [`design/`](design/).

### Agents

| Tab | Agent | What it does |
|---|---|---|
| AI-Times | `ai_times` | 5 AI-news + 5 personality YouTube videos · daily HTML digest |
| Mailman | `mailman` | Gmail OAuth triage · LLM 7-category classification, labels/stars, key-people alerts |
| Wallstreet Wolf | `wallstreet_wolf` | 20+ ticker watchlist · gainers/losers · FX & metals · LLM commentary |
| Compass | `compass` | Sector bias (sector ETFs) + pivot key levels for /ES, /NQ & 10 majors · LLM read |
| Aegis | `aegis` | Reputation guardian — Reddit + Hacker News mentions · LLM risk/sentiment + human-approved replies |
| GitHub Trending | `devdaily` | GitHub trending + Dev.to · LLM learning digest |
| Strategy Scout | `strategy_scout` | Top trading strategies traders are running · LLM curation |
| Capitol Tracker | `capitol_tracker` | Congressional STOCK Act trades for configurable politicians · LLM commentary |
| Morning Brief | `morning_brief` | Personalized daily digest fusing the other agents' outputs |
| Options Flow | `options_flow` | Unusual options activity · IV percentile + put/call signals · LLM read |
| Earnings Calendar | `earnings_cal` | Upcoming earnings with expected move + IV-crush setups |
| Cisco Pulse | `cisco_pulse` | Cisco PSIRT advisories, ACI/NDFC intel & news via RSS · LLM summary |
| 🐺 Alpha Wolf | `alpha_wolf` | **Master agent & live decision maker** — fuses six trading sub-agents + **live quotes** into one LLM game-plan: a time-of-day session schedule (pre-market → open → midday → power hour → close), daily ideas with live-anchored entry/stop/target levels and dollar position sizing, then executes them on a simulated paper portfolio. A **"Right now" engine** scores every idea against a live market clock + quotes (WAIT / ACT NOW / STOPPED / TARGET HIT), and a **30-min pulse** emails you when a window opens or a level is hit. |

> **Compass** replaces the earlier *Market Direction* agent; **Aegis** is new (human-in-the-loop, never auto-posts). Set the brand to monitor via `AEGIS_BRAND` in `.env` (default `Anthropic`).

### Key API endpoints

```
GET  /api/state                     # full orchestrator snapshot (res, agents, llm, events, alarm)
GET  /api/system/resources          # live CPU/RAM/Disk/GPU + alarms
GET  /api/agent/{id}/data           # per-agent cached data
POST /api/agent/{id}/trigger        # manual run (devdaily/mailman/aegis accept config body)
POST /api/agent/{id}/stop
POST /api/demo/spike   {resource}   # demo: spike a resource > 90% (alarm)
POST /api/demo/crash   {agent_id?}  # demo: crash an agent → watchdog restarts it
GET  /api/demo/mode                 # demo-mode state + core (graded) agents
POST /api/demo/mode    {enabled}    # demo mode: show/schedule only the 4 graded agents
POST /api/aegis/approve {id, reply} # approve a suggested reply
POST /api/aegis/dismiss {id}
GET  /api/alpha-wolf/portfolio      # paper portfolio (equity, positions, trades)
GET  /api/alpha-wolf/now            # LIVE decision: market clock + ideas scored vs live quotes
POST /api/alpha-wolf/pulse          # run the in-session pulse check now (alerts on changes)
POST /api/alpha-wolf/execution      # toggle/size paper-trade execution
```

## Agent-4 Use-Case Proposal: GitHub Trending

**Problem:** Software engineers and developers often struggle to keep up with the fast-paced ecosystem of new repositories, tools, and technical articles published daily. Manually curating these sources is time-consuming and often leads to information overload or missing out on key industry trends.

**Solution:** I propose **Agent-4: GitHub Trending**, a specialized agent designed to solve this professional challenge. It will connect to the GitHub REST API to fetch the top trending repositories of the day and use the Dev.to API to pull the most popular programming articles. 

The local LLM will then process these disparate data sources, filtering out noise, categorizing the content by relevance (e.g., frontend, backend, AI), and generating a concise, actionable summary of the best learning opportunities. This personalized digest will be accessible via the orchestrator dashboard and sent automatically as a scheduled daily email, ensuring developers stay continuously updated with minimal friction.

## Setup Instructions

### Prerequisites
- Python 3.12+
- Node.js (for React frontend)
- Ollama with `qwen3.5:4b` installed locally (`ollama pull qwen3.5:4b`)
- API Keys: YouTube Data API v3, Gmail OAuth 2.0 (`client_secret.json`), GitHub PAT.

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
