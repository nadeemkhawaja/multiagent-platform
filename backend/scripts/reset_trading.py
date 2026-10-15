#!/usr/bin/env python3
"""
Reset the trading state for a fresh Alpaca account.

    python3 scripts/reset_trading.py            # show what would be cleared
    python3 scripts/reset_trading.py --yes      # clear it
    python3 scripts/reset_trading.py --yes --archive   # …keeping a JSON copy
    python3 scripts/reset_trading.py --yes --prune-dead-agents

Local only: this NEVER places, cancels or closes an order. It clears what this
app stores — the portfolio snapshot, the trade log, the closed-trade journal,
position metadata, working entry orders, the master plan, the pulse record and
every alpha_wolf_* setting — and then re-baselines return% against whatever the
connected account actually holds. Point it at a brand-new paper account and the
app starts from zero with the defaults in broker_rules.py.

--archive writes the journal and trade log to backend/archive/ first. The old
account's 100 trades are the only evidence of what the strategy actually did;
docs/STRATEGY_REVIEW.md was written from them. Keep them.

--prune-dead-agents also drops stored rows belonging to agents that no longer
exist in this codebase (ai_times, mailman, compass, aegis, …). They are invisible
to the UI but they are still served by /api/agent/{name}/data, which is how a
screen can end up showing a reading from August.
"""
import argparse
import asyncio
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import (get_agent_data, delete_agent_data, delete_config,  # noqa: E402
                      all_config, SessionLocal, AgentData)

ALPHA = "alpha_wolf"
# Agents with a module in backend/agents/. Anything else in agent_data is a
# leftover from a deleted agent.
LIVE_AGENTS = {"alpha_wolf", "technologia", "wallstreet_wolf"}


def _summary() -> dict:
    data = get_agent_data(ALPHA) or {}
    journal = data.get("journal") or []
    trades = data.get("trades") or []
    portfolio = data.get("portfolio") or {}
    positions = portfolio.get("positions") or {}
    pnl = sum(j.get("pnl") or 0 for j in journal)
    return {"journal": len(journal), "trades": len(trades),
            "positions": sorted(positions), "realized_pnl": round(pnl, 2),
            "pending": len(data.get("pending_entries") or []),
            "settings": sorted(k for k in all_config() if k.startswith("alpha_wolf_"))}


def _dead_agent_rows() -> dict:
    db = SessionLocal()
    try:
        rows = db.query(AgentData.agent_name, AgentData.key).all()
    finally:
        db.close()
    out = {}
    for name, key in rows:
        if name not in LIVE_AGENTS:
            out.setdefault(name, []).append(key)
    return out


def _archive(data: dict) -> str:
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "archive")
    os.makedirs(root, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(root, f"alpha_wolf-{stamp}.json")
    with open(path, "w") as fh:
        json.dump({"archived_at": stamp,
                   "journal": data.get("journal") or [],
                   "trades": data.get("trades") or [],
                   "portfolio": data.get("portfolio") or {}}, fh, indent=1)
    return path


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="actually clear it")
    ap.add_argument("--archive", action="store_true",
                    help="save the journal and trade log to backend/archive/ first")
    ap.add_argument("--prune-dead-agents", action="store_true",
                    help="also drop rows for agents that no longer exist")
    args = ap.parse_args()

    before = _summary()
    print("Current Alpha Wolf state")
    print(f"  closed trades in the journal : {before['journal']}  "
          f"(realized ${before['realized_pnl']:,.2f})")
    print(f"  trade-log rows               : {before['trades']}")
    print(f"  open positions               : {', '.join(before['positions']) or 'none'}")
    print(f"  working entry orders         : {before['pending']}")
    print(f"  stored settings              : {len(before['settings'])}")
    dead = _dead_agent_rows()
    if dead:
        print(f"  rows from deleted agents     : {sum(len(v) for v in dead.values())} "
              f"across {len(dead)} agent(s) — {', '.join(sorted(dead))}")

    if before["positions"]:
        print("\n  NOTE: those positions are this app's last snapshot, not the broker's "
              "book.\n        Nothing here closes a position. If a real position is open "
              "at Alpaca,\n        close it there (or in the UI) before resetting.")

    if not args.yes:
        print("\nDry run. Re-run with --yes to clear it (add --archive to keep a copy).")
        return 0

    if args.archive:
        print(f"\narchived → {_archive(get_agent_data(ALPHA) or {})}")

    import alpaca_broker as broker
    rows = delete_agent_data(ALPHA, *broker.RESET_DATA_KEYS)
    cfgs = delete_config(*broker.RESET_CONFIG_KEYS)
    print(f"cleared {rows} stored row(s) and {cfgs} setting(s)")

    if args.prune_dead_agents and dead:
        n = sum(delete_agent_data(name) for name in dead)
        print(f"pruned {n} row(s) from {len(dead)} deleted agent(s)")

    if not broker.configured():
        print("\nAlpaca keys are not set — local state is clear, but return% can't be "
              "baselined yet.\nAdd ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY to .env, then "
              "re-run this with --yes.")
        return 0

    account = await broker._account()
    equity = float(account["equity"])
    from database import set_config
    set_config("alpha_wolf_baseline_equity", equity)
    set_config("alpha_wolf_created_at", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    s = broker.get_settings()
    print(f"\nConnected to Alpaca account {account.get('account_number')} "
          f"({account.get('status')})")
    print(f"  equity ${equity:,.2f} · cash ${float(account['cash']):,.2f} · "
          f"return% re-baselined to today")
    print("\nTrading starts from these defaults:")
    print(f"  entry window     {s['entry_window']['label']}  (no pre-market, no late entries)")
    print(f"  concurrent       {s['max_positions']} position(s), max "
          f"{s['max_new_trades_per_day']} new trades/day")
    print(f"  direction        {'long and short' if s['allow_shorts'] else 'LONG ONLY'}")
    print(f"  quality          grade {s['min_grade']}+ cards, reward/risk ≥ {s['min_rr']}:1")
    print(f"  sizing           {s['risk_pct']}% equity risked per trade, "
          f"{s['position_pct']}% concentration cap")
    print(f"  circuit breaker  halt new entries at -{s['max_daily_loss_pct']}% on the day")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
