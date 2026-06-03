# Multi-Agent Personal Auto-Scheduling Platform — Complete Handoff

> **Last updated:** 2026-06-03 | **Status:** Core structure complete, 12 gaps identified

---

## 1. Project Overview

Build a Multi-Agent Auto-Scheduling Platform with a central orchestrator managing 4 specialized agents, all running locally with a local LLM (Qwen via Ollama). The project is graded out of 100 marks.

### Grading Rubric
| # | Deliverable | Marks |
|---|---|---|
| 1 | Orchestrator & Architecture | 15 |
| 2 | AI-Times | 15 |
| 3 | Mailman | 15 |
| 4 | Wallstreet Wolf | 15 |
| 5 | Agent-4 (DevDaily) | 15 |
| 6 | Code Quality, Repo & Creativity | 10 |
| 7 | Demo Video (max 10 min, YouTube) | 15 |

---

## 2. Tech Stack (Finalized)
- **Backend:** Python 3.12, FastAPI, APScheduler, SQLAlchemy (SQLite)
- **Frontend:** React (Vite), Vanilla CSS (dark glassmorphism theme)
- **LLM:** Ollama on `localhost:11434`, model `qwen2.5` (or `qwen3`)
- **Ports:** Backend `:8000`, Frontend `:5173`, Ollama `:11434`
- **Version Control:** Git (local repo initialized, 3 commits so far)

---

## 3. File Structure
```
MultiAgent Platform/
├── .env.example          # API keys template
├── .gitignore
├── README.md             # Setup instructions + 150-word Agent-4 proposal
├── architecture.mmd      # Mermaid source
├── architecture.png      # Rendered diagram
├── requirements.txt      # Python deps
├── handoff.md            # THIS FILE
│
├── backend/
│   ├── main.py           # FastAPI app, lifespan, scheduler, all endpoints
│   ├── database.py       # SQLite engine, AgentData + SystemLog models
│   ├── llm_client.py     # Ollama wrapper with asyncio.Semaphore(1)
│   ├── orchestrator.py   # psutil resource monitoring, agent status tracking
│   └── agents/
│       ├── __init__.py
│       ├── agent1_ai_times.py       # YouTube Data API v3
│       ├── agent2_mailman.py        # Gmail OAuth 2.0 + LLM classification
│       ├── agent3_wallstreet_wolf.py # yfinance (20 stocks + metals + forex)
│       └── agent4_devdaily.py       # GitHub API + Dev.to API + LLM summary
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx                  # Sidebar nav + tab routing
        ├── index.css                # Full design system (dark, glass, animations)
        └── components/
            ├── OrchestratorDashboard.jsx  # CPU/RAM/Disk/Thread gauges + alarm
            └── AgentTabs.jsx              # All 4 agent views + manual trigger
```

---

## 4. Key Architecture Decisions

### LLM Semaphore (Deadlock Prevention)
```python
# backend/llm_client.py
llm_semaphore = asyncio.Semaphore(1)

async def generate_completion(prompt, system_prompt="..."):
    async with llm_semaphore:  # Only 1 agent at a time
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", ...)
            return response.json()["message"]["content"]
```

### Agent Scheduling (APScheduler)
```python
# backend/main.py — inside lifespan()
scheduler.add_job(ai_times_job, 'cron', hour=8, minute=0, id='ai_times')
scheduler.add_job(mailman_job, 'interval', minutes=15, id='mailman')
scheduler.add_job(wallstreet_wolf_job, 'cron', hour=17, minute=0, id='wallstreet_wolf')
scheduler.add_job(devdaily_job, 'cron', hour=9, minute=0, id='devdaily')
```

### System Monitoring
```python
# backend/orchestrator.py
def get_system_resources():
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage('/').percent,
        "active_threads": psutil.Process().num_threads(),
        "alarm": cpu > 90 or ram > 90 or disk > 90
    }
```

### API Endpoints
```
GET  /api/system/resources       → Live CPU/RAM/Disk/Threads
GET  /api/system/agents          → All agent statuses
GET  /api/agent/{name}/data      → Cached data for a specific agent
POST /api/agent/{name}/trigger   → Manually run an agent
POST /api/test-llm               → Test LLM connectivity
```

---

## 5. Agent Summary

| Agent | External APIs | LLM Usage | Email | Schedule |
|---|---|---|---|---|
| AI-Times | YouTube Data API v3 | None currently | STUBBED | Daily 8:00 AM |
| Mailman | Gmail API (OAuth 2.0) | Classifies into 7 categories | STUBBED | Every 15 min |
| Wallstreet Wolf | Yahoo Finance (yfinance) | Market commentary | STUBBED | Daily 5:00 PM |
| DevDaily | GitHub REST API + Dev.to API | Learning digest summary | STUBBED | Daily 9:00 AM |

---

## 6. CRITICAL GAPS — Must Fix Before Demo

### Gap 1: No Crashed Agent Auto-Restart
The orchestrator does NOT detect or restart crashed agents. Need a watchdog loop.

### Gap 2: ALL Email Sending is Stubbed
All 4 agents have `print("Would send email...")` instead of actual SMTP/Gmail sending.

### Gap 3: Mailman Missing "AI Summaries"
PDF requires LLM-generated summaries per email. Currently only shows Gmail's raw snippet.

### Gap 4: Mailman Has No Daily Summary Email
PDF requires a daily summary email from Mailman. Not implemented.

### Gap 5: Wallstreet Wolf Email is Stubbed
Same as Gap 2.

### Gap 6: DevDaily Has No Real Automated Action
Only does a cache refresh. Needs actual email or alert.

### Gap 7: DevDaily Has No "User Configurable Parameters" in UI
PDF explicitly requires this for Agent-4. No config inputs exist on the dashboard.

### Gap 8: `fade-in` CSS Class Missing
Both main components reference `className="fade-in"` but it's not in `index.css`.

### Gap 9: Alarm Not Resource-Specific
Shows generic message. PDF wants specific corrective action per resource.

### Gap 10: `last_run` Timestamp Never Updated
Always shows `null`.

### Gap 11: Wallstreet Wolf Missing "Full Watchlist" Block
PDF requires Block 3 — complete watchlist table. Only Top 5 Gainers/Losers are shown.

### Gap 12: Security Issues
- CORS `allow_origins=["*"]` should be `["http://localhost:5173"]`
- Bare `except:` clauses

---

## 7. Priority Order for Next Session

| Priority | What | Why |
|---|---|---|
| 🔴 P0 | Implement real email sending (shared utility) | Affects all 4 agents |
| 🔴 P0 | Add crashed agent watchdog + restart | Orchestrator rubric |
| 🔴 P0 | Add LLM AI summaries to Mailman | Mailman rubric |
| 🟡 P1 | Add Full Watchlist table to Wolf tab | Wolf rubric |
| 🟡 P1 | Add user config params to DevDaily | Agent-4 rubric |
| 🟡 P1 | Per-resource alarm messages | Orchestrator rubric |
| 🟢 P2 | Fix fade-in CSS, last_run, CORS | Polish & code quality |

---

## 8. How to Run

### Prerequisites
- Python 3.12+, Node.js, Ollama installed
- Run `ollama run qwen2.5` in a separate terminal

### Backend
```bash
cd "MultiAgent Platform"
source venv/bin/activate
cp .env.example .env   # Fill in API keys
cd backend
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd "MultiAgent Platform/frontend"
npm install
npm run dev   # Opens on http://localhost:5173
```

### Required API Keys (.env)
```
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5
YOUTUBE_API_KEY=<from Google Cloud Console>
DAILY_DIGEST_EMAIL=<your Gmail address>
GITHUB_TOKEN=<GitHub Personal Access Token>
```
For Gmail OAuth: Place `credentials.json` from Google Cloud Console in `backend/`.
