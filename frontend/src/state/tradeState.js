// ============================================================================
// tradeState.js — ONE vocabulary for "what is this trade doing right now".
//
// Alpha Wolf is the only place a trade is taken, so its verdict is the only
// verdict. Technologia renders the same badge from the same map rather than
// keeping a second opinion: a card that reads "TODAY'S A+ SETUP" on one tab
// while the other says the target came and went is not two views of a trade,
// it is two different instructions from the same data.
// ============================================================================
import { T, AGENT_COLOR } from "../theme/tokens";

// `levels` says which of entry/stop/target still mean anything — printing an
// entry price on a trade that closed two hours ago is an invitation to take it.
export const stateStyle = (k) => ({
  ACT:           { c: T.green,   label: "ACT NOW",       rank: 0, levels: "full" },
  IN_WINDOW:     { c: AGENT_COLOR.alpha_wolf, label: "IN WINDOW", rank: 1, levels: "full" },
  HOLDING:       { c: T.blue,    label: "HOLDING",       rank: 2, levels: "manage" },
  WAIT:          { c: T.ink3,    label: "WAIT",          rank: 3, levels: "full" },
  MONITOR:       { c: T.amber,   label: "MONITOR",       rank: 4, levels: "full" },
  NEXT_SESSION:  { c: T.ink3,    label: "NEXT SESSION",  rank: 5, levels: "full" },
  NO_TRADE:      { c: T.ink4,    label: "NO TRADE",      rank: 6, levels: "none" },
  WINDOW_PASSED: { c: T.ink4,    label: "WINDOW PASSED", rank: 7, levels: "none" },
  BANKED:        { c: T.green,   label: "BANKED",        rank: 8, levels: "done" },
  TARGET_HIT:    { c: T.ink4,    label: "MISSED",        rank: 9, levels: "none" },
  STOPPED:       { c: T.red,     label: "INVALIDATED",  rank: 10, levels: "none" },
  // A stop or target through on a name we are actually IN is not history, it
  // is the most urgent row on the page — it says close the position.
  EXIT_TARGET:   { c: T.green,   label: "TAKE PROFIT",   rank: 0, levels: "manage" },
  EXIT_STOP:     { c: T.red,     label: "EXIT NOW",      rank: 0, levels: "manage" },
}[k] || { c: T.amber, label: "MONITOR", rank: 4, levels: "full" });

// The badge key differs from the backend state only where being in the trade
// flips the meaning of the same price event.
export const stateKey = (i) => (i.held && i.state === "TARGET_HIT" ? "EXIT_TARGET"
  : i.held && i.state === "STOPPED" ? "EXIT_STOP" : i.state);

// Ticker → the live decision Alpha Wolf has reached for it, from /alpha-wolf/now.
export function statesByTicker(now) {
  const out = {};
  for (const i of now?.ideas || []) {
    const t = String(i.ticker || "").toUpperCase();
    if (t) out[t] = i;
  }
  return out;
}
