"""
Persistent agent memory with semantic recall.

Agents call remember() after a run to store what they reported, and recall() /
seen_before() before generating output so the LLM can reference prior context
("what changed since yesterday") and skip items already reported.

Embeddings come from a local Ollama embedding model (EMBED_MODEL, default
nomic-embed-text) so everything stays on-machine. Every operation degrades
gracefully: if the embed model is unavailable, rows are stored without a
vector and recall() falls back to most-recent-first, so memory can never
break an agent run.
"""
import os
import json
import math
from datetime import datetime

import httpx

import database
from database import Memory
from llm_client import OLLAMA_BASE_URL

EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
MAX_PER_AGENT = int(os.getenv("MEMORY_MAX_PER_AGENT", "500"))


async def embed_text(text: str):
    """Return an embedding vector for text, or None if the model is unavailable."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{OLLAMA_BASE_URL}/api/embed",
                json={"model": EMBED_MODEL, "input": text},
                timeout=30.0,
            )
            r.raise_for_status()
            vectors = r.json().get("embeddings") or []
            return vectors[0] if vectors else None
    except Exception as e:
        print(f"[Memory] embedding failed ({EMBED_MODEL}): {e}")
        return None


def cosine_similarity(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _row_to_dict(row: Memory, sim=None) -> dict:
    out = {
        "id": row.id,
        "agent_id": row.agent_id,
        "kind": row.kind,
        "text": row.text,
        "meta": json.loads(row.meta) if row.meta else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if sim is not None:
        out["similarity"] = round(sim, 4)
    return out


def _prune(db, agent_id: str):
    """Keep at most MAX_PER_AGENT rows per agent, dropping the oldest."""
    count = db.query(Memory).filter_by(agent_id=agent_id).count()
    if count <= MAX_PER_AGENT:
        return
    excess = (
        db.query(Memory)
        .filter_by(agent_id=agent_id)
        .order_by(Memory.created_at.asc(), Memory.id.asc())
        .limit(count - MAX_PER_AGENT)
        .all()
    )
    for row in excess:
        db.delete(row)


async def remember(agent_id: str, text: str, kind: str = "note", meta: dict = None) -> int:
    """Store a memory (with embedding when available). Returns the row id."""
    vector = await embed_text(text)
    db = database.SessionLocal()
    try:
        row = Memory(
            agent_id=agent_id,
            kind=kind,
            text=text,
            meta=json.dumps(meta) if meta else None,
            embedding=json.dumps(vector) if vector else None,
        )
        db.add(row)
        db.flush()  # session has autoflush=False; prune must count the new row
        _prune(db, agent_id)
        db.commit()
        return row.id
    finally:
        db.close()


def recent(agent_id: str, k: int = 5, kind: str = None) -> list:
    """Most recent memories for an agent, newest first. No embedding needed."""
    db = database.SessionLocal()
    try:
        q = db.query(Memory).filter_by(agent_id=agent_id)
        if kind:
            q = q.filter_by(kind=kind)
        rows = q.order_by(Memory.created_at.desc(), Memory.id.desc()).limit(k).all()
        return [_row_to_dict(r) for r in rows]
    finally:
        db.close()


async def recall(agent_id: str, query: str, k: int = 5, kind: str = None,
                 min_similarity: float = 0.25) -> list:
    """Memories most similar to query, best first. Falls back to recency when
    the query can't be embedded or no stored rows have vectors."""
    query_vec = await embed_text(query)
    if not query_vec:
        return recent(agent_id, k=k, kind=kind)

    db = database.SessionLocal()
    try:
        q = db.query(Memory).filter_by(agent_id=agent_id)
        if kind:
            q = q.filter_by(kind=kind)
        rows = q.all()
    finally:
        db.close()

    scored = []
    for row in rows:
        if not row.embedding:
            continue
        try:
            sim = cosine_similarity(query_vec, json.loads(row.embedding))
        except (json.JSONDecodeError, TypeError):
            continue
        if sim >= min_similarity:
            scored.append((sim, row))

    if not scored and rows:
        return recent(agent_id, k=k, kind=kind)
    scored.sort(key=lambda t: t[0], reverse=True)
    return [_row_to_dict(row, sim) for sim, row in scored[:k]]


async def seen_before(agent_id: str, text: str, threshold: float = 0.85,
                      kind: str = None) -> bool:
    """True if a stored memory is semantically near-identical to text.
    Used for duplicate suppression. Returns False when embeddings are
    unavailable (better to repeat an item than to drop a new one)."""
    matches = await recall(agent_id, text, k=1, kind=kind, min_similarity=threshold)
    return bool(matches and matches[0].get("similarity") is not None)
