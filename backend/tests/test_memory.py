"""Tests for memory.py — persistent agent memory with semantic recall.
Embeddings are mocked; no Ollama needed. Run from backend:  python -m pytest -q
"""
import asyncio
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import memory


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point database.py's engine/SessionLocal at a fresh temp SQLite file."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", SessionLocal)
    return database


def fake_embedder(table):
    """Embedder that maps known substrings to fixed vectors, else None."""
    async def _embed(text):
        for key, vec in table.items():
            if key in text:
                return vec
        return None
    return _embed


# ── cosine_similarity ────────────────────────────────────────────────────────
def test_cosine_identical_vectors():
    assert memory.cosine_similarity([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors():
    assert memory.cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)


def test_cosine_handles_empty_and_mismatched():
    assert memory.cosine_similarity([], [1, 2]) == 0.0
    assert memory.cosine_similarity([1, 2], [1, 2, 3]) == 0.0
    assert memory.cosine_similarity([0, 0], [1, 1]) == 0.0


# ── remember / recent ────────────────────────────────────────────────────────
def test_remember_and_recent_roundtrip(db, monkeypatch):
    monkeypatch.setattr(memory, "embed_text", fake_embedder({"alpha": [1.0, 0.0]}))
    asyncio.run(memory.remember("wolf", "alpha day", kind="snap", meta={"d": 1}))
    asyncio.run(memory.remember("wolf", "no vector here", kind="snap"))

    rows = memory.recent("wolf", k=5)
    assert len(rows) == 2
    assert rows[0]["text"] == "no vector here"   # newest first
    assert rows[1]["meta"] == {"d": 1}


def test_recent_filters_by_kind_and_agent(db, monkeypatch):
    monkeypatch.setattr(memory, "embed_text", fake_embedder({}))
    asyncio.run(memory.remember("wolf", "a", kind="snap"))
    asyncio.run(memory.remember("wolf", "b", kind="brief"))
    asyncio.run(memory.remember("compass", "c", kind="snap"))

    assert [r["text"] for r in memory.recent("wolf", kind="snap")] == ["a"]
    assert len(memory.recent("wolf")) == 2


def test_remember_prunes_oldest_beyond_cap(db, monkeypatch):
    monkeypatch.setattr(memory, "embed_text", fake_embedder({}))
    monkeypatch.setattr(memory, "MAX_PER_AGENT", 3)
    for i in range(5):
        asyncio.run(memory.remember("wolf", f"item {i}"))
    rows = memory.recent("wolf", k=10)
    assert len(rows) == 3
    assert [r["text"] for r in rows] == ["item 4", "item 3", "item 2"]


# ── recall ───────────────────────────────────────────────────────────────────
def test_recall_ranks_by_similarity(db, monkeypatch):
    table = {
        "markets up": [1.0, 0.0],
        "markets down": [-1.0, 0.0],
        "sideways": [0.0, 1.0],
        "QUERY": [0.9, 0.1],
    }
    monkeypatch.setattr(memory, "embed_text", fake_embedder(table))
    for text in ["markets up big", "markets down hard", "sideways chop"]:
        asyncio.run(memory.remember("wolf", text))

    # Default threshold keeps only the close match
    out = asyncio.run(memory.recall("wolf", "QUERY", k=3))
    assert [r["text"] for r in out] == ["markets up big"]
    assert out[0]["similarity"] > 0.9

    # With the threshold disabled, results come back ranked best-first
    out = asyncio.run(memory.recall("wolf", "QUERY", k=2, min_similarity=-1.0))
    assert [r["text"] for r in out] == ["markets up big", "sideways chop"]


def test_recall_falls_back_to_recency_without_query_vector(db, monkeypatch):
    monkeypatch.setattr(memory, "embed_text", fake_embedder({"stored": [1.0, 0.0]}))
    asyncio.run(memory.remember("wolf", "stored item"))

    out = asyncio.run(memory.recall("wolf", "unembeddable query"))
    assert out[0]["text"] == "stored item"
    assert "similarity" not in out[0]


def test_recall_falls_back_when_no_rows_have_vectors(db, monkeypatch):
    monkeypatch.setattr(memory, "embed_text", fake_embedder({"QUERY": [1.0, 0.0]}))
    asyncio.run(memory.remember("wolf", "old plain row"))

    out = asyncio.run(memory.recall("wolf", "QUERY"))
    assert [r["text"] for r in out] == ["old plain row"]


def test_recall_empty_agent_returns_empty(db, monkeypatch):
    monkeypatch.setattr(memory, "embed_text", fake_embedder({"QUERY": [1.0, 0.0]}))
    assert asyncio.run(memory.recall("ghost", "QUERY")) == []


# ── seen_before ──────────────────────────────────────────────────────────────
def test_seen_before_detects_near_duplicate(db, monkeypatch):
    table = {"AI breakthrough": [1.0, 0.0], "AI breakthrough again": [0.99, 0.01]}
    monkeypatch.setattr(memory, "embed_text", fake_embedder(table))
    asyncio.run(memory.remember("brief", "AI breakthrough story"))

    assert asyncio.run(memory.seen_before("brief", "AI breakthrough again today")) is True


def test_seen_before_false_for_new_content(db, monkeypatch):
    table = {"AI breakthrough": [1.0, 0.0], "earnings season": [0.0, 1.0]}
    monkeypatch.setattr(memory, "embed_text", fake_embedder(table))
    asyncio.run(memory.remember("brief", "AI breakthrough story"))

    assert asyncio.run(memory.seen_before("brief", "earnings season starts")) is False


def test_seen_before_false_when_embeddings_unavailable(db, monkeypatch):
    monkeypatch.setattr(memory, "embed_text", fake_embedder({}))
    asyncio.run(memory.remember("brief", "some story"))
    assert asyncio.run(memory.seen_before("brief", "some story")) is False
