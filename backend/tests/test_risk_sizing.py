"""Tests for risk-based position sizing, GTC bracket orders, and real-fill
entry pricing. Run from the backend directory:  python -m pytest -q
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alpaca_broker as broker
from broker_rules import size_position


def _settings(position_pct=10.0, risk_pct=0.5):
    return {"position_pct": position_pct, "risk_pct": risk_pct}


# ── Risk-based sizing ──────────────────────────────────────────────────────
def test_wide_stop_takes_a_smaller_position_than_a_tight_stop():
    """The core property: the wider the stop, the fewer shares — so the dollar
    risk stays constant instead of the dollar notional."""
    equity = cash = 100_000.0
    tight, _ = size_position(equity, cash, 100.0, 92.0, _settings())   # $8 risk/share
    wide, _ = size_position(equity, cash, 100.0, 75.0, _settings())    # $25 risk/share
    assert tight > wide
    assert tight == 62    # 0.5% of 100k = $500 risk / $8  = 62 sh
    assert wide == 20     #                  $500 risk / $25 = 20 sh


def test_dollar_risk_is_equal_across_trades_with_different_stops():
    """Two very different setups should put the same amount of money at risk."""
    equity = cash = 100_000.0
    budget = equity * 0.5 / 100.0                       # $500

    shares_a, _ = size_position(equity, cash, 400.0, 360.0, _settings())   # $40/share
    shares_b, _ = size_position(equity, cash, 50.0, 44.0, _settings())     # $6/share

    risk_a = shares_a * (400.0 - 360.0)
    risk_b = shares_b * (50.0 - 44.0)
    # within one share's worth of risk of the budget, and of each other
    assert abs(risk_a - budget) <= 40.0
    assert abs(risk_b - budget) <= 6.0
    assert abs(risk_a - risk_b) <= 40.0


def test_concentration_cap_still_binds_on_a_very_tight_stop():
    """A 0.5%-away stop would otherwise justify an enormous position — the
    position_pct cap has to win."""
    shares, why = size_position(100_000.0, 100_000.0, 100.0, 99.5, _settings())
    assert shares == 100          # 10% of 100k / $100 = 100 sh, not 500/0.5 = 1000
    assert why == ""


def test_short_sizing_uses_distance_to_a_stop_above_the_entry():
    shares, _ = size_position(100_000.0, 100_000.0, 200.0, 210.0, _settings())
    assert shares == 50           # $500 risk / $10 per share


def test_cash_constrains_size_below_the_risk_budget():
    shares, why = size_position(100_000.0, 1_000.0, 100.0, 98.0, _settings())
    assert shares == 10           # only $1k cash / $100
    assert why == ""


def test_stop_at_entry_is_rejected_rather_than_sized():
    shares, why = size_position(100_000.0, 100_000.0, 100.0, 100.0, _settings())
    assert shares == 0
    assert "cannot size by risk" in why


def test_stop_too_wide_to_afford_one_share_is_skipped_with_reason():
    shares, why = size_position(10_000.0, 10_000.0, 5_000.0, 1_000.0, _settings())
    assert shares == 0
    assert "too wide" in why


def test_missing_price_is_rejected():
    shares, why = size_position(100_000.0, 100_000.0, 0.0, 90.0, _settings())
    assert shares == 0
    assert why == "no price available"


def test_risk_pct_setting_scales_the_position():
    equity = cash = 100_000.0
    half, _ = size_position(equity, cash, 100.0, 90.0, _settings(risk_pct=0.5))
    double, _ = size_position(equity, cash, 100.0, 90.0, _settings(risk_pct=1.0))
    assert half == 50 and double == 100


def test_fractional_shares_supported_for_the_simulator():
    shares, _ = size_position(100_000.0, 100_000.0, 100.0, 93.0, _settings(),
                              whole_shares=False)
    assert shares == pytest.approx(71.4286, rel=1e-3)


# ── GTC brackets ───────────────────────────────────────────────────────────
def test_bracket_order_is_submitted_gtc_with_both_legs(monkeypatch):
    """Day-TIF bracket legs are cancelled at the close, leaving overnight
    positions unprotected — the entry must go out GTC."""
    captured = {}

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"id": "o1", "legs": [{"stop_price": "95"}, {"limit_price": "120"}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            captured.update(json)
            return FakeResponse()

    monkeypatch.setattr(broker.httpx, "AsyncClient", FakeClient)
    order = asyncio.run(broker._place_bracket("NVDA", "long", 10, 95.0, 120.0))

    assert captured["time_in_force"] == "gtc"
    assert captured["order_class"] == "bracket"
    assert captured["stop_loss"] == {"stop_price": "95.0"}
    assert captured["take_profit"] == {"limit_price": "120.0"}
    assert order["id"] == "o1"


def test_bracket_missing_a_leg_is_logged_loudly(monkeypatch, caplog):
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"id": "o2", "legs": [{"stop_price": "95"}]}   # no take-profit

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None): return FakeResponse()

    monkeypatch.setattr(broker.httpx, "AsyncClient", FakeClient)
    with caplog.at_level("WARNING"):
        asyncio.run(broker._place_bracket("NVDA", "long", 10, 95.0, 120.0))
    assert "only 1 leg" in caplog.text


# ── Real fill prices ───────────────────────────────────────────────────────
def _fill_client(statuses):
    """Fake httpx client whose GET returns each queued order status in turn."""
    seq = list(statuses)

    class FakeResponse:
        def __init__(self, payload): self._p = payload
        def raise_for_status(self): pass
        def json(self): return self._p

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None):
            return FakeResponse(seq.pop(0) if seq else {"status": "accepted"})

    return FakeClient


def test_await_fill_returns_the_real_filled_price(monkeypatch):
    monkeypatch.setattr(broker.httpx, "AsyncClient",
                        _fill_client([{"status": "filled", "filled_avg_price": "101.37",
                                       "filled_qty": "25"}]))
    assert asyncio.run(broker._await_fill("o1")) == {"price": 101.37, "shares": 25}


def test_await_fill_polls_until_the_order_fills(monkeypatch):
    monkeypatch.setattr(broker, "FILL_POLL_DELAY_S", 0)
    monkeypatch.setattr(broker.httpx, "AsyncClient", _fill_client([
        {"status": "accepted", "filled_avg_price": None},
        {"status": "partially_filled", "filled_avg_price": None},
        {"status": "filled", "filled_avg_price": "99.10", "filled_qty": "10"},
    ]))
    assert asyncio.run(broker._await_fill("o1")) == {"price": 99.10, "shares": 10}


def test_await_fill_gives_up_on_a_rejected_order(monkeypatch):
    monkeypatch.setattr(broker, "FILL_POLL_DELAY_S", 0)
    monkeypatch.setattr(broker.httpx, "AsyncClient",
                        _fill_client([{"status": "rejected"}]))
    assert asyncio.run(broker._await_fill("o1")) == {}


def test_await_fill_returns_empty_when_never_filled(monkeypatch):
    monkeypatch.setattr(broker, "FILL_POLL_DELAY_S", 0)
    monkeypatch.setattr(broker.httpx, "AsyncClient", _fill_client([]))
    assert asyncio.run(broker._await_fill("o1")) == {}


def test_no_order_id_short_circuits():
    assert asyncio.run(broker._await_fill(None)) == {}


# ── _last_fill filters by symbol client-side ───────────────────────────────
def test_last_fill_ignores_other_symbols(monkeypatch):
    """Alpaca's activities endpoint ignores the `symbol` param and returns the
    whole account's fills — filtering has to happen here."""
    activities = [
        {"symbol": "MSFT", "price": "393.14", "side": "buy"},
        {"symbol": "AAPL", "price": "339.66", "side": "sell"},
    ]

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return activities

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None): return FakeResponse()

    monkeypatch.setattr(broker.httpx, "AsyncClient", FakeClient)
    out = asyncio.run(broker._last_fill("AAPL"))
    assert out["price"] == 339.66
    assert asyncio.run(broker._last_fill("TSLA")) is None
