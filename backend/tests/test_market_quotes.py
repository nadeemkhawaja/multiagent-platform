"""Tests for the Alpaca real-time overlay in tools/market.py — specifically the
symbol filter (one bad symbol must not sink the batch) and the fallback path.
Run from the backend directory: python -m pytest -q tests/test_market_quotes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import market


def test_futures_and_index_symbols_are_filtered_out(monkeypatch):
    """Alpaca 400s the whole batch on a non-equity symbol, so ES=F/NQ=F/^VIX
    must never reach it — otherwise every good symbol loses its live price."""
    seen = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"trades": {s: {"p": 1.0} for s in seen["symbols"].split(",")}}

    class FakeClient:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, path, params=None):
            seen["symbols"] = params["symbols"]
            return FakeResp()

    monkeypatch.setattr(market.httpx, "Client", FakeClient)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "k")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "s")

    out = market.alpaca_last_trades_sync(["AAPL", "ES=F", "NQ=F", "^VIX", "BRK.B"])
    assert seen["symbols"] == "AAPL,BRK.B"
    assert set(out) == {"AAPL", "BRK.B"}


def test_no_keys_returns_empty_rather_than_raising(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "")
    assert market.alpaca_last_trades_sync(["AAPL"]) == {}


def test_network_failure_falls_back_silently(monkeypatch):
    def boom(**kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(market.httpx, "Client", boom)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "k")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "s")
    assert market.alpaca_last_trades_sync(["AAPL"]) == {}


def test_overlay_recomputes_change_against_yfinance_prev_close():
    """The whole point of the split: Alpaca supplies the price, yfinance the
    previous close. Using Alpaca's own IEX prior close reported AAPL as -7.4%
    against a true -1.1%."""
    # yfinance row: price 310.00, change +2.00 -> its prev close was 308.00
    rows = [{"symbol": "AAPL", "price": 310.00, "change": 2.00, "change_pct": 0.65},
            {"symbol": "ES=F", "price": 7519.25, "change": 21.5, "change_pct": 0.29}]
    out = market.apply_live_prices(rows, {"AAPL": 308.52})

    aapl, es = out[0], out[1]
    assert aapl["price"] == 308.52 and aapl["realtime"] is True
    assert aapl["change"] == 0.52                       # 308.52 - 308.00
    assert aapl["change_pct"] == round(0.52 / 308.00 * 100, 2)
    # Untouched: Alpaca carries no futures, so the yfinance row must survive.
    assert es["price"] == 7519.25 and es["change_pct"] == 0.29
    assert "realtime" not in es


def test_overlay_survives_a_zero_previous_close():
    rows = [{"symbol": "X", "price": 5.0, "change": 5.0, "change_pct": 0.0}]
    out = market.apply_live_prices(rows, {"X": 6.0})
    assert out[0]["price"] == 6.0 and out[0]["change_pct"] == 0.0
