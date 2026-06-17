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


# ── Paper Broker: order decisions + fills for Alpha Wolf execution ───────────
def _settings(**kw):
    base = {"enabled": True, "capital": 100_000.0, "position_pct": 10.0, "max_positions": 8}
    base.update(kw)
    return base


def test_decide_orders_opens_daily_ideas():
    from paper_broker import decide_orders
    plan = {"daily": {"ideas": [
        {"ticker": "NVDA", "direction": "long", "thesis": "AI demand"},
        {"ticker": "TSLA", "direction": "short", "thesis": "weak deliveries"},
        {"ticker": "SPY", "direction": "neutral", "thesis": "wait"},
    ]}}
    orders = decide_orders(plan, {}, _settings())
    assert [(o["action"], o["ticker"], o.get("direction")) for o in orders] == [
        ("open", "NVDA", "long"), ("open", "TSLA", "short")]


def test_decide_orders_skips_already_held_and_respects_max_positions():
    from paper_broker import decide_orders
    plan = {"daily": {"ideas": [
        {"ticker": "NVDA", "direction": "long"},
        {"ticker": "AMD", "direction": "long"},
        {"ticker": "MSFT", "direction": "long"},
    ]}}
    positions = {"NVDA": {"direction": "long", "shares": 10, "entry_price": 100.0}}
    orders = decide_orders(plan, positions, _settings(max_positions=2))
    # NVDA already held long → skipped; only one slot left after NVDA
    assert [(o["action"], o["ticker"]) for o in orders] == [("open", "AMD")]


def test_decide_orders_closes_and_reopens_on_direction_flip():
    from paper_broker import decide_orders
    plan = {"daily": {"ideas": [{"ticker": "TSLA", "direction": "long"}]}}
    positions = {"TSLA": {"direction": "short", "shares": 5, "entry_price": 200.0}}
    orders = decide_orders(plan, positions, _settings())
    assert orders[0]["action"] == "close" and orders[0]["ticker"] == "TSLA"
    assert orders[1] == {"action": "open", "ticker": "TSLA", "direction": "long",
                         "thesis": "", "reason": "daily plan idea"}


def test_decide_orders_closes_avoided_holdings_without_reopening():
    from paper_broker import decide_orders
    plan = {"daily": {"ideas": [{"ticker": "COIN", "direction": "long"}]},
            "avoid": ["Stay away from COIN into the SEC ruling"]}
    positions = {"COIN": {"direction": "long", "shares": 5, "entry_price": 150.0}}
    orders = decide_orders(plan, positions, _settings())
    assert [(o["action"], o["ticker"]) for o in orders] == [("close", "COIN")]


def test_avoid_hits_only_matches_held_tickers():
    from paper_broker import avoid_hits
    hits = avoid_hits(["Avoid NVDA and meme stocks", "No crypto until VIX settles"],
                      {"NVDA", "AAPL"})
    assert hits == {"NVDA"}


def test_apply_orders_fills_open_and_close_with_pnl():
    from paper_broker import apply_orders, new_portfolio
    pf = new_portfolio(100_000.0)
    trades = []
    executed, skipped = apply_orders(
        pf, [{"action": "open", "ticker": "NVDA", "direction": "long", "reason": "idea"}],
        {"NVDA": 100.0}, _settings(), trades)
    assert not skipped and executed[0]["action"] == "BUY"
    assert pf["positions"]["NVDA"]["shares"] == 100.0       # 10% of 100k @ $100
    assert pf["cash"] == 90_000.0

    executed, skipped = apply_orders(
        pf, [{"action": "close", "ticker": "NVDA", "reason": "avoid"}],
        {"NVDA": 110.0}, _settings(), trades)
    assert executed[0]["action"] == "SELL" and executed[0]["pnl"] == 1000.0
    assert pf["cash"] == 101_000.0 and pf["realized_pnl"] == 1000.0
    assert not pf["positions"]


def test_apply_orders_short_pnl_and_missing_price_skip():
    from paper_broker import apply_orders, new_portfolio
    pf = new_portfolio(100_000.0)
    trades = []
    executed, skipped = apply_orders(
        pf, [{"action": "open", "ticker": "TSLA", "direction": "short", "reason": "idea"},
             {"action": "open", "ticker": "XYZ", "direction": "long", "reason": "idea"}],
        {"TSLA": 200.0}, _settings(), trades)
    assert executed[0]["action"] == "SHORT"
    assert skipped[0]["ticker"] == "XYZ" and skipped[0]["why"] == "no price available"

    # price drops → short profits on cover
    executed, _ = apply_orders(
        pf, [{"action": "close", "ticker": "TSLA", "reason": "flip"}],
        {"TSLA": 180.0}, _settings(), trades)
    assert executed[0]["action"] == "COVER" and executed[0]["pnl"] == 1000.0
    assert pf["cash"] == 101_000.0


def test_portfolio_summary_tracks_equity_and_return():
    from paper_broker import new_portfolio, portfolio_summary
    pf = new_portfolio(100_000.0)
    pf["cash"] = 90_000.0
    pf["positions"]["NVDA"] = {"direction": "long", "shares": 100.0,
                               "entry_price": 100.0, "last_price": 105.0}
    s = portfolio_summary(pf)
    assert s["equity"] == 100_500.0
    assert s["unrealized_pnl"] == 500.0
    assert s["return_pct"] == 0.5


# ── Alpha Wolf: plan sanitization (LLM output does not always honor schema) ──
def test_sanitize_plan_coerces_object_fields_to_text():
    from agents.agent13_alpha_wolf import _sanitize_plan
    messy = {
        "headline": {"text": "Risk-on into CPI", "confidence": 0.8},
        "stance": "risk-on",
        "regime": ["Bullish regime", "vol compressed"],
        "confluence": [{"ticker": "NVDA", "feeds": ["flow", "congress"]}],
        "daily": {"bias": "bullish", "summary": {"note": "Buy dips."},
                  "ideas": [{"ticker": "nvda", "direction": "LONG",
                             "thesis": {"reason": "AI demand"},
                             "trigger": {"level": 120}, "risk": "below 110"}]},
        "weekly": {"bias": "sideways", "summary": "Wait.",
                   "themes": [{"name": "AI capex"}], "ideas": "none"},
        "avoid": [{"ticker": "COIN", "why": "SEC ruling"}],
        "catalysts": "CPI Thursday",
        "risk_notes": {"sizing": "2% per trade"},
    }
    plan = _sanitize_plan(messy)
    assert plan["headline"] == "Risk-on into CPI — 0.8"
    assert plan["stance"] == "RISK-ON"
    assert plan["regime"] == "Bullish regime, vol compressed"
    assert plan["confluence"] == ["NVDA — flow, congress"]
    assert plan["daily"]["bias"] == "BULLISH"
    assert plan["daily"]["summary"] == "Buy dips."
    idea = plan["daily"]["ideas"][0]
    # daily ideas carry live-trading fields (entry/stop/target/when), absent → ""
    assert idea == {"ticker": "NVDA", "direction": "long", "thesis": "AI demand",
                    "risk": "below 110", "trigger": "120",
                    "entry": "", "stop": "", "target": "", "when": ""}
    assert plan["daily"]["timeline"] == []              # no timeline given → []
    assert plan["weekly"]["bias"] == "NEUTRAL"          # invalid bias → NEUTRAL
    assert plan["weekly"]["themes"] == ["AI capex"]
    assert plan["weekly"]["ideas"] == []                # non-list ideas dropped
    assert plan["avoid"] == ["COIN — SEC ruling"]
    assert plan["catalysts"] == ["CPI Thursday"]
    assert plan["risk_notes"] == "2% per trade"
    # every value the UI renders directly is now a plain string
    for v in [plan["headline"], plan["regime"], plan["risk_notes"],
              *plan["confluence"], *plan["avoid"], *plan["catalysts"],
              *plan["weekly"]["themes"]]:
        assert isinstance(v, str)


def test_sanitize_plan_handles_garbage_input():
    from agents.agent13_alpha_wolf import _sanitize_plan
    for garbage in (None, "not a dict", [], {"daily": "x", "weekly": 7}):
        plan = _sanitize_plan(garbage)
        assert plan["stance"] == "NEUTRAL"
        assert plan["daily"]["ideas"] == [] and plan["weekly"]["ideas"] == []


def test_sanitize_plan_drops_ideas_without_ticker():
    from agents.agent13_alpha_wolf import _sanitize_plan
    plan = _sanitize_plan({"daily": {"ideas": [
        {"direction": "long", "thesis": "no ticker"},
        "just a string",
        {"ticker": "AMD", "direction": "long"},
    ]}})
    assert [i["ticker"] for i in plan["daily"]["ideas"]] == ["AMD"]


# ── Alpha Wolf: live decision engine (market clock + idea scoring) ───────────
def _et(y, mo, d, h, mi):
    import datetime
    from agents.agent13_alpha_wolf import ET
    return datetime.datetime(y, mo, d, h, mi, tzinfo=ET)


def test_market_clock_sessions():
    from agents.agent13_alpha_wolf import market_clock
    # Friday 2026-06-12 across the trading day
    assert market_clock(_et(2026, 6, 12, 8, 0))["session"] == "pre"
    assert market_clock(_et(2026, 6, 12, 9, 45))["session"] == "open"
    midday = market_clock(_et(2026, 6, 12, 12, 0))
    assert midday["session"] == "midday" and midday["is_open"] is True
    assert market_clock(_et(2026, 6, 12, 15, 30))["session"] == "power"
    closed = market_clock(_et(2026, 6, 12, 21, 0))
    assert closed["session"] == "closed" and closed["is_open"] is False


def test_market_clock_weekend_is_closed():
    from agents.agent13_alpha_wolf import market_clock
    sat = market_clock(_et(2026, 6, 13, 11, 0))      # Saturday
    assert sat["trading_day"] is False and sat["is_open"] is False
    assert "Pre-market" in sat["next_event"]["label"]


def test_first_price_parses_and_rejects_hallucinations():
    from agents.agent13_alpha_wolf import _first_price
    assert _first_price("$146.20 zone (9:35-9:40 ET)", 140) == 146.20
    assert _first_price("146.20", None) == 146.20
    # a level wildly off the live quote is a hallucination → dropped
    assert _first_price("$898.00", 142) is None
    # bare times must not be parsed as prices
    assert _first_price("around 9:30 ET", None) is None


def test_window_minutes_parsing():
    from agents.agent13_alpha_wolf import _window_minutes
    assert _window_minutes("9:30-10:30 ET open") == (570, 630)
    assert _window_minutes("power hour") == (900, 960)
    a, b = _window_minutes("3:45 PM ET")
    assert a < 945 < b                                # window straddles 3:45pm


def test_idea_now_states():
    from agents.agent13_alpha_wolf import _idea_now, market_clock
    clock = market_clock(_et(2026, 6, 12, 10, 0))     # in the open window
    idea = {"ticker": "AMD", "direction": "long", "entry": "$146.20",
            "stop": "$143.80", "target": "$152.50", "when": "9:30-10:30 ET"}
    assert _idea_now(idea, 143.0, clock, 2500)["state"] == "STOPPED"
    assert _idea_now(idea, 153.0, clock, 2500)["state"] == "TARGET_HIT"
    assert _idea_now(idea, 146.25, clock, 2500)["state"] == "ACT"   # at entry
    # before the window opens → WAIT
    pre = market_clock(_et(2026, 6, 12, 9, 0))
    assert _idea_now(idea, 146.25, pre, 2500)["state"] == "WAIT"
    # sizing: $2500 budget / $146.25 → 17 shares
    sized = _idea_now(idea, 146.25, clock, 2500)
    assert sized["size_shares"] == 17
