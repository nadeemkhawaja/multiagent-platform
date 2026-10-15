"""Tests for the Alpha Wolf daily-loss circuit breaker in alpaca_broker.py.
Run from the backend directory:  python -m pytest -q
"""
import asyncio
import os
import sys

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


def test_first_check_of_day_sets_baseline_and_does_not_trip(db):
    settings = {"max_daily_loss_pct": 3.0}
    status = broker._daily_breaker_status(100_000.0, settings)
    assert status["tripped"] is False
    assert status["baseline_equity"] == 100_000.0
    assert status["daily_pnl_pct"] == 0.0


def test_loss_within_limit_does_not_trip(db):
    settings = {"max_daily_loss_pct": 3.0}
    broker._daily_breaker_status(100_000.0, settings)          # sets today's baseline
    status = broker._daily_breaker_status(98_500.0, settings)  # -1.5%
    assert status["tripped"] is False
    assert status["daily_pnl_pct"] == -1.5


def test_loss_past_limit_trips(db):
    settings = {"max_daily_loss_pct": 3.0}
    broker._daily_breaker_status(100_000.0, settings)          # sets today's baseline
    status = broker._daily_breaker_status(96_000.0, settings)  # -4%
    assert status["tripped"] is True
    assert status["daily_pnl_pct"] == -4.0


def test_baseline_persists_across_calls_same_day(db):
    settings = {"max_daily_loss_pct": 3.0}
    first = broker._daily_breaker_status(100_000.0, settings)
    second = broker._daily_breaker_status(99_000.0, settings)
    assert second["baseline_equity"] == first["baseline_equity"] == 100_000.0


def test_new_day_resets_baseline(db, monkeypatch):
    settings = {"max_daily_loss_pct": 3.0}
    broker._daily_breaker_status(100_000.0, settings)
    database.set_config("alpha_wolf_daily_baseline_date", "2020-01-01")  # simulate a prior day
    status = broker._daily_breaker_status(90_000.0, settings)
    assert status["tripped"] is False
    assert status["baseline_equity"] == 90_000.0


def test_save_settings_persists_max_daily_loss_pct(db):
    out = broker.save_settings(max_daily_loss_pct=5.0)
    assert out["max_daily_loss_pct"] == 5.0
    assert broker.get_settings()["max_daily_loss_pct"] == 5.0


def test_save_settings_clamps_max_daily_loss_pct(db):
    assert broker.save_settings(max_daily_loss_pct=0.1)["max_daily_loss_pct"] == 0.5
    assert broker.save_settings(max_daily_loss_pct=999)["max_daily_loss_pct"] == 50.0


# ── Broker rejection reasons reach the trader ───────────────────────────────
def test_api_error_extracts_alpacas_own_message():
    class _Resp:
        text = '{"code": 40310000, "message": "insufficient buying power"}'

    class _Err(Exception):
        response = _Resp()

    assert broker.api_error(_Err("HTTP 403")) == "insufficient buying power"


def test_api_error_falls_back_to_the_raw_body_then_the_exception():
    class _Resp:
        text = "not json at all"

    class _Err(Exception):
        response = _Resp()

    assert broker.api_error(_Err("boom")) == "not json at all"
    assert broker.api_error(Exception("connection reset")) == "connection reset"


def test_api_error_is_truncated_for_a_ui_row():
    assert len(broker.api_error(Exception("x" * 500))) == 200


# ── After the bell: reconcile, never place ─────────────────────────────────
def test_a_close_after_the_bell_is_journaled_the_same_day(db, monkeypatch):
    """A bracket that fills at 15:58 used to stay invisible until 09:30 the next
    morning: meta still claimed the position was open, the exit never reached
    the journal, and a profitable day showed as no trades at all."""
    state = {}

    async def positions():
        return {}                       # Alpaca says flat — the bracket filled

    async def last_fill(t):
        return {"price": 371.40, "reason": "take-profit filled"}

    async def snapshot(meta):
        return {"cash": 100971.78, "starting_capital": 100000.0, "positions": {},
                "realized_pnl": 973.28}

    async def must_not_run(*a, **kw):
        raise AssertionError("risk_check must not place orders after the close")

    monkeypatch.setattr(broker, "configured", lambda: True)
    monkeypatch.setattr(broker, "_market_open_now", lambda: False)        # past 16:00
    monkeypatch.setattr(broker, "_reconcile_window_now", lambda: True)    # before 16:30
    monkeypatch.setattr(broker, "_positions_by_ticker", positions)
    monkeypatch.setattr(broker, "_last_fill", last_fill)
    monkeypatch.setattr(broker, "_snapshot_portfolio", snapshot)
    monkeypatch.setattr(broker, "_close_position", must_not_run)
    monkeypatch.setattr(broker, "_open_orders_by_symbol", must_not_run)
    monkeypatch.setattr(broker, "_replace_order", must_not_run)
    monkeypatch.setattr(broker, "get_agent_data", lambda *a, **kw: {
        "positions_meta": {"AVGO": {"opened_at": "2026-09-02 14:00", "entry_price": 368.58,
                                    "shares": 27.0, "direction": "long", "stop": 366.96,
                                    "initial_stop": 366.96, "target": 371.40}},
        "trades": [], "journal": [], "pending_entries": []})
    monkeypatch.setattr(broker, "save_agent_data", lambda a, d: state.update(d))

    out = asyncio.run(broker.risk_check())
    assert [c["ticker"] for c in out["closed"]] == ["AVGO"]
    assert state["journal"][0]["ticker"] == "AVGO"
    assert state["journal"][0]["pnl"] > 0
    assert "AVGO" not in state["positions_meta"]      # the orphan record is gone


def test_risk_check_still_stops_outside_the_reconcile_window(monkeypatch):
    monkeypatch.setattr(broker, "configured", lambda: True)
    monkeypatch.setattr(broker, "_reconcile_window_now", lambda: False)
    assert asyncio.run(broker.risk_check())["skipped"] == "market closed"
