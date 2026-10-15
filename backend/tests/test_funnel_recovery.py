"""Regression guards for the defects that made the funnel stop firing.

Every test here pins a behaviour that was measurably broken in production, and
each docstring records the observation rather than restating the assertion —
these are the cases that made 619 Technologia runs produce nothing.

Pure functions and synthetic bars except where a fetch is monkeypatched.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import auction, playbook, strategies, levels   # noqa: E402


def bar(c, o=None, h=None, l=None, v=1000.0, t=None):
    o = c if o is None else o
    b = {"open": o, "high": h if h is not None else max(o, c),
         "low": l if l is not None else min(o, c), "close": c, "volume": v}
    if t is not None:
        b["t"] = t
    return b


def session(closes, start=570, step=5, **kw):
    return [bar(c, t=start + i * step, **kw) for i, c in enumerate(closes)]


def poi(low, high, confluence, side, distance, sources=("vwap",)):
    return {"low": low, "high": high, "mid": round((low + high) / 2, 2),
            "confluence": confluence, "sources": list(sources), "side": side,
            "distance": distance, "distance_atr": distance}


# ══ F-1: the card must trade the zone price is AT ═══════════════════════════
def test_card_prefers_the_zone_price_is_standing_in_over_the_strongest_one():
    """The defect, exactly as observed on MSFT: price 480.54 sat 15c from an
    8-confluence zone while the card committed to a 7-confluence zone $14.82
    overhead and reported WAIT. pois is ranked by confluence, so candidates[0]
    was the far one, and arming requires price INSIDE the chosen zone — making a
    trigger a ~0.4% coincidence instead of an outcome."""
    price = 100.0
    pois = [
        poi(112.0, 112.2, 9, "resistance", 12.1),   # strongest, unreachable today
        poi(100.0, 100.4, 4, "resistance", 0.2),    # weaker, price is in it
    ]
    bars = session([99.8, 99.9, 100.0, 100.1, 100.0, 100.0])
    card = playbook.trade_card(
        symbol="X", label="X", price=price, bars=bars, atr=1.0, reach_atr=8.0,
        context={"context": "TREND_DOWN", "playbook": "sell rallies", "reasons": []},
        levels=[{"price": 96.0, "label": "pdl"}, {"price": 92.0, "label": "naked_poc"}],
        pois=pois)
    assert card["poi"]["low"] == 100.0, "must pick the zone price is actually at"
    assert card["trigger"]["state"] != "NONE"


def test_confluence_still_wins_between_zones_at_comparable_distance():
    """Proximity outranking confluence is only correct when the distances really
    differ — otherwise this would trade noise over a level everyone can see."""
    pois = [
        poi(103.0, 103.2, 9, "resistance", 3.1),
        poi(103.0, 103.2, 3, "resistance", 3.0),   # a hair nearer, far weaker
    ]
    bars = session([100.0] * 6)
    chosen, _ = playbook._pick_candidate(pois, bars, "short", atr=2.0)
    assert chosen["confluence"] == 9


def test_card_will_not_name_a_zone_more_than_a_session_away():
    """MU's card pointed at a zone $47.88 out — 1.2x its entire daily ATR and
    4.4x the session's actual range. 'Reachable today' was measured as 2.5 DAILY
    ATRs, which is several sessions of travel."""
    pois = [poi(150.0, 150.5, 9, "resistance", 50.0)]
    card = playbook.trade_card(
        symbol="X", label="X", price=100.0, bars=session([100.0] * 6), atr=1.0,
        reach_atr=10.0,   # reach = 1.0 x 10.0 = 10.0, the zone is 50 away
        context={"context": "TREND_DOWN", "playbook": "sell rallies", "reasons": []},
        levels=[], pois=pois)
    assert card["action"] == "WAIT"
    assert "more than a session's range" in card["why"]


# ══ F-2: honest R ══════════════════════════════════════════════════════════
def test_stop_floor_is_more_than_a_single_average_bar():
    """A floor of exactly one average bar means one average bar against you is a
    stop-out, which is the coin flip the floor exists to prevent. Live AVGO
    priced a $0.80 stop on a $392 name and reported 4.94R."""
    assert playbook.MIN_STOP_ATR >= 2.0


def test_intraday_atr_spans_the_session_not_the_last_70_minutes():
    """atr(bars, 14) on 5-minute bars measures 70 minutes, so every threshold
    scaled to it moved with the last hour of tape — 24% low on CSCO and 57% HIGH
    on TSLA in the same run. A quiet final stretch must not shrink the estimate."""
    busy = [bar(100 + i, h=100 + i + 2, l=100 + i - 2) for i in range(40)]
    calm = [bar(140, h=140.05, l=139.95) for _ in range(20)]
    bars = busy + calm

    windowed = strategies.atr(bars, 14)
    session_wide = strategies.intraday_atr(bars)
    assert windowed < 0.5, "the 14-bar window sees only the calm tail"
    assert session_wide > windowed * 3, "a session-wide estimate must not collapse"


def test_intraday_atr_needs_enough_bars_to_mean_anything():
    assert strategies.intraday_atr([bar(100)] * 5) is None


# ══ F-3: grade A must be reachable ═════════════════════════════════════════
def test_grade_a_does_not_require_scanner_grade_volume():
    """2x relative volume is a threshold for finding names in a universe of
    thousands. On a fixed list of 22 megacaps it is cleared on earnings days and
    little else, so grade A — and with it 'Today's A+ Setup' — was unreachable by
    construction while triggered 2R cards were capped at B."""
    trig = {"state": "TRIGGERED", "kind": "sweep", "why": "swept and reclaimed"}
    # A now needs a 2.5R structural target as well as a strong zone — the old
    # 2.0 bar was met by the invented "measured move" target on every card.
    assert playbook._grade(6, trig, rr1=2.6, in_play=False) == "A"
    assert playbook._grade(6, trig, rr1=2.6, in_play=True) == "A+"
    # Unusual participation is still worth saying — it just grades up, not in.
    assert playbook._grade(6, trig, rr1=2.6, in_play=True) == "A+"
    # …and a 2.4R card is an honest B rather than an A, because A is reserved.
    assert playbook._grade(6, trig, rr1=2.4, in_play=True) == "B"


def test_a_grade_still_needs_a_real_zone_and_a_paying_target():
    trig = {"state": "TRIGGERED", "kind": "sweep", "why": "swept"}
    assert playbook._grade(2, trig, rr1=2.4, in_play=True) == "B"     # thin zone
    # Below the 2R floor is no longer a B at all: the card is refused upstream,
    # and a grade that cannot trade should not look like one that can.
    assert playbook._grade(6, trig, rr1=1.4, in_play=True) == "C"     # weak target


# ══ F-4: a stand-down must not withhold the map ════════════════════════════
def test_stand_down_still_reports_where_price_is():
    """UNDECIDED returned poi=None, so on a day the auction had not resolved the
    reader got no zone, no levels and nothing to set an alert on — 6 of 24
    megacaps in one live run. The gate is about action, not information."""
    pois = [poi(99.0, 99.4, 6, "support", 0.8), poi(120.0, 120.4, 8, "resistance", 20.0)]
    card = playbook.trade_card(
        symbol="X", label="X", price=100.0, bars=session([100.0] * 6), atr=1.0,
        context={"context": "UNDECIDED", "playbook": auction.PLAYBOOKS["UNDECIDED"],
                 "reasons": []},
        levels=[], pois=pois)
    assert card["action"] == "STAND_DOWN"
    assert card["poi"] is not None, "the nearest zone is still worth showing"
    assert card["poi"]["low"] == 99.0


def test_balance_survives_a_slight_lean():
    """net=+-2 with rotational evidence was sent to UNDECIDED — reported as 'the
    auction has not decided' when it had decided to rotate. BALANCE only permits
    edge fades, so the looser bound cannot authorise a directional trade."""
    ctx = auction.day_context(
        session([100, 100.4, 100.2, 100.5, 100.3, 100.4]),
        vwap=100.0,                                   # +1 above VWAP
        prior={"pdh": 105.0, "pdl": 95.0, "pdc": 100.0},
        ib={"extension": "none", "ib_shape": "wide"},
        opening={"direction": "long", "confidence": 1, "type": "OPEN_AUCTION",
                 "open_px": 100.0},
        value_loc={"location": "inside_value"}, atr=2.0)
    assert ctx["context"] == "BALANCE"


# ══ F-7: the shared bar cache ══════════════════════════════════════════════
def test_concurrent_callers_for_one_symbol_make_a_single_request(monkeypatch):
    """Two agents on aligned intervals started in the same second and asked for
    the same bars from two thread pools at once — ~40 concurrent requests, which
    drew rate limits and '[Errno 24] Too many open files'. Fetches then returned
    [] and symbols were dropped silently: one stored run holds 2 of 24."""
    levels.clear_bar_cache()
    calls = []
    gate = threading.Event()

    def produce():
        calls.append("fetch")
        gate.wait(timeout=2)
        return [bar(100)]

    results = []
    threads = [threading.Thread(target=lambda: results.append(
        levels._cached(("daily", "AAPL", "1y"), produce))) for _ in range(8)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join()

    assert len(calls) == 1, f"expected one upstream fetch, got {len(calls)}"
    assert all(r == [bar(100)] for r in results)
    levels.clear_bar_cache()


def test_an_empty_result_is_never_cached(monkeypatch):
    """Caching a rate-limit failure would pin a dead symbol in place for the whole
    TTL, turning a transient miss into an outage."""
    levels.clear_bar_cache()
    attempts = []

    def flaky():
        attempts.append(1)
        return [] if len(attempts) == 1 else [bar(101)]

    assert levels._cached(("daily", "X", "1y"), flaky) == []
    assert levels._cached(("daily", "X", "1y"), flaky) == [bar(101)]
    assert len(attempts) == 2
    levels.clear_bar_cache()
