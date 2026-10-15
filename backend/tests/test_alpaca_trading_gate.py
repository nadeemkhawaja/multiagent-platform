"""Tests for the weekday trading gate and fill-confirmation guard in
alpaca_broker.execute_plan(). Run from the backend directory:  python -m pytest -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import alpaca_broker as broker


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", SessionLocal)
    return database


@pytest.mark.parametrize("weekday,expected", [
    (0, True), (1, True), (2, True), (3, True), (4, True),   # Mon-Fri
    (5, False), (6, False),                                   # Sat, Sun
])
def test_is_trading_day_matches_weekday(monkeypatch, weekday, expected):
    class FakeDT:
        @staticmethod
        def now(tz=None):
            return SimpleNamespace(weekday=lambda: weekday)
    monkeypatch.setattr(broker.datetime, "datetime", FakeDT)
    assert broker._is_trading_day() is expected


def test_execute_plan_skips_entirely_on_weekend(db, monkeypatch):
    monkeypatch.setattr(broker, "configured", lambda: True)
    monkeypatch.setattr(broker, "_is_trading_day", lambda: False)
    monkeypatch.setattr(broker, "get_settings", lambda: {"enabled": True})

    async def boom(*a, **kw):
        raise AssertionError("no Alpaca call should happen on a non-trading day")
    monkeypatch.setattr(broker, "_positions_by_ticker", boom)
    monkeypatch.setattr(broker, "_place_bracket", boom)
    monkeypatch.setattr(broker, "_close_position", boom)

    out = asyncio.run(broker.execute_plan({"daily": {"ideas": []}}))
    assert out["executed"] == []
    assert "weekend" in out["note"].lower()


def test_close_not_recorded_until_actually_filled(db, monkeypatch):
    """An Alpaca order that's merely 'accepted' (no fill yet) must not be
    journaled as closed, and the position must stay tracked so a later
    risk_check can reconcile the real fill."""
    async def fake_positions_by_ticker():
        return {"TSLA": {"direction": "short", "shares": 32, "entry_price": 309.08, "last_price": 313.03}}

    async def fake_close_position(ticker, errors=None):
        # Alpaca accepted the close order but hasn't filled it yet.
        return {"status": "accepted", "filled_avg_price": None}

    async def fake_account():
        return {"equity": "100000", "cash": "90000"}

    async def fake_snapshot_portfolio(meta):
        return {"cash": 90000, "starting_capital": 100000, "positions": {}, "realized_pnl": 0.0}

    monkeypatch.setattr(broker, "configured", lambda: True)
    monkeypatch.setattr(broker, "_is_trading_day", lambda: True)
    monkeypatch.setattr(broker, "get_settings", lambda: {
        "enabled": True, "position_pct": 10.0, "max_positions": 8,
        "max_hold_days": 10, "max_daily_loss_pct": 3.0,
    })
    monkeypatch.setattr(broker, "decide_orders",
                        lambda plan, positions, settings: [{"action": "close", "ticker": "TSLA", "reason": "test"}])
    monkeypatch.setattr(broker, "_positions_by_ticker", fake_positions_by_ticker)
    monkeypatch.setattr(broker, "_close_position", fake_close_position)
    monkeypatch.setattr(broker, "_account", fake_account)
    monkeypatch.setattr(broker, "_snapshot_portfolio", fake_snapshot_portfolio)
    monkeypatch.setattr(broker, "save_agent_data", lambda *a, **kw: None)
    monkeypatch.setattr(broker, "get_agent_data", lambda *a, **kw: {
        "positions_meta": {"TSLA": {"opened_at": "2026-07-24 13:03"}}, "trades": [], "journal": [],
    })

    out = asyncio.run(broker.execute_plan({"daily": {"ideas": []}}))
    assert out["executed"] == []
    assert any("not yet filled" in s["why"] for s in out["skipped"])
