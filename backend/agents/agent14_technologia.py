# ============================================================================
# Agent 14 — Technologia
# Adapts the EminiPlayer /ES thinkScript framework (Volume Profile zones,
# VSA signals, VWAP/CVD momentum, MFI divergence) to Python for the stock
# watchlist plus /ES and /NQ futures. Real computed indicators (not LLM
# guesses) feed a 0-6 bull/bear bias score per symbol; the single highest-
# conviction setup of the day is called out as "Today's A+ Setup" — the
# one-trade-per-day discipline from the source material, adapted from a
# literal trade latch (this agent doesn't execute) to a daily focus signal.
#
# /ES and /NQ are informational only — Alpaca (the paper broker) can't trade
# futures, so these never generate paper orders; they feed Alpha Wolf as
# context like Compass's pivots do today.
# ============================================================================
import asyncio
import concurrent.futures
import datetime
import logging
from zoneinfo import ZoneInfo

from database import save_agent_data, get_agent_data, get_config
from llm_client import generate_completion
from orchestrator import orchestrator
from email_utils import send_html_email
from tools import levels as levels_tool
from tools import technologia_signals as sig
from tools import strategies as strat
from tools import auction, smc, playbook
from agents.agent3_wallstreet_wolf import get_watchlist, ticker_name

log = logging.getLogger("technologia")

AGENT_ID = "technologia"
ET = ZoneInfo("America/New_York")

FUTURES = {"ES=F": "/ES", "NQ=F": "/NQ"}
# EminiPlayer's defined entry window for /ES day trades — bars 13-30 / 10:30-11:55 ET.
ENTRY_WINDOW = (10 * 60 + 30, 11 * 60 + 55)  # minutes since midnight ET


def _in_entry_window(now: datetime.datetime = None) -> bool:
    now = now or datetime.datetime.now(ET)
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and ENTRY_WINDOW[0] <= mins <= ENTRY_WINDOW[1]


def symbols() -> list:
    return get_watchlist() + list(FUTURES.keys())


def _label(symbol: str) -> str:
    return FUTURES.get(symbol) or ticker_name(symbol)


def compute_for_symbol_sync(symbol: str, benchmark_change_pct: float = None,
                            progress: float = None):
    """Full Technologia signal snapshot for one symbol. Sync — called via a
    thread pool, same pattern as tools/levels.py and tools/technicals.py."""
    if progress is None:
        now = datetime.datetime.now(ET)
        progress = strat.session_progress(now.hour * 60 + now.minute)
    # One multi-session intraday fetch instead of two: it carries today's bars
    # AND the prior sessions the cross-session levels need (yesterday's value
    # area, naked POCs, the opening-volume baseline).
    sessions = levels_tool.fetch_recent_sessions_sync(symbol, days=5)
    session_bars = sessions[-1]["bars"] if sessions else levels_tool.fetch_session_bars_sync(symbol)
    # A year of daily bars: the Decision Point screen needs the 52-week
    # extremes. Everything that read a 3-month window still gets one (recent),
    # so swing levels and the coarse weekly profile are unchanged.
    year_bars = levels_tool.fetch_daily_bars_sync(symbol, period="1y")
    daily_bars = year_bars[-63:] if year_bars else []
    if not session_bars and not daily_bars:
        return None

    price = round(session_bars[-1]["close"] if session_bars else daily_bars[-1]["close"], 2)
    rth = auction.rth_bars(session_bars)
    vwap = levels_tool.session_vwap(rth or session_bars)
    vwap_pos = levels_tool.vwap_position(price, vwap)
    profile = levels_tool.volume_profile(rth or session_bars)
    # Coarse "weekly" VP context from the last 5 daily bars — real weekly
    # volume-profile granularity needs intraday history TOS has and yfinance
    # doesn't retain; this is the same "computed, not guessed" tradeoff the
    # source material's weekly VP zones make at a coarser resolution.
    weekly_profile = levels_tool.volume_profile(daily_bars[-5:]) if len(daily_bars) >= 5 else {}
    swings = (levels_tool.swing_levels(daily_bars, price=price) if daily_bars
              else {"support": [], "resistance": []})
    near = levels_tool.nearest_levels(price, swings["support"], swings["resistance"])

    mfi_series = sig.money_flow_index(session_bars) if session_bars else []
    mfi_last = next((v for v in reversed(mfi_series) if v is not None), None)
    divergence = sig.mfi_divergence(session_bars, mfi_series) if session_bars else None
    vsa = sig.approximate_vsa(session_bars) if session_bars else {"signal": None}
    cvd = sig.approximate_cvd(session_bars) if session_bars else {"cvd": None, "trend": None}
    bias = sig.bias_score(vwap_pos, mfi_last, divergence, vsa, cvd)

    # TWO ATRs, deliberately. The daily ATR sizes risk and answers "can this
    # level be reached today"; the 5-minute ATR is what an intraday imbalance
    # or a zone width has to be measured against. Using the daily figure for
    # both — the first cut of this did — set the fair-value-gap floor at 0.76
    # on NVDA and the zone tolerance at $1.89, which found zero gaps and then
    # merged the entire session's levels into one meaningless zone.
    #
    # The intraday figure is a session-wide median, not atr(bars, 14): a 14-bar
    # window is only 70 minutes and swung ±50% run to run, dragging every
    # threshold scaled to it along with the last hour of tape. See
    # strategies.intraday_atr — the daily:intraday ratio is expected to be large.
    atr14 = strat.atr(daily_bars, 14) if daily_bars else None
    entry_scale_bars = rth or session_bars
    atr_intraday = (strat.intraday_atr(entry_scale_bars)
                    or strat.atr(entry_scale_bars, 14)
                    or (atr14 / 12 if atr14 else None))
    opening_rvol = strat.opening_relative_volume(sessions)

    # How much is this name actually trading today. An INPUT to the funnel's
    # liquidity gate, not a verdict — two sibling verdict engines (a VWAP/EMA
    # state and the full Decision Point screen) used to be computed here and
    # published beside the card, which is how one symbol could read ENTER, +2
    # neutral and DEAD at the same time. Only the card decides now.
    metrics = strat.participation(year_bars, session_bars, price,
                                  progress=progress, opening_rvol=opening_rvol)

    # ── The funnel: context → location → trigger → risk ────────────────────
    # Everything above is an INPUT from here down. Only the card is a verdict.
    prior_levels = auction.prior_day_levels(daily_bars)
    # RTH first, whole session as a fallback: /ES and /NQ trade nearly around
    # the clock, and on a prior day whose RTH slice came back empty the value
    # area would otherwise be None — taking the value-location and 80%-rule
    # logic offline for exactly the two symbols the framework was written for.
    prior_profile = {}
    if len(sessions) >= 2:
        prev = sessions[-2]["bars"]
        prior_profile = (levels_tool.volume_profile(auction.rth_bars(prev))
                         or levels_tool.volume_profile(prev))
    session_profiles = [
        {"date": s["date"],
         **(levels_tool.volume_profile(auction.rth_bars(s["bars"]))
            or levels_tool.volume_profile(s["bars"]))}
        for s in sessions
    ]
    nakeds = auction.naked_pocs(session_profiles, price)
    ib = auction.initial_balance(session_bars, atr=atr14)
    opening = auction.opening_type(session_bars, atr=atr14)
    on_range = auction.overnight_range(session_bars)
    value_loc = auction.open_vs_value(opening.get("open_px"),
                                      prior_profile.get("vah"), prior_profile.get("val"))
    rule80 = auction.eighty_percent_rule(session_bars, prior_profile.get("vah"),
                                         prior_profile.get("val"))
    context = auction.day_context(session_bars, vwap=vwap, prior=prior_levels, ib=ib,
                                  opening=opening, value_loc=value_loc, atr=atr14)

    entry_bars = rth or session_bars
    zones = (smc.fair_value_gaps(entry_bars, atr_intraday)
             + smc.order_blocks(entry_bars, atr_intraday))
    ref_levels = playbook.reference_levels(
        price=price, vwap=vwap, profile=profile, prior_profile=prior_profile,
        prior=prior_levels, ib=ib, on_range=on_range, nakeds=nakeds,
        swings=(swings["support"] + swings["resistance"]), zones=zones)
    # Zones are clustered on the intraday scale; reachability is judged on the
    # daily one, so a level a day's range away still counts as in play.
    pois = playbook.points_of_interest(ref_levels, price, atr_intraday, reach_atr=atr14)
    liquidity = strat.liquidity_floor(metrics)

    card = playbook.trade_card(
        symbol=symbol, label=_label(symbol), price=price, bars=entry_bars,
        atr=atr_intraday, context=context, levels=ref_levels, pois=pois,
        liquidity=liquidity, reach_atr=atr14,
        in_window=(_in_entry_window() if symbol in FUTURES else True))

    return {
        "symbol": symbol, "label": _label(symbol), "price": price,
        "vwap": vwap, "vwap_position": vwap_pos, "atr14": atr14,
        "atr_intraday": atr_intraday, "liquidity": liquidity,
        "poc": profile.get("poc"), "vah": profile.get("vah"), "val": profile.get("val"),
        "weekly_poc": weekly_profile.get("poc"), "weekly_vah": weekly_profile.get("vah"),
        "weekly_val": weekly_profile.get("val"),
        "nearest_support": near.get("support"), "nearest_resistance": near.get("resistance"),
        "mfi": mfi_last, "mfi_divergence": divergence,
        "vsa_signal": vsa.get("signal"), "cvd_trend": cvd.get("trend"),
        "bias_score": bias["score"], "bias_direction": bias["direction"], "bias_reasons": bias["reasons"],
        "participation": metrics,
        "auction": {"prior": prior_levels, "prior_value": prior_profile, "ib": ib,
                    "opening": opening, "overnight": on_range, "value_location": value_loc,
                    "eighty_pct_rule": rule80, "naked_pocs": nakeds},
        "context": context, "pois": pois, "zones": zones, "card": card,
        "is_futures": symbol in FUTURES,
    }


def _benchmark_change_sync(symbol: str = "SPY"):
    """Today's move in the index, so relative strength is measured against
    something rather than asserted."""
    bars = levels_tool.fetch_daily_bars_sync(symbol, period="1mo")
    if len(bars) < 2 or not bars[-2]["close"]:
        return None
    return round((bars[-1]["close"] - bars[-2]["close"]) / bars[-2]["close"] * 100, 2)


def compute_sync(syms: list) -> dict:
    bench = _benchmark_change_sync()
    now = datetime.datetime.now(ET)
    # One progress value for the whole batch, so every symbol's relative volume
    # is projected against the same point in the session.
    progress = strat.session_progress(now.hour * 60 + now.minute)
    out = {}
    # 8 was chosen per-agent, but the limit that matters is per-PROCESS: Wolf runs
    # its own pool against the same upstream, and when the two aligned the
    # combined burst was what triggered the rate limits and the file-handle
    # exhaustion. 4 here plus the shared bar cache in tools/levels keeps the
    # steady-state request count well under the old peak.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(compute_for_symbol_sync, sym, bench, progress): sym for sym in syms}
        for fut in concurrent.futures.as_completed(futs):
            try:
                res = fut.result()
            except Exception as e:
                # Don't let one bad symbol take the batch down, but don't hide it
                # either — a swallowed exception here is why coverage collapses
                # invisibly.
                log.warning(f"compute failed for {futs[fut]}: {e}")
                continue
            if res:
                out[futs[fut]] = res
    missing = [s for s in syms if s not in out]
    if missing:
        log.warning(f"no data for {len(missing)}/{len(syms)} symbols: {', '.join(missing)}")
    return {s: out[s] for s in syms if s in out}


# The compute window, in minutes since midnight ET. It opens at 08:00 — an hour
# BEFORE the equity open — because Alpha Wolf synthesizes the master game-plan at
# 08:30 and reads this agent's stored snapshot to do it. With the window opening
# at 09:00 the plan was built, every single day, on the previous session's
# 16:15 cards: the funnel never had a say in the plan that traded that morning.
# Pre-market bars are thin and most cards will read WAIT or STAND_DOWN — that is
# the honest answer at 08:00, and it is still today's answer rather than
# yesterday's.
OPEN_MIN, CLOSE_MIN = 8 * 60, 16 * 60 + 15


def _market_is_open(now: datetime.datetime = None) -> bool:
    """The session window this agent computes in — pre-market head start
    included.

    The job ran on a bare 30-minute interval with no clock, so it fired at 01:02
    ET and through weekends. Those runs computed nothing useful, spent an LLM
    call each, and — because the payload is one row — OVERWROTE the snapshot the
    trading session had produced. The 09:45 verdict was routinely replaced by a
    dead-tape reading from the middle of the night.
    """
    now = now or datetime.datetime.now(ET)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return OPEN_MIN <= mins <= CLOSE_MIN


def snapshot_age_minutes(data: dict = None):
    """How old the stored signals snapshot is, in minutes — None if there is
    none or its stamp can't be read.

    Alpha Wolf uses this to decide whether the cards it is about to fold into
    the master plan are current or a relic of an earlier run. The stamp is
    written as '%Y-%m-%d %H:%M ET' by the job below; `generated_ts` is the same
    instant as an epoch, kept for snapshots written before that field existed.
    """
    payload = ((data if data is not None else get_agent_data(AGENT_ID)) or {}).get("signals") or {}
    ts = payload.get("generated_ts")
    if not isinstance(ts, (int, float)):
        stamp = str(payload.get("generated_at") or "").removesuffix(" ET").strip()
        try:
            ts = datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=ET).timestamp()
        except ValueError:
            return None
    return max(0.0, (datetime.datetime.now(ET).timestamp() - ts) / 60)


GRADE_RANK = {"A+": 0, "A": 1, "B": 2, "C": 3, "NONE": 4}
ACTION_RANK = {"LONG": 0, "SHORT": 0, "WAIT": 1, "STAND_DOWN": 2}


def rank_key(t: dict):
    """Sort order for the watchlist: actionable cards first, best grade first,
    then by the confluence weight of the zone behind them. The old key was
    -abs(bias_score), which put the loudest indicator reading on top whether or
    not there was a trade at that price."""
    c = t.get("card") or {}
    poi = c.get("poi") or {}
    return (ACTION_RANK.get(c.get("action"), 3), GRADE_RANK.get(c.get("grade"), 3),
            -poi.get("confluence", 0), -abs(t.get("bias_score") or 0))


def summary_line(t: dict) -> str:
    """The card first (the verdict), then the readings behind it. Order matters:
    every consumer of this line — the email, the LLM prompt, Alpha Wolf — used
    to open with a bias score that answered a different question than the one
    the reader was asking."""
    card = t.get("card")
    bits = [playbook.card_line(card)] if card else []
    bits += [f"${t['price']}", f"bias {t['bias_direction']} ({t['bias_score']:+d}/6)"]
    if t.get("vwap") is not None:
        bits.append(f"VWAP {t['vwap']} ({t['vwap_position']})")
    if t.get("mfi_divergence"):
        bits.append(f"MFI {t['mfi_divergence']} divergence")
    if t.get("nearest_support") is not None:
        bits.append(f"S {t['nearest_support']}")
    if t.get("nearest_resistance") is not None:
        bits.append(f"R {t['nearest_resistance']}")
    part = strat.participation_line(t.get("participation") or {})
    if part:
        bits.append(part)
    return " · ".join(bits)


THREE_STAGE_EXIT = (
    "Three-stage exit once in a trade: partial at the prior swing level, "
    "remainder at the 20 SMA, trail the runner behind structure."
)


async def build_llm_commentary(setups: list, top_setup: dict = None) -> str:
    """Commentary over the FUNNEL's output, not over raw indicator readings.

    The prompt is deliberately narrow. The computation already decided context,
    zone, trigger and levels; asking the model to re-derive a view from raw
    numbers invites it to invent a bullish story about a stand-down day. Its
    only job here is to compress what was computed into something readable —
    and to say plainly when the answer is "no trade".
    """
    if not setups:
        return "No qualifying technical setups this run."
    lines = [f"{s['label']} ({s['symbol']}): {summary_line(s)}" for s in setups[:10]]
    top_txt = (f"\nToday's A+ card (one-trade discipline): {top_setup['label']} — "
               f"{playbook.card_line(top_setup['card'])}." if top_setup else
               "\nNo symbol produced a tradeable card — the correct output today is 'stand down'.")
    prompt = f"""You are a systematic day-trading analyst. Each line below is ALREADY a decided verdict produced by a four-stage funnel: auction context (trend/balance/undecided) → point of interest (a price zone where several independent methods agree) → trigger (a liquidity sweep or structure shift, never a mere touch) → risk (entry, stop, T1/T2, R).

Write 3-5 bullets. Each starts with '• ' on its own line, max 16 words.

Rules:
- Report the cards. Do NOT invent a direction the funnel did not give you.
- Name the ticker, the zone price, and the trigger or the reason it is waiting.
- If most lines are STAND_DOWN or WAIT, say that clearly in the first bullet. A quiet tape is a finding, not a failure to find something.
- No paragraphs, no intro or outro. /no_think

{chr(10).join(lines)}
{top_txt}"""
    try:
        return await generate_completion(prompt, agent_id=AGENT_ID)
    except Exception:
        return ("Cards computed for the full watchlist — read the A/B grades first; "
                "everything else is waiting on a trigger or standing down.")


def _build_email(payload: dict) -> str:
    setups = payload.get("setups", [])
    top = payload.get("top_setup")
    rows = "".join(f"""
    <div style='padding:10px 0;border-bottom:1px solid #f0f0f0'>
      <div style='font-size:13px;font-weight:700;color:#1a1a2e'>{s['label']} ({s['symbol']}) — <span style='color:{"#16a34a" if s["bias_direction"]=="bullish" else "#dc2626" if s["bias_direction"]=="bearish" else "#6b7280"}'>{s['bias_direction'].upper()} {s['bias_score']:+d}/6</span></div>
      <div style='font-size:12px;color:#555;margin-top:3px'>{summary_line(s)}</div>
    </div>""" for s in setups[:12])
    top_section = ""
    if top:
        top_section = f"""
    <div style='background:#f5f3ff;border-left:4px solid #7c3aed;padding:14px 20px;margin-bottom:16px;border-radius:0 8px 8px 0'>
      <div style='font-size:12px;font-weight:700;color:#7c3aed;margin-bottom:6px'>TODAY'S A+ SETUP — ONE-TRADE DISCIPLINE</div>
      <div style='font-size:14px;font-weight:700;color:#1a1a2e'>{top['label']} ({top['symbol']})</div>
      <div style='font-size:12.5px;color:#444;margin-top:4px'>{summary_line(top)}</div>
      <div style='font-size:11.5px;color:#7c3aed;margin-top:8px'>{THREE_STAGE_EXIT}</div>
    </div>"""
    return f"""<!DOCTYPE html><html><body style='font-family:Helvetica,sans-serif;background:#f6f7f9;margin:0;padding:0'>
<div style='max-width:640px;margin:24px auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb'>
  <div style='background:linear-gradient(135deg,#1e1b4b,#7c3aed);padding:26px 32px'>
    <div style='font-size:22px;font-weight:800;color:#fff'>◭ Technologia</div>
    <div style='font-size:13px;color:#ddd6fe;margin-top:4px'>VP zones · VWAP · MFI divergence · VSA/CVD (approx)</div>
  </div>
  <div style='padding:20px 32px;background:#f5f3ff;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:14px;line-height:1.6;color:#312e81'>{payload.get("commentary","")}</div>
  </div>
  <div style='padding:20px 32px'>
    {top_section}
    <div style='font-size:12px;font-weight:700;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px'>ALL SIGNALS</div>
    {rows}
  </div>
  <div style='padding:14px 32px;text-align:center;font-size:11px;color:#aeb4bf'>
    Technologia · Multi-Agent Platform · Educational analysis only, not financial advice
  </div>
</div></body></html>"""


async def technologia_job(force: bool = False):
    log.info("Technologia starting")
    if not force and not _market_is_open():
        # Refresh nothing and overwrite nothing. The stored snapshot stays as the
        # last thing the live tape actually said.
        log.info("Technologia skipped — outside market hours")
        orchestrator.update_agent_status(AGENT_ID, "idle")
        orchestrator.set_progress(AGENT_ID, "Market closed — holding the last session's cards")
        return
    orchestrator.update_agent_status(AGENT_ID, "running")
    try:
        syms = symbols()
        orchestrator.set_progress(AGENT_ID, f"Computing VP/VWAP/MFI/VSA signals for {len(syms)} symbols…")
        computed = await asyncio.to_thread(compute_sync, syms)

        setups = sorted(computed.values(), key=rank_key)
        # "Qualifying" now means the funnel produced an actual trade, not that
        # an indicator sum crossed 3. A watchlist of 24 megacaps on a quiet day
        # SHOULD return zero — that is the screen working, not a bug.
        actionable = [s for s in setups if (s.get("card") or {}).get("action") in ("LONG", "SHORT")]
        armed = [s for s in setups if (s.get("card") or {}).get("action") == "WAIT"
                 and (s.get("card") or {}).get("poi")]
        qualifying = actionable
        # The headline card has to be one that can actually become a trade.
        # /ES and /NQ outrank everything on confluence often enough that the
        # day's featured setup was regularly a futures card Alpha Wolf can never
        # route to Alpaca — the two tabs then named different trades of the day.
        # Futures stay in the table and still drive the tape gate; they just
        # don't get to be the headline.
        equity_setups = [s for s in actionable if s["symbol"] not in FUTURES]
        top_setup = equity_setups[0] if equity_setups else None

        now_et = datetime.datetime.now(ET)
        futures_in_window = _in_entry_window(now_et)

        commentary = await build_llm_commentary(setups, top_setup)

        payload = {
            "setups": setups,
            "top_setup": top_setup,
            "qualifying_count": len(qualifying),
            "armed_count": len(armed),
            "cards": [s["card"] for s in setups if s.get("card")],
            "commentary": commentary,
            "three_stage_exit": THREE_STAGE_EXIT,
            "entry_window": {"start": "10:30", "end": "11:55", "in_window": futures_in_window,
                            "note": "Applies to /ES and /NQ per the source framework — first OR breakout "
                                    "is typically a liquidity grab, trade the reversal, not the breakout."},
            "generated_at": now_et.strftime("%Y-%m-%d %H:%M ET"),
            # The same instant as an epoch, so freshness is a subtraction rather
            # than a string parse — Alpha Wolf checks this every pulse.
            "generated_ts": now_et.timestamp(),
            # Coverage, so a starved run is legible instead of looking like a
            # quiet tape. A run that saw 2 of 24 symbols found nothing because it
            # had no data, not because there was nothing to find.
            "coverage": {"requested": len(syms), "returned": len(computed),
                         "missing": [s for s in syms if s not in computed]},
        }
        save_agent_data(AGENT_ID, {"signals": payload})
        # Keep the session's best card even after a later, quieter run. Without
        # this the day's one good setup is unrecoverable ten minutes after it
        # appeared, which is most of why the app felt like it never fired.
        if top_setup:
            best = (get_agent_data(AGENT_ID) or {}).get("best_of_session") or {}
            session_date = now_et.strftime("%Y-%m-%d")
            prior_rr = (best.get("card") or {}).get("rr") or 0
            if best.get("date") != session_date or (top_setup["card"].get("rr") or 0) >= prior_rr:
                save_agent_data(AGENT_ID, {"best_of_session": {
                    "date": session_date, "at": now_et.strftime("%H:%M ET"),
                    "symbol": top_setup["symbol"], "label": top_setup["label"],
                    "card": top_setup["card"]}})
        orchestrator.update_agent_status(AGENT_ID, "idle")

        recipient = get_config("recipient", "")
        if recipient:
            send_html_email(recipient, "◭ Technologia — Daily Technical Setups", _build_email(payload))

        log.info(f"Technologia complete — {len(computed)}/{len(syms)} symbols, "
                 f"{len(qualifying)} tradeable card(s), {len(armed)} waiting on a trigger")
    except Exception as e:
        log.error(f"Technologia error: {e}", exc_info=True)
        orchestrator.update_agent_status(AGENT_ID, "error", str(e))
        raise


def email_preview() -> dict:
    data = (get_agent_data(AGENT_ID) or {}).get("signals") or {}
    if not data:
        return {"html": "<p>No Technologia data yet. Run the agent first.</p>"}
    return {"html": _build_email(data)}
