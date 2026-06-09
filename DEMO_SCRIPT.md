# Demo Run Checklist — 10-Minute Video

> Rubric rule: **if any agent you show isn't working, that agent's full marks are deducted.** So: warm everything up first, keep **Demo Mode ON**, and only show the 4 graded agents + orchestrator. Product demo only — no slides.

---

## A. Pre-flight (do this BEFORE you hit record)

1. **Model ready**

   ```bash
   ollama list                 # confirm a Qwen3 model is present
   ollama pull qwen3:8b        # or set LLM_MODEL=qwen3:4b in .env for a faster demo
   ```

2. **Settings filled in** — `.env` has `DAILY_DIGEST_EMAIL`, `SMTP_APP_PASSWORD`, `YOUTUBE_API_KEY`, `GITHUB_TOKEN`, `KEY_PEOPLE`; `backend/credentials.json` present.

3. **Start the platform**

   ```bash
   cd "/Users/nkhawaja/Downloads/Claud Programming/MultiAgent Platform"
   ./start.sh
   # Dashboard → http://localhost:5173   API → http://localhost:5174/docs
   ```

   First Mailman run opens a Google OAuth window — approve it now (off-camera) so `token.json` exists.

4. **Turn ON Demo Mode** — Orchestrator tab → Demo Controls → toggle **Demo mode ON**. Sidebar collapses to the 4 graded agents; extras are paused so nothing fires mid-recording.

5. **Warm up every agent once** (this caches data and warms the LLM so first-call latency doesn't show on camera): click Run/Refresh on AI-Times, Mailman, Wallstreet Wolf, and GitHub Trending. Wait for each to finish (green/idle).

6. **Screen** — 1080p, browser zoom so text is readable. Close unrelated tabs/notifications.

---

## B. Recording order (~10 min, with time budget)

### 1. Orchestrator — "the brain" (~2:00)
- Point out **live CPU / RAM / Disk / GPU / threads** gauges updating (≤5s).
- Show the **LLM Semaphore** panel — "one permit, serialized inference, no deadlocks."
- Show the **event log** and the managed-agents grid (auto-restart on).
- **Simulate CPU > 90%** → red **alarm banner appears with a suggested corrective action** → click *Acknowledge*. (One line: "the orchestrator detects the breach and recommends a fix.")
- **Crash a random agent** → it flips to crashed → **watchdog auto-restarts it ~4s later** without restarting the platform. (This is your resource/deadlock/zombie-handling story — narrate it.)

### 2. Agent-1 · AI-Times (~1:30)
- Open tab → **Refresh** → show **5 AI-news + 5 personality** videos (thumbnail, title, channel, date) from the last 24–48h.
- Mention: YouTube Data API v3 + daily HTML digest email on a schedule.

### 3. Agent-2 · Mailman (~1:30)
- **Run scan** → show the **7-category** breakdown (Urgent / Action Required / Follow-Up / Newsletter / Notification / Personal / Other) and the per-email **AI summaries**.
- Flip to Gmail for 5s → show the **labels + stars** applied and a **key-people alert**.
- Mention: Gmail OAuth 2.0 + daily summary.

### 4. Agent-3 · Wallstreet Wolf (~1:30)
- Open tab → show **Top 5 Gainers / Top 5 Losers / full 20+ watchlist**, the **FX pairs + Gold/Silver** section, and the **LLM market commentary** card.
- Mention: live Yahoo Finance + daily market-brief email.

### 5. Agent-4 · GitHub Trending (Your Choice) (~1:30)
- Set a **configurable parameter** (e.g., language = `python`, count = 5) → **Run**.
- Show **GitHub trending + Dev.to articles + the local-LLM summary** in one digest.
- Mention: two external APIs + one LLM step + scheduled daily email — and that it solves a real "keep up with the dev ecosystem" problem.

### 6. Close (~0:30)
- One line that ties it together: **everything runs locally** — Qwen3 via Ollama (point at the model name on the dashboard), SQLite for caching/persistence, no hosted LLM APIs.

---

## C. On-camera reminders
- Keep **Demo Mode ON** the whole time — don't open the bonus agents.
- If an agent looks slow, you already warmed it in pre-flight; give the LLM a beat and narrate the semaphore queue.
- Don't show errors or the terminal stack traces. If something misfires, cut and retake that segment.
- Stay **under 10:00** — anything over is marked 0. Practice once with a timer.
- Upload to **YouTube** and submit the link.

## D. Mention-but-don't-dwell (creativity, ~10s if time allows)
- "Beyond the four graded agents, the platform also runs seven bonus agents — e.g., a Cisco Pulse NetOps agent tied to my day job — hidden here in demo mode for a clean run." Then move on.
