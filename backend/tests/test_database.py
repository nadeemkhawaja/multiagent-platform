"""Tests for database.py config + agent-data helpers, against a temp SQLite DB.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database


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


# ── Config key/value store ───────────────────────────────────────────────────
def test_set_and_get_config_roundtrip(db):
    db.set_config("greeting", "hello")
    assert db.get_config("greeting") == "hello"


def test_get_config_returns_default_when_missing(db):
    assert db.get_config("missing_key", "fallback") == "fallback"
    assert db.get_config("missing_key") is None


def test_set_config_json_value_roundtrip(db):
    db.set_config("watchlist", ["AAPL", "MSFT", "NVDA"])
    assert db.get_config("watchlist") == ["AAPL", "MSFT", "NVDA"]

    db.set_config("schedule", {"type": "cron", "hour": 8, "minute": 0})
    assert db.get_config("schedule") == {"type": "cron", "hour": 8, "minute": 0}


def test_set_config_overwrites_existing(db):
    db.set_config("k", "v1")
    db.set_config("k", "v2")
    assert db.get_config("k") == "v2"


def test_all_config_returns_all_keys(db):
    db.set_config("a", 1)
    db.set_config("b", {"x": 2})
    db.set_config("c", "plain")
    cfg = db.all_config()
    assert cfg["a"] == 1
    assert cfg["b"] == {"x": 2}
    assert cfg["c"] == "plain"


# ── Agent data store ──────────────────────────────────────────────────────────
def test_save_and_get_agent_data(db):
    db.save_agent_data("compass", {"compass": {"composite": 5}, "extra": [1, 2, 3]})
    out = db.get_agent_data("compass")
    assert out["compass"] == {"composite": 5}
    assert out["extra"] == [1, 2, 3]


def test_save_agent_data_updates_existing_key(db):
    db.save_agent_data("compass", {"compass": {"composite": 5}})
    db.save_agent_data("compass", {"compass": {"composite": 10}})
    out = db.get_agent_data("compass")
    assert out["compass"] == {"composite": 10}


def test_get_agent_data_returns_empty_dict_for_unknown_agent(db):
    assert db.get_agent_data("nonexistent_agent") == {}


def test_save_agent_data_keeps_separate_agents_isolated(db):
    db.save_agent_data("compass", {"compass": {"composite": 1}})
    db.save_agent_data("options_flow", {"flow": {"signals": []}})
    assert "flow" not in db.get_agent_data("compass")
    assert "compass" not in db.get_agent_data("options_flow")
