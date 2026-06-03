# Multi-Agent Personal Auto-Scheduling Platform

A fully operational Multi-Agent Auto-Scheduling Platform running entirely on a local machine using a locally hosted LLM (Qwen3 via Ollama). A central orchestrator manages five specialized agents, handles resource scheduling, and serves a web-based dashboard.

## Agent-4 Use-Case Proposal: DevDaily

**Problem:** Software engineers and developers often struggle to keep up with the fast-paced ecosystem of new repositories, tools, and technical articles published daily. Manually curating these sources is time-consuming and often leads to information overload or missing out on key industry trends.

**Solution:** I propose **Agent-4: DevDaily**, a specialized agent designed to solve this professional challenge. It will connect to the GitHub REST API to fetch the top trending repositories of the day and use the Dev.to API to pull the most popular programming articles. 

The local LLM will then process these disparate data sources, filtering out noise, categorizing the content by relevance (e.g., frontend, backend, AI), and generating a concise, actionable summary of the best learning opportunities. This personalized digest will be accessible via the orchestrator dashboard and sent automatically as a scheduled daily email, ensuring developers stay continuously updated with minimal friction.

## Setup Instructions

### Prerequisites
- Python 3.12+
- Node.js (for React frontend)
- Ollama with `qwen3` (or `qwen2.5`) installed locally (`ollama run qwen3`)
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
