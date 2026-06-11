# Setup Checkpoint — Multi-Agent Platform

> **Last updated:** 2026-06-04 (Session 3)
> **Goal:** Everything real — all agents live, real APIs, real outbound email. No mocks.

---

## Environment (NK-Mac, Apple Silicon)

| Item | Status |
|------|--------|
| Ollama + qwen3.5:4b | ✅ Running |
| Node v26 | ✅ OK |
| Python 3.12 (via Homebrew) | ✅ `python3.12 --version` → 3.12.1 |
| Project root | `/Users/nkhawaja/Downloads/Claud Programming/MultiAgent Platform` |

---

## Credentials — Status

| Credential | Status |
|-----------|--------|
| `YOUTUBE_API_KEY` | ✅ In .env |
| `backend/credentials.json` (Gmail OAuth) | ✅ Downloaded and placed |
| `GITHUB_TOKEN` | ✅ In .env |
| `SMTP_APP_PASSWORD` | ✅ In .env |
| `DAILY_DIGEST_EMAIL` | ⚠️ Update to `nadeem.khawaja@gmail.com` |
| `KEY_PEOPLE` | ⚠️ Update with real emails |
| Gmail test user | ✅ Added `nadeem.khawaja@gmail.com` in Google Cloud OAuth consent |

---

## .env Template

```
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=qwen3.5:4b
DAILY_DIGEST_EMAIL=nadeem.khawaja@gmail.com
SMTP_APP_PASSWORD=<16-char app password>
YOUTUBE_API_KEY=<AIza...>
KEY_PEOPLE=nadeem.khawaja@gmail.com,someone@example.com
GITHUB_TOKEN=<ghp_...>
```

---

## Agents

| Agent | Status | Notes |
|-------|--------|-------|
| Agent-1: AI-Times | ✅ Ready | YouTube Data API v3 key set |
| Agent-2: Mailman | ✅ Ready | credentials.json placed; first run opens browser for OAuth → creates token.json |
| Agent-3: Wallstreet Wolf | ✅ Ready | yfinance — no API key needed |
| Agent-4: GitHub Trending | ✅ Ready | GitHub trending + Dev.to articles |
| Agent-5: Market Direction Briefer | 🔧 Building | ES/NQ futures, VIX, Fear&Greed, LLM pre-market bias |

---

## What changed in Session 3

1. `run.sh` → renamed to `start.sh`; `stop.sh` added
2. Both backend and frontend bind to `0.0.0.0` (accessible on any network IP)
3. Full UI overhaul: futuristic neon theme (dark bg, cyan/purple neon accents, glowing rings, animated status)
4. All hardcoded `localhost:8000` replaced with dynamic `window.location.hostname`
5. Agent-5 added: Market Direction Briefer

---

## How to Run

```bash
cd "/Users/nkhawaja/Downloads/Claud Programming/MultiAgent Platform"
chmod +x start.sh stop.sh
./start.sh
# Dashboard: http://localhost:5173  (or http://<your-ip>:5173)
# API docs:  http://localhost:8000/docs
# Stop:      ./stop.sh  OR  Ctrl+C
# Logs:      logs/backend.log  logs/frontend.log
```

First Mailman run: browser opens for Gmail OAuth → approve → token.json written to backend/.

---

## Notes for next session
- Cannot launch processes on user's Mac from sandbox; guide via commands.
- User preference: concise and direct.
- Graded assignment rubric: Orchestrator + 4 required agents + demo video. Agent-5 is extra.
