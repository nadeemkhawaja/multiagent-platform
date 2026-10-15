# ============================================================================
# Broker rules — the pure, broker-agnostic half of execution.
#
# Position sizing, the risk gates, order decisions, the closed-trade journal
# and its stats. No network, no database, no event loop: every function here
# takes plain dicts and returns plain dicts, so each rule that decides whether
# real money moves is unit-testable on its own.
#
# This file is what remains of paper_broker.py, which also carried a complete
# simulated fill engine — a virtual cash balance, synthetic fills at yfinance
# prices, its own portfolio/risk_check/reset. Nothing called it: main.py and
# Alpha Wolf both run `import alpaca_broker as paper_broker`, so Alpaca has been
# the only broker for a while and 400-odd lines of a second one sat behind it
# looking authoritative. One broker, one set of rules.
#
# The gates here were rewritten after the first 100 live trades lost $2,331 at a
# 26% win rate — see docs/STRATEGY_REVIEW.md. What changed and why is commented
# at each gate.
# ============================================================================
import re
import logging
import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("broker_rules")

AGENT_ID = "alpha_wolf"
ET = ZoneInfo("America/New_York")

DEFAULT_CAPITAL = 10_000.0
# Concentration cap and risk per trade, sized for a $10k account.
#
# At the old 10% / 0.5% these were nonsense on a small balance: a 10% cap is
# $1,000, which on a $345 megacap buys 2 shares, and with a stop 0.4 daily ATR
# wide that is $5 of actual risk — 0.05% of equity. The notional cap bound every
# single trade and `risk_pct` never governed anything.
#
# 25% x 2 concurrent positions = half the account deployed at most, and the
# daily breaker still halts new entries at -3% on the day.
DEFAULT_POSITION_PCT = 25.0     # % of equity — concentration cap per position
DEFAULT_RISK_PCT = 1.0          # % of equity risked per trade (entry → stop)
# Was 8. Eight slots and one plan pass meant the account opened everything that
# cleared the gate in the same minute: on 2026-10-15 that was AAPL, CSCO, GOOGL
# and PLTR, all short, all at 09:36, ~$9,800 each. That is one leveraged bet on
# the Nasdaq, not four trades, and the sizer has no concept of correlation. The
# 26 trades opened in the same minute as another lost $1,912 of the $2,331 total.
DEFAULT_MAX_POSITIONS = 2
# …and a hard ceiling on how many NEW trades a session may open, so a choppy day
# that keeps printing cards can't turn into twelve entries.
DEFAULT_MAX_NEW_TRADES_PER_DAY = 3
DEFAULT_MAX_HOLD_DAYS = 10      # auto-close a position the plan stopped mentioning
TRADE_LOG_LIMIT = 200
JOURNAL_LIMIT = 500
ATR_STOP_MULT = 1.2             # default stop distance when the card gave none
ATR_TARGET_RR = 2.0             # default target = 2× the stop risk
# Reward/risk floor. 1.8 was below what the funnel's own first target now has to
# clear (playbook.MIN_RR_T1 = 2.0), which made it decorative.
DEFAULT_MIN_RR = 2.0
# Grades allowed to trade, best first. The funnel already refuses to emit an
# order below B; this is the setting that lets the trader tighten it further.
GRADE_ORDER = ("A+", "A", "B", "C")
DEFAULT_MIN_GRADE = "B"
# Shorts off by default. Of the 100 trades on the first account, 38 shorts lost
# $2,160 and 62 longs lost $171 — the short side IS the loss, and 7 pre-market
# shorts alone accounted for $1,506 of it. Re-enable it from the Alpha Wolf tab
# once the long side has shown positive expectancy over a real sample.
DEFAULT_ALLOW_SHORTS = False

_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")


# ── The entry window ────────────────────────────────────────────────────────
# Minutes since midnight ET. Entries only; closes, stop/target management and
# fill reconciliation are deliberately NOT bounded by this.
#
# `execute_plan` used to check only that it was a weekday, and Alpha Wolf's plan
# cron fires at 08:30 — so cards computed from one or two thin pre-market bars
# became live bracket orders. 42 of 200 fills landed in the 08:00 hour; the 16
# pre-market entries lost $1,391. Session VWAP, the volume profile and the
# initial balance — every input behind those cards — barely exist at 08:34.
#
# The late bound exists for the mirror reason: an entry submitted at 15:40 is a
# position opened with twenty minutes left to work, on a level computed for a
# session that is closing, and SESSION_FLAT_MIN flattens it at 15:45 anyway.
ENTRY_OPEN_MIN = 9 * 60 + 45
ENTRY_CLOSE_MIN = 15 * 60 + 30


def window_state_for(minutes: int, trading_day: bool = True) -> dict:
    """Is it legal to OPEN a position at `minutes` past midnight ET? Pure.

    Split out from entry_window_state so every caller that ALREADY has a clock —
    the live decision snapshot carries one, and the tests pass one — asks about
    that clock instead of about wall time. A function handed a 10:00 clock that
    then consults datetime.now() is untestable and, worse, can disagree with the
    screen it is rendering.
    """
    fmt = lambda m: f"{m // 60}:{m % 60:02d}"            # noqa: E731
    if not trading_day:
        return {"open": False, "minutes": minutes,
                "why": "weekend — no entries, Alpha Wolf only trades Mon-Fri"}
    if minutes < ENTRY_OPEN_MIN:
        return {"open": False, "minutes": minutes,
                "why": f"entries open at {fmt(ENTRY_OPEN_MIN)} ET — pre-market and the "
                       f"opening 15 minutes are too thin for the levels these cards use"}
    if minutes >= ENTRY_CLOSE_MIN:
        return {"open": False, "minutes": minutes,
                "why": f"entries closed at {fmt(ENTRY_CLOSE_MIN)} ET — too late to give a "
                       f"position room before the session flat"}
    return {"open": True, "minutes": minutes,
            "why": f"entry window {fmt(ENTRY_OPEN_MIN)}-{fmt(ENTRY_CLOSE_MIN)} ET"}


def entry_window_state(now: datetime.datetime = None) -> dict:
    """window_state_for() against a wall clock (ET)."""
    now = now or datetime.datetime.now(ET)
    return window_state_for(now.hour * 60 + now.minute, now.weekday() < 5)


# ── Position math ───────────────────────────────────────────────────────────
def position_value(pos: dict, price: float = None) -> float:
    """Current liquidation value of a position. Shorts hold their entry value
    as reserved margin and earn/lose the move from entry."""
    price = price if price is not None else pos.get("last_price", pos["entry_price"])
    shares = pos["shares"]
    if pos.get("direction") == "short":
        margin = pos.get("margin", pos["entry_price"] * shares)
        return margin + (pos["entry_price"] - price) * shares
    return price * shares


def position_pnl(pos: dict, price: float = None) -> float:
    price = price if price is not None else pos.get("last_price", pos["entry_price"])
    move = (price - pos["entry_price"]) * pos["shares"]
    return -move if pos.get("direction") == "short" else move


def portfolio_equity(portfolio: dict) -> float:
    return round(portfolio["cash"] + sum(position_value(p) for p in portfolio["positions"].values()), 2)


def portfolio_summary(portfolio: dict) -> dict:
    equity = portfolio_equity(portfolio)
    start = portfolio.get("starting_capital") or DEFAULT_CAPITAL
    return {
        "equity": equity,
        "cash": round(portfolio["cash"], 2),
        "open_positions": len(portfolio["positions"]),
        "realized_pnl": round(portfolio.get("realized_pnl", 0.0), 2),
        "unrealized_pnl": round(sum(position_pnl(p) for p in portfolio["positions"].values()), 2),
        "return_pct": round((equity - start) / start * 100, 2) if start else 0.0,
    }


# ── Broader-market alignment (/ES + /NQ) ────────────────────────────────────
# Index futures are the tide every equity swims in: a long in a name whose own
# technicals look fine still fights the tape when /ES and /NQ are both bid
# lower. These read the COMPUTED /ES and /NQ bias from Technologia (VWAP, MFI,
# divergence, VSA, CVD — the same -6..+6 score the tab shows), so the direction
# filter rests on measured index state rather than anyone's prose.
INDEX_SYMBOLS = ("ES=F", "NQ=F")
INDEX_ALIGN_MIN = 3        # |combined| at/above this makes the tape directional


def market_bias(technologia: dict) -> dict:
    """Broader-market direction from the /ES and /NQ confluence scores.
    Returns {direction, score, detail}: direction is bullish/bearish only when
    the two indices AGREE and their combined conviction clears the bar —
    /ES up against /NQ down is chop, not a trend, and must not gate anything."""
    setups = ((technologia or {}).get("signals") or {}).get("setups") or []
    found = {s.get("symbol"): s for s in setups if s.get("symbol") in INDEX_SYMBOLS}
    scores = {sym: s.get("bias_score") for sym, s in found.items()
              if isinstance(s.get("bias_score"), (int, float))}
    if not scores:
        return {"direction": "unknown", "score": 0, "detail": "no /ES or /NQ reading available"}
    vals = list(scores.values())
    combined = sum(vals)
    label = ", ".join(f"{'/ES' if k == 'ES=F' else '/NQ'} {v:+d}" for k, v in sorted(scores.items()))
    # Disagreement between the two indices = no usable market direction.
    if len(vals) > 1 and not (all(v > 0 for v in vals) or all(v < 0 for v in vals)):
        return {"direction": "mixed", "score": combined, "detail": f"{label} — indices disagree"}
    if abs(combined) < INDEX_ALIGN_MIN:
        return {"direction": "neutral", "score": combined, "detail": f"{label} — no clear tape"}
    return {"direction": "bullish" if combined > 0 else "bearish",
            "score": combined, "detail": label}


# ── The gate (pure — unit-testable without DB or network) ───────────────────
def cards_by_ticker(technologia: dict) -> dict:
    """Technologia's computed trade cards keyed by symbol."""
    payload = ((technologia or {}).get("signals") or {})
    return {c["symbol"]: c for c in (payload.get("cards") or []) if c.get("symbol")}


def traded_today(trades: list, today: str = None) -> set:
    """Tickers this session has already traded — pure.

    A trade log row is written on every fill, entry or exit, so one appearance
    here means the account has already committed to that name today.
    """
    today = today or datetime.datetime.now().strftime("%Y-%m-%d")
    return {str(t.get("ticker", "")).upper() for t in trades or []
            if str(t.get("ts", "")).startswith(today) and t.get("ticker")}


def opened_today(trades: list, today: str = None) -> int:
    """How many NEW positions this session has opened — the daily trade cap
    counts entries, not round trips, so an exit never buys back a slot."""
    today = today or datetime.datetime.now().strftime("%Y-%m-%d")
    return sum(1 for t in trades or []
               if str(t.get("ts", "")).startswith(today)
               and str(t.get("action", "")).upper() in ("BUY", "SHORT"))


def idea_gate(idea: dict, settings: dict, market: dict = None, traded: set = None,
              opened: int = 0, window: dict = None):
    """Why a card should NOT trade, or None if it clears the gate.

    Every idea reaching here is a funnel card: a context, a zone with named
    sources, a fired trigger, an entry/stop/T1 priced off real levels and a
    grade. So the gates are about RISK and TIMING, not about re-judging the
    setup — the funnel already refused everything below grade B.

    Two gates were deleted outright:
      * the confidence floor. It scored the LLM's own ideas 1-10 and nothing
        originates from the LLM any more. On the live account it also carried no
        information (grade 8: -$2,030, grade 9: +$1,010, no score: -$1,149).
      * stance alignment ("no longs on a RISK-OFF stance"). `stance` is a word
        the model wrote; the computed /ES-/NQ tape below is the same filter with
        a measurement behind it.
    """
    d = str(idea.get("direction", "")).lower()
    if d not in ("long", "short"):
        return None                       # neutral ideas never trade anyway
    if window and not window.get("open", True):
        return f"gated: {window.get('why', 'outside the entry window')}"
    if d == "short" and not settings.get("allow_shorts", DEFAULT_ALLOW_SHORTS):
        return ("gated: shorts are off — the short side lost $2,160 of the first "
                "account's $2,331 (turn on in the risk settings)")
    grade = str(idea.get("grade") or "").upper()
    min_grade = str(settings.get("min_grade") or DEFAULT_MIN_GRADE).upper()
    if min_grade in GRADE_ORDER:
        if grade not in GRADE_ORDER:
            return "gated: card has no grade"
        if GRADE_ORDER.index(grade) > GRADE_ORDER.index(min_grade):
            return f"gated: grade {grade} is below the {min_grade} floor"
    min_rr = float(settings.get("min_rr", DEFAULT_MIN_RR))
    rr = idea.get("rr")
    if rr is not None and rr < min_rr:
        return f"gated: reward/risk {rr}:1 below the {min_rr}:1 floor"
    cap = int(settings.get("max_new_trades_per_day", DEFAULT_MAX_NEW_TRADES_PER_DAY))
    if opened >= cap:
        return (f"gated: {opened} position{'s' if opened != 1 else ''} already opened today — "
                f"the daily cap is {cap}")
    # Counter-tape trades are blocked only when the indices actually agree;
    # "mixed", "neutral" and "unknown" all leave the direction filter off, so
    # a missing Technologia run can never silently halt trading.
    if settings.get("align_market", True) and market:
        md = market.get("direction")
        if md == "bearish" and d == "long":
            return f"gated: broader market is bearish ({market.get('detail')}) — no fresh longs against the tape"
        if md == "bullish" and d == "short":
            return f"gated: broader market is bullish ({market.get('detail')}) — no fresh shorts against the tape"
    # One trade per symbol per session. The funnel re-runs every 30 minutes and
    # its verdict legitimately changes with the tape: AVGO printed a LONG card at
    # 14:00, filled, and by 15:51 the same symbol printed a SHORT. Without this
    # the plan closes the winner and reverses into the other side of the same name
    # on the same afternoon, and a stop-out becomes an invitation to re-enter an
    # hour later. Neither is a decision anyone made.
    if settings.get("one_trade_per_symbol", True) and traded:
        if str(idea.get("ticker", "")).upper() in traded:
            return ("gated: already traded today — one trade per symbol per session "
                    "(turn off in the risk settings to allow re-entry)")
    return None


def gate_plan(plan: dict, settings: dict, market: dict = None, traded: set = None,
              opened: int = 0, window: dict = None) -> tuple:
    """Filter the plan's daily ideas through idea_gate before order decisions.
    Returns (plan copy with only tradeable ideas, rejection records for the
    execution report). Only OPEN candidates are gated — closes of held
    positions (avoid list, direction flips) always go through.

    Ideas are gated in the order the plan lists them (best grade first) and the
    daily cap counts up as they pass, so a day with three slots left fills them
    with the three best cards rather than the first three it happens to see.
    """
    daily = plan.get("daily") or {}
    keep, rejected = [], []
    taken = 0
    for i in daily.get("ideas") or []:
        if not isinstance(i, dict):
            continue
        why = idea_gate(i, settings, market, traded, opened + taken, window)
        if why:
            rejected.append({"action": "open", "ticker": str(i.get("ticker", "")).upper(),
                             "direction": str(i.get("direction", "")).lower(), "why": why})
        else:
            keep.append(i)
            taken += 1
    return {**plan, "daily": {**daily, "ideas": keep}}, rejected


# ── Order decisions (pure — unit-testable without DB or network) ────────────
def avoid_hits(avoid: list, held: set) -> set:
    """Held tickers explicitly mentioned in the plan's avoid list."""
    hits = set()
    for line in avoid or []:
        for word in _TICKER_RE.findall(str(line)):
            if word in held:
                hits.add(word)
    return hits


def decide_orders(plan: dict, positions: dict, settings: dict) -> list:
    """Translate the plan into close/open orders against current positions:
    - close anything the plan now says to avoid,
    - close (and re-open) anything whose direction flipped,
    - open daily ideas (long/short) up to max_positions."""
    daily = plan.get("daily") or {}
    ideas = [i for i in (daily.get("ideas") or []) if isinstance(i, dict) and i.get("ticker")]
    by_ticker = {str(i["ticker"]).upper(): i for i in ideas}
    held = set(positions)
    avoided = avoid_hits(plan.get("avoid"), held)

    orders = []
    for t in sorted(avoided):
        orders.append({"action": "close", "ticker": t, "reason": "flagged in today's avoid list"})

    flipped = set()
    for t, pos in positions.items():
        if t in avoided:
            continue
        idea = by_ticker.get(t)
        if not idea:
            continue
        d = str(idea.get("direction", "")).lower()
        if d in ("long", "short") and d != pos.get("direction"):
            orders.append({"action": "close", "ticker": t, "reason": f"plan flipped {pos.get('direction')} → {d}"})
            flipped.add(t)

    open_slots = settings["max_positions"] - (len(held) - len(avoided) - len(flipped))
    # Plan order is grade order, so a capped day takes the best cards. `ideas`
    # was iterated as a dict before, which on a 2-slot account meant the two
    # trades taken were whichever tickers hashed first.
    for idea in ideas:
        t = str(idea["ticker"]).upper()
        d = str(idea.get("direction", "")).lower()
        if d not in ("long", "short"):
            continue
        if t in avoided:
            continue
        if t in held and t not in flipped:
            continue                      # already positioned the right way
        if open_slots <= 0:
            break
        orders.append({"action": "open", "ticker": t, "direction": d,
                       "thesis": str(idea.get("thesis", ""))[:300],
                       "reason": "funnel card",
                       # Levels come straight off the card — see
                       # agent13.cards_to_ideas.
                       "entry": idea.get("entry_px"),
                       "stop": idea.get("stop_px"), "target": idea.get("target_px"),
                       "atr14": idea.get("atr14"),
                       "grade": idea.get("grade"), "rr": idea.get("rr")})
        open_slots -= 1
    return orders


def _default_levels(direction: str, price: float, atr) -> tuple:
    """ATR-based stop/target when the card didn't supply usable levels:
    stop 1.2×ATR against the trade, target at 2× that risk. Falls back to a
    2%/4% envelope when no ATR is known."""
    risk = ATR_STOP_MULT * atr if atr else price * 0.02
    if direction == "short":
        return round(price + risk, 2), round(price - ATR_TARGET_RR * risk, 2)
    return round(price - risk, 2), round(price + ATR_TARGET_RR * risk, 2)


def size_position(equity: float, cash: float, price: float, stop: float, settings: dict,
                  whole_shares: bool = True) -> tuple:
    """Risk-based position size: risk a fixed % of equity on the entry→stop
    distance, so a wide stop takes a small position and a tight stop a larger
    one. Every trade then risks the same amount, and the equity curve reflects
    whether the ideas were good rather than how wide their stops happened to
    be. Still capped by position_pct (concentration) and available cash.

    Returns (shares, reason) — shares of 0 means skip, with the reason why.
    Pure — unit-testable."""
    if not price or price <= 0:
        return 0, "no price available"
    risk_pct = float(settings.get("risk_pct") or DEFAULT_RISK_PCT)
    risk_per_share = abs(price - stop) if stop else 0.0
    if risk_per_share <= 0:
        return 0, "stop is at or through the entry — cannot size by risk"

    by_risk = (equity * risk_pct / 100.0) / risk_per_share
    notional_cap = min(cash, equity * settings["position_pct"] / 100.0)
    by_notional = notional_cap / price
    shares = min(by_risk, by_notional)
    shares = int(shares) if whole_shares else round(shares, 4)

    if shares <= 0:
        if by_risk < by_notional:
            return 0, (f"stop is ${risk_per_share:.2f} away — too wide to risk only "
                       f"{risk_pct:g}% of equity on even 1 share")
        return 0, "insufficient cash for 1 share"
    return shares, ""


def _sane_stop(direction, price, stop):
    """A stop on the wrong side of the entry is worse than none."""
    if not stop:
        return None
    return stop if (direction == "short") == (stop > price) else None


def _sane_target(direction, price, target):
    if not target:
        return None
    return target if (direction == "short") == (target < price) else None


def _journal_close(journal: list, ticker: str, pos: dict, price: float, pnl: float, reason: str):
    """Append a closed-trade record — the raw material for win-rate and
    P&L-attribution stats on the Alpha Wolf tab, and the only evidence that can
    say whether a change to these rules helped."""
    if journal is None:
        return
    basis = pos["entry_price"] * pos["shares"]
    hold_days = None
    try:
        entered = datetime.datetime.strptime(pos.get("entry_date", ""), "%Y-%m-%d %H:%M")
        hold_days = round((datetime.datetime.now() - entered).total_seconds() / 86400, 1)
    except (ValueError, TypeError):
        pass
    # R multiple against the INITIAL stop — the risk actually accepted at entry,
    # not wherever a breakeven move or a trail later put it.
    initial_stop = pos.get("initial_stop") or pos.get("stop")
    r_multiple = None
    if initial_stop:
        risk_per_share = abs(pos["entry_price"] - initial_stop)
        if risk_per_share > 0:
            r_multiple = round((pnl / pos["shares"]) / risk_per_share, 2)
    journal.insert(0, {
        "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ticker": ticker, "direction": pos.get("direction"), "shares": pos["shares"],
        "entry_price": pos["entry_price"], "exit_price": round(price, 4),
        "entry_date": pos.get("entry_date"), "hold_days": hold_days,
        "pnl": round(pnl, 2), "pnl_pct": round(pnl / basis * 100, 2) if basis else 0.0,
        "r_multiple": r_multiple,
        "stop": pos.get("stop"), "target": pos.get("target"),
        "grade": pos.get("grade"),
        "reason": reason, "thesis": str(pos.get("thesis", ""))[:200],
    })
    del journal[JOURNAL_LIMIT:]


# ── Performance stats from the closed-trade journal ─────────────────────────
def journal_stats(journal: list) -> dict:
    closed = [j for j in journal or [] if isinstance(j.get("pnl"), (int, float))]
    if not closed:
        return {"trades": 0}
    wins = [j for j in closed if j["pnl"] > 0]
    losses = [j for j in closed if j["pnl"] <= 0]
    gross_win = sum(j["pnl"] for j in wins)
    gross_loss = -sum(j["pnl"] for j in losses)
    holds = [j["hold_days"] for j in closed if isinstance(j.get("hold_days"), (int, float))]
    by_reason = {}
    for j in closed:
        key = ("stop" if "stop hit" in str(j.get("reason", "")) else
               "target" if "target hit" in str(j.get("reason", "")) else "plan")
        r = by_reason.setdefault(key, {"n": 0, "pnl": 0.0})
        r["n"] += 1
        r["pnl"] = round(r["pnl"] + j["pnl"], 2)
    # R-multiple expectancy — the average trade in units of risk taken.
    # Positive expectancy with 100+ trades is the actual definition of an edge.
    # The first account's was -0.35R over 100 trades.
    rs = [j["r_multiple"] for j in closed if isinstance(j.get("r_multiple"), (int, float))]
    r_wins = [r for r in rs if r > 0]
    r_losses = [r for r in rs if r <= 0]
    # Win rate bucketed by the funnel's grade — shows whether an A actually beats
    # a B, or whether the grading is noise. This used to bucket by the LLM's
    # self-rated confidence, which measured nothing.
    by_grade = {}
    for j in closed:
        key = str(j.get("grade") or "n/a")
        b = by_grade.setdefault(key, {"n": 0, "wins": 0, "pnl": 0.0})
        b["n"] += 1
        b["wins"] += 1 if j["pnl"] > 0 else 0
        b["pnl"] = round(b["pnl"] + j["pnl"], 2)
    win_rate = len(wins) / len(closed)
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    # The one number that says whether this is worth running: expected dollars
    # per trade. Negative means every additional trade is a cost.
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss
    return {
        "trades": len(closed),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(win_rate * 100, 1),
        "total_pnl": round(gross_win - gross_loss, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(-avg_loss, 2),
        "payoff": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
        "expectancy": round(expectancy, 2),
        # What win rate this payoff ratio needs just to break even. Printing it
        # beside the actual win rate is the whole diagnosis in two numbers.
        "breakeven_win_rate": (round(avg_loss / (avg_win + avg_loss) * 100, 1)
                               if (avg_win + avg_loss) > 0 else None),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "best": max(closed, key=lambda j: j["pnl"])["pnl"],
        "worst": min(closed, key=lambda j: j["pnl"])["pnl"],
        "avg_hold_days": round(sum(holds) / len(holds), 1) if holds else None,
        "by_exit": by_reason,
        "expectancy_r": round(sum(rs) / len(rs), 2) if rs else None,
        "avg_win_r": round(sum(r_wins) / len(r_wins), 2) if r_wins else None,
        "avg_loss_r": round(sum(r_losses) / len(r_losses), 2) if r_losses else None,
        "by_grade": by_grade,
    }
