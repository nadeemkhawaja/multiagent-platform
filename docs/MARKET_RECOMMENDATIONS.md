# Market-Based Improvement Recommendations

*Last updated: June 2026*

This document compares the platform against the current multi-agent landscape
(LangGraph, CrewAI, AutoGen/AG2, OpenAI Agents SDK, Anthropic Agent SDK, n8n 2.0,
Zapier Agents) and recommends where to invest next.

## Where the platform stands

**Strengths worth protecting** — these are genuine differentiators, not gaps:

- **Local-first / data sovereignty.** Everything runs on one machine with a local
  LLM (Ollama/Qwen3). This is exactly the positioning n8n 2.0 leaned into for its
  2026 release ("full data sovereignty"), and it differentiates against
  cloud-only platforms like Zapier Agents.
- **Operational reliability.** Watchdog auto-restart, semaphore-serialized LLM
  access, durable run history, and a live resource dashboard are stronger ops
  ergonomics than most open-source frameworks ship out of the box.
- **Real working agents.** 13 domain agents with real integrations (Gmail,
  YouTube, yfinance, Reddit, Congress feeds) — most frameworks ship toy examples.

**Structural gaps vs. the market** (from the codebase survey):

| Capability | Status here | Market baseline (2026) |
|---|---|---|
| Tool/function calling | Hardcoded HTTP per agent | Pluggable tool registries everywhere (n8n Tool Nodes, CrewAI tools, vendor SDKs) |
| MCP support | None | 10,000+ public servers; adopted by OpenAI, Google, Microsoft; Linux Foundation standard |
| LLM providers | Ollama only | Provider-agnostic is table stakes; vendor SDKs ship tool use + tracing natively |
| Memory / RAG | None (re-fetch each run) | n8n 2.0 ships persistent agent memory + vector DB integration |
| Agent communication | Flat supervisor, no agent-to-agent | Graphs (LangGraph), handoffs (OpenAI SDK), conversations (AutoGen) |
| Streaming | `stream: False` | Full/per-node token streaming standard across frameworks |
| Tracing & cost metrics | Dashboard telemetry only | Run-level traces, token/cost/latency breakdowns (LangSmith, built-in vendor tracing) |
| Human-in-the-loop | One-off (Aegis approvals) | First-class framework primitive (LangGraph's key selling point) |
| Deployment | start.sh / stop.sh | Docker is table stakes |
| Guardrails | HTML escaping, JSON mode | Prompt-injection defenses, output validation, approval layers |

## Recommendations, in priority order

### 1. Add MCP client support (highest leverage)

MCP is the clearest market signal of the past year: 10k+ public servers, 97M+
monthly SDK downloads, donated to the Linux Foundation, and adopted by every
major vendor. For this platform it solves a concrete internal problem: every
agent currently hand-rolls its API integrations (`agents/agent1_ai_times.py`
through `agent13`). An MCP client layer would let agents consume Gmail, GitHub,
market-data, and thousands of community servers through one protocol instead of
bespoke `httpx` code — and Zapier already exposes 30,000+ actions via its MCP
server, which this platform could consume directly.

*Scope:* an `mcp_client.py` alongside `llm_client.py`, plus a config table for
registered servers. Migrate one agent (Mailman → Gmail MCP server) as proof.

### 2. Introduce a provider-abstraction layer for LLMs

`llm_client.py` is hardcoded to Ollama. Keep local-first as the *default*, but
abstract the client so a per-agent model choice is possible (e.g. local Qwen3
for routine summarization, a frontier API model for the Morning Brief
synthesis). Every framework in the 2026 comparisons treats provider-agnosticism
as table stakes, and it unblocks two other items cheaply: streaming responses
(currently `stream: False`) and per-run token/cost accounting.

### 3. Extract a real tool registry

Before adding more agents, factor the per-agent API calls into declared,
reusable tools (a `tools/` package with typed signatures). This is the
architectural pattern shared by every surveyed framework — n8n's AI Agent node
composes tools, CrewAI agents declare them, vendor SDKs schema-validate them.
It also makes MCP integration (#1) natural: MCP servers just become another
tool source. The 13 agents currently duplicate fetch/parse/retry logic that a
registry would centralize.

### 4. Persistent agent memory + lightweight RAG

Agents currently have amnesia — every run re-fetches and re-summarizes from
scratch. n8n 2.0's headline features were persistent agent memory and vector-DB
RAG. Concretely valuable here: Wolf and Compass could reference prior market
analyses ("VIX regime changed since yesterday"), Aegis could learn from past
approved/dismissed replies, and Morning Brief could deduplicate against what it
already reported. A local embedding model via Ollama + SQLite-vec (or Chroma)
keeps this consistent with the local-first story.

### 5. Run-level tracing and cost metrics

The dashboard shows machine telemetry (CPU/GPU/tokens-per-second) but not
*agent* telemetry: per-run token counts, latency breakdown (fetch vs. LLM vs.
send), success rates over time. Observability is the most-cited 2026 gap in
agent platforms generally — teams are inventing their own because no protocol
mandates it. The `agent_runs` table is already in place; extend it with token
and stage-timing columns and surface trends in the dashboard.

### 6. Generalize human-in-the-loop into a primitive

Aegis already has the right idea (suggest, never auto-post, approve via UI).
Promote that pattern into an orchestrator-level `approval` primitive any agent
can use — e.g. Mailman drafts requiring sign-off before send. Human-in-the-loop
is LangGraph's flagship production feature; this platform can match it with
modest effort because the WebSocket + dashboard plumbing already exists.

### 7. Docker packaging

A `docker-compose.yml` (backend + frontend + Ollama) replaces `start.sh`/`stop.sh`
and makes the project shareable/reproducible. Pure table stakes; low effort.

## Deliberately deprioritized

- **Graph-based orchestration (LangGraph-style):** the agents are independent
  scheduled monitors, not collaborative workflows. Adopting graph orchestration
  would add abstraction tax (the same critique leveled at heavy frameworks —
  CrewAI carries up to 3× token overhead vs. leaner approaches) without a
  driving use case. Revisit only if agents start needing to delegate to each
  other.
- **A2A protocol:** still converging; MCP first.
- **Cloud/multi-tenant deployment:** would dilute the local-first
  differentiator. Docker (#7) is enough.

## Sources

- [AI Agent Frameworks Compared: LangGraph vs CrewAI vs AutoGen (2026)](https://pecollective.com/blog/ai-agent-frameworks-compared/)
- [2026 AI Agent Framework Showdown — QubitTool](https://qubittool.com/blog/ai-agent-framework-comparison-2026)
- [Best open source frameworks for building AI agents in 2026 — Firecrawl](https://www.firecrawl.dev/blog/best-open-source-agent-frameworks)
- [MCP Adoption Statistics 2026](https://www.digitalapplied.com/blog/mcp-adoption-statistics-2026-model-context-protocol)
- [Everything your team needs to know about MCP in 2026 — WorkOS](https://workos.com/blog/everything-your-team-needs-to-know-about-mcp-in-2026)
- [Agent Interoperability Protocols 2026: MCP, A2A, ACP — Zylos Research](https://zylos.ai/research/2026-03-26-agent-interoperability-protocols-mcp-a2a-acp-convergence/)
- [n8n vs Zapier: The Definitive 2026 Automation Face-Off — HatchWorks](https://hatchworks.com/blog/ai-agents/n8n-vs-zapier/)
- [What is n8n? The Ultimate 2026 Workflow Automation & AI Guide](https://www.ai.cc/blogs/what-is-n8n-automation-guide-2026/)
- [Zapier vs Make vs n8n in 2026 — Automation Labs](https://medium.com/@automation.labs/zapier-vs-make-vs-n8n-in-2026-where-ai-agents-actually-fit-1edbbeff85f3)
