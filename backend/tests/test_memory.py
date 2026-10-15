"""Tests for memory.py — persistent, recency-based agent memory.
Run from backend:  python -m pytest -q
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


# ── remember / recent ────────────────────────────────────────────────────────
def test_remember_and_recent_roundtrip(db):
    asyncio.run(memory.remember("wolf", "alpha day", kind="snap", meta={"d": 1}))
    asyncio.run(memory.remember("wolf", "no vector here", kind="snap"))

    rows = memory.recent("wolf", k=5)
    assert len(rows) == 2
    assert rows[0]["text"] == "no vector here"   # newest first
    assert rows[1]["meta"] == {"d": 1}


def test_recent_filters_by_kind_and_agent(db):
    asyncio.run(memory.remember("wolf", "a", kind="snap"))
    asyncio.run(memory.remember("wolf", "b", kind="brief"))
    asyncio.run(memory.remember("compass", "c", kind="snap"))

    assert [r["text"] for r in memory.recent("wolf", kind="snap")] == ["a"]
    assert len(memory.recent("wolf")) == 2


def test_remember_prunes_oldest_beyond_cap(db, monkeypatch):
    monkeypatch.setattr(memory, "MAX_PER_AGENT", 3)
    for i in range(5):
        asyncio.run(memory.remember("wolf", f"item {i}"))
    rows = memory.recent("wolf", k=10)
    assert len(rows) == 3
    assert [r["text"] for r in rows] == ["item 4", "item 3", "item 2"]


# ── recall (recency-based fallback) ──────────────────────────────────────────
def test_recall_returns_recency_ordered_rows(db):
    for text in ["markets up big", "markets down hard", "sideways chop"]:
        asyncio.run(memory.remember("wolf", text))

    out = asyncio.run(memory.recall("wolf", "irrelevant query", k=2))
    assert [r["text"] for r in out] == ["sideways chop", "markets down hard"]


def test_recall_empty_agent_returns_empty(db):
    assert asyncio.run(memory.recall("ghost", "QUERY")) == []


# ── seen_before (exact-text match) ───────────────────────────────────────────
def test_seen_before_true_for_exact_repeat(db):
    asyncio.run(memory.remember("brief", "AI breakthrough story"))
    assert asyncio.run(memory.seen_before("brief", "AI breakthrough story")) is True


def test_seen_before_false_for_new_content(db):
    asyncio.run(memory.remember("brief", "AI breakthrough story"))
    assert asyncio.run(memory.seen_before("brief", "earnings season starts")) is False


def test_seen_before_false_when_nothing_stored(db):
    assert asyncio.run(memory.seen_before("brief", "some story")) is False
