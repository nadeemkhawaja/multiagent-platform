"""
Persistent agent memory (recency-based).

Agents call remember() after a run to store what they reported, and recent()
before generating output so the LLM can reference prior context ("what
changed since yesterday"). recall() and seen_before() are kept for API
compatibility but are recency-based, not semantic — there's no local
embedding model in this stack.
"""
import os
import json

import database
from database import Memory

MAX_PER_AGENT = int(os.getenv("MEMORY_MAX_PER_AGENT", "500"))


def _row_to_dict(row: Memory) -> dict:
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "kind": row.kind,
        "text": row.text,
        "meta": json.loads(row.meta) if row.meta else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


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
    """Store a memory. Returns the row id."""
    db = database.SessionLocal()
    try:
        row = Memory(
            agent_id=agent_id,
            kind=kind,
            text=text,
            meta=json.dumps(meta) if meta else None,
        )
        db.add(row)
        db.flush()  # session has autoflush=False; prune must count the new row
        _prune(db, agent_id)
        db.commit()
        return row.id
    finally:
        db.close()


def recent(agent_id: str, k: int = 5, kind: str = None) -> list:
    """Most recent memories for an agent, newest first."""
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
    """Recency-based recall — kept async and signature-compatible with
    callers/API routes; `query`/`min_similarity` are accepted but unused."""
    return recent(agent_id, k=k, kind=kind)


async def seen_before(agent_id: str, text: str, threshold: float = 0.85,
                      kind: str = None) -> bool:
    """Exact-text duplicate check against recent memories. No semantic
    matching available — near-duplicates with different wording won't be
    caught, but exact repeats (the common case) are."""
    recents = recent(agent_id, k=20, kind=kind)
    return any(r["text"] == text for r in recents)
