"""Unit tests for pure-logic helpers across the financial/content agents — no
network, LLM, or Ollama required.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── AI-Times: English-language filter + video shaping ───────────────────────
def test_is_english_with_language_metadata():
    from agents.agent1_ai_times import _is_english
    assert _is_english("Some title", default_audio_lang="en-US") is True
    assert _is_english("Some title", default_audio_lang="es-ES") is False
    assert _is_english("Some title", default_lang="en") is True


def test_is_english_falls_back_to_script_heuristic():
    from agents.agent1_ai_times import _is_english
    assert _is_english("OpenAI releases new model") is True
    assert _is_english("人工知能の最新ニュース") is False
    assert _is_english("") is True


def test_video_from_item_and_strip_internal():
    from agents.agent1_ai_times import _video_from_item, _strip_internal
    item = {
        "id": "abc123",
        "snippet": {
            "title": "AI News",
            "channelTitle": "Some Channel",
            "publishedAt": "2024-01-01T00:00:00Z",
            "thumbnails": {"high": {"url": "http://img"}},
            "defaultAudioLanguage": "en",
        },
        "contentDetails": {"duration": "PT5M30S"},
        "statistics": {"viewCount": "12345"},
    }
    v = _video_from_item(item, trusted=True)
    assert v["title"] == "AI News"
    assert v["url"] == "https://www.youtube.com/watch?v=abc123"
    assert v["duration"] == "5:30"
    assert v["views"] == "12K"
    assert v["trusted"] is True

    stripped = _strip_internal(v)
    assert "_lang_audio" not in stripped
    assert "_title_raw" not in stripped
    assert stripped["title"] == "AI News"


# ── Compass: VIX regime classification ───────────────────────────────────────
def test_vix_regime_thresholds():
    from agents.agent5_compass import _vix_regime
    assert _vix_regime(12) == "Low"
    assert _vix_regime(15) == "Normal"   # boundary: not < 15
    assert _vix_regime(20) == "Normal"
    assert _vix_regime(25) == "Normal"   # boundary: not > 25
    assert _vix_regime(30) == "Elevated"


# ── Strategy Scout: HTML cleanup ─────────────────────────────────────────────
def test_clean_strips_html_and_unescapes_entities():
    from agents.agent7_strategy_scout import _clean
    assert _clean("<b>Hello &amp; welcome</b>") == "Hello & welcome"
    assert _clean(None) == ""
    assert _clean("  spaced  ") == "spaced"


# ── Capitol Tracker: date/amount parsing, filters, stats ─────────────────────
def test_parse_date_multiple_formats():
    from agents.agent8_capitol_tracker import _parse_date
    assert _parse_date("01/15/2024") == date(2024, 1, 15)
    assert _parse_date("2024-01-15") == date(2024, 1, 15)
    assert _parse_date("January 15, 2024") == date(2024, 1, 15)
    assert _parse_date("") is None
    assert _parse_date("not a date") is None


def test_normalize_amount_known_and_unknown():
    from agents.agent8_capitol_tracker import _normalize_amount
    assert _normalize_amount("$1,001 - $15,000") == "$1K–$15K"
    assert _normalize_amount("") == "—"
    assert _normalize_amount("weird value") == "weird value"


def test_filter_house_matches_name_and_date():
    from agents.agent8_capitol_tracker import _filter_house
    raw = [
        {"representative": "Nancy Pelosi", "transaction_date": "01/10/2024", "ticker": "NVDA",
         "asset_description": "NVIDIA Corp", "type": "Purchase", "amount": "$1,001 - $15,000",
         "disclosure_date": "01/20/2024", "district": "CA11"},
        {"representative": "Some Other", "transaction_date": "01/10/2024", "ticker": "AAPL",
         "asset_description": "Apple Inc", "type": "Sale", "amount": "$1,001 - $15,000",
         "disclosure_date": "01/20/2024", "district": "TX01"},
        {"representative": "Nancy Pelosi", "transaction_date": "01/01/2023", "ticker": "MSFT",
         "asset_description": "Microsoft", "type": "Purchase", "amount": "$1,001 - $15,000",
         "disclosure_date": "01/05/2023", "district": "CA11"},
    ]
    out = _filter_house(raw, ["Pelosi"], date(2024, 1, 1))
    assert len(out) == 1
    assert out[0]["ticker"] == "NVDA"
    assert out[0]["chamber"] == "House"


def test_filter_senate_matches_name_and_date():
    from agents.agent8_capitol_tracker import _filter_senate
    raw = [
        {"senator": "Tommy Tuberville", "transaction_date": "02/01/2024", "ticker": "TSLA",
         "asset_description": "Tesla Inc", "type": "Purchase", "amount": "$15,001 - $50,000",
         "disclosure_date": "02/10/2024", "state": "AL"},
        {"senator": "Someone Else", "transaction_date": "02/01/2024", "ticker": "MSFT",
         "asset_description": "Microsoft", "type": "Sale", "amount": "$1,001 - $15,000",
         "disclosure_date": "02/10/2024", "state": "NY"},
    ]
    out = _filter_senate(raw, ["Tuberville"], date(2024, 1, 1))
    assert len(out) == 1
    assert out[0]["chamber"] == "Senate"
    assert out[0]["amount"] == "$15K–$50K"


def test_stats_includes_net_activity_and_top_tickers():
    from agents.agent8_capitol_tracker import _stats
    trades = [
        {"politician": "A", "ticker": "NVDA", "type": "Purchase"},
        {"politician": "A", "ticker": "NVDA", "type": "Purchase"},
        {"politician": "B", "ticker": "AAPL", "type": "Sale"},
        {"politician": "C", "ticker": "NVDA", "type": "Sale"},
    ]
    s = _stats(trades)
    assert s["total"] == 4
    assert s["purchases"] == 2
    assert s["sales"] == 2
    assert s["net_activity"] == 0
    assert s["politicians_found"] == 3
    assert s["top_tickers"][0] == {"ticker": "NVDA", "count": 3}


def test_stats_handles_empty_trades():
    from agents.agent8_capitol_tracker import _stats
    s = _stats([])
    assert s["total"] == 0
    assert s["net_activity"] == 0
    assert s["top_tickers"] == []


# ── Options Flow: numeric helpers + realized volatility ──────────────────────
def test_safe_float_valid_and_invalid():
    from agents.agent10_options_flow import _safe_float
    assert _safe_float("3.14") == 3.14
    assert _safe_float(None, default=2.0) == 2.0
    assert _safe_float("nope", default=-1) == -1


def test_get_watchlist_uses_default_when_too_short(monkeypatch):
    from agents import agent10_options_flow as of
    monkeypatch.setattr(of, "get_config", lambda key, default="": "")
    assert of._get_watchlist() == of.DEFAULT_WATCHLIST


def test_get_watchlist_uses_custom_when_enough_tickers(monkeypatch):
    from agents import agent10_options_flow as of
    custom = "AAPL,MSFT,NVDA,TSLA,AMZN,META"
    monkeypatch.setattr(of, "get_config", lambda key, default="": custom)
    assert of._get_watchlist() == ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"]


def test_realized_vol_computes_positive_value():
    import pandas as pd
    from agents.agent10_options_flow import _realized_vol
    closes = pd.Series([100, 101, 99, 102, 98, 103, 97, 104, 96, 105], dtype=float)
    hist = pd.DataFrame({"Close": closes})
    vol = _realized_vol(hist)
    assert vol > 0


def test_realized_vol_returns_zero_for_short_history():
    import pandas as pd
    from agents.agent10_options_flow import _realized_vol
    hist = pd.DataFrame({"Close": [100.0, 101.0]})
    assert _realized_vol(hist) == 0.0


def test_realized_vol_returns_zero_for_empty_history():
    import pandas as pd
    from agents.agent10_options_flow import _realized_vol
    hist = pd.DataFrame({"Close": pd.Series([], dtype=float)})
    assert _realized_vol(hist) == 0.0


# ── Earnings Calendar: date/move/urgency helpers ─────────────────────────────
def test_safe_returns_value_or_default():
    from agents.agent11_earnings_calendar import _safe
    assert _safe(3.14) == 3.14
    assert _safe(None, "default") == "default"
    assert _safe(float("nan"), "default") == "default"


def test_days_until_computes_delta():
    import datetime
    from agents.agent11_earnings_calendar import _days_until
    target = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    assert _days_until(target) == 5
    assert _days_until("not-a-date") is None


def test_expected_move_calculates_pct():
    from agents.agent11_earnings_calendar import _expected_move
    assert _expected_move(100, 3, 2) == 5.0
    assert _expected_move(0, 3, 2) is None


def test_urgency_buckets():
    from agents.agent11_earnings_calendar import _urgency
    assert _urgency(None) == 4
    assert _urgency(2) == 0
    assert _urgency(5) == 1
    assert _urgency(10) == 2
    assert _urgency(30) == 3


def test_earnings_get_watchlist_uses_default_when_too_short(monkeypatch):
    from agents import agent11_earnings_calendar as ec
    monkeypatch.setattr(ec, "get_config", lambda key, default="": "")
    assert ec._get_watchlist() == ec.DEFAULT_WATCHLIST


# ── Alpha Wolf: cross-agent summaries fed to the synthesis LLM call ──────────
def test_compass_summary_includes_vix_when_present():
    from agents.agent13_alpha_wolf import _compass_summary
    d = {"compass": {"composite": 12, "sectors": [{"k": "Technology", "bias": 20}],
                      "vix": {"level": 14.2, "regime": "Low"}, "read": "Markets look constructive."}}
    out = _compass_summary(d)
    assert "VIX 14.2 (Low volatility)" in out
    assert "Composite bias: 12" in out
    assert "Technology +20" in out


def test_compass_summary_handles_missing_vix():
    from agents.agent13_alpha_wolf import _compass_summary
    d = {"compass": {"composite": -5, "sectors": [], "read": "Quiet day."}}
    out = _compass_summary(d)
    assert "VIX" not in out
    assert "Composite bias: -5" in out


def test_compass_summary_handles_empty_input():
    from agents.agent13_alpha_wolf import _compass_summary
    assert "Composite bias: ?" in _compass_summary({})
    assert "Composite bias: ?" in _compass_summary(None)


def test_wolf_summary_formats_gainers_and_losers():
    from agents.agent13_alpha_wolf import _wolf_summary
    d = {"market_data": {"top_gainers": [{"symbol": "NVDA", "change_pct": 5.2}],
                          "top_losers": [{"symbol": "INTC", "change_pct": -3.1}],
                          "commentary": "Tech leads."}}
    out = _wolf_summary(d)
    assert "NVDA 5.2%" in out
    assert "INTC -3.1%" in out
    assert "Tech leads." in out


def test_scout_summary_formats_strategies():
    from agents.agent13_alpha_wolf import _scout_summary
    d = {"scout": {"strategies": [{"name": "ORB", "type": "momentum", "timeframe": "5m"}]}}
    assert _scout_summary(d) == "Trending strategies: ORB (momentum/5m)"
    assert _scout_summary({}) == "Trending strategies: n/a"


def test_capitol_summary_formats_trades():
    from agents.agent13_alpha_wolf import _capitol_summary
    d = {"tracker": {"trades": [{"politician": "Nancy Pelosi", "type": "Purchase", "ticker": "NVDA"}],
                      "commentary": "Notable buy."}}
    out = _capitol_summary(d)
    assert "Pelosi Purc NVDA" in out
    assert "Notable buy." in out


def test_options_summary_formats_signals():
    from agents.agent13_alpha_wolf import _options_summary
    d = {"flow": {"top5": [{"ticker": "TSLA", "type": "call", "iv_pct": 80}], "commentary": "Hot."}}
    out = _options_summary(d)
    assert "TSLA call IV%ile 80" in out
    assert "Hot." in out


def test_earnings_summary_formats_calendar():
    from agents.agent13_alpha_wolf import _earnings_summary
    d = {"calendar": {"this_week": [{"ticker": "AAPL", "earnings_date": "2024-01-25", "expected_pct": 4.5}],
                       "iv_crush_opp": [{"ticker": "AAPL"}]}}
    out = _earnings_summary(d)
    assert "AAPL 2024-01-25 exp±4.5%" in out
    assert "IV-crush setups flagged: 1" in out


def test_earnings_summary_handles_no_earnings():
    from agents.agent13_alpha_wolf import _earnings_summary
    out = _earnings_summary({"calendar": {"this_week": [], "iv_crush_opp": []}})
    assert "none this week" in out
