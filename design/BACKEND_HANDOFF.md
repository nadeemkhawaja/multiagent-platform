# Multi-Agent Auto-Scheduling Platform — Backend Implementation Guide

This document is the build spec for the **backend** that powers the dashboard prototype
(`Multi-Agent Platform.html`). The prototype is the source of truth for UI, data shapes, and
behavior; this guide tells you how to produce that data for real, on a local machine, with a
locally-hosted LLM.

> **How to use this with Claude / Claude Code:** paste this file in, then build module by module
> in the order under [§12 Build Order](#12-build-order). Each agent section lists its external API,
> its LLM step, its schedule, and the **exact JSON contract** the matching dashboard tab consumes.
> Match those shapes and the existing front-end will light up without changes.

---

## 1. Goals & Constraints

| Requirement | Decision |
|---|---|
| Local LLM only — no hosted APIs | **Ollama** running `qwen3` (e.g. `qwen3.5:4b` or `qwen3:14b`) |
| All inference local | Every LLM call goes through `llm.generate()` → `http://localhost:11434` |
| Persistent storage | **SQLite** (`platform.db`) via SQLAlchemy |
| Backend language | **Python 3.12**, async (FastAPI + asyncio) |
| Frontend | The existing HTML/React dashboard (served as static files) |
| Dashboard refresh | ≤ 5 s — use **WebSocket** push (fallback: poll `/api/state` every 2 s) |
| Resource alarm | Raise when CPU/RAM/Disk/GPU > 90 %, surface suggested action |
| LLM concurrency | **One permit semaphore** — only one agent calls the model at a time |
| Resilience | Supervisor restarts crashed agents without restarting the platform |

---

## 2. Tech Stack

```
Python 3.12
├── fastapi + uvicorn        # API + WebSocket + static hosting
├── sqlalchemy (+ aiosqlite) # ORM over SQLite
├── apscheduler              # cron-style agent scheduling
├── psutil                   # CPU / RAM / disk / threads
├── pynvml (optional)        # GPU/VRAM usage for the LLM card
├── httpx                    # async HTTP (Ollama + external APIs)
├── pydantic / pydantic-settings  # config + response models
├── google-api-python-client + google-auth-oauthlib  # Gmail, YouTube
├── yfinance                 # Yahoo Finance (Wallstreet Wolf)
└── jinja2 + aiosmtplib      # HTML email rendering + sending
```

Local services: **Ollama** (`ollama serve`, model pulled via `ollama pull qwen3`).

---

## 3. Project Structure

```
platform/
├── main.py                  # FastAPI app, mounts API + static dashboard
├── config.py                # pydantic-settings, reads .env
├── db.py                    # SQLAlchemy engine/session, models
├── llm.py                   # Ollama client + the LLM semaphore
├── orchestrator/
│   ├── supervisor.py        # agent registry, lifecycle, restart
│   ├── monitor.py           # psutil/pynvml sampling + alarm logic
│   └── scheduler.py         # APScheduler wiring
├── agents/
│   ├── base.py              # Agent ABC (run(), schedule, state)
│   ├── ai_times.py          # Agent-1
│   ├── mailman.py           # Agent-2
│   ├── wolf.py              # Agent-3
│   ├── compass.py           # Agent-4
│   └── aegis.py             # Agent-5
├── api/
│   ├── routes.py            # REST endpoints (see §11)
│   └── ws.py                # WebSocket broadcaster
├── email/templates/*.html   # Jinja2 digests
└── dashboard/               # the built HTML/JS prototype (static)
```

---

## 4. Database Schema (SQLite)

```sql
-- agent run history & current status
CREATE TABLE agent_runs (
  id INTEGER PRIMARY KEY, agent_id TEXT, started_at TEXT, finished_at TEXT,
  status TEXT, tokens INTEGER, error TEXT
);
CREATE TABLE agent_state (
  agent_id TEXT PRIMARY KEY, status TEXT, last_run TEXT, next_run TEXT,
  restarts INTEGER DEFAULT 0, schedule TEXT
);

-- resource samples (ring/sparkline history; keep last ~24)
CREATE TABLE resource_samples (
  ts TEXT, cpu REAL, ram REAL, disk REAL, gpu REAL, threads INTEGER
);

-- orchestrator event log
CREATE TABLE events (ts TEXT, message TEXT, level TEXT);

-- Agent-1 AI-Times
CREATE TABLE videos (
  video_id TEXT PRIMARY KEY, set_type TEXT,  -- 'news' | 'personality'
  title TEXT, channel TEXT, duration TEXT, views TEXT,
  published_at TEXT, thumbnail_url TEXT, fetched_at TEXT
);

-- Agent-2 Mailman
CREATE TABLE emails (
  msg_id TEXT PRIMARY KEY, sender TEXT, sender_email TEXT, subject TEXT,
  category TEXT, summary TEXT, starred INTEGER, is_key_person INTEGER,
  received_at TEXT, classified_at TEXT
);
CREATE TABLE key_people (name TEXT PRIMARY KEY, email TEXT);

-- Agent-3 Wolf
CREATE TABLE quotes (
  symbol TEXT, name TEXT, price REAL, change_pct REAL, ts TEXT
);

-- Agent-4 Compass
CREATE TABLE sector_bias (sector TEXT, score INTEGER, rationale TEXT, ts TEXT);
CREATE TABLE key_levels (
  symbol TEXT, kind TEXT,  -- 'future' | 'stock'
  price REAL, pivot REAL, r1 REAL, r2 REAL, s1 REAL, s2 REAL, bias TEXT, ts TEXT
);
CREATE TABLE news_sentiment (source TEXT, headline TEXT, sentiment TEXT, ts TEXT);

-- Agent-5 Aegis
CREATE TABLE mentions (
  id TEXT PRIMARY KEY, source TEXT, sub TEXT, author TEXT, text TEXT,
  risk TEXT, sentiment INTEGER, reason TEXT, suggested_reply TEXT,
  status TEXT,  -- 'new' | 'approved' | 'dismissed'
  created_at TEXT
);
```

---

## 5. Local LLM + the Semaphore (`llm.py`)

The single most important orchestration rule: **only one agent may call the model at a time.**
Use one asyncio semaphore with a single permit. Every call acquires it, so the model is never
contended and there is no deadlock (single resource, no circular waits).

```python
import httpx, asyncio, time

_PERMIT = asyncio.Semaphore(1)        # exactly one concurrent LLM call
_state = {"holder": None, "queue": [], "held_s": 0.0, "tokens": 0, "rate": 0}

async def generate(agent_id: str, prompt: str, *, system: str = "", json_mode=False) -> str:
    _state["queue"].append(agent_id)
    async with _PERMIT:                # blocks here while another agent holds it
        _state["queue"].remove(agent_id)
        _state["holder"] = agent_id
        t0 = time.time()
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post("http://localhost:11434/api/generate", json={
                "model": "qwen3", "prompt": prompt, "system": system,
                "stream": False, **({"format": "json"} if json_mode else {})
            })
        data = r.json()
        _state["held_s"] = round(time.time() - t0, 1)
        _state["tokens"] = data.get("eval_count", 0)
        _state["holder"] = None
        return data["response"]
```

`_state` feeds the dashboard's **LLM Semaphore** panel. Broadcast it on change.
Deadlock prevention notes: a single global lock with strict acquire→use→release ordering and a
**hard timeout** (120 s) on the HTTP call guarantees the permit is always released; wrap the body
in `try/finally` if you add early returns.

**Prompt patterns** (keep system prompts terse; Qwen3 follows JSON-mode well):
- *Mailman classify:* "Classify this email into exactly one of: Urgent, Action Required, Follow-Up, Newsletter, Notification, Personal, Other. Return JSON `{category, summary}` where summary ≤ 25 words."
- *Wolf commentary:* feed the gainers/losers table, ask for a 3-4 sentence risk-on/off read.
- *Compass bias:* feed headlines + sector tags, ask for `{sector, score:-100..100, rationale}` per sector.
- *Aegis:* "Given this public mention, return JSON `{risk: high|med|low, sentiment:-100..100, reason, suggested_reply}`. The reply is a calm, factual draft for human approval — never inflammatory."

---

## 6. Orchestrator — Monitor & Alarm (`monitor.py`)

Sample every 2 s, store to `resource_samples`, broadcast. Alarm logic:

```python
THRESH = 90
ACTIONS = {
  "cpu": "Throttle Wolf's 5-min poll and pause non-critical agents until load < 75%.",
  "ram": "Flush LLM KV-cache and reduce Qwen3 context window to free memory.",
  "gpu": "Queue depth high — serialize inference further and lower batch size.",
  "disk":"Rotate logs and clear cached thumbnails/emails older than 7 days.",
}
def check_alarm(s):
    for k in ("cpu","ram","gpu","disk"):
        if s[k] >= THRESH:
            return {"resource": k, "value": s[k], "label": k.upper(), "action": ACTIONS[k]}
    return None
```

`cpu = psutil.cpu_percent()`, `ram = psutil.virtual_memory().percent`,
`disk = psutil.disk_usage('/').percent`, `threads = sum(p.num_threads() ...)` or process-local,
`gpu` via `pynvml` (utilization) — if no NVML, approximate from Ollama activity or report `null`.

---

## 7. Orchestrator — Supervisor (`supervisor.py`)

- Registry of agents; each has `id, schedule, status, next_run, restarts`.
- Wrap every agent `run()` in a guard: on exception → `status="crashed"`, log event,
  remove it from the LLM queue, then **schedule a restart** a few seconds later
  (`status="running"`, `restarts += 1`) — the rest of the platform keeps running.
- Persist status to `agent_state`; broadcast every transition (drives nav status dots + Agents grid/table).

```python
async def supervised(agent):
    try:
        agent.status = "running"; broadcast()
        await agent.run()
        agent.status = "idle"; agent.record_run()
    except Exception as e:
        agent.status = "crashed"; log(f"✕ {agent.name} crashed: {e}", "error")
        llm.drop_from_queue(agent.id)
        asyncio.get_event_loop().call_later(4, lambda: restart(agent))
```

---

## 8. The Agents

Each agent: `run()` does **fetch (external API) → LLM step → persist → (scheduled) email/alert**.
Schedules are configurable (stored in `agent_state.schedule`, editable from the UI later).

### Agent-1 · AI-Times  (`#e5484d`)
- **API:** YouTube Data API v3 (`search.list` + `videos.list`). Two queries → 5 **news** + 5 **personality/interview** videos from the last 24-48 h.
- **LLM step:** (optional) summarize/curate which 5 are most relevant.
- **Scheduled action:** render `ai_times_digest.html` (Jinja2) and email daily at `08:00` via SMTP.
- **Dashboard contract** (`GET /api/ai-times`):
```json
{ "news": [ {"id","title","channel","duration","views","date","thumbnail"} x5 ],
  "personality": [ {...} x5 ],
  "digest": {"scheduled":"08:00","last_sent":"08:00","recipient":"you@gmail.com"} }
```

### Agent-2 · Mailman  (`#2f6feb`)
- **API:** Gmail API via **OAuth 2.0** (`gmail.readonly` + `gmail.modify` for labels/stars).
- **LLM step:** classify each new email → one of 7 categories + ≤25-word summary.
- **Side effects:** apply a Gmail label per category, **star** Urgent + key-people mail, raise an alert when a key person emails.
- **Scheduled action:** scan every 15 min; daily summary email at `08:05`.
- **Dashboard contract** (`GET /api/mailman`):
```json
{ "categories": [ {"k":"Urgent","n":3,"c":"#e5484d"}, ... ],
  "emails": [ {"id","from","email","subj","cat","star":true,"key":true,"sum","t"} ],
  "key_people": ["Sarah Chen", ...],
  "summary": {"sent":"08:05","total":65,"urgent":3,"action":7,"archived":22} }
```
- **Actions:** `POST /api/mailman/scan`, `POST /api/mailman/star {id}`.

### Agent-3 · Wallstreet Wolf  (`#16a34a`)
- **API:** Yahoo Finance via `yfinance` — 22-symbol watchlist, live + historical. FX pairs + Gold/Silver (`EURUSD=X`, `GC=F`, `SI=F`, …).
- **LLM step:** market commentary card from the gainers/losers snapshot.
- **Scheduled action:** daily market brief email at `16:30`.
- **Dashboard contract** (`GET /api/wolf`):
```json
{ "watch": [ {"t":"NVDA","n":"NVIDIA","p":1284.30,"ch":4.82}, ... 22 ],
  "fx":     [ {"p":"EUR/USD","v":1.0942,"ch":0.18}, ... ],
  "metals": [ {"p":"Gold","sym":"XAU/USD","v":2418.60,"ch":0.88}, {"Silver"...} ],
  "commentary": "Risk-on tone as semis lead ...",
  "brief": {"scheduled":"16:30"} }
```
Top-5 gainers/losers are derived on the client by sorting `watch` on `ch` (or precompute server-side).

### Agent-4 · Compass  (`#f59e0b`)
- **API:** a news API (Finnhub / NewsAPI / RSS) for headlines; price feed for pivot math (reuse yfinance).
- **LLM step:** (a) per-sector directional **bias score** −100..+100 with rationale, (b) per-headline sentiment, (c) a short composite "read".
- **Key levels (computed, not LLM):** classic floor-trader pivots from prior session H/L/C —
  `pivot=(H+L+C)/3`, `R1=2*pivot−L`, `S1=2*pivot−H`, `R2=pivot+(H−L)`, `S2=pivot−(H−L)` —
  for **/ES** and **/NQ** futures and 10 majors (NVDA, MSFT, AAPL, AMZN, GOOGL, META, TSLA, AMD, AVGO, NFLX).
- **Scheduled action:** pre-market brief / bias alert at `07:00`.
- **Dashboard contract** (`GET /api/compass`):
```json
{ "sectors": [ {"k":"Technology","bias":64,"why":"..."}, ... ],
  "news":    [ {"src":"Reuters","t":"...","s":"bull|bear|neutral","min":"22m"} ],
  "futures": [ {"t":"/ES","n":"E-mini S&P 500","px":5948.5,"piv":5942,"r1":5967,"r2":5988,"s1":5921,"s2":5896,"bias":"bull"}, {"/NQ"...} ],
  "levels":  [ {"t":"NVDA","px":1284,"piv":1271,"r1":1308,"s1":1244,"bias":"bull"}, ... 10 ],
  "read": "Tone leans constructive ...", "brief": {"scheduled":"07:00"} }
```

### Agent-5 · Aegis  (`#0d9488`)  — Reputation Guardian
- **API:** mention sources you *legitimately* have access to — your own Page/profile mentions, plus a public search API (Reddit, Mastodon, a news/HN endpoint). **Do not** scrape or auto-post on arbitrary third-party content; this agent is **human-in-the-loop**.
- **LLM step:** per mention → `{risk, sentiment, reason, suggested_reply}`. The reply is a **draft only**.
- **Side effects:** real-time alert on a high-risk mention; daily reputation digest at `18:00`. Posting a reply requires explicit user approval in the UI (then your code posts via the source's official API where permitted).
- **Dashboard contract** (`GET /api/aegis`):
```json
{ "stats": {"mentions":27,"net_sentiment":-21,"high_risk":1,"avg_response":"12m"},
  "mentions": [ {"id","src":"Reddit","sub":"r/startups","author","text","risk":"high","sent":-78,"why","reply"} ] }
```
- **Actions:** `POST /api/aegis/scan`, `POST /api/aegis/approve {id, reply}`, `POST /api/aegis/dismiss {id}`.

---

## 9. Scheduling (`scheduler.py`)

Use APScheduler with an asyncio executor. Each agent gets an interval/cron trigger; every fire goes
through the supervisor (so crashes are caught) and the LLM step goes through the semaphore (so the
model is never double-called).

```python
sched.add_job(lambda: supervised(mailman), "interval", minutes=15)
sched.add_job(lambda: supervised(wolf),    "interval", minutes=5)
sched.add_job(lambda: supervised(compass), "interval", minutes=30)
sched.add_job(lambda: supervised(aegis),   "interval", minutes=10)
sched.add_job(lambda: supervised(ai_times),"cron", hour=8)
# email jobs
sched.add_job(send_wolf_brief, "cron", hour=16, minute=30)
```

---

## 10. Email (SMTP)

Render Jinja2 HTML templates, send via `aiosmtplib` (Gmail SMTP with an app password, or any relay).
Keep one template per agent digest. Store `last_sent` so the dashboard can show "Sent today 08:00".

---

## 11. API Surface (`api/routes.py` + `ws.py`)

```
GET  /api/state              # orchestrator snapshot: res, threads, agents[], llm{}, events[], alarm
GET  /api/ai-times           GET /api/mailman      GET /api/wolf
GET  /api/compass            GET /api/aegis
POST /api/mailman/scan       POST /api/mailman/star
POST /api/aegis/scan         POST /api/aegis/approve     POST /api/aegis/dismiss
POST /api/demo/spike {resource}     POST /api/demo/crash {agent_id}   # optional, drives the demo buttons
WS   /ws                     # pushes {type:'state'|'aitimes'|...} payloads on change (≤5s)
```

`/api/state` must match the prototype's `Sim.state` shape:
```json
{ "res": {"cpu":{"v":38,"hist":[...]}, "ram":{...}, "disk":{...}, "gpu":{...}},
  "threads": 42,
  "agents": [ {"id","n","glyph","desc","status","cpu","mem","nextS","schedule","restarts"} x5 ],
  "llm": {"holder":"wolf","heldS":1.8,"tokens":612,"rate":34,"queue":["mailman","aegis"]},
  "events": [ {"t":"08:12","m":"...","c":"#16a34a"} ],
  "alarm": null }
```

Wire the front-end by replacing the in-browser `Sim` (in `data.jsx`) with a thin client that
hydrates from `/api/state` and updates on `/ws` messages — the components already read this shape.

---

## 12. Build Order

1. **Skeleton:** FastAPI + static hosting of the dashboard + SQLite + config.
2. **`llm.py`:** Ollama call + the 1-permit semaphore + `/api/state.llm`.
3. **Monitor + WebSocket:** psutil sampling → `/ws` → live rings/sparklines + alarm.
4. **Supervisor + scheduler:** agent lifecycle, crash→restart, event log.
5. **Agent-3 Wolf** (easiest external API — `yfinance`, no OAuth) end-to-end incl. email.
6. **Agent-1 AI-Times** (YouTube key) → **Agent-4 Compass** (news + pivots).
7. **Agent-2 Mailman** (Gmail OAuth — the heaviest auth) with labels/stars.
8. **Agent-5 Aegis** (mention sources + approval flow).
9. **Demo endpoints** (`/api/demo/*`) so the dashboard's alarm/crash buttons hit the real supervisor.
10. Swap the front-end `Sim` for the live API client; verify each tab against its contract in §8.

---

## 13. Configuration (`.env`)

```
OLLAMA_MODEL=qwen3
YOUTUBE_API_KEY=...
GMAIL_OAUTH_CLIENT=client_secret.json
NEWS_API_KEY=...
SMTP_HOST=smtp.gmail.com
SMTP_USER=you@gmail.com
SMTP_PASS=app-password
DIGEST_RECIPIENT=you@gmail.com
KEY_PEOPLE=Sarah Chen,Marcus Webb,David Okafor
```

## 14. Run

```bash
ollama serve & ollama pull qwen3
uvicorn main:app --reload --port 8787
# dashboard at http://localhost:8787
```

---

### Front-end ↔ backend mapping cheat-sheet

| Dashboard tab | Endpoint | Agent module |
|---|---|---|
| Orchestrator | `/api/state` + `/ws` | `orchestrator/*` |
| AI-Times | `/api/ai-times` | `agents/ai_times.py` |
| Mailman | `/api/mailman` | `agents/mailman.py` |
| Wallstreet Wolf | `/api/wolf` | `agents/wolf.py` |
| Compass | `/api/compass` | `agents/compass.py` |
| Aegis | `/api/aegis` | `agents/aegis.py` |

The prototype's `data.jsx` contains realistic example rows for every one of these shapes — use it as
your fixture data and golden reference while building.
